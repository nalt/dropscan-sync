# dropscan-sync
Download/synchronize script and class for mail scanning service dropscan.de.

Python-Skript zum Download und Synchronisieren der Briefumschläge und Scans von dropscan.de.
Kann als Klasse oder Shell-Skript verwendet werden.
Benutzername und Password werden in einer Datei dropscan-credentials.json festgelegt, oder über die Argumente -u und -p.

- Test

  ```dropscan.py -u ... -p ... -v 3 -t```
- Download/sync aller Sendungen: Nur nicht vorhandene Dateien werden heruntergeladen.

  ```dropscan.py -u ... -p ... -s```
-  Heruntergeladenene Sendungen zu einem vorhandenen Forward-Batch hinzufügen: Dazu die genwünschten Sendungen in einen Ordner verschieben (z.B. ./forward/). Die Dateien dürfen nicht umbenannt werden.
  
  ```dropscan.py -u ... -p ... --forward_dir ./forward```

```
usage: dropscan.py [-h] [-t] [-s] [--batches] [-F FORWARD_MAILING]
                   [--forward_dir FORWARD_DIR] [-u U] [-p P] [--thumbs]
                   [-d DIR] [-v V] [--proxy PROXY]

optional arguments:
  -h, --help            show this help message and exit
  -t                    Run demo/test (login, list mailings, download)
  -s, --sync            One-way sync: Download missing files of all mailings
                        to current folder
  --batches             List forwarding batches (only unsent)
  -F FORWARD_MAILING, --forward_mailing FORWARD_MAILING
                        Add the specified mailing slug to the first existing
                        unsent forwarding batch
  --forward_dir FORWARD_DIR
                        Add all mailings in given directory to forwarding
                        batch. Must use -s.
  -u U                  Dropscan username (may be specified in credentials
                        file)
  -p P                  Dropscan password (may be specified in credentials
                        file)
  --thumbs              Also sync thumbs of envelopes
  -d DIR, --dir DIR     Additional folder(s) to check for locally existing
                        files during sync.
  -v V                  Set Verbosity [0..3]
  --proxy PROXY         Use a proxy server to connect to Dropscan
```

No affiliation with dropscan.de
