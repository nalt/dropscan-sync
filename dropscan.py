#!/usr/bin/python
"""
Client class and downloader for the dropscan.de scan service.
List, download and synchronize (one-way) mailings
2015-06
(c) Nicolas Alt
"""

import requests
from pyquery import PyQuery as pq
import argparse
import re
import os.path
import json
#import urllib3
#urllib3.disable_warnings()


def enum(*sequential, **named):
    enums = dict(zip(sequential, range(len(sequential))), **named)
    reverse = dict((value, key) for key, value in enums.iteritems())
    enums['reverse_mapping'] = reverse
    return type('Enum', (), enums)


class Dropscan:
	FILTER = enum('received', 'scanned', 'forwarded', 'destroyed')
	TYPE   = enum('thumb', 'envelope', 'pdf', 'zip')
	verbose = 0
	user = ""
	password = ""
	session = None
	scanbox = None;
	folders = []

	def __init__(self, user, password, verbose=0):
		self.user = user
		self.password = password
		self.verbose = verbose
		self.session = requests.Session()


	def setProxy(self, https_proxy):
		self.session.proxies = { 'https': https_proxy }

	def login(self):
		""" Login to dropscan.de. Saves cookie and the scanbox ID as class variables. """
		# Get Auth Token from Login form
		if self.verbose >= 3: print "--- Pre-Login ---"
		r = self.session.get('https://secure.dropscan.de/login')
		d = pq(r.content)
		auth_token = d('[name=authenticity_token]').attr("value")
		if self.verbose >= 3: print "Auth token: ", auth_token

		# Login
		if self.verbose >= 3: print "--- Login ---" 
		auth = { 'user[email]': self.user, 'user[password]': self.password, 'user[remember_me]': 0,
		'authenticity_token': auth_token}
		r = self.session.post('https://secure.dropscan.de/login',
			data = auth, allow_redirects=True)
		# STATUS is 200 on error, 302 on success (if not following redirect)
		if self.verbose >= 3: print "Status code: ", r.status_code, "\nURL: ", r.url
		#print r.text

		# Get scanbox-id from URL. Login results in a 302 forward to the scanbox URL.
		m = re.search('.*/scanboxes/([0-9a-fA-F].*)$', r.url)
		if m is None:
			raise Exception("Login error (scanbox not found)."); 
		else:
			self.scanbox = m.group(1)

	def getList(self, filter):
		"""
		List of mailings in specified box. Returns the JSON-struct from Dropscan directly.
		filter -- Use self.FILTER enum
		"""
		filter_str = self.FILTER.reverse_mapping[filter]
		if self.verbose >= 3: print "--- getList (", filter_str, ") ---"
		r = self.session.get('https://secure.dropscan.de/scanboxes/' + 
			self.scanbox + '/mailings.json?filter=' + filter_str)
		list = r.json()
		return list

	def getBatches(self, only_unsent=True):
		"""
		Get list of all forwarding batches
		Returns the JSON-struct from Dropscan, adds is_sent flag
		"""
		r = self.session.get('https://secure.dropscan.de/forwarding_batches.json')
		batches = r.json()
		batches = [ b.update({'is_sent': 'sent_at' in b }) or b for b in batches ]
		batches = [ b for b in batches if not b['is_sent'] or not only_unsent ]
		return batches

	def addMailingtoBatch(self, mailing_slug, batch_id=None):
		"""
		Adds a mailing to an existing forwarding batch.
		mailing_slug  -- "slug" of mailing to add
		batch_id      -- id of forwarding batch. If unspecified, the first unsent batch is used.
		"""
		if batch_id is None:
			batches = self.getBatches();
			if len(batches) == 0:
				if self.verbose >= 1: print "No unsent batch available"
				return False
			batch_id = batches[0]['id']
		r = self.session.get('https://secure.dropscan.de/scanboxes/%s/mailings/%s/forward?forwarding_batch_id=%s&src=detail' %
			(self.scanbox, mailing_slug, batch_id));
		return r.status_code == 200

	def isScanned(self, mailing):
		"""
		Check if given mailing has been scanned, i.e. PDF is available
		"""
		# TODO: Check scanned_at field? Which status codes are possible?
		return mailing['status'] == 'scanned' or mailing['status'] == 'destroyed'

	def downloadMailing(self, mailing, type, filename=""):
		"""
		Download thumb, envelope (JPG) or PDF for a mailing.
		mailing   -- One entry returned from getList()
		type      -- Thumbnail, envelope or full PDF. Use self.TYPE enum.
		filename  -- Save to given file. If empty, return the JPG/PDF
		"""
		m = mailing
		if type == self.TYPE.thumb:
			url = m['envelope_thumbnail_url']
		elif type == self.TYPE.envelope:
			# The URL of the large enelope is *.jpg instead of *.small.jpg
			# Otherwise, this would have to be extracted from /scanboxes/*/mailings/*
			url = re.sub(r'^(.*)\.small\.(.*)$', r'\1.\2', m['envelope_thumbnail_url']);
		elif type == self.TYPE.pdf:
			if not self.isScanned(m):
				if self.verbose >=2: print "Mailing %s  not yet scanned" % (m['barcode'])
				return False
			url = 'https://secure.dropscan.de/scanboxes/' + \
				self.scanbox + '/mailings/' + m['slug'] + '/download_pdf'
		elif type == self.TYPE.zip:
			raise Exception("ZIP download not implemented.")

		if self.verbose >= 3: print "--- Download mailing %s (%s) ---" % (m['barcode'], self.TYPE.reverse_mapping[type])
		r = self.session.get(url, verify=False)
		if len(filename) > 0:
			with open(filename, 'wb') as fd:
				fd.write(r.content)
			return True
		else:
			return r.content

	def setLocalFolders(self, folders):
		"""
		Additional folder(s) to check for locally existing files  
		"""
		if folders is None: self.folders = []
		else: self.folders = folders
		if self.verbose >= 3: print "Local folders: ", self.folders


	def syncMailings(self, mailings, thumbs=False):
		"""
		Download all missing files (thumbs, envelope, pdf) for the given mailings
		mailings     -- struct returned from getList()
		"""
		for m in reversed(mailings):
			# Rewrite data
			date_ = re.search('([0-9]*)\.([0-9]*)\.([0-9]*)', m['created_at'])
			date = date_.group(3) + '-' + date_.group(2) + '-' + date_.group(1)
			# ID & Filenames for this mailing
			id = (date + '_' +  m['barcode']).encode('utf8');

			for f in [self.TYPE.thumb, self.TYPE.envelope, self.TYPE.pdf]:
				if f == self.TYPE.thumb and not thumbs:
					# Do not download thumbs
					continue
				if f == self.TYPE.pdf and not self.isScanned(m):
					# Do not try to download PDF for non-scanned mailing
					continue
				filename = id + '_' + D.TYPE.reverse_mapping[f]
				filename += '.pdf' if (f == self.TYPE.pdf) else '.jpg'
				# Check if file already exists locally
				file_exists = False
				for folder in ['.'] + self.folders:
					if os.path.isfile(folder + '/' + filename):
						file_exists = True
						if self.verbose >= 3: print "Local file found: ", folder + '/' + filename
				# Perform download, if required:
				if not file_exists:
					res = self.downloadMailing(m, f, filename)
					if self.verbose >= 0:
						if res: print "Mailing stored to", filename
						else: print   "Mailing failed to download:", filename
				else:
					if self.verbose >= 1:
						print "File", filename, "already exists."


