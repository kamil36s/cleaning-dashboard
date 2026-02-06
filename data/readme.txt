README (data folder)
====================

This is a VERY DETAILED, idiot-friendly guide to how the data folder works.
Keep it simple: you only copy files into /data/raw and run one command.


1) What this folder is for
--------------------------
The /data folder is where all habit data inputs and outputs live.

Inputs (you put these here):
- /data/raw/db  -> .db backup files from Loop Habits
- /data/raw/csv -> .csv exports (Checkmarks.csv)

Outputs (the script generates these):
- /data/habit-data.json  -> final clean data for review
- /js/habit-data.js      -> same data, used by the widget
- /data/conflicts.json   -> list of conflicts (never overwritten)
- /data/report.json      -> technical report (machine-readable)
- /data/report.html      -> human friendly report (newest on top)

IMPORTANT: Do not edit output files by hand. They are regenerated every import.


2) The ONE command you run
--------------------------
From project root:
  python scripts\build-habits.py

Shortcut (same thing):
  npm run habits:import

Windows double-click shortcut:
  data\import-habits.bat
  (keeps the window open so you can read the summary)

Timezone matters. CSV dates are converted to timestamp at 00:00
in the timezone you choose. Default is Europe/Warsaw.

Common choices:
- --tz Europe/Warsaw   (default, CET/CEST)
- --tz UTC             (simple, consistent)
- --tz local           (your current system timezone)


3) What happens when you drop Checkmarks.csv (step by step)
-----------------------------------------------------------
Example: you copy Checkmarks.csv into /data/raw/csv.

Then you run:
  python scripts\build-habits.py

The script does this, in order:
1. Finds the newest .db file in /data/raw/db
2. Finds ALL .csv files in /data/raw/csv (including subfolders)
3. Reads the DB:
   - habits list (name, type, unit)
   - repetitions (timestamp, value)
4. Reads each CSV:
   - tries encoding: utf-8, cp1250, latin-1
   - parses rows into (habit, date, value)
5. Merges all data:
   - conflict = same habit + same date + different value
   - conflicts are NOT overwritten
   - first value is kept (DB is read before CSV)
6. Writes outputs:
   - data/habit-data.json
   - js/habit-data.js
   - data/conflicts.json
   - data/report.json
   - data/report.html (newest section on top)


4) CSV formats supported (two types)
------------------------------------
Type A: "header" format (many habits in one file)

Example:
  Date,Concerta/Atenza,Medikinet,Reading
  2025-01-01,1,0,30
  2025-01-02,1,1,25

Rules:
- first column must be Date (or Day)
- each habit is a column
- empty cells are skipped

Type B: "simple" format (one habit per folder)

Example path:
  data/raw/csv/010 Pregabalin/Checkmarks.csv

Example file content:
  2025-01-01,1
  2025-01-02,0

Rules:
- first column is date YYYY-MM-DD
- second column is value
- habit name is taken from the PARENT folder name
  (leading numbers are removed)
  Example: "010 Pregabalin" -> "Pregabalin"


5) Files that are ignored on purpose
------------------------------------
- Scores.csv  -> ignored
- Habits.csv  -> ignored
They are skipped but still listed in the report.


6) Conflict rules (VERY IMPORTANT)
----------------------------------
Conflict = same habit + same date + different value.

What happens:
- the existing value stays
- the incoming value is NOT written
- the conflict is saved to data/conflicts.json
- report.html shows conflicts

This is to guarantee: "no source of truth, never overwrite".

Which value wins?
- DB is read before CSV.
- For same date, DB value will stay if CSV differs.
- For multiple CSV files, the first one in sorted path order wins.


7) How the widget gets data
---------------------------
The widget reads:
  /js/habit-data.js

That file is generated on every import, so after you run the script
the widget automatically sees the new data.


8) How to verify the import
---------------------------
Open:
  data/report.html
and check the newest section at the TOP.

You will see:
- how many habits
- how many points read
- how many kept
- conflicts (if any)
- which files were used


9) Typical weekly workflow
--------------------------
1. Copy new DB file into /data/raw/db
2. Copy new Checkmarks.csv into /data/raw/csv
3. Run:
     python scripts\build-habits.py
4. Open data/report.html and check warnings
5. Open index.html and test the widget


10) If something looks wrong
----------------------------
- Check data/report.html (it lists skipped rows and errors)
- Check data/conflicts.json (maybe a conflict blocked a value)
- Verify timezone (--tz). Wrong tz can shift a date by 1 day.
- Make sure the CSV format matches one of the supported formats.


11) Optional: run only specific files
-------------------------------------
You can point to specific files:
  python scripts\build-habits.py --db "data/raw/db/YourFile.db" --csv "data/raw/csv/Checkmarks.csv"

Or a whole folder:
  python scripts\build-habits.py --csv "data/raw/csv"


12) Summary (short)
------------------
- Put DB in /data/raw/db
- Put CSV in /data/raw/csv
- Run the script
- Check report.html
- Widget reads js/habit-data.js

Done.
