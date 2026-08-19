Clean_Raw_Mercury.py - README
==============================

OVERVIEW
--------
Cleans the four raw Mercury exports (DailyEvents, DailyUsers, MonthlyEvents,
MonthlyUsers) in one run. Reads from the input/ folder, writes cleaned CSVs
to output/, and writes a summary report per dataset to reports/.

REQUIREMENTS
------------
Python 3 with the packages listed in requirements.txt (currently just pandas) installed.

VIRTUAL ENVIRONMENT SETUP
---------------------------
A .venv virtual environment is used for this project. To create it and
install dependencies into it:

    python -m venv .venv
    .venv\Scripts\Activate.ps1        (PowerShell; activate.bat for CMD prompt)
    pip install -r requirements.txt

(On cmd.exe, activate with .venv\Scripts\activate.bat instead; on Git Bash,
source .venv/Scripts/activate.)

Once activated, your terminal's python/pip point at .venv, and the script
can be run as described below.

HOW TO RUN
----------
From a terminal (with the virtual environment activated):

    python Clean_Raw_Mercury.py

The script locates its own input/, output/, and reports/ folders next to
itself, so it can be run from any working directory.

INPUT FILES
------------
Place exactly one file per dataset in the input/ folder, named:

    MercuryDailyEvents_yyyy-mm-dd.txt
    MercuryDailyUsers_yyyy-mm-dd.txt
    MercuryMonthlyEvents_yyyy-mm-dd.txt
    MercuryMonthlyUsers_yyyy-mm-dd.txt

where yyyy-mm-dd is the export date (e.g. 2026-08-02).

- Extension must be .txt (not .csv).
- The prefix is case-sensitive (MercuryDailyEvents, not mercurydailyevents).
- Exactly one matching file per prefix in input/ - zero or multiple files
  matching the same prefix will raise an error.
- Files must be ;-delimited UTF-8 text with record values quoted ("...").

Required raw header columns per file:

  DailyEvents:
    Date, CompanyCode, CompanyName, Country, Operation, EventType,
    DeviceCategory, SearchTerm, ContentType, ContentTitleEN, downloadLanguage,
    Theme, Route, uniqueUsers, DateRange

  DailyUsers:
    Date, CompanyCode, CompanyName, Country, Operation, sessions,
    uniqueUsers, DateRange

  MonthlyEvents:
    yearMonth, CompanyCode, CompanyName, Country, Operation, EventType,
    SearchTerm, DeviceCategory, ContentType, ContentTitleEN, downloadLanguage,
    Theme, Route, uniqueUsers, DateRange

  MonthlyUsers:
    yearMonth, CompanyCode, CompanyName, Country, Operation, sessions,
    uniqueUsers, DateRange

Extra columns (FileName, PipelineRunID, ImportDate, CreatedBy, DataSource,
UserType, newUniqueUsers, ...) are fine to include - they are ignored.

Rows with a blank key date (Date for the daily files, yearMonth for the
monthly files) are silently dropped rather than causing an error.

OUTPUT
------
For each dataset, the script writes:

  output/<Prefix>_<month_tag>_cleaned.csv
      ;-delimited UTF-8 CSV, cleaned and sorted.

  reports/<Prefix>_<month_tag>_report.txt
      Plain-text summary: input file name, raw/cleaned row counts,
      duplicate-row counts, rows dropped for being blank or missing their
      key date, and describe() stats for the numeric columns.

month_tag is yyyymm for the month BEFORE the input filename's date suffix
(the export date's month minus one). E.g. an input file dated 2026-08-02
produces month_tag 202607, so the output is MercuryDailyEvents_202607_cleaned.csv.
