#!/usr/bin/env python3
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
import isodate
import subprocess

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
	list_count = 20
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

	def setListCount(self, count):
		"""
		Set number of items to request from dropscan; their default is 20
		"""
		self.list_count = count

	def login(self):
		""" Login to dropscan.de. Saves cookie and the scanbox ID as class variables. """
		# Get Auth Token from Login form
		if self.verbose >= 3: print ("--- Pre-Login ---")
		r = self.session.get('https://secure.dropscan.de/login')
		d = pq(r.content)
		auth_token = d('meta[name="csrf-token"]').attr("content")
		if auth_token is None: print("Error: No auth token")
		if self.verbose >= 3: print ("Auth token: ", auth_token)

		# Login
		if self.verbose >= 3: print ("--- Login ---")
		auth = { 'user[email]': self.user, 'user[password]': self.password, 'user[remember_me]': 0,
		'authenticity_token': auth_token}
		r = self.session.post('https://secure.dropscan.de/login',
			data = auth, allow_redirects=True)
		# STATUS is 200 on error, 302 on success (if not following redirect)
		if self.verbose >= 3: print ("Status code: ", r.status_code, "\nURL: ", r.url)

		# Get scanbox-id from URL. Login results in a 302 forward to the scanbox URL.
		m = re.search('.*/mailings$', r.url)
		if m is None:
			raise Exception("Login error.");
		self.getScanboxes()
		return True

	def getScanboxes(self):
		"""
		Get info about scanboxes, sets self.scanbox
		"""
		r = self.session.get('https://secure.dropscan.de/services/scanboxes')
		scanboxes = r.json()
		self.scanbox = scanboxes[0]['id']
		if self.verbose >= 2:
			print("Scanbox ID:", self.scanbox, "Receipients:", ','.join([r['name'] for r in scanboxes[0]['recipients']]))
		

	def getList(self, filter):
		"""
		List of mailings in specified box. Returns the JSON-struct from Dropscan directly.
		filter -- Use self.FILTER enum
		"""
		filter_str = self.FILTER.reverse_mapping[filter]
		# https://secure.dropscan.de/services/mailings?max_per_page=100&scanbox_ids=1834&sort_dir=desc&sorting=scanned_at&statuses=scanned
		#url = 'https://secure.dropscan.de/scanboxes/' + \
		url = 'https://secure.dropscan.de/services/mailings?sort_dir=desc&sorting=created_at&' + \
			"scanbox_ids=" + self.scanbox + '&statuses=' + filter_str + '&max_per_page=' + str(self.list_count)
		r = self.session.get(url)
		mailings = r.json()
		if self.verbose >= 3:
			print("--- getList", filter_str, len(mailings), " mailings ---")
			print(url)
		return mailings

	def getBatches(self, only_unsent=True):
		"""
		Get list of all forwarding batches
		Returns the JSON-struct from Dropscan, adds is_sent flag
		"""
		r = self.session.get('https://secure.dropscan.de/services/forwarding_batches?max_per_page=100&page=0')
		batches = r.json()
		batches = [ b.update({'is_sent': 'sent_at' in b and b['sent_at'] is not None }) or b for b in batches ]
		batches = [ b for b in batches if not b['is_sent'] or not only_unsent ]
		batches.sort(key=lambda e: e['requested_for'])
		return batches

	def addMailingtoBatch(self, mailing, batch=None):
		"""
		Adds a mailing to an existing forwarding batch.
		mailing       -- mailing to add, used field id (was "slug")
		batch         -- Batch struct, as returned by getBatches. If unspecified, the first unsent batch is used.
		Returns: added, alreadyin, nobatch, error
		"""
		# Get batch struct, if unspecified
		if batch is None:
			batches = self.getBatches()
			# print(batches)
			if len(batches) == 0:
				if self.verbose >= 1: print ("No unsent batch available")
				return "nobatch"
			batch = batches[0]
		# Check if mailing already in batch
		for m in batch['mailings']:
			if m == mailing['id'] or ('forwarding_batch_id' in mailing and mailing['forwarding_batch_id'] is not None):
				if self.verbose >= 1: print ("Mailing", m['id'], "already in batch")
				return "alreadyin"
		# Add mailing to batch
		r = self.session.post('https://secure.dropscan.de/services/mailings/%s/request_forward' %
			(mailing['id']), json = { "forwarding_batch_id": batch['id'] } )
		ok = r.status_code == 200
		if not ok and self.verbose >= 1:
			print ("Failed to add mailing", mailing['id'], "to batch")
		return "added" if ok else "error"


	def addFolderstoBatch(self, mailings, forward_folders):
		"""
		Add all mailing files (envelopes) found in any of folders to forwarding batch.
		mailings         -- Mailings struct from getList()
		forward_folders  -- List of folders with mailings to be forwarded
		"""
		count = 0
		# Build local files DB
		self.localFileMailing(mailings[0], self.TYPE.envelope, forward_folders)
		for m in reversed(mailings):
			# Check mailing status
			if not (m['status'] == 'scanned' or m['status'] == 'received'):
				continue
			# Check for local file
			r1 = re.compile('.*[-_\. ]' + m['barcode'] + '[-_\. ]')
			local_files = list(filter(r1.match, self.local_files_cache))

			# If file is found,
			if len(local_files) > 0:
				res = self.addMailingtoBatch(m)
				if res == 'added':
					count += 1
					print ("Adding mailing to batch:", local_files[0])
				elif res == 'error':
					print ("Error adding mailing to batch:", local_files[0])
		return count
		

	def addOldtoBatch(self, mailings, older_days):
		"""
		Add mailings older than older_days to batch
		"""
		count = 0
		for m in mailings:
			if not (m['status'] == 'scanned' or m['status'] == 'received'):
				continue
			ndays = (datetime.datetime.now(datetime.timezone.utc) - isodate.parse_datetime(m['created_at'])).days
			if ndays > older_days:
				res = self.addMailingtoBatch(m)
				if res == 'added':
					count += 1
					print ("Added old mailing %s (%d days) to batch." % (m['id'], ndays))
				elif res == 'error':
					print ("Error adding old mailing %s to batch." % (m['id']))
		return count

	def downloadMailing(self, mailing, type, filename=""):
		"""
		Download thumb, envelope (JPG) or PDF for a mailing.
		Uses subfolders for recipients, if they exist
		mailing   -- One entry returned from getList()
		type      -- Thumbnail, envelope or full PDF. Use self.TYPE enum.
		filename  -- Save to given file. If empty, return the JPG/PDF stream
		Rerturns:	 True (written to file), Contents, False (error), None (nothing to download)
		"""
		m = mailing
		#url_json ='https://secure.dropscan.de/scanboxes/' + \
		#		self.scanbox + '/mailings/' + mailing['slug'] + '.json'
		#r = self.session.get(url_json)
		#m = r.json()

		if type == self.TYPE.thumb:
			url = m['envelope_thumbnail_url']
		elif type == self.TYPE.envelope:
			# The URL of the large envelope is *.jpg instead of *.small.jpg
			# Otherwise, this would have to be extracted from /scanboxes/*/mailings/*
			#OLD url = re.sub(r'^(.*)\.small\.(.*)$', r'\1.\2', m['envelope_thumbnail_url']);
			url = m['envelope_url']
		elif type == self.TYPE.pdf:
			if not 'scanned_at' in m or not m['scanned_at']:
				if self.verbose >=2: print ("Mailing %s not (yet) scanned" % (m['barcode']))
				return None
			url = "https://secure.dropscan.de/services/mailings/" + m['id'] + "/pdf?src="
			#OLD url = 'https://secure.dropscan.de/scanboxes/' + self.scanbox + '/mailings/' + m['slug'] + '/download_pdf'
		elif type == self.TYPE.zip:
			raise Exception("ZIP download not implemented.")

		if self.verbose >= 3: print ("--- Download mailing %s (%s) ---" % (m['barcode'], self.TYPE.reverse_mapping[type]))
		# Determine filename - sort by receipient first name
		rec = m['recipient'].split(" ")[0]
		if os.path.isdir(rec):
			filename = rec + os.sep + filename
		elif self.verbose >= 2:
			print('Sorting by receipient: Folder "%s" not found')
		# HTTP GET
		r = self.session.get(url, verify=False)
		if r.status_code != 200:
			if self.verbose >= 2:
				print("Invalid HTTP status code", r.status_code, "on URL", url)
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
		if os.path.exists(tmp_env):
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
		if self.verbose >= 3: print ("Local folders: ", self.folders)
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
		date_ = isodate.parse_datetime(m['created_at'])
		date = date_.strftime('%Y-%m-%d')
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

	def checkMultiple(self, mailings):
		"""
		Check if there are multiple files for one mailing
		"""
		# Create file database:
		self.localFileMailing(mailings[0], self.TYPE.pdf, self.folders)
		for m in reversed(mailings):
			r1 = re.compile('.*[-_\. ]' + m['barcode'] + '.*\.pdf')
			r2 = re.compile('.*[-_\. ]' + m['barcode'] + '.*\.jpg')
			local_pdf = list(filter(r1.match, self.local_files_cache))
			local_jpg = list(filter(r2.match, self.local_files_cache))
			if len(local_pdf) > 1 or len(local_jpg) > 1:
				print("Found multiple files for", m['barcode'])
				for f in local_pdf + local_jpg: print("  ", f)


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
			# TODO: Code may have errors, e.g. if some files already exist
			exists = [False] * len(self.TYPE.reverse_mapping)
			for f in ftypes:
				stored = False
				# Check for local file
				(file_org, local_file) = self.localFileMailing(m, f, self.folders)
				filename[f] = file_org if local_file is None else local_file

				if f == self.TYPE.full and local_file is not None:
					exists[self.TYPE.full] = local_file
				# Perform download, if required:
				if not exists[self.TYPE.full] and f != self.TYPE.full and \
					local_file is None and \
					not file_org in self.syncdb:
					stored = self.downloadMailing(m, f, filename[f])
					if stored:
						self.writeSyncDB(file_org)
						filename[f] = stored
						print ("Mailing stored to", filename[f])
					elif stored is False:
						#if self.verbose >= 0:
						print ("Mailing failed to download:", filename[f])
						continue
					elif stored is None:
						pass
				else:
					if self.verbose >= 3:
						print ("File", filename[f], "not required/already exists")
				exists[f] = os.path.isfile(filename[f])

				# Combine envelope & mailing into one file
				if f == self.TYPE.pdf and combine and not exists[self.TYPE.full] and exists[self.TYPE.envelope] and exists[self.TYPE.pdf]:
					r = self.combineFiles(filename[self.TYPE.envelope], filename[self.TYPE.pdf])
					if r:
						filename[self.TYPE.full] = r
						r_ren = self.writeTag(m, r)
						filename[self.TYPE.full] = r_ren if r_ren else r
						print ("Mailing combined to", r)
					else:
						print ("Failed: Combining mailing")

				# Rename files to include current labels
				ren = self.writeTag(m, filename[f])
				if ren:
					filename[f] = ren

				# Postproc script
				script_post = os.path.dirname(os.path.realpath(__file__)) + '/postproc.sh'
				if os.path.isfile(script_post) and f == self.TYPE.pdf and stored:
					fn = filename[self.TYPE.full] if combine else filename[self.TYPE.pdf]
					print(fn)
					if os.path.isfile(fn):
						run = subprocess.run([script_post, fn]) #, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
						#res = run.stdout.decode('utf-8')
						# TODO: Should store new filename to filename, but not really needed any more 


	def writeTag(self, mailing, local_file):
		"""
		Adds tags to filename (by renaming) for deleted/forwarded status
		"""
		if local_file is None or not os.path.isfile(local_file):
			return
		tag = ''
		if mailing['status'] == 'forwarded': tag = 'F'
		if mailing['status'] == 'forward_requested': tag = 'R'
		if mailing['status'] == 'destroyed': tag = 'D'
		if mailing['status'] == 'destroy_requested': tag = 'D'
		# Scan filename for <barcode>-<tags>
		b = mailing['barcode']
		m = re.match(".*("+b+")(-[A-Z]*)|.*("+b+")", local_file)
		if tag and (m.group(1) or m.group(3)):
			file_tag = m.group(2) if m.group(2) is not None else '-'
			if not tag in file_tag:
				file_tag += tag
			if 'F' in file_tag and 'R' in file_tag:
				file_tag = file_tag.replace('R', '')
			if m.group(2):
				pos = m.span(2)
				local_file_new = local_file[:pos[0]] + file_tag + local_file[pos[1]:]
			else:
				pos = m.span(0)[1]
				local_file_new = local_file[:pos] + file_tag + local_file[pos:]

			if local_file_new != local_file:
				if not os.path.isfile(local_file_new):
					os.rename(local_file, local_file_new)
					if self.verbose >= 1 or True:
						print("New Tags, renamed from:", local_file, "to:", local_file_new)
					return local_file_new
				else:
					if self.verbose >= 1:
						print("Renamed failed, file exists:", local_file_new)
		return None


