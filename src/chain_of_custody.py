"""
Chain of Custody Log Module

Append-only audit log that records file hashes on ingestion and all interactions
(scan, export, verify) to support technical quality and admissibility in court.
Uses SHA-256 for file hashes; log entries are timestamped and immutable.
Tamper protection: each entry includes a hash chain (entry_hash) so any modification
can be detected when verifying.
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple

# Genesis hash for first entry in chain (or after legacy entries)
_CUSTODY_LOG_GENESIS = hashlib.sha256(b"PDFRecon custody log v1").hexdigest()

# Actions that can be recorded
ACTION_INGEST = "INGEST"
ACTION_EXPORT = "EXPORT"
ACTION_VERIFY = "VERIFY"
ACTION_CASE_OPEN = "CASE_OPEN"
ACTION_CASE_SAVE = "CASE_SAVE"
ACTION_REPORT_SIGNED = "REPORT_SIGNED"


def sha256_file(filepath: Path, buf_size: int = 65536) -> str:
    """Compute SHA-256 hash of a file for custody records."""
    h = hashlib.sha256()
    with filepath.open("rb") as f:
        while chunk := f.read(buf_size):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    """Compute SHA-256 hash of bytes (e.g. in-memory revision or report)."""
    return hashlib.sha256(data).hexdigest()


def _ensure_log_dir(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)


def _canonical_entry(entry: dict) -> str:
    """Canonical JSON for hashing (exclude entry_hash, sort keys)."""
    out = {k: v for k, v in entry.items() if k != "entry_hash"}
    return json.dumps(out, sort_keys=True, ensure_ascii=False)


def _get_last_entry_hash(log_path: Path) -> str:
    """Read last line of log; return its entry_hash or genesis if empty/legacy."""
    if not log_path.exists():
        return _CUSTODY_LOG_GENESIS
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        if not lines:
            return _CUSTODY_LOG_GENESIS
        last = json.loads(lines[-1])
        return last.get("entry_hash") or _CUSTODY_LOG_GENESIS
    except Exception:
        return _CUSTODY_LOG_GENESIS


def append_custody_event(
    log_path: Path,
    action: str,
    item_path: Optional[str] = None,
    file_hash: Optional[str] = None,
    details: Optional[dict] = None,
    case_path: Optional[str] = None,
) -> None:
    """
    Append a single custody event to the log file (one JSON object per line).
    Each entry includes entry_hash = SHA256(prev_entry_hash + canonical(entry))
    for tamper detection.
    """
    _ensure_log_dir(log_path)
    entry = {
        "timestamp_utc": datetime.now(tz=timezone.utc).isoformat(),
        "action": action,
        "item_path": item_path,
        "file_hash": file_hash,
        "details": details or {},
        "case_path": case_path,
    }
    prev_hash = _get_last_entry_hash(log_path)
    chain_input = prev_hash + _canonical_entry(entry)
    entry["entry_hash"] = hashlib.sha256(chain_input.encode("utf-8")).hexdigest()
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logging.debug("Custody event: %s %s", action, item_path or "")


def log_ingestion(log_path: Path, file_path: Path, file_hash: str, case_path: Optional[str] = None) -> None:
    """Record that a file was ingested (scanned); hash must be computed before calling."""
    append_custody_event(
        log_path,
        action=ACTION_INGEST,
        item_path=str(file_path),
        file_hash=file_hash,
        details={"description": "File ingested for forensic analysis"},
        case_path=case_path,
    )


def log_export(
    log_path: Path,
    export_path: Path,
    export_format: str,
    report_hash: Optional[str] = None,
    case_path: Optional[str] = None,
) -> None:
    """Record that an export was performed (e.g. Excel, signed report)."""
    details = {"export_format": export_format}
    if report_hash:
        details["report_sha256"] = report_hash
    append_custody_event(
        log_path,
        action=ACTION_EXPORT,
        item_path=str(export_path),
        file_hash=report_hash,
        details=details,
        case_path=case_path,
    )


def log_verify(
    log_path: Path,
    item_path: str,
    expected_hash: str,
    actual_hash: str,
    passed: bool,
    case_path: Optional[str] = None,
) -> None:
    """Record an integrity verification result."""
    append_custody_event(
        log_path,
        action=ACTION_VERIFY,
        item_path=item_path,
        file_hash=actual_hash,
        details={
            "expected_hash": expected_hash,
            "passed": passed,
        },
        case_path=case_path,
    )


def log_signed_report(
    log_path: Path,
    report_path: Path,
    report_sha256: str,
    signature_info: Optional[dict] = None,
    case_path: Optional[str] = None,
) -> None:
    """Record that a digitally signed report was generated."""
    details = {"report_sha256": report_sha256}
    if signature_info:
        details["signature"] = signature_info
    append_custody_event(
        log_path,
        action=ACTION_REPORT_SIGNED,
        item_path=str(report_path),
        file_hash=report_sha256,
        details=details,
        case_path=case_path,
    )


def get_custody_log_path(case_root: Path, case_filepath: Optional[Path] = None) -> Path:
    """
    Resolve the custody log file path for a case.
    If case_filepath is given (e.g. case_20250101.prc), log is next to it with .custody.log.
    Otherwise uses case_root / "custody.log".
    """
    if case_filepath:
        cf = Path(case_filepath)
        if cf.suffix.lower() == ".prc":
            return cf.parent / (cf.stem + ".custody.log")
    return case_root / "custody.log"


def read_and_verify_custody_log(log_path: Path) -> Tuple[List[dict], bool, Optional[int], str]:
    """
    Read custody log and verify the hash chain.

    Returns:
        (entries, valid, first_bad_line, message)
        - entries: list of parsed entry dicts (without entry_hash for display if desired, or with)
        - valid: True if chain is intact
        - first_bad_line: 1-based line number of first tampered line, or None
        - message: human-readable status (e.g. "Integrity verified" or "Tampering detected at line N")
    """
    entries = []
    if not log_path.exists():
        return [], True, None, "No audit log file found."
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
    except Exception as e:
        return [], False, None, f"Could not read log: {e}"
    prev_hash = _CUSTODY_LOG_GENESIS
    first_bad = None
    for i, line in enumerate(lines, start=1):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            return entries, False, i, f"Tampering or corruption at line {i} (invalid JSON)."
        stored_hash = entry.get("entry_hash")
        # Legacy entries have no entry_hash; we only verify from first hash-bearing entry onward
        if stored_hash is not None:
            expected = hashlib.sha256((prev_hash + _canonical_entry(entry)).encode("utf-8")).hexdigest()
            if stored_hash != expected:
                first_bad = i
                return entries, False, first_bad, f"Tampering detected at line {i}. Log integrity compromised."
            prev_hash = stored_hash
        else:
            prev_hash = _CUSTODY_LOG_GENESIS  # legacy entry: next chain starts from genesis
        entries.append(entry)
    if not entries:
        return [], True, None, "Log file is empty."
    return entries, True, None, "Integrity verified. Hash chain intact."


def format_custody_log_display(entries: List[dict]) -> str:
    """Format log entries for display in the audit log viewer (one block per entry)."""
    lines = []
    for i, e in enumerate(entries, 1):
        lines.append(f"--- Entry {i} ---")
        lines.append(f"  Time (UTC): {e.get('timestamp_utc', '')}")
        lines.append(f"  Action:     {e.get('action', '')}")
        if e.get("item_path"):
            lines.append(f"  Item:       {e['item_path']}")
        if e.get("file_hash"):
            lines.append(f"  Hash:       {e['file_hash']}")
        if e.get("details"):
            for k, v in e["details"].items():
                lines.append(f"  {k}: {v}")
        if e.get("case_path"):
            lines.append(f"  Case:       {e['case_path']}")
        # Do not display entry_hash to keep UI simple; it is used only for verification
        lines.append("")
    return "\n".join(lines)
