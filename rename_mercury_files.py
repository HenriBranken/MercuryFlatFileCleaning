import re
import shutil
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "output"
TO_UPLOAD_DIR = OUTPUT_DIR / "to_upload"

PREFIXES = ["MercuryDailyEvents", "MercuryDailyUsers", "MercuryMonthlyEvents", "MercuryMonthlyUsers"]


def find_cleaned_file(output_dir: Path, prefix: str) -> tuple[Path, str]:
    """Return (path, ccyymm) for the single {prefix}_<ccyymm>_cleaned.csv file in output_dir, or raise."""
    filename_re = re.compile(rf"^{re.escape(prefix)}_(\d{{6}})_cleaned\.csv$")
    matches = sorted(
        (p, match.group(1))
        for p in output_dir.glob(f"{prefix}_*_cleaned.csv")
        if (match := filename_re.match(p.name))
    )
    if not matches:
        raise FileNotFoundError(f"No {prefix}_<ccyymm>_cleaned.csv file found in {output_dir}")
    if len(matches) > 1:
        raise ValueError(
            f"Multiple candidate cleaned files found for {prefix} in {output_dir}: "
            f"{[p.name for p, _ in matches]}."
        )
    return matches[0]


def main() -> None:
    found = {prefix: find_cleaned_file(OUTPUT_DIR, prefix) for prefix in PREFIXES}

    ccyymm_values = {ccyymm for _, ccyymm in found.values()}
    if len(ccyymm_values) > 1:
        detail = ", ".join(f"{prefix}={ccyymm}" for prefix, (_, ccyymm) in found.items())
        raise ValueError(f"Cleaned output files do not share the same ccyymm month tag: {detail}")

    TO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    for prefix, (src_path, _) in found.items():
        dest_path = TO_UPLOAD_DIR / f"{prefix}.csv"
        shutil.copy2(src_path, dest_path)
        print(f"Copied {src_path.name} -> {dest_path}")


if __name__ == "__main__":
    main()
