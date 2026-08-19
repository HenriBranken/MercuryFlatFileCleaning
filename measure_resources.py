"""Measure wall time, CPU time, peak memory, and disk footprint of Clean_Raw_Mercury.py.

Runs the pipeline in-process (so peak memory reflects the same single-process
execution a normal `python Clean_Raw_Mercury.py` run produces), then reports:

- Wall-clock time: time.perf_counter()
- CPU time: time.process_time() (actual processor time used, excludes idle/IO wait)
- Peak working-set memory: Windows GetProcessMemoryInfo API (same counter Task
  Manager shows), via ctypes -- no extra packages required.
- Disk footprint: sizes of the raw input files and the CSVs/reports this run produced.

Usage:
    python measure_resources.py
"""
import ctypes
import runpy
import time
from ctypes import wintypes
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TARGET_SCRIPT = SCRIPT_DIR / "Clean_Raw_Mercury.py"


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


_kernel32 = ctypes.windll.kernel32
_psapi = ctypes.windll.psapi
_kernel32.GetCurrentProcess.restype = wintypes.HANDLE
_psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD]
_psapi.GetProcessMemoryInfo.restype = wintypes.BOOL


def peak_working_set_mb() -> float:
    counters = PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
    handle = _kernel32.GetCurrentProcess()
    if not _psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
        raise ctypes.WinError()
    return counters.PeakWorkingSetSize / (1024 * 1024)


def folder_size_kb(folder: Path, pattern: str) -> float:
    return sum(p.stat().st_size for p in folder.glob(pattern)) / 1024


def main() -> None:
    wall_start = time.perf_counter()
    cpu_start = time.process_time()

    runpy.run_path(str(TARGET_SCRIPT), run_name="__main__")

    cpu_time = time.process_time() - cpu_start
    wall_time = time.perf_counter() - wall_start

    print("\n" + "=" * 60)
    print("RESOURCE MEASUREMENT")
    print("=" * 60)
    print(f"Wall-clock time  : {wall_time:.3f} s")
    print(f"CPU time         : {cpu_time:.3f} s")
    print(f"Peak working set : {peak_working_set_mb():.1f} MB")
    print(f"Input footprint  : {folder_size_kb(SCRIPT_DIR / 'input', '*.txt'):.1f} KB")
    print(f"Output footprint : {folder_size_kb(SCRIPT_DIR / 'output', 'Mercury*_cleaned.csv'):.1f} KB")
    print(f"Reports footprint: {folder_size_kb(SCRIPT_DIR / 'reports', 'Mercury*_report.txt'):.1f} KB")


if __name__ == "__main__":
    main()
