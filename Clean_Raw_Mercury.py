import csv
import io
import re
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
INPUT_DIR = SCRIPT_DIR / "input"
OUTPUT_DIR = SCRIPT_DIR / "output"
REPORTS_DIR = SCRIPT_DIR / "reports"
DROPPED_AND_DUPES_DIR = SCRIPT_DIR / "dropped_and_dupes"


def find_default_input(directory: Path, prefix: str, filename_re: re.Pattern) -> Path:
    """Return the single {prefix}_yyyy-mm-dd.txt file in directory, or raise."""
    matches = sorted(p for p in directory.glob(f"{prefix}_*.txt") if filename_re.match(p.name))
    if not matches:
        raise FileNotFoundError(f"No {prefix}_yyyy-mm-dd.txt file found in {directory}")
    if len(matches) > 1:
        raise ValueError(
            f"Multiple candidate input files found in {directory}: "
            f"{[m.name for m in matches]}. Pass one explicitly."
        )
    return matches[0]


def month_tag_from_filename(path: Path, prefix: str, filename_re: re.Pattern) -> str:
    """Return yyyymm for the month before the filename's yyyy-mm-dd date suffix."""
    match = filename_re.match(path.name)
    if not match:
        raise ValueError(f"Filename '{path.name}' does not match expected pattern {prefix}_yyyy-mm-dd.txt")
    year, month = (int(g) for g in match.groups())
    # month_tag refers to the prior month's data, not the export date's month.
    year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return f"{year}{month:02d}"


def sum_numeric_cols(df: pd.DataFrame, sum_cols: list[str]) -> dict[str, int]:
    """Return {col: sum} for each of df's numeric sum_cols."""
    return {col: int(df[col].sum()) for col in sum_cols}


def write_report(
    reports_dir: Path,
    prefix: str,
    month_tag: str,
    input_path: Path,
    df_raw: pd.DataFrame,
    df_cleaned: pd.DataFrame,
    output_path: Path,
    rows_before_collapse: int,
    sums_before_collapse: dict[str, int],
    sums_after_collapse: dict[str, int],
) -> tuple[Path, str]:
    """Write the cleaning summary report and return (path, text)."""
    report_lines = [
        f"Input file: {input_path.name}",
        f"Raw row count: {len(df_raw)}",
        f"Raw duplicate rows: {int(df_raw.duplicated().sum())}",
        "=======================================================================",
        f"Month tag: {month_tag}",
        f"Blank/missing-key rows dropped: {len(df_raw) - rows_before_collapse}",
        f"Duplicate rows collapsed: {rows_before_collapse - len(df_cleaned)}",
        "=======================================================================",
        f"Cleaned row count: {len(df_cleaned)}",
        f"Cleaned duplicate rows: {int(df_cleaned.duplicated().sum())}",
        f"Output file: {output_path.name}",
        "=======================================================================",
        "Numeric field sums, before dedup (post blank-drop) vs after dedup:",
    ]
    name_width = max(len(col) for col in sums_before_collapse) + 2
    all_match = True
    for col in sums_before_collapse:
        before_sum = sums_before_collapse[col]
        after_sum = sums_after_collapse[col]
        is_match = before_sum == after_sum
        all_match = all_match and is_match
        verdict = "MATCH" if is_match else "MISMATCH"
        report_lines.append(
            f"  {col:<{name_width}}before={str(before_sum):<16}after={str(after_sum):<16}{verdict}"
        )
    report_lines.append(f"All numeric sums match: {all_match}")
    report_text = "\n".join(report_lines) + "\n"
    report_text += "\n\n\n" + df_cleaned.describe().to_string() + "\n"

    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"{prefix}_{month_tag}_report.txt"
    report_path.write_text(report_text, encoding="utf-8")

    return report_path, report_text


