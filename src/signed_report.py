"""
Digitally Signed Report Export

Exports findings to a report file and optionally signs it (SHA-256 hash
and PKCS#7 or detached signature) for admissibility and chain of custody.
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import APP_VERSION
from .chain_of_custody import log_signed_report


def build_findings_report(
    all_scan_data: dict,
    file_annotations: dict,
    exif_outputs: dict,
    evidence_hashes: dict,
    scan_folder: Optional[str] = None,
    case_path: Optional[str] = None,
) -> dict:
    """Build a structured report dict suitable for signing and export."""
    report = {
        "generator": "PDFRecon",
        "version": APP_VERSION,
        "generated_utc": datetime.now(tz=timezone.utc).isoformat(),
        "scan_folder": scan_folder,
        "case_path": case_path,
        "evidence_hashes": evidence_hashes,
        "file_count": len(all_scan_data),
        "findings": [],
    }
    for path_str, data in all_scan_data.items():
        entry = {
            "path": path_str,
            "md5": data.get("md5"),
            "status": data.get("status"),
            "is_revision": data.get("is_revision", False),
            "annotation": file_annotations.get(path_str),
            "exif_summary": (exif_outputs.get(path_str) or "")[:2000],
            "indicators": {},
            "revision_diff": data.get("revision_diff"),
            "extracted_javascript": data.get("extracted_javascript"),
        }
        for k, v in (data.get("indicator_keys") or {}).items():
            if isinstance(v, dict) and not any(
                isinstance(x, (dict, list)) for x in v.values()
            ):
                entry["indicators"][k] = v
            else:
                entry["indicators"][k] = "(present)"
        report["findings"].append(entry)
    return report


def export_signed_report(
    report_data: dict,
    output_path: Path,
    custody_log_path: Optional[Path] = None,
    case_path: Optional[str] = None,
    sign_with_key: Optional[Path] = None,
) -> str:
    """
    Export report as JSON, compute SHA-256, optionally sign, and append to custody log.

    Returns the SHA-256 hash of the report content (hex).
    """
    output_path = Path(output_path)
    report_data["_signed_utc"] = datetime.now(tz=timezone.utc).isoformat()
    content_for_hash = json.dumps(report_data, indent=2, default=str, ensure_ascii=False)
    report_hash = hashlib.sha256(content_for_hash.encode("utf-8")).hexdigest()
    report_data["_report_sha256"] = report_hash
    content = json.dumps(report_data, indent=2, default=str, ensure_ascii=False)
    report_bytes = content.encode("utf-8")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(report_bytes)

    signature_info = None
    if sign_with_key and sign_with_key.exists():
        try:
            sig = _sign_detached(report_bytes, sign_with_key)
            if sig:
                sig_path = output_path.with_suffix(output_path.suffix + ".sig")
                sig_path.write_bytes(sig)
                signature_info = {"detached_signature": str(sig_path), "algorithm": "PKCS#7"}
        except Exception as e:
            logging.warning("Report signing failed: %s", e)

    if custody_log_path:
        log_signed_report(
            custody_log_path,
            output_path,
            report_hash,
            signature_info=signature_info,
            case_path=case_path,
        )
    return report_hash


def sign_file_detached(file_path: Path, key_path: Path) -> Optional[dict]:
    """
    Sign a file with private key (PEM); write file_path.suffix + .sig.
    Returns signature_info dict for custody log, or None.
    """
    file_path = Path(file_path)
    key_path = Path(key_path)
    if not file_path.exists() or not key_path.exists():
        return None
    data = file_path.read_bytes()
    sig = _sign_detached(data, key_path)
    if not sig:
        return None
    sig_path = file_path.with_suffix(file_path.suffix + ".sig")
    sig_path.write_bytes(sig)
    return {"detached_signature": str(sig_path), "algorithm": "PKCS#7"}


def _sign_detached(data: bytes, key_path: Path) -> Optional[bytes]:
    """Sign data with private key (PEM); return PKCS#7 detached signature or None."""
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography import x509
        from cryptography.hazmat.backends import default_backend
        key_path = Path(key_path)
        pem = key_path.read_bytes()
        if b"PRIVATE" in pem:
            key = serialization.load_pem_private_key(pem, password=None, backend=default_backend())
            sig = key.sign(data, padding.PKCS1v15(), hashes.SHA256())
            return sig
    except ImportError:
        logging.debug("cryptography not installed; skipping PKCS#7 sign")
    except Exception as e:
        logging.warning("Signing failed: %s", e)
    return None


def verify_report_hash(report_path: Path) -> Optional[str]:
    """Read report, recompute SHA-256, return hash if file exists."""
    if not report_path.exists():
        return None
    data = report_path.read_bytes()
    # Remove _report_sha256 / _signed_utc for consistent verification if we want to verify content-only
    return hashlib.sha256(data).hexdigest()
