#!/usr/bin/python3
"""
Client class and downloader for the dropscan.de scan service.
List, download and synchronize (one-way) mailings
INSTALL: sudo apt install python-pyquery python-certifi python3-pyquery
2015-06
(c) Nicolas Alt
"""

import requests
from pyquery import PyQuery as pq
import argparse
import re
import os.path, shutil
import json
import datetime

from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
#import urllib3
#urllib3.disable_warnings()


def enum(*sequential, **named):
    enums = dict(zip(sequential, range(len(sequential))), **named)
    reverse = dict((value, key) for key, value in enums.items())
    enums['reverse_mapping'] = reverse
    return type('Enum', (), enums)


class Dropscan:
	FILTER = enum('received', 'scanned', 'forwarded', 'destroyed')
	TYPE   = enum('thumb', 'envelope', 'pdf', 'zip', 'full')
	SYNC_DB = "dropscan.sync"
	verbose = 0
	user = ""
	password = ""
	session = None
	scanbox = None;
	folders = ['.']
	syncdb = []
	local_folders_cache = None
	local_files_cache = None

	def __init__(self, user, password, verbose=0):
		self.user = user
		self.password = password
		self.verbose = verbose
		self.session = requests.Session()

	def readSyncDB(self):
		"""
		Read "database" of local files
		"""
		if os.path.exists(self.SYNC_DB):
			with open(self.SYNC_DB) as f:
			    files_local = f.readlines()
		else:
			files_local = []
		self.syncdb = [ i.split("\t")[0] for i in files_local ]

	def writeSyncDB(self, name):
		with open(self.SYNC_DB, 'a') as f:
			f.write(name + "\t" + datetime.datetime.now().isoformat() + "\n")

	def setProxy(self, https_proxy):
		self.session.proxies = { 'https': https_proxy }

	def login(self):
		""" Login to dropscan.de. Saves cookie and the scanbox ID as class variables. """
		# Get Auth Token from Login form
		if self.verbose >= 3: print ("--- Pre-Login ---", end=" ")
		r = self.session.get('https://secure.dropscan.de/login')
		d = pq(r.content)
		auth_token = d('[name=authenticity_token]').attr("value")
		if self.verbose >= 3: print ("Auth token: ", auth_token, end=" ")

		# Login
		if self.verbose >= 3: print ("--- Login ---" , end=" ")
		auth = { 'user[email]': self.user, 'user[password]': self.password, 'user[remember_me]': 0,
		'authenticity_token': auth_token}
		r = self.session.post('https://secure.dropscan.de/login',
			data = auth, allow_redirects=True)
		# STATUS is 200 on error, 302 on success (if not following redirect)
		if self.verbose >= 3: print ("Status code: ", r.status_code, "\nURL: ", r.url, end=" ")
		#print (r.text

		# Get scanbox-id from URL. Login results in a 302 forward to the scanbox URL., end=" ")
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
		if self.verbose >= 3: print ("--- getList (", filter_str, ") ---", end=" ")
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

	def addMailingtoBatch(self, mailing_slug, batch=None):
		"""
		Adds a mailing to an existing forwarding batch.
		mailing_slug  -- "slug" of mailing to add
		batch         -- Batch struct, as returned by getBatches. If unspecified, the first unsent batch is used.
		Returns: added, alreadyin, nobatch, error
		"""
		# Get batch struct, if unspecified
		if batch is None:
			batches = self.getBatches();
			if len(batches) == 0:
				if self.verbose >= 1: print ("No unsent batch available", end=" ")
				return "nobatch"
			batch = batches[0]
		# Check if mailing already in batch
		for m in batch['mailings']:
			if m['slug'] == mailing_slug:
				if self.verbose >= 1: print ("Mailing", m['slug'], "already in batch", end=" ")
				return "alreadyin"
		# Add mailing to batch
		r = self.session.get('https://secure.dropscan.de/scanboxes/%s/mailings/%s/forward?forwarding_batch_id=%s&src=detail' %
			(self.scanbox, mailing_slug, batch['id']));
		ok = r.status_code == 200
		if not ok and self.verbose >= 1: print ("Failed to add mailing", mailing_slug, "to batch", end=" ")
		return "added" if ok else "error"


	def addFolderstoBatch(self, mailings, forward_folders):
		"""
		Add all mailing files (envelopes) found in any of folders to forwarding batch.
		mailings         -- Mailings struct from getList()
		forward_folders  -- List of folders with mailings to be forwarded
		"""
		for m in reversed(mailings):
			# Check mailing status
			if not (m['status'] == 'scanned' or m['status'] == 'received'):
				continue
			# Check for local file
			(filename, local_file) = self.localFileMailing(m, self.TYPE.envelope, forward_folders)
			# If file is found, 
			if local_file is not None:
				res = self.addMailingtoBatch(m['slug'])
				if res == 'added':
					print ("Adding mailing to batch:", filename, end=" ")
				elif res == 'error':
					print ("Error adding mailing to batch:", filename, end=" ")

	def downloadMailing(self, mailing, type, filename=""):
		"""
		Download thumb, envelope (JPG) or PDF for a mailing.
		Uses subfolders for recipients, if they exist
		mailing   -- One entry returned from getList()
		type      -- Thumbnail, envelope or full PDF. Use self.TYPE enum.
		filename  -- Save to given file. If empty, return the JPG/PDF stream
		Rerturns:	 True (written to file), Contents, False (error), None (nothing to download)
		"""
		#m = mailing
		url_json ='https://secure.dropscan.de/scanboxes/' + \
				self.scanbox + '/mailings/' + mailing['slug'] + '.json'
		r = self.session.get(url_json)
		m = r.json()

		if type == self.TYPE.thumb:
			url = m['envelope_thumbnail_url']
		elif type == self.TYPE.envelope:
			# The URL of the large envelope is *.jpg instead of *.small.jpg
			# Otherwise, this would have to be extracted from /scanboxes/*/mailings/*
			url = re.sub(r'^(.*)\.small\.(.*)$', r'\1.\2', m['envelope_thumbnail_url']);
		elif type == self.TYPE.pdf:
			if not 'scanned_at' in m:
				if self.verbose >=2: print ("Mailing %s  not yet scanned" % (m['barcode']))
				return None
			url = 'https://secure.dropscan.de/scanboxes/' + \
				self.scanbox + '/mailings/' + m['slug'] + '/download_pdf'
		elif type == self.TYPE.zip:
			raise Exception("ZIP download not implemented.")

		if self.verbose >= 3: print ("--- Download mailing %s (%s) ---" % (m['barcode'], self.TYPE.reverse_mapping[type]))
		# Find filename
		rec = m['recipient']['name']
		if os.path.isdir(rec):
			filename = rec + os.sep + filename
		elif self.verbose >= 2:
			print('Folder "%s" not found to sort by recipient')
		# HTTP GET
		r = self.session.get(url, verify=False)
		if r.status_code != 200:
			if self.verbose >= 2: print("Invalid HTTP status code", r.status_code)
			return False
		if len(filename) > 0:
			with open(filename, 'wb') as fd:
				fd.write(r.content)
			return filename
		else:
			return r.content

	def combineFiles(self, file_envelope, file_pdf):
		"""
		Combines the envelope JPG and the mailing PDF into single file
		"""
		tmp_env = file_envelope + '.pdf'
		ret2 = 1

		file_full = file_pdf.replace('_pdf', '')
		if os.path.isfile(file_full):
			if self.verbose >= 3: print("Cannot combine to %s; file exists" % (file_full))
			return False

		ret1 = os.system('convert "%s" "%s"' % (file_envelope, tmp_env))
		if ret1 == 0:
			ret2 = os.system('pdftk "%s" "%s" cat output "%s"' % (file_pdf, tmp_env, file_full))
			if ret2 == 0 and os.path.exists(file_full):
				os.remove(file_pdf)
				os.remove(file_envelope)
		os.remove(tmp_env)
		if (ret1 == 0) and (ret2 == 0): return file_full
		else: return False


	def setLocalFolders(self, folders):
		"""
		Additional folder(s) to check for locally existing files  
		"""
		if folders is None: self.folders = []
		else: self.folders = folders + ['.']
		self.folders = list(set(self.folders))  # Unique elements
		if self.verbose >= 3: print ("Local folders: ", self.folders, end=" ")
		self.local_files = None

	def localFileMailing(self, mailing, type, search_folders):
		"""
		Create filename for given mailing and check whether it exists locally
		in any of the given folders
		mailing         -- Mailing struct, element from list returned by getList()
		type            -- ... from enum self.TYPE
		search_folders  -- List of local folders to search in for file
		Returns: (filename, local_file)
		filename        -- Filename for this mailing, constructed from mailing id and type
		local_path      -- local_file found for this mailing if existing, or None
		"""
		m = mailing
		# Create list of local files, if needed
		if search_folders != self.local_folders_cache:
			self.local_files_cache = []
			for folder in search_folders:
				if folder[-1] != os.sep: folder += os.sep
				files = os.listdir(folder)
				self.local_files_cache += [folder + f for f in files]
			if self.verbose >= 3:
				print("Created file list with", len(self.local_files_cache), "entries")
			self.local_folders_cache = search_folders

		# Create filename for this mailing
		date_ = re.search('([0-9]*)\.([0-9]*)\.([0-9]*)', m['created_at'])
		date = date_.group(3) + '-' + date_.group(2) + '-' + date_.group(1)
		# ID & Filenames for this mailing
		code = m['barcode']
		type_str = '_' + self.TYPE.reverse_mapping[type] if type != self.TYPE.full else ''
		ext = 'jpg' if (type in [self.TYPE.thumb, self.TYPE.envelope]) else 'pdf'
		filename = date + '_' + code + type_str + '.' + ext

		# Find locally existing file (or None)
		# Condition accodring to regexp: *<code><-tags><_type>.<ext>
		r = re.compile('.*[-_\. ]' + m['barcode'] + "[-A-Z]*" + type_str + '\.' + ext)
		local_file = list(filter(r.match, self.local_files_cache))
		if len(local_file) > 1 and self.verbose >= 2:
			print("Found multiple identical files:", local_file)
		local_file = local_file[0] if len(local_file) >= 1 else None

		return (filename, local_file)

	def syncMailings(self, mailings, thumbs=False, combine=True):
		"""
		Download all missing files (thumbs, envelope, pdf) for the given mailings
		mailings     -- struct returned from getList()
		"""
		filename = {}
		ftypes = [self.TYPE.full, self.TYPE.envelope, self.TYPE.pdf]
		if thumbs:
			ftypes.append(self.TYPE.thumb)
		for m in reversed(mailings):
			all_exist = True
			full_exists = False
			for f in ftypes:
				# Check for local file
				(file_org, local_file) = self.localFileMailing(m, f, self.folders)
				filename[f] = file_org if local_file is None else local_file

				if f == self.TYPE.full and local_file is not None:
					full_exists = local_file
				# Perform download, if required:
				if not full_exists and f != self.TYPE.full and \
					local_file is None and \
					not file_org in self.syncdb:
					stored = self.downloadMailing(m, f, filename[f])
					if stored:
						self.writeSyncDB(file_org)
						filename[f] = stored
						print ("Mailing stored to", filename[f])
					elif stored is False:
						#if self.verbose >= 0:
						all_exist = False
						print (  "Mailing failed to download:", filename[f])
					elif stored is None:
						# File does not exist (yet)
						all_exist = False
				else:
					if self.verbose >= 3:
						print ("File", filename[f], "already exists.")

				# Combine envelope & mailing into one file
				if f == self.TYPE.pdf and combine and not full_exists and all_exist:
					r = self.combineFiles(filename[self.TYPE.envelope], filename[self.TYPE.pdf])
					if r:
						filename[self.TYPE.full] = r
						r_ren = self.writeTag(m, r)
						print ("Mailing combined to", r)
					else:
						print ("Failed: Combining mailing")

				# Rename files to include current labels
				ren = self.writeTag(m, filename[f])
				if ren:
					filename[f] = ren

	def writeTag(self, mailing, local_file):
		"""
		Adds tags to filename (by renaming) for deleted/forwarded status
		"""
		if local_file is None or not os.path.isfile(local_file):
			return
		tag = ''
		if mailing['status'] == 'forwarded': tag = 'F'
		if mailing['status'] == 'destroyed': tag = 'D'
		# Scan filename for barcode-tags
		b = mailing['barcode']
		m = re.match(".*("+b+")-([A-Z]*)|.*("+b+")", local_file);
		if m[1] or m[3]:
			pos = m.span()[1]
			file_tag = m[2] if m[2] is not None else ''
			if not tag in file_tag:
				if m[2] is None: tag = '-' + tag
				local_file_new = local_file[:pos] + tag + local_file[pos:]
				if not os.path.isfile(local_file_new):
					os.rename(local_file, local_file_new)
					if self.verbose >= 1 or True:
						print("New Tags, renamed to:", local_file_new)
					return local_file_new
				else:
					if self.verbose >= 1:
						print("Renamed failed, file exists:", local_file_new)
		return None