def demo(user, password, args):
	"""	Demo/test routine: Login, list mailings, download one mailing """
	print ("=== Running test ====")
	D = Dropscan(user, password, args.v)
	if args.proxy:
		D.setProxy(args.proxy)
	D.login()

	print ("=== List of all mailings ===")
	for f in  [D.FILTER.received, D.FILTER.scanned, D.FILTER.forwarded, D.FILTER.destroyed]:
		print ("INBOX:", D.FILTER.reverse_mapping[f])
		l = D.getList(f)
		for (i,m) in enumerate(l):
			(filename,local_file) = D.localFileMailing(m, D.TYPE.envelope, D.folders)
			print ("%2d: %s %s. local envelope: %s" % (i, m['created_at'], m['barcode'], str(local_file)))

	print ("=== Download of last mailing to demo_*.pdf / .jpg ===")
	l = D.getList(D.FILTER.scanned)
	print (l[-1])
	# data1 = D.downloadMailing(l[-1], D.TYPE.thumb, 'demo_thumb.jpg')
	data2 = D.downloadMailing(l[-1], D.TYPE.envelope, 'demo_envelope.jpg')
	data3 = D.downloadMailing(l[-1], D.TYPE.pdf, 'demo_pdf.pdf')



if __name__ == '__main__':
	parser = argparse.ArgumentParser()
	# group = parser.add_usage_group(kind='any', required=True) # http://stackoverflow.com/questions/6722936
	parser.add_argument('-t', action='store_true', help='MODE: Run demo/test (login, list mailings, download)')
	parser.add_argument('-s', '--sync', action='store_true', help='MODE: One-way sync: Download missing files of all mailings to current folder')
	parser.add_argument('--nodb', action='store_true', help='Do not read Sync-DB (existence of local files is always checked)')
	parser.add_argument('--batches', action='store_true', help='MODE: List forwarding batches (only unsent)')
	parser.add_argument('-F', '--forward_mailing', help='MODE: Add the specified mailing slug to the first existing unsent forwarding batch')
	parser.add_argument('--forward_dir', action='append', help='Add all mailings in given directory to forwarding batch, if one exists. Must use -s.')
	parser.add_argument('--forward_older', type=int, default=-1, help='Add all mailings older than given number of days to forwarding batch, if one exists. Must use -s.')
	parser.add_argument('-c', '--check_multiple', action='store_true', help='MODE: Check if there are multiple files of the same mailing')
	parser.add_argument('-u', required=0, help='Dropscan username (may be specified in credentials file)')
	parser.add_argument('-p', required=0, help='Dropscan password (may be specified in credentials file)')
	parser.add_argument('--thumbs', action='store_true', help='Also sync thumbs of envelopses')
	parser.add_argument('-r', '--recursive',  action='store_true', help='Check all subfolders for locally existing files during sync.')
	parser.add_argument('-d', '--dir',  action='append', help='Additional folder(s) to check for locally existing files during sync.')
	parser.add_argument('--count', type=int, help='Number of list items to request from Dropscan (default 20)')
	parser.add_argument('--proxy', help='Use a proxy server to connect to Dropscan')
	parser.add_argument('-v', default=0, type=int, help='Set Verbosity [0..3]')
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
		if args.v >= 2: print ("Credentials loaded from", cred_file)
	except:
		if args.v >= 2: print ("Credentials file", cred_file, "not loaded.")

	if args.u: user = args.u
	if args.p: password = args.p

	D = Dropscan(user, password, args.v)
	if args.count:
		D.setListCount(args.count)
	if args.proxy:
		D.setProxy(args.proxy)
	# Search folders
	folders = []
	if args.recursive:
		folders = [d[0] for d in os.walk('.')]
	if args.dir:
		folders += args.dir
	if args.forward_dir:
		for d in args.forward_dir:
			if not (d.startswith('./') or d.startswith('/')):
				folders +=  ['./' + d]
			else:
				folders += [d]
	D.setLocalFolders(folders)

	# Test/demo
	if args.t:
		demo(user, password, args)

	# Sync
	elif args.sync:
		if not args.nodb:
			D.readSyncDB()
		# Do main Sync
		D.login()
		l1 = D.getList(D.FILTER.scanned)
		l2 = D.getList(D.FILTER.received)
		l3 = D.getList(D.FILTER.forwarded)
		l4 = D.getList(D.FILTER.destroyed)
		D.syncMailings(l4+l3+l2+l1, args.thumbs)
		#D.syncMailings(l2, args.thumbs)
		#D.syncMailings(l1, args.thumbs)

		# Auto-add mailings in folder to forward batch
		if args.forward_dir:
			D.addFolderstoBatch(l1+l2, args.forward_dir)
		if args.forward_older > -1:
			D.addOldtoBatch(l1+l2, args.forward_older)


	# Check for multiple files:
	elif args.check_multiple:
		if not args.count:
			D.setListCount(1000)
			D.login()
			l1 = D.getList(D.FILTER.scanned)
			l2 = D.getList(D.FILTER.received)
			l3 = D.getList(D.FILTER.forwarded)
			l4 = D.getList(D.FILTER.destroyed)
			D.checkMultiple(l4+l3+l2+l1)

	# List unsent forwarding batches
	elif args.batches:
		D.login()
		l = D.getBatches()
		print(json.dumps(l, sort_keys=True, indent=2))
		if len(l) == 0:
			print ("There is no unsent forwarding batch. Create one using the web interface")

	# Add mailing to forwarding batch
	elif args.forward_mailing:
		D.login()
		res = D.addMailingtoBatch(args.forward_mailing)
		print ("Result:", res)

	else:
		parser.print_help()