def read_semicolon_csv_protecting_backslashes(path: Path) -> pd.DataFrame:
    """Read a ;-delimited raw export, preserving literal backslashes outside \\" escapes."""
    with open(path, "r", encoding="utf-8") as f:
        raw_text = f.read()

    # Protect literal backslashes that aren't a genuine CSV \" escape (e.g. a company
    # name containing a literal backslash) by doubling them, so escapechar below only
    # ever consumes actual \" sequences and every other backslash survives intact.
    protected_text = re.sub(r'\\(?!")', r"\\\\", raw_text)

    return pd.read_csv(
        io.StringIO(protected_text), sep=";", engine="python", escapechar="\\",
        dtype=str, keep_default_na=False, encoding="utf-8",
    )


def blank_out_dash_cells(df: pd.DataFrame) -> pd.DataFrame:
    """Replace any cell whose value is exactly "-" (ignoring surrounding whitespace) with blank."""
    return df.apply(lambda col: col.mask(col.str.strip() == "-", ""))


def replace_icas_with_lyra(df: pd.DataFrame, col: str = "Operation") -> pd.DataFrame:
    """Replace every case-insensitive occurrence of "icas" in col with "Lyra" (e.g. "ICAS Latina" -> "Lyra Latina")."""
    df[col] = df[col].str.replace("icas", "Lyra", case=False, regex=True)
    return df


def collapse_duplicate_rows(
    df: pd.DataFrame, ls_cols: list[str], sum_cols: list[str], sort_cols: list[str]
) -> pd.DataFrame:
    """Sum sum_cols across rows that match on every other ls_cols value, collapsing duplicates into one row."""
    group_cols = [c for c in ls_cols if c not in sum_cols]
    collapsed = df.groupby(group_cols, as_index=False, sort=False)[sum_cols].sum()[ls_cols]
    return collapsed.sort_values(by=sort_cols, ascending=True).reset_index(drop=True)