def demo(user, password, args):
	"""	Demo/test routine: Login, list mailings, download one mailing """
	print ("=== Running test ====", end=" ")
	D = Dropscan(user, password, args.v)
	if args.proxy:
		D.setProxy(args.proxy)
	D.login()

	print ("=== List of all mailings ===", end=" ")
	for f in  [D.FILTER.received, D.FILTER.scanned, D.FILTER.forwarded, D.FILTER.destroyed]:
		print ("INBOX:", D.FILTER.reverse_mapping[f], end=" ")
		l = D.getList(f)
		for (i,m) in enumerate(l):
			(filename,local_file) = D.localFileMailing(m, D.TYPE.envelope, D.folders)
			print ("%2d: %s %s. local envelope: %s" % (i, m['created_at'], m['barcode'], str(local_file)), end=" ")

	print ("=== Download of last mailing to demo_*.pdf / .jpg ===", end=" ")
	l = D.getList(D.FILTER.scanned)
	print (l[-1])
	# data1 = D.downloadMailing(l[-1], D.TYPE.thumb, 'demo_thumb.jpg'), end=" ")
	data2 = D.downloadMailing(l[-1], D.TYPE.envelope, 'demo_envelope.jpg')
	data3 = D.downloadMailing(l[-1], D.TYPE.pdf, 'demo_pdf.pdf')



