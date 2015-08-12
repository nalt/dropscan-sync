# dropscan-sync
Download/synchronize script for mail scanning service dropscan.de

Python-Skript zum Download und Synchronisieren der Briefumschläge und Scans von dropscan.de.
Benutzername und Password werden in einer Datei dropscan-credentials.json festgelegt, oder über die Argumente -u und -p.

Testen: ```dropscan.py -u ... -p ... -v 3 -t```

Download/sync aller Sendungen: ```dropscan.py -u ... -p ... -s```

```
usage: dropscan.py [-h] [-t] [-s] [-u U] [-p P] [--thumbs] [-d DIR] [-v V]
                   [--proxy PROXY]

optional arguments:
  -h, --help         show this help message and exit
  -t                 Run demo/test (login, list mailings, download)
  -s, --sync         One-way sync: Download missing files of all mailings to
                     current folder
  -u U               Dropscan username (may be specified in credentials file)
  -p P               Dropscan password (may be specified in credentials file)
  --thumbs           Also sync thumbs of envelopses
  -d DIR, --dir DIR  Additional folder(s) to check for locally existing files
                     during sync.
  -v V               Set Verbosity [0..3]
  --proxy PROXY      Use a proxy server to connect to Dropscan
```

No affiliation with dropscan.de
