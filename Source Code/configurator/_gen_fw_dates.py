"""
_gen_fw_dates.py  —  Generate fw_dates.json for the OCC configurator build.

Place this script alongside build_exe.bat and your .uf2 firmware files.
For each non-nuke .uf2 file in the current directory, it looks for a
matching .uf2.date sidecar file (e.g. Wired_Guitar_Controller.uf2.date).
If found, the date string inside is used.  Otherwise, the file's
last-modified timestamp is used as a fallback.

The output fw_dates.json maps UF2 filenames to build date strings, e.g.:
    {
      "Wired_Guitar_Controller.uf2": "Mar 13 2026",
      "Wired_Drum_Controller.uf2": "Mar 10 2026"
    }
"""

import os
import json
import datetime

dates = {}

for f in os.listdir('.'):
    if not f.lower().endswith('.uf2'):
        continue
    if f.lower() == 'resetfw.uf2':
        continue

    sidecar = f + '.date'
    if os.path.isfile(sidecar):
        dates[f] = open(sidecar).read().strip()
    else:
        mtime = os.path.getmtime(f)
        dt = datetime.datetime.fromtimestamp(mtime)
        dates[f] = dt.strftime('%b %d %Y')

with open('fw_dates.json', 'w') as out:
    json.dump(dates, out, indent=2)

print('  fw_dates.json:', json.dumps(dates, indent=2))