if __name__ == '__main__':
	parser = argparse.ArgumentParser()
	# group = parser.add_usage_group(kind='any', required=True) # http://stackoverflow.com/questions/6722936
	parser.add_argument('-t', action='store_true', help='Run demo/test (login, list mailings, download)')
	parser.add_argument('-s', '--sync', action='store_true', help='One-way sync: Download missing files of all mailings to current folder')
	parser.add_argument('--nodb', action='store_true', help='Do not read Sync-DB (existence of local files is always checked)')
	parser.add_argument('--batches', action='store_true', help='List forwarding batches (only unsent)')
	parser.add_argument('-F', '--forward_mailing', help='Add the specified mailing slug to the first existing unsent forwarding batch')
	parser.add_argument('--forward_dir', action='append', help='Add all mailings in given directory to forwarding batch. Must use -s.')
	parser.add_argument('-u', required=0, help='Dropscan username (may be specified in credentials file)')
	parser.add_argument('-p', required=0, help='Dropscan password (may be specified in credentials file)')
	parser.add_argument('--thumbs', action='store_true', help='Also sync thumbs of envelopses')
	parser.add_argument('-r', '--recursive',  action='store_true', help='Check all subfolders for locally existing files during sync.')
	parser.add_argument('-d', '--dir',  action='append', help='Additional folder(s) to check for locally existing files during sync.')
	parser.add_argument('-v', default=0, type=int, help='Set Verbosity [0..3]')
	parser.add_argument('--proxy', help='Use a proxy server to connect to Dropscan')
	args = parser.parse_args()

	# Check tools
	for tool in [ 'convert', 'pdftk' ]:
		if shutil.which(tool) is None:
			print("Missing, please install:", tool)


	# Read credentials file
	user = ''
	password = ''
	cred_file = os.path.dirname(os.path.realpath(__file__)) + '/dropscan-credentials.json'
	try:
		json_data = open(cred_file).read()
		cred = json.loads(json_data)
		user = cred["user"]
		password = cred["password"]
		if args.v >= 2: print ("Credentials loaded from", cred_file, end=" ")
	except:
		if args.v >= 2: print ("Credentials file", cred_file, "not loaded.", end=" ")

	if args.u: user = args.u
	if args.p: password = args.p

	# Test/demo
	if args.t:
		demo(user, password, args)
	
	# Sync
	elif args.sync:
		D = Dropscan(user, password, args.v)
		if not args.nodb:
			D.readSyncDB()
		if args.proxy:
			D.setProxy(args.proxy)
		# Search folders
		folders = []
		if args.recursive:
			folders = [d[0] for d in os.walk('.')]
		if args.dir:
			folders += args.dir
		if args.forward_dir:
			folders += args.forward_dir
		D.setLocalFolders(folders)
		D.login()
		l1 = D.getList(D.FILTER.scanned)
		l2 = D.getList(D.FILTER.received)
		l3 = D.getList(D.FILTER.forwarded)
		D.syncMailings(l2, args.thumbs)
		D.syncMailings(l1, args.thumbs)

		# Auto-add mailings in folder to forward batch
		if args.forward_dir:
			D.addFolderstoBatch(l1+l2, args.forward_dir)

	# List unsent forwarding batches
	elif args.batches:
		D = Dropscan(user, password, args.v)
		D.login()
		l = D.getBatches()
		print(l)
		if len(l) == 0:
			print ("There is no unsent forwarding batch. Create one using the web interface", end=" ")

	# Add mailing to forwarding batch
	elif args.forward_mailing:
		D = Dropscan(user, password, args.v)
		D.login()
		res = D.addMailingtoBatch(args.forward_mailing);
		print ("Result:", res, end=" ")

	else:
		parser.print_help()