def demo(user, password, args):
	"""	Demo/test routine: Login, list mailings, download one mailing """
	print "=== Running test ===="
	D = Dropscan(user, password, args.v)
	if args.proxy:
		D.setProxy(args.proxy)
	D.login()

	print "=== List of all mailings ==="
	for f in  [D.FILTER.received, D.FILTER.scanned, D.FILTER.forwarded, D.FILTER.destroyed]:
		print "INBOX:", D.FILTER.reverse_mapping[f]
		l = D.getList(f)
		for (i,m) in enumerate(l):
			print "%2d: %s %s" % (i, m['created_at'], m['barcode'])

	print "=== Download of last mailing to demo_*.pdf / .jpg ==="
	l = D.getList(D.FILTER.scanned)
	print l[-1]
	# data1 = D.downloadMailing(l[-1], D.TYPE.thumb, 'demo_thumb.jpg')
	data2 = D.downloadMailing(l[-1], D.TYPE.envelope, 'demo_envelope.jpg')
	data3 = D.downloadMailing(l[-1], D.TYPE.pdf, 'demo_pdf.pdf')



if __name__ == '__main__':
	parser = argparse.ArgumentParser()
	# group = parser.add_usage_group(kind='any', required=True) # http://stackoverflow.com/questions/6722936
	parser.add_argument('-t', action='store_true', help='Run demo/test (login, list mailings, download)')
	parser.add_argument('-s', '--sync', action='store_true', help='One-way sync: Download missing files of all mailings to current folder')
	parser.add_argument('--batches', action='store_true', help='List forwarding batches (only unsent)')
	parser.add_argument('-F', '--forward_mailing', help='Add the specified mailing slug to the first existing unsent forwarding batch')
	parser.add_argument('-u', required=0, help='Dropscan username (may be specified in credentials file)')
	parser.add_argument('-p', required=0, help='Dropscan password (may be specified in credentials file)')
	parser.add_argument('--thumbs', action='store_true', help='Also sync thumbs of envelopses')
	parser.add_argument('-d', '--dir',  action='append', help='Additional folder(s) to check for locally existing files during sync.')
	parser.add_argument('-v', default=0, type=int, help='Set Verbosity [0..3]')
	parser.add_argument('--proxy', help='Use a proxy server to connect to Dropscan')
	args = parser.parse_args()

	# Read credentials file
	user = ''
	password = ''
	cred_file = os.path.dirname(os.path.realpath(__file__)) + '/dropscan-credentials.json'
	try:
		json_data = open(cred_file).read()
		cred = json.loads(json_data)
		user = cred["user"]
		password = cred["password"]
		if args.v >= 2: print "Credentials loaded from", cred_file
	except:
		if args.v >= 2: print "Credentials file", cred_file, "not loaded."

	if args.u: user = args.u
	if args.p: password = args.p

	# Test/demo
	if args.t:
		demo(user, password, args)
	
	# Sync
	elif args.sync:
		D = Dropscan(user, password, args.v)
		if args.proxy:
			D.setProxy(args.proxy)
		D.setLocalFolders(args.dir)
		D.login()
		l1 = D.getList(D.FILTER.scanned)
		l2 = D.getList(D.FILTER.received)
		D.syncMailings(l2, args.thumbs)
		D.syncMailings(l1, args.thumbs)

	# List unsent forwarding batches
	elif args.batches:
		D = Dropscan(user, password, args.v)
		D.login()
		l = D.getBatches()
		print(l)
		if len(l) == 0:
			print "There is no unsent forwarding batch. Create one using the web interface"

	# Add mailing to forwarding batch
	elif args.forward_mailing:
		D = Dropscan(user, password, args.v)
		D.login()
		res = D.addMailingtoBatch(args.forward_mailing);
		print "Result:", res

	else:
		parser.print_help()
