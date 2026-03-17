#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDFRecon Command Line Interface

Enables integration into automated pipelines: scan directories, export
signed reports, extract embedded JavaScript, and maintain chain of custody.
"""

import argparse
import json
import multiprocessing
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime

# Ensure package is importable when run as script
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config import PDFReconConfig, APP_VERSION
from src.scan_worker import process_single_file_worker, build_scan_config, _worker_init
from src.chain_of_custody import (
    get_custody_log_path,
    log_ingestion,
    sha256_file,
    append_custody_event,
    ACTION_CASE_SAVE,
)
from src.signed_report import build_findings_report, export_signed_report
from src.utils import CaseEncoder, case_decoder
from src.js_extractor import extract_javascript_from_file


def find_pdf_files(folder: Path):
    """Yield PDF paths under folder."""
    for base, _, files in os.walk(folder):
        for fn in files:
            if fn.lower().endswith(".pdf"):
                yield Path(base) / fn


def cmd_scan(args: argparse.Namespace) -> int:
    """Run forensic scan on a directory and optionally write case + custody log."""
    folder = Path(args.dir).resolve()
    if not folder.is_dir():
        print(f"Error: not a directory: {folder}", file=sys.stderr)
        return 1
    out_dir = Path(args.output_dir).resolve() if args.output_dir else folder
    out_dir.mkdir(parents=True, exist_ok=True)
    custody_log = Path(args.custody_log).resolve() if args.custody_log else get_custody_log_path(out_dir)
    jobs = args.jobs or max(1, (os.cpu_count() or 2) - 1)
    cfg = build_scan_config()
    pdf_list = list(find_pdf_files(folder))
    if not pdf_list:
        print(f"No PDFs found under {folder}", file=sys.stderr)
        return 0
    print(f"Scanning {len(pdf_list)} PDF(s) with {jobs} worker(s)...")
    all_scan_data = {}
    exif_outputs = {}
    timeline_data = {}
    evidence_hashes = {}
    file_annotations = {}
    path_to_id = {}
    revision_counter = 0
    with ProcessPoolExecutor(max_workers=jobs, initializer=_worker_init, initargs=(cfg,)) as executor:
        future_to_path = {executor.submit(process_single_file_worker, str(p), cfg): p for p in pdf_list}
        for future in as_completed(future_to_path):
            path = future_to_path[future]
            try:
                results = future.result()
                for r in results:
                    path_key = str(r["path"]) if isinstance(r["path"], Path) else r["path"]
                    r["path"] = path_key
                    if isinstance(r.get("original_path"), Path):
                        r["original_path"] = str(r["original_path"])
                    all_scan_data[path_key] = r
                    if not r.get("is_revision"):
                        exif_outputs[path_key] = r.get("exif", "")
                        timeline_data[path_key] = r.get("timeline", {})
                    else:
                        revision_counter += 1
                        exif_outputs[path_key] = r.get("exif", "")
                        timeline_data[path_key] = r.get("timeline", {})
            except Exception as e:
                print(f"Error processing {path}: {e}", file=sys.stderr)
    # Evidence hashes for originals (non-revisions)
    for path_key, data in all_scan_data.items():
        if data.get("is_revision"):
            continue
        try:
            p = Path(path_key)
            if p.exists():
                evidence_hashes[path_key] = sha256_file(p)
                if args.custody_log or args.output_dir:
                    log_ingestion(custody_log, p, evidence_hashes[path_key], case_path=None)
        except Exception as e:
            print(f"Hash/custody skip {path_key}: {e}", file=sys.stderr)
    case_data = {
        "app_version": APP_VERSION,
        "scan_folder": str(folder),
        "all_scan_data": all_scan_data,
        "file_annotations": file_annotations,
        "exif_outputs": exif_outputs,
        "timeline_data": timeline_data,
        "path_to_id": path_to_id,
        "revision_counter": revision_counter,
        "evidence_hashes": evidence_hashes,
    }
    case_path = out_dir / f"case_cli_{datetime.now().strftime('%Y%m%d_%H%M%S')}.prc"
    with open(case_path, "w", encoding="utf-8") as f:
        json.dump(case_data, f, cls=CaseEncoder, indent=2)
    if custody_log:
        append_custody_event(
            custody_log,
            action=ACTION_CASE_SAVE,
            item_path=str(case_path),
            file_hash=sha256_file(case_path),
            details={"source": "cli_scan"},
        )
    print(f"Case saved: {case_path}")
    print(f"Custody log: {custody_log}")
    return 0


def cmd_export_signed(args: argparse.Namespace) -> int:
    """Export a signed report from an existing case file."""
    case_path = Path(args.case).resolve()
    if not case_path.exists():
        print(f"Error: case file not found: {case_path}", file=sys.stderr)
        return 1
    with open(case_path, "r", encoding="utf-8") as f:
        case_data = json.load(f, object_hook=case_decoder)
    all_scan_data = case_data.get("all_scan_data", {})
    if isinstance(all_scan_data, list):
        all_scan_data = {str(x.get("path")): x for x in all_scan_data}
    report = build_findings_report(
        all_scan_data,
        case_data.get("file_annotations", {}),
        case_data.get("exif_outputs", {}),
        case_data.get("evidence_hashes", {}),
        scan_folder=case_data.get("scan_folder"),
        case_path=str(case_path),
    )
    out_path = Path(args.output).resolve() if args.output else case_path.with_suffix(".signed_report.json")
    custody_log = get_custody_log_path(case_path.parent, case_path) if args.custody else None
    key_path = Path(args.sign_key).resolve() if args.sign_key else None
    h = export_signed_report(report, out_path, custody_log_path=custody_log, case_path=str(case_path), sign_with_key=key_path)
    print(f"Signed report: {out_path}")
    print(f"Report SHA-256: {h}")
    return 0


def cmd_extract_js(args: argparse.Namespace) -> int:
    """Extract embedded JavaScript from a PDF file."""
    path = Path(args.file).resolve()
    if not path.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        return 1
    scripts = extract_javascript_from_file(path)
    if not scripts:
        print("No embedded JavaScript found.")
        return 0
    out = args.output
    if out:
        out_path = Path(out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            for i, s in enumerate(scripts):
                f.write(f"--- Script {i + 1} ({s.get('source', '?')}) ---\n")
                f.write(s.get("code", ""))
                f.write("\n\n")
        print(f"Extracted {len(scripts)} script(s) to {out_path}")
    else:
        for i, s in enumerate(scripts):
            print(f"--- Script {i + 1} ({s.get('source', '?')}) ---")
            print(s.get("code", ""))
            print()
    return 0


def main():
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(prog="pdfrecon", description="PDFRecon CLI for forensic scan and report export.")
    parser.add_argument("--version", action="version", version=APP_VERSION)
    sub = parser.add_subparsers(dest="command", help="Command")
    # scan
    p_scan = sub.add_parser("scan", help="Scan a directory for PDFs and produce a case file and custody log.")
    p_scan.add_argument("dir", help="Directory to scan for PDFs")
    p_scan.add_argument("--output-dir", "-o", help="Output directory for case file (default: same as scan dir)")
    p_scan.add_argument("--custody-log", "-c", help="Path to chain-of-custody log (default: <output-dir>/custody.log)")
    p_scan.add_argument("--jobs", "-j", type=int, help="Parallel workers (default: CPU count - 1)")
    p_scan.set_defaults(func=cmd_scan)
    # export-signed
    p_export = sub.add_parser("export-signed", help="Export a digitally signed report from a case file.")
    p_export.add_argument("case", help="Path to .prc case file")
    p_export.add_argument("--output", help="Output report path (default: <case>.signed_report.json)")
    p_export.add_argument("--custody", action="store_true", help="Append to chain-of-custody log")
    p_export.add_argument("--sign-key", help="Path to PEM private key for detached signature (optional)")
    p_export.set_defaults(func=cmd_export_signed)
    # extract-js
    p_js = sub.add_parser("extract-js", help="Extract embedded JavaScript from a PDF (for malicious file analysis).")
    p_js.add_argument("file", help="PDF file path")
    p_js.add_argument("--output", "-o", help="Write scripts to file (default: stdout)")
    p_js.set_defaults(func=cmd_extract_js)
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
