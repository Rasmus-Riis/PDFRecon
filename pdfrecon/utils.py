"""
Utilities Module

Helper functions for file operations, imports, and data formatting.
"""

import hashlib
import sys
from pathlib import Path
from datetime import datetime, timezone
from tkinter import messagebox


def _import_with_fallback(module_name, import_name, install_cmd):
    """Safely import optional dependencies with user-friendly error messages."""
    try:
        return __import__(module_name, fromlist=[import_name])
    except ImportError:
        error_msg = f"The {import_name} library is not installed.\n\nPlease run 'pip install {install_cmd}' in your terminal to use this program."
        messagebox.showerror("Missing Library", error_msg)
        sys.exit(1)


def md5_file(fp: Path, buf_size: int = 4 * 1024 * 1024) -> str:
    """
    Fast MD5 hash of a file with reusable buffer (fewer allocations).
    """
    h = hashlib.md5()
    with fp.open("rb", buffering=0) as f:
        buf = bytearray(buf_size)
        mv = memoryview(buf)
        while True:
            n = f.readinto(mv)
            if not n:
                break
            h.update(mv[:n])
    return h.hexdigest()


def fmt_times_pair(ts: float) -> tuple:
    """Return ('DD-MM-YYYY HH:MM:SS±ZZZZ', 'YYYY-mm-ddTHH:MM:SSZ')."""
    local = datetime.fromtimestamp(ts).astimezone()
    utc = datetime.fromtimestamp(ts, tz=timezone.utc)
    return local.strftime("%d-%m-%Y %H:%M:%S%z"), utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_stat_times(path: Path) -> tuple or None:
    """Safely get file system times."""
    try:
        st = path.stat()
        return (st.st_atime, st.st_mtime, st.st_ctime)
    except Exception:
        return None


def sha256_file(filepath: Path) -> str:
    """Calculates the SHA-256 hash of a file."""
    sha256_hash = hashlib.sha256()
    try:
        with filepath.open("rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()
    except FileNotFoundError:
        return ""
    except Exception as e:
        return f"Error: {str(e)}"

def resolve_path(filename, base_is_parent=False):
    """
    Resolves the correct path for a resource file, whether running as a script
    or as a frozen executable (e.g., with PyInstaller).
    """
    if getattr(sys, 'frozen', False):
        # If the app is frozen, the base path is the folder containing the exe.
        base_path = Path(sys.executable).parent
        # When frozen and base_is_parent=True, look for the file next to the exe (e.g., exiftool.exe)
        if base_is_parent:
            return base_path / filename
        # Otherwise, look in _MEIPASS for bundled data files (translations, etc.)
        return Path(getattr(sys, '_MEIPASS', base_path)) / filename
    else:
        # If running as a normal script, the base path is the script's folder.
        base_path = Path(__file__).resolve().parent

    # If base_is_parent=True, go up one level to project root
    if base_is_parent:
        base_path = base_path.parent

    return base_path / filename