def drop_blank_and_missing_key_rows(
    df: pd.DataFrame, ls_cols: list[str], key_col: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split df into (kept, dropped) rows; dropped rows are tagged Status='dropped blank'."""
    present_ls_cols = [c for c in ls_cols if c in df.columns]
    is_blank = df[present_ls_cols].apply(lambda col: col.str.strip() == "").all(axis=1)
    blank_rows = df.loc[is_blank]
    df = df.loc[~is_blank].copy()

    missing_key = df[key_col].str.strip() == ""
    missing_key_rows = df.loc[missing_key]
    df = df.loc[~missing_key].copy()

    dropped = pd.concat([blank_rows, missing_key_rows], ignore_index=True)[present_ls_cols].copy()
    dropped["Status"] = "dropped blank"
    return df, dropped


def extract_duplicate_group_rows(df: pd.DataFrame, ls_cols: list[str], sum_cols: list[str]) -> pd.DataFrame:
    """Return every row (all N, not N-1) in a group that collapse_duplicate_rows will later merge."""
    group_cols = [c for c in ls_cols if c not in sum_cols]
    dup_rows = df.loc[df.duplicated(subset=group_cols, keep=False), ls_cols].copy()
    dup_rows["Status"] = "duplicate collapsed"
    return dup_rows


def write_dropped_and_dupes(
    dropped_and_dupes_dir: Path, prefix: str, month_tag: str, ls_cols: list[str],
    dropped_blank: pd.DataFrame, duplicate_rows: pd.DataFrame,
) -> Path:
    """Combine dropped-blank and duplicate-group rows into one Status-tagged audit CSV."""
    combined = pd.concat([dropped_blank, duplicate_rows], ignore_index=True).reindex(columns=ls_cols + ["Status"])
    dropped_and_dupes_dir.mkdir(parents=True, exist_ok=True)
    path = dropped_and_dupes_dir / f"{prefix}_{month_tag}_dropped_and_dupes.csv"
    combined.to_csv(path, sep=";", index=False, encoding="utf-8", quoting=csv.QUOTE_MINIMAL)
    return path


# ---- 1. MercuryDailyEvents ----

LS_COLS_DE = [
    "Date", "CompanyCode", "CompanyName", "Country", "Operation", "EventType", "DeviceCategory",
    "SearchTerm", "ContentType", "ContentTitle", "DownloadLanguage", "Theme", "Route",
    "UniqueUsers", "DateRange",
]
LS_STRING_COLS_DE = [
    "CompanyCode", "CompanyName", "Country", "Operation", "EventType", "DeviceCategory",
    "SearchTerm", "ContentType", "ContentTitle", "DownloadLanguage", "Theme", "Route",
    "DateRange",
]
LS_INT_COLS_DE = ["UniqueUsers"]

RENAME_MAP_DE = {
    "ContentTitleEN": "ContentTitle",
    "downloadLanguage": "DownloadLanguage",
    "uniqueUsers": "UniqueUsers",
}

SORT_COLS_DE = [
    "Date", "CompanyCode", "CompanyName", "Country", "Operation", "EventType",
    "DeviceCategory", "SearchTerm", "ContentType", "ContentTitle",
]

PREFIX_DE = "MercuryDailyEvents"
FILENAME_RE_DE = re.compile(r"^MercuryDailyEvents_(\d{4})-(\d{2})-\d{2}\.txt$")


def clean_de(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Clean a raw MercuryDailyEvents dataframe into the final schema."""
    df = df.rename(columns=RENAME_MAP_DE)

    df, dropped_de = drop_blank_and_missing_key_rows(df, LS_COLS_DE, "Date")

    # %f always zero-pads to 6-digit microseconds; slicing off the last 3 leaves milliseconds.
    df["Date"] = pd.to_datetime(df["Date"], format="%Y-%m-%d").dt.strftime("%Y-%m-%d %H:%M:%S.%f").str[:-3]

    df = df[LS_COLS_DE]

    for col in LS_STRING_COLS_DE:
        df[col] = df[col].str.strip().str.replace(r"\s+", " ", regex=True)

    df = replace_icas_with_lyra(df)

    for col in LS_INT_COLS_DE:
        df[col] = df[col].replace("", "0").astype(int)

    df = df.sort_values(by=SORT_COLS_DE, ascending=True).reset_index(drop=True)

    return df, dropped_de


# ---- 2. MercuryDailyUsers ----

LS_COLS_DU = [
    "Date", "CompanyCode", "CompanyName", "Country", "Operation", "Sessions", "UniqueUsers", "DateRange",
]
LS_STRING_COLS_DU = [
    "CompanyCode", "CompanyName", "Country", "Operation", "DateRange",
]
LS_INT_COLS_DU = ["Sessions", "UniqueUsers"]

SORT_COLS_DU = ["Date", "CompanyCode", "CompanyName", "Country", "Operation"]

PREFIX_DU = "MercuryDailyUsers"
FILENAME_RE_DU = re.compile(r"^MercuryDailyUsers_(\d{4})-(\d{2})-\d{2}\.txt$")


def clean_du(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Clean a raw MercuryDailyUsers dataframe into the final schema."""
    df = df.rename(columns=lambda c: c[:1].upper() + c[1:] if c else c)

    df, dropped_du = drop_blank_and_missing_key_rows(df, LS_COLS_DU, "Date")

    # %f always zero-pads to 6-digit microseconds; slicing off the last 3 leaves milliseconds.
    df["Date"] = pd.to_datetime(df["Date"], format="%Y-%m-%d").dt.strftime("%Y-%m-%d %H:%M:%S.%f").str[:-3]

    df = df[LS_COLS_DU]

    for col in LS_STRING_COLS_DU:
        df[col] = df[col].str.strip().str.replace(r"\s+", " ", regex=True)

    df = replace_icas_with_lyra(df)

    for col in LS_INT_COLS_DU:
        df[col] = df[col].replace("", "0").astype(int)

    df = df.sort_values(by=SORT_COLS_DU, ascending=True).reset_index(drop=True)

    return df, dropped_du


# ---- 3. MercuryMonthlyEvents ----

LS_COLS_ME = [
    "MonthDate", "CompanyCode", "CompanyName", "Country", "Operation", "EventType", "SearchTerm",
    "DeviceCategory", "ContentType", "ContentTitle", "DownloadLanguage", "Theme", "Route",
    "UniqueUsers", "DateRange",
]
LS_STRING_COLS_ME = [
    "CompanyCode", "CompanyName", "Country", "Operation", "EventType", "SearchTerm",
    "DeviceCategory", "ContentType", "ContentTitle", "DownloadLanguage", "Theme", "Route",
    "DateRange",
]
LS_INT_COLS_ME = ["UniqueUsers"]

RENAME_MAP_ME = {
    "yearMonth": "MonthDate",
    "ContentTitleEN": "ContentTitle",
    "downloadLanguage": "DownloadLanguage",
    "uniqueUsers": "UniqueUsers",
}

SORT_COLS_ME = ["MonthDate", "CompanyCode", "CompanyName", "Country", "Operation", "EventType"]

PREFIX_ME = "MercuryMonthlyEvents"
FILENAME_RE_ME = re.compile(r"^MercuryMonthlyEvents_(\d{4})-(\d{2})-\d{2}\.txt$")


def clean_me(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Clean a raw MercuryMonthlyEvents dataframe into the final schema."""
    df = df.rename(columns=RENAME_MAP_ME)

    df, dropped_me = drop_blank_and_missing_key_rows(df, LS_COLS_ME, "MonthDate")

    # Raw MonthDate values are "yyyy-mm" (no day); %m-only parsing defaults the day to 1.
    # %f always zero-pads to 6-digit microseconds; slicing off the last 3 leaves milliseconds.
    df["MonthDate"] = pd.to_datetime(df["MonthDate"], format="%Y-%m").dt.strftime("%Y-%m-%d %H:%M:%S.%f").str[:-3]

    df = df[LS_COLS_ME]

    for col in LS_STRING_COLS_ME:
        df[col] = df[col].str.strip().str.replace(r"\s+", " ", regex=True)

    df = replace_icas_with_lyra(df)

    for col in LS_INT_COLS_ME:
        df[col] = df[col].replace("", "0").astype(int)

    df = df.sort_values(by=SORT_COLS_ME, ascending=True).reset_index(drop=True)

    return df, dropped_me


# ---- 4. MercuryMonthlyUsers ----

LS_COLS_MU = ["MonthDate", "CompanyCode", "CompanyName", "Country", "Operation", "Sessions", "UniqueUsers", "DateRange"]
LS_STRING_COLS_MU = ["CompanyCode", "CompanyName", "Country", "Operation", "DateRange"]
LS_INT_COLS_MU = ["Sessions", "UniqueUsers"]

RENAME_MAP_MU = {
    "yearMonth": "MonthDate",
    "sessions": "Sessions",
    "uniqueUsers": "UniqueUsers",
}

SORT_COLS_MU = ["MonthDate", "CompanyCode", "CompanyName", "Country", "Operation"]

PREFIX_MU = "MercuryMonthlyUsers"
FILENAME_RE_MU = re.compile(r"^MercuryMonthlyUsers_(\d{4})-(\d{2})-\d{2}\.txt$")


def clean_mu(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Clean a raw MercuryMonthlyUsers dataframe into the final schema."""
    df = df.rename(columns=RENAME_MAP_MU)

    df, dropped_mu = drop_blank_and_missing_key_rows(df, LS_COLS_MU, "MonthDate")

    # Raw MonthDate values are "yyyy-mm" (no day); %m-only parsing defaults the day to 1.
    # %f always zero-pads to 6-digit microseconds; slicing off the last 3 leaves milliseconds.
    df["MonthDate"] = pd.to_datetime(df["MonthDate"], format="%Y-%m").dt.strftime("%Y-%m-%d %H:%M:%S.%f").str[:-3]

    df = df[LS_COLS_MU]

    for col in LS_STRING_COLS_MU:
        df[col] = df[col].str.strip().str.replace(r"\s+", " ", regex=True)

    df = replace_icas_with_lyra(df)

    for col in LS_INT_COLS_MU:
        df[col] = df[col].replace("", "0").astype(int)

    df = df.sort_values(by=SORT_COLS_MU, ascending=True).reset_index(drop=True)

    return df, dropped_mu


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    DROPPED_AND_DUPES_DIR.mkdir(parents=True, exist_ok=True)

    # DailyEvents
    input_file_de = None  # e.g. "input/MercuryDailyEvents_2026-08-02.txt"
    input_path_de = Path(input_file_de).resolve() if input_file_de else find_default_input(INPUT_DIR, PREFIX_DE, FILENAME_RE_DE)
    month_tag_de = month_tag_from_filename(input_path_de, PREFIX_DE, FILENAME_RE_DE)

    df_raw_de = read_semicolon_csv_protecting_backslashes(input_path_de)
    df_raw_de = blank_out_dash_cells(df_raw_de)
    df_cleaned_de, dropped_blank_de = clean_de(df_raw_de)
    rows_before_collapse_de = len(df_cleaned_de)
    sums_before_collapse_de = sum_numeric_cols(df_cleaned_de, LS_INT_COLS_DE)
    duplicate_rows_de = extract_duplicate_group_rows(df_cleaned_de, LS_COLS_DE, LS_INT_COLS_DE)
    df_cleaned_de = collapse_duplicate_rows(df_cleaned_de, LS_COLS_DE, LS_INT_COLS_DE, SORT_COLS_DE)
    sums_after_collapse_de = sum_numeric_cols(df_cleaned_de, LS_INT_COLS_DE)

    output_path_de = OUTPUT_DIR / f"{PREFIX_DE}_{month_tag_de}_cleaned.csv"
    df_cleaned_de.to_csv(output_path_de, sep=";", index=False, encoding="utf-8", quoting=csv.QUOTE_MINIMAL)
    print(f"Cleaned {len(df_cleaned_de)} rows -> {output_path_de}")

    dropped_and_dupes_path_de = write_dropped_and_dupes(
        DROPPED_AND_DUPES_DIR, PREFIX_DE, month_tag_de, LS_COLS_DE, dropped_blank_de, duplicate_rows_de,
    )
    print(f"Dropped/dupes audit ({len(dropped_blank_de) + len(duplicate_rows_de)} rows) -> {dropped_and_dupes_path_de}")

    report_path_de, report_text_de = write_report(
        reports_dir=REPORTS_DIR,
        prefix=PREFIX_DE,
        month_tag=month_tag_de,
        input_path=input_path_de,
        df_raw=df_raw_de,
        df_cleaned=df_cleaned_de,
        output_path=output_path_de,
        rows_before_collapse=rows_before_collapse_de,
        sums_before_collapse=sums_before_collapse_de,
        sums_after_collapse=sums_after_collapse_de,
    )
    print(report_text_de)
    print(f"Report written -> {report_path_de}")

    # DailyUsers
    input_file_du = None  # e.g. "input/MercuryDailyUsers_2026-08-02.txt"
    input_path_du = Path(input_file_du).resolve() if input_file_du else find_default_input(INPUT_DIR, PREFIX_DU, FILENAME_RE_DU)
    month_tag_du = month_tag_from_filename(input_path_du, PREFIX_DU, FILENAME_RE_DU)

    df_raw_du = pd.read_csv(input_path_du, sep=";", dtype=str, keep_default_na=False, encoding="utf-8")
    df_raw_du = blank_out_dash_cells(df_raw_du)
    df_cleaned_du, dropped_blank_du = clean_du(df_raw_du)
    rows_before_collapse_du = len(df_cleaned_du)
    sums_before_collapse_du = sum_numeric_cols(df_cleaned_du, LS_INT_COLS_DU)
    duplicate_rows_du = extract_duplicate_group_rows(df_cleaned_du, LS_COLS_DU, LS_INT_COLS_DU)
    df_cleaned_du = collapse_duplicate_rows(df_cleaned_du, LS_COLS_DU, LS_INT_COLS_DU, SORT_COLS_DU)
    sums_after_collapse_du = sum_numeric_cols(df_cleaned_du, LS_INT_COLS_DU)

    output_path_du = OUTPUT_DIR / f"{PREFIX_DU}_{month_tag_du}_cleaned.csv"
    df_cleaned_du.to_csv(output_path_du, sep=";", index=False, encoding="utf-8", quoting=csv.QUOTE_MINIMAL)
    print(f"Cleaned {len(df_cleaned_du)} rows -> {output_path_du}")

    dropped_and_dupes_path_du = write_dropped_and_dupes(
        DROPPED_AND_DUPES_DIR, PREFIX_DU, month_tag_du, LS_COLS_DU, dropped_blank_du, duplicate_rows_du,
    )
    print(f"Dropped/dupes audit ({len(dropped_blank_du) + len(duplicate_rows_du)} rows) -> {dropped_and_dupes_path_du}")

    report_path_du, report_text_du = write_report(
        reports_dir=REPORTS_DIR,
        prefix=PREFIX_DU,
        month_tag=month_tag_du,
        input_path=input_path_du,
        df_raw=df_raw_du,
        df_cleaned=df_cleaned_du,
        output_path=output_path_du,
        rows_before_collapse=rows_before_collapse_du,
        sums_before_collapse=sums_before_collapse_du,
        sums_after_collapse=sums_after_collapse_du,
    )
    print(report_text_du)
    print(f"Report written -> {report_path_du}")

    # MonthlyEvents
    input_file_me = None  # e.g. "input/MercuryMonthlyEvents_2026-08-02.txt"
    input_path_me = Path(input_file_me).resolve() if input_file_me else find_default_input(INPUT_DIR, PREFIX_ME, FILENAME_RE_ME)
    month_tag_me = month_tag_from_filename(input_path_me, PREFIX_ME, FILENAME_RE_ME)

    df_raw_me = read_semicolon_csv_protecting_backslashes(input_path_me)
    df_raw_me = blank_out_dash_cells(df_raw_me)
    df_cleaned_me, dropped_blank_me = clean_me(df_raw_me)
    rows_before_collapse_me = len(df_cleaned_me)
    sums_before_collapse_me = sum_numeric_cols(df_cleaned_me, LS_INT_COLS_ME)
    duplicate_rows_me = extract_duplicate_group_rows(df_cleaned_me, LS_COLS_ME, LS_INT_COLS_ME)
    df_cleaned_me = collapse_duplicate_rows(df_cleaned_me, LS_COLS_ME, LS_INT_COLS_ME, SORT_COLS_ME)
    sums_after_collapse_me = sum_numeric_cols(df_cleaned_me, LS_INT_COLS_ME)

    output_path_me = OUTPUT_DIR / f"{PREFIX_ME}_{month_tag_me}_cleaned.csv"
    df_cleaned_me.to_csv(output_path_me, sep=";", index=False, encoding="utf-8", quoting=csv.QUOTE_MINIMAL)
    print(f"Cleaned {len(df_cleaned_me)} rows -> {output_path_me}")

    dropped_and_dupes_path_me = write_dropped_and_dupes(
        DROPPED_AND_DUPES_DIR, PREFIX_ME, month_tag_me, LS_COLS_ME, dropped_blank_me, duplicate_rows_me,
    )
    print(f"Dropped/dupes audit ({len(dropped_blank_me) + len(duplicate_rows_me)} rows) -> {dropped_and_dupes_path_me}")

    report_path_me, report_text_me = write_report(
        reports_dir=REPORTS_DIR,
        prefix=PREFIX_ME,
        month_tag=month_tag_me,
        input_path=input_path_me,
        df_raw=df_raw_me,
        df_cleaned=df_cleaned_me,
        output_path=output_path_me,
        rows_before_collapse=rows_before_collapse_me,
        sums_before_collapse=sums_before_collapse_me,
        sums_after_collapse=sums_after_collapse_me,
    )
    print(report_text_me)
    print(f"Report written -> {report_path_me}")

    # MonthlyUsers
    input_file_mu = None  # e.g. "input/MercuryMonthlyUsers_2026-08-02.txt"
    input_path_mu = Path(input_file_mu).resolve() if input_file_mu else find_default_input(INPUT_DIR, PREFIX_MU, FILENAME_RE_MU)
    month_tag_mu = month_tag_from_filename(input_path_mu, PREFIX_MU, FILENAME_RE_MU)

    df_raw_mu = pd.read_csv(input_path_mu, sep=";", dtype=str, keep_default_na=False, encoding="utf-8")
    df_raw_mu = blank_out_dash_cells(df_raw_mu)
    df_cleaned_mu, dropped_blank_mu = clean_mu(df_raw_mu)
    rows_before_collapse_mu = len(df_cleaned_mu)
    sums_before_collapse_mu = sum_numeric_cols(df_cleaned_mu, LS_INT_COLS_MU)
    duplicate_rows_mu = extract_duplicate_group_rows(df_cleaned_mu, LS_COLS_MU, LS_INT_COLS_MU)
    df_cleaned_mu = collapse_duplicate_rows(df_cleaned_mu, LS_COLS_MU, LS_INT_COLS_MU, SORT_COLS_MU)
    sums_after_collapse_mu = sum_numeric_cols(df_cleaned_mu, LS_INT_COLS_MU)

    output_path_mu = OUTPUT_DIR / f"{PREFIX_MU}_{month_tag_mu}_cleaned.csv"
    df_cleaned_mu.to_csv(output_path_mu, sep=";", index=False, encoding="utf-8", quoting=csv.QUOTE_MINIMAL)
    print(f"Cleaned {len(df_cleaned_mu)} rows -> {output_path_mu}")

    dropped_and_dupes_path_mu = write_dropped_and_dupes(
        DROPPED_AND_DUPES_DIR, PREFIX_MU, month_tag_mu, LS_COLS_MU, dropped_blank_mu, duplicate_rows_mu,
    )
    print(f"Dropped/dupes audit ({len(dropped_blank_mu) + len(duplicate_rows_mu)} rows) -> {dropped_and_dupes_path_mu}")

    report_path_mu, report_text_mu = write_report(
        reports_dir=REPORTS_DIR,
        prefix=PREFIX_MU,
        month_tag=month_tag_mu,
        input_path=input_path_mu,
        df_raw=df_raw_mu,
        df_cleaned=df_cleaned_mu,
        output_path=output_path_mu,
        rows_before_collapse=rows_before_collapse_mu,
        sums_before_collapse=sums_before_collapse_mu,
        sums_after_collapse=sums_after_collapse_mu,
    )
    print(report_text_mu)
    print(f"Report written -> {report_path_mu}")

    print("Cleaned outputs:")
    for label, out_path, rpt_path, dd_path in [
        ("DailyEvents",   output_path_de, report_path_de, dropped_and_dupes_path_de),
        ("DailyUsers",    output_path_du, report_path_du, dropped_and_dupes_path_du),
        ("MonthlyEvents", output_path_me, report_path_me, dropped_and_dupes_path_me),
        ("MonthlyUsers",  output_path_mu, report_path_mu, dropped_and_dupes_path_mu),
    ]:
        print(f"  {label:14s} -> {out_path.name}  (report: {rpt_path.name})  (dropped/dupes: {dd_path.name})")


if __name__ == "__main__":
    main()
