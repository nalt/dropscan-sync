# dropscan-sync
Download/synchronize script and class for the German mail scanning service dropscan.de. // Python-Skript zum Download und Synchronisieren der Scans (Dokument und Briefumschläge) von dropscan.de.

Kann als Klasse oder Shell-Skript verwendet werden.
Benutzername und Password werden in einer Datei dropscan-credentials.json festgelegt, oder über die Argumente -u und -p.

- Funktionen (siehe MODE bei Kommandozeile):
 
  -t (test), -s (sync), --batches, -c

- Test

  ```dropscan.py -u ... -p ... -v 3 -t```
- Download/sync aller Sendungen: Nur nicht vorhandene Dateien werden heruntergeladen.

  ```dropscan.py -u ... -p ... -s```
-  Heruntergeladene Sendungen zu einem vorhandenen Forward-Batch hinzufügen: Dazu die gewünschten Sendungen in einen Ordner verschieben (z.B. ./forward/). Die Dateien dürfen nicht umbenannt werden.
  
   ```dropscan.py -u ... -p ... --forward_dir ./forward```

## Externe Tools

- `convert, pdftk` um Sendung + Umschlag zusammenzufügen (combineFiles)
- `./postproc.sh` wird nach Download einer neuen Sendung ausgeführt, falls das Skript existiert
## Kommandozeile
```
dropscan.py [-h] [-t] [-s] [--nodb] [--batches] [-F FORWARD_MAILING]
            [--forward_dir FORWARD_DIR] [--forward_older FORWARD_OLDER] [-c] [-u U] [-p P]
            [--thumbs] [-r] [-d DIR] [--count COUNT] [--proxy PROXY] [-v V]

optional arguments:
  -h, --help            show this help message and exit
  -t                    MODE: Run demo/test (login, list mailings, download)
  -s, --sync            MODE: One-way sync: Download missing files of all mailings to current
                        folder
  --nodb                Do not read Sync-DB (existence of local files is always checked)
  --batches             MODE: List forwarding batches (only unsent)
  -F FORWARD_MAILING, --forward_mailing FORWARD_MAILING
                        MODE: Add the specified mailing slug to the first existing unsent
                        forwarding batch
  --forward_dir FORWARD_DIR
                        Add all mailings in given directory to forwarding batch, if one exists.
                        Must use -s.
  --forward_older FORWARD_OLDER
                        Add all mailings older than given number of days to forwarding batch, if
                        one exists. Must use -s.
  -c, --check_multiple  MODE: Check if there are multiple files of the same mailing
  -u U                  Dropscan username (may be specified in credentials file)
  -p P                  Dropscan password (may be specified in credentials file)
  --thumbs              Also sync thumbs of envelopses
  -r, --recursive       Check all subfolders for locally existing files during sync.
  -d DIR, --dir DIR     Additional folder(s) to check for locally existing files during sync.
  --count COUNT         Number of list items to request from Dropscan (default 20)
  --proxy PROXY         Use a proxy server to connect to Dropscan
  -v V                  Set Verbosity [0..3]

```

No affiliation with dropscan.de
