"""
Scan Worker Module

Contains process_single_file_worker() - a top-level, picklable function
that processes one PDF file and returns a plain list of dicts.

This module must NOT import tkinter or reference any GUI objects so it
can safely be used with multiprocessing.ProcessPoolExecutor (which spawns
fresh Python processes on Windows using the 'spawn' start method).
"""

import hashlib
import logging
import re
import shutil
import subprocess
import sys
import time
import zlib
import base64
import binascii
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import fitz
from PIL import Image, ImageChops

try:
    import exiftool as _exiftool_module
    _EXIFTOOL_MODULE_AVAILABLE = True
except ImportError:
    _EXIFTOOL_MODULE_AVAILABLE = False
    _exiftool_module = None

from .config import (
    PDFReconConfig,
    PDFCorruptionError,
    PDFTooLargeError,
    PDFEncryptedError,
    KV_PATTERN,
    DATE_TZ_PATTERN,
    LAYER_OCGS_BLOCK_RE,
    OBJ_REF_RE,
    LAYER_OC_REF_RE,
)
from .pdf_processor import safe_pdf_open, count_layers
from .scanner import detect_indicators as scanner_detect_indicators
from .revision_diff import extract_text_from_pdf_bytes, compute_highlighted_changes
from .js_extractor import extract_embedded_javascript


# ---------------------------------------------------------------------------
# Per-worker-process persistent ExifTool singleton
# ---------------------------------------------------------------------------

# Set once per OS worker process by _worker_init(); stays None in the GUI process.
_et_process = None


# ---------------------------------------------------------------------------
# Internal helpers (pure functions, no GUI/Tk dependencies)
# ---------------------------------------------------------------------------

def _decompress_stream(b: bytes) -> str:
    """Attempt to decompress a PDF stream using common filters."""
    for fn in (
        zlib.decompress,
        lambda d: base64.a85decode(re.sub(rb"\s", b"", d), adobe=True),
        lambda d: binascii.unhexlify(re.sub(rb"\s|>", b"", d)),
    ):
        try:
            return fn(b).decode("latin1", "ignore")
        except Exception:
            pass
    return ""


def _extract_text_for_scanning(raw: bytes) -> str:
    """
    Fast raw-byte text extraction for indicator hunting.
    This is the standalone equivalent of PDFReconApp.extract_text().
    """
    txt_segments = []
    # ⚡ Bolt Optimization: Use re.findall instead of list(re.finditer)
    # Leveraging C-level list comprehensions bypasses the overhead of
    # generating and iterating over Match objects in Python.
    stream_matches = re.findall(rb"(?s)stream\b(.*?)\bendstream", raw)

    found_touchup_marker = False
    for body_raw in stream_matches:
        body = body_raw.strip(b"\r\n ")
        if len(body) <= 500_000:
            try:
                decompressed = _decompress_stream(body)
                if decompressed:
                    txt_segments.append(decompressed)
                    if not found_touchup_marker and re.search(r"TouchUp", decompressed, re.I):
                        found_touchup_marker = True
            except Exception:
                try:
                    decoded = body.decode("latin1", "ignore")
                    txt_segments.append(decoded)
                    if not found_touchup_marker and "TouchUp" in decoded:
                        found_touchup_marker = True
                except Exception:
                    pass

    txt_segments.append(raw[:1_000_000].decode("latin1", "ignore"))
    if len(raw) > 1_000_000:
        txt_segments.append(raw[-1_000_000:].decode("latin1", "ignore"))

    xmp_match = re.search(rb"<\?xpacket begin=.*?\?>(.*?)<\?xpacket end=[^>]*\?>", raw, re.S)
    if xmp_match:
        try:
            txt_segments.append(xmp_match.group(1).decode("utf-8", "ignore"))
        except Exception:
            txt_segments.append(xmp_match.group(1).decode("latin1", "ignore"))

    if found_touchup_marker or re.search(rb"touchup_textedit", raw, re.I):
        txt_segments.append("TouchUp_TextEdit")

    return "\n".join(txt_segments)


def _extract_touchup_text(doc):
    """
    Extracts text from elements marked with TouchUp_TextEdit.
    Uses a 'Masking' strategy: creates a copy of the PDF, masks all non-TouchUp
    text using pikepdf, then extracts the remaining (correctly decoded) text via fitz.
    This ensures CID-encoded fonts (common in TouchUp edits) are correctly translated.

    Inlined from worker_extracted.py (which is not importable as a module).
    """
    import pikepdf
    import io

    page_results = {}
    if not doc or doc.is_closed:
        return page_results

    try:
        try:
            pdf_bytes = doc.tobytes()
            pdf = pikepdf.open(io.BytesIO(pdf_bytes))
        except Exception as e:
            logging.debug(f"Pikepdf open failed for TouchUp masking: {e}")
            return page_results

        with pdf:
            for page_num, page in enumerate(pdf.pages):
                try:
                    ops = pikepdf.parse_content_stream(page)
                    new_ops = []
                    touchup_stack = [False]
                    mp_flag = False
                    in_flagged_bt = False
                    properties = {}
                    if "/Resources" in page and "/Properties" in page.Resources:
                        properties = page.Resources.Properties

                    for operands, operator in ops:
                        op_name = str(operator)

                        if op_name in {"BDC", "BMC"}:
                            is_touchup = False
                            tag = ""
                            if operands and (isinstance(operands[0], pikepdf.Name) or isinstance(operands[0], str)):
                                tag = str(operands[0])
                            if "TouchUp" in tag:
                                is_touchup = True
                            elif properties and operands and operands[0] in properties:
                                try:
                                    if "TouchUp" in str(properties[operands[0]]):
                                        is_touchup = True
                                except Exception:
                                    pass
                            touchup_stack.append(is_touchup or touchup_stack[-1])

                        elif op_name == "EMC":
                            if len(touchup_stack) > 1:
                                touchup_stack.pop()
                            in_flagged_bt = False
                            mp_flag = False

                        elif op_name in {"MP", "DP"}:
                            tag = ""
                            if operands and (isinstance(operands[0], pikepdf.Name) or isinstance(operands[0], str)):
                                tag = str(operands[0])
                            if "TouchUp" in tag:
                                mp_flag = True
                            elif properties and operands and operands[0] in properties:
                                try:
                                    if "TouchUp" in str(properties[operands[0]]):
                                        mp_flag = True
                                except Exception:
                                    pass

                        elif op_name == "BT":
                            if mp_flag:
                                in_flagged_bt = True
                                mp_flag = False

                        elif op_name == "ET":
                            in_flagged_bt = False

                        is_inside_touchup = touchup_stack[-1] or in_flagged_bt

                        if not is_inside_touchup and op_name in {"Tj", "TJ", "'", '"'}:
                            if op_name == "TJ":
                                new_list = []
                                for item in operands[0]:
                                    if isinstance(item, pikepdf.String):
                                        new_list.append(pikepdf.String(" " * len(bytes(item))))
                                    else:
                                        new_list.append(item)
                                new_ops.append(([new_list], operator))
                            else:
                                new_ops.append(([pikepdf.String(" " * len(bytes(operands[0])))], operator))
                        else:
                            new_ops.append((operands, operator))

                    page.set_contents(pikepdf.unparse_content_stream(new_ops))

                except Exception as e:
                    logging.debug(f"Failed to mask page {page_num}: {e}")
                    continue

            out_buf = io.BytesIO()
            pdf.save(out_buf)
            out_buf.seek(0)

            with fitz.open(stream=out_buf, filetype="pdf") as masked_doc:
                for i, masked_page in enumerate(masked_doc):
                    text = masked_page.get_text("text").strip()
                    if text:
                        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                        if lines:
                            page_results[i + 1] = lines

        return page_results

    except Exception as e:
        logging.warning(f"Robust TouchUp extraction failed: {e}")
        return {}


def _resolve_exiftool_path() -> Path | None:
    """Locate the exiftool executable using the same search order as PDFReconApp."""
    # 1. Configured path
    if PDFReconConfig.EXIFTOOL_PATH:
        p = Path(PDFReconConfig.EXIFTOOL_PATH)
        if p.is_file():
            return p

    # 2. System PATH
    system_path = shutil.which("exiftool")
    if system_path:
        return Path(system_path)

    # 3. Bundled (next to executable when frozen, or next to this file)
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).parent / "exiftool.exe")
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "exiftool.exe")
    else:
        candidates.append(Path(__file__).parent.parent / "exiftool.exe")
        candidates.append(Path(__file__).parent / "exiftool.exe")

    for p in candidates:
        if p.is_file():
            return p

    return None


def _run_exiftool(path: Path, detailed: bool = False) -> str:
    """
    Run exiftool on a file and return its output as a string.

    Primary path: uses the persistent ExifToolHelper process started by
    _worker_init() (one per OS worker process) to avoid per-file startup cost.

    Fallback: spawns a fresh subprocess as before, used when the persistent
    process is unavailable (GUI thread, ExifTool not found, or on error).
    """
    global _et_process

    # ------------------------------------------------------------------
    # Fast path: persistent process (available after _worker_init runs)
    # ------------------------------------------------------------------
    if _et_process is not None:
        try:
            args = ["-a", "-u", "-s", "-G1"]
            if detailed:
                args.append("-struct")
            args.append(str(path))
            raw_output = _et_process.execute(*args)
            # execute() returns str; strip blank lines to match subprocess output
            return "\n".join(line for line in raw_output.splitlines() if line.strip())
        except Exception as e:
            logging.warning(
                f"ExifToolHelper.execute failed for {path.name}: {e} "
                "— falling back to subprocess"
            )
            # Fall through to subprocess below

    # ------------------------------------------------------------------
    # Slow path: spawn a fresh subprocess (original behaviour)
    # ------------------------------------------------------------------
    exe_path = _resolve_exiftool_path()
    if not exe_path:
        return "ExifTool not found."

    try:
        file_content = path.read_bytes()
        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        command = [str(exe_path)]
        if detailed:
            command.extend(["-a", "-u", "-s", "-G1", "-struct"])
        else:
            command.extend(["-a", "-u", "-s", "-G1"])
        command.append("-")   # read from stdin

        run_kw = dict(
            capture_output=True,
            check=False,
            timeout=PDFReconConfig.EXIFTOOL_TIMEOUT,
        )
        if startupinfo is not None:
            run_kw["startupinfo"] = startupinfo
        if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            run_kw["creationflags"] = subprocess.CREATE_NO_WINDOW
        process = subprocess.run(command, input=file_content, **run_kw)

        if process.returncode != 0 or process.stderr:
            error_message = process.stderr.decode("latin-1", "ignore").strip()
            if not process.stdout.strip():
                return f"ExifTool error:\n{error_message}"
            logging.warning(f"ExifTool stderr for {path.name}: {error_message}")

        try:
            raw_output = process.stdout.decode("utf-8").strip()
        except UnicodeDecodeError:
            raw_output = process.stdout.decode("latin-1", "ignore").strip()

        return "\n".join(line for line in raw_output.splitlines() if line.strip())

    except subprocess.TimeoutExpired:
        logging.error(f"ExifTool timed out for {path.name}")
        return f"ExifTool error:\nTimeout after {PDFReconConfig.EXIFTOOL_TIMEOUT} seconds."
    except Exception as e:
        logging.error(f"ExifTool failed for {path}: {e}")
        return f"ExifTool error:\n{e}"


def _parse_exif_data(exiftool_out: str) -> dict:
    """Parse EXIFTool output into a structured dict (standalone, no self needed)."""
    # Must match DataProcessingMixin.SOFTWARE_TOKENS (Wikipedia "List of PDF software" + project-specific).
    software_tokens = re.compile(
        r"(abbey|abbyy|acrobat|adobe|apache|birt|billy|bluebeam|bullzip|businesscentral|cairo|canva|chrome|chromium|"
        r"clibpdf|collabora|cups|cutepdf|deskpdf|dinero|dynamics|ecopy|economic|edge|eboks|evince|excel|firefox|"
        r"finereader|formpipe|foxit|fpdf|framemaker|gdoc|ghostscript|ghostview|gimp|helpndoc|illustrator|ilovepdf|"
        r"imagemagick|indesign|inkscape|itext|javelin|jasperreports|karbon|kmd|lasernet|latex|libharu|libreoffice|"
        r"luatex|mathcad|microsoft|mobipocket|mupdf|navision|netcompany|nitro|okular|office|openoffice|openpdf|"
        r"paperport|pagestream|pageplus|pdf24|pdfarranger|pdfbox|pdfcreator|pdfedit|pdfescape|pdfgear|pdflatex|"
        r"pdfjs|pdfsam|pdfsharp|pdfstudio|pdftk|pdfxchange|photoshop|poppler|powerpoint|pstoedit|primopdf|prince|"
        r"qpdf|qiqqa|quartz|reportlab|revu|safari|scribus|serif|skim|skia|smallpdf|sodapdf|solidconverter|"
        r"stdu|sumatra|swftools|tcpdf|tex|utopia|visma|word|wkhtml|wkhtmltopdf|xara|xetex|xpdf)",
        re.IGNORECASE,
    )

    data = {
        "producer_pdf": "", "producer_xmppdf": "", "softwareagent": "",
        "application": "", "software": "", "creatortool": "", "xmptoolkit": "",
        "create_dt": None, "modify_dt": None, "history_events": [], "all_dates": [],
    }
    lines = exiftool_out.splitlines()
    history_pattern = re.compile(r"\[XMP-xmpMM\]\s+History\s+:\s+(.*)")

    def looks_like_software(s: str) -> bool:
        return bool(s and software_tokens.search(s))

    for ln in lines:
        m = KV_PATTERN.match(ln)
        if not m:
            continue
        group = m.group("group").strip().lower()
        tag = m.group("tag").strip().lower().replace(" ", "")
        val = m.group("value").strip()

        if tag == "producer":
            if group == "pdf" and not data["producer_pdf"]:
                data["producer_pdf"] = val
            elif group in ("xmp-pdf", "xmp_pdf") and not data["producer_xmppdf"]:
                data["producer_xmppdf"] = val
        elif tag == "softwareagent" and not data["softwareagent"]:
            data["softwareagent"] = val
        elif tag == "application" and not data["application"]:
            data["application"] = val
        elif tag == "software" and not data["software"]:
            data["software"] = val
        elif tag == "creatortool" and not data["creatortool"] and looks_like_software(val):
            data["creatortool"] = val
        elif tag == "xmptoolkit" and not data["xmptoolkit"]:
            data["xmptoolkit"] = val

    if not data["producer_pdf"] and data["producer_xmppdf"]:
        data["producer_pdf"] = data["producer_xmppdf"]
    if not data["producer_xmppdf"] and data["producer_pdf"]:
        data["producer_xmppdf"] = data["producer_pdf"]

    for ln in lines:
        hist_match = history_pattern.match(ln)
        if hist_match:
            history_str = hist_match.group(1)
            event_blocks = re.findall(r'\{([^}]+)\}', history_str)
            for block in event_blocks:
                details = {
                    k.strip(): v.strip()
                    for k, v in (pair.split("=", 1) for pair in block.split(",") if "=" in pair)
                }
                if "When" in details:
                    try:
                        dt_obj = datetime.fromisoformat(details["When"].replace("Z", "+00:00"))
                        data["history_events"].append((dt_obj, details))
                    except (ValueError, IndexError):
                        pass
            continue

        kv_match = KV_PATTERN.match(ln)
        if not kv_match:
            continue
        val_str = kv_match.group("value").strip()
        match = DATE_TZ_PATTERN.match(val_str)
        if match:
            parts = match.groupdict()
            date_part = parts.get("date").replace(":", "-", 2).replace(" ", "T")
            tz_part = parts.get("tz")
            try:
                full_date_str = date_part
                if tz_part:
                    full_date_str += tz_part.replace("Z", "+00:00")
                dt = datetime.fromisoformat(full_date_str)
                tag_name = kv_match.group("tag").strip().lower().replace(" ", "")
                group_name = kv_match.group("group").strip()
                data["all_dates"].append({"dt": dt, "tag": tag_name, "group": group_name, "full_str": val_str})
            except ValueError:
                continue

    for d in data["all_dates"]:
        if d["tag"] in {"createdate", "creationdate"}:
            if data["create_dt"] is None or d["dt"] < data["create_dt"]:
                data["create_dt"] = d["dt"]
        elif d["tag"] in {"modifydate", "metadatadate"}:
            if data["modify_dt"] is None or d["dt"] > data["modify_dt"]:
                data["modify_dt"] = d["dt"]

    return data


def _parse_raw_content_timeline(txt: str) -> list:
    """Extract timestamps directly from raw PDF text content."""
    from .config import PDF_DATE_PATTERN
    events = []
    for m in PDF_DATE_PATTERN.finditer(txt):
        key = m.group(1)
        raw_date = m.group(2)
        try:
            dt = datetime(
                int(raw_date[0:4]), int(raw_date[4:6]), int(raw_date[6:8]),
                int(raw_date[8:10]), int(raw_date[10:12]), int(raw_date[12:14]),
            )
            events.append((dt, f"Raw PDF    - {key}: {raw_date}"))
        except (ValueError, IndexError):
            continue
    return events


def _get_filesystem_times(filepath: Path) -> list:
    """Return filesystem created/modified events for a file."""
    events = []
    try:
        stat = filepath.stat()
        events.append((datetime.fromtimestamp(stat.st_ctime), f"File System  - Created: {datetime.fromtimestamp(stat.st_ctime).isoformat()}"))
        events.append((datetime.fromtimestamp(stat.st_mtime), f"File System  - Modified: {datetime.fromtimestamp(stat.st_mtime).isoformat()}"))
    except Exception:
        pass
    return events


def _detect_tool_change(exif_out: str, parsed: dict) -> dict:
    """Determine if the editing tool changed between creation and modification."""
    create_tool = parsed["producer_pdf"] or parsed["producer_xmppdf"] or parsed["application"] or parsed["software"] or parsed["creatortool"] or ""
    modify_tool = parsed["softwareagent"] or create_tool

    create_engine = modify_engine = ""
    if parsed["xmptoolkit"]:
        if parsed["create_dt"]:
            create_engine = parsed["xmptoolkit"]
        if parsed["modify_dt"]:
            modify_engine = parsed["xmptoolkit"]

    changed_tool = bool(create_tool and modify_tool and create_tool.strip() != modify_tool.strip())
    changed_engine = bool(create_engine and modify_engine and create_engine.strip() != modify_engine.strip())

    reason = ""
    if changed_tool and changed_engine:
        reason = "mixed"
    elif changed_tool:
        reason = "producer" if (parsed["producer_pdf"] or parsed["producer_xmppdf"]) else "software"
    elif changed_engine:
        reason = "engine"

    return {
        "changed": changed_tool or changed_engine,
        "create_tool": create_tool, "modify_tool": modify_tool,
        "create_engine": create_engine, "modify_engine": modify_engine,
        "modify_dt": parsed["modify_dt"],
        "reason": reason,
    }


def _parse_exiftool_timeline(exif_out: str, parsed: dict) -> list:
    """Generate timeline events from parsed EXIF data."""
    events = []
    create_tool = parsed["producer_pdf"] or parsed["producer_xmppdf"] or parsed["application"] or parsed["software"] or parsed["creatortool"] or ""
    modify_tool = parsed["softwareagent"] or create_tool

    for dt_obj, details in parsed["history_events"]:
        action = details.get("Action", "N/A")
        agent = details.get("SoftwareAgent", "")
        changed = details.get("Changed", "")
        desc = [f"Action: {action}"]
        if agent:
            desc.append(f"Agent: {agent}")
        if changed:
            desc.append(f"Changed: {changed}")
        events.append((dt_obj, f"XMP History   - {' | '.join(desc)}"))

    label_map = {"createdate": "Created", "creationdate": "Created", "modifydate": "Modified", "metadatadate": "Metadata"}
    for d in parsed["all_dates"]:
        label = label_map.get(d["tag"], d["tag"])
        tool = create_tool if d["tag"] in {"createdate", "creationdate"} else modify_tool
        tool_part = f" | Tool: {tool}" if tool else ""
        events.append((d["dt"], f"ExifTool ({d['group']}) - {label}: {d['full_str']}{tool_part}"))

    if parsed["xmptoolkit"]:
        anchor_dt = parsed["create_dt"] or (parsed["all_dates"][0]["dt"] if parsed["all_dates"] else datetime.now())
        events.append((anchor_dt, f"XMP Engine: {parsed['xmptoolkit']}"))

    return events


def _generate_timeline(filepath: Path, txt: str, exif_out: str, parsed_exif: dict) -> dict:
    """Combines all timeline event sources into sorted aware/naive buckets."""
    all_events = []
    all_events.extend(_get_filesystem_times(filepath))
    all_events.extend(_parse_exiftool_timeline(exif_out, parsed_exif))
    all_events.extend(_parse_raw_content_timeline(txt))

    try:
        info = _detect_tool_change(exif_out, parsed_exif)
        if info.get("changed"):
            when = info.get("modify_dt")
            if not when and all_events:
                naive_dts = [e[0] for e in all_events if e[0].tzinfo is None]
                when = max(naive_dts) if naive_dts else max(e[0] for e in all_events)
            if not when:
                when = datetime.now()
            create_t = info.get("create_tool", "?")
            modify_t = info.get("modify_tool", "?")
            line = f"Tool changed: {create_t} → {modify_t}"
            if info.get("reason") == "engine":
                line += f" (XMP engine: {info.get('create_engine', '?')} → {info.get('modify_engine', '?')})"
            all_events.append((when, line))
    except Exception:
        pass

    aware_events = sorted([(dt, desc) for dt, desc in all_events if dt.tzinfo is not None], key=lambda x: x[0])
    naive_events = sorted([(dt, desc) for dt, desc in all_events if dt.tzinfo is None], key=lambda x: x[0])
    return {"aware": aware_events, "naive": naive_events}


def _extract_revisions(raw: bytes, original_path: Path) -> list:
    """Extract PDF revisions from raw bytes (same logic as PDFReconApp.extract_revisions)."""
    revisions = []
    offsets = []
    pos = len(raw)
    while (pos := raw.rfind(b"%%EOF", 0, pos)) != -1:
        offsets.append(pos)

    sorted_offsets = sorted(offsets)
    if sorted_offsets and sorted_offsets[-1] > len(raw) - 100:
        sorted_offsets.pop()
    valid_offsets = [o for o in sorted_offsets if o >= 500]

    if valid_offsets:
        altered_dir = original_path.parent / "Altered_files"
        altered_dir.mkdir(parents=True, exist_ok=True)

        for offset in valid_offsets:
            rev_bytes = raw[: offset + 5]
            is_valid = False
            try:
                test_doc = fitz.open(stream=rev_bytes, filetype="pdf")
                if len(test_doc) > 0:
                    is_valid = True
                test_doc.close()
            except Exception:
                pass

            if is_valid:
                rev_idx = len(revisions) + 1
                rev_filename = f"{original_path.stem}_rev{rev_idx}_@{offset}.pdf"
                rev_path = altered_dir / rev_filename
                rev_path.write_bytes(rev_bytes)
                revisions.append((rev_path, original_path.name, rev_bytes))

    return revisions


def _add_layer_indicators(raw: bytes, path: Path, indicators: dict) -> None:
    """Add layer-related indicators (same logic as PDFReconApp._add_layer_indicators)."""
    try:
        layers_cnt = count_layers(raw)
    except Exception:
        layers_cnt = 0

    if layers_cnt <= 0:
        return

    indicators["HasLayers"] = {"count": layers_cnt}

    page_count = 0
    try:
        with fitz.open(path) as _doc:
            page_count = _doc.page_count
    except Exception:
        pass

    if page_count and layers_cnt > page_count:
        indicators["MoreLayersThanPages"] = {"layers": layers_cnt, "pages": page_count}


def _extract_all_document_ids(txt: str, exif_output: str) -> dict:
    """Extract document IDs from a PDF for cross-referencing (standalone copy)."""
    def _norm(val):
        if val is None:
            return None
        if isinstance(val, (bytes, bytearray)):
            val = val.decode("utf-8", "ignore")
        s = str(val).strip()
        s = re.sub(r"^urn:uuid:", "", s, flags=re.I)
        s = re.sub(r"^(uuid:|xmp\.iid:|xmp\.did:)", "", s, flags=re.I)
        s = s.strip("<>").strip()
        return s.upper() if s else None

    own_ids: set = set()
    ref_ids: set = set()

    for tag in ("xmpMM:DocumentID", "xmpMM:InstanceID"):
        m = re.search(rf'{tag}(?:>|=")([^<"]+)', txt, re.I)
        if m:
            v = _norm(m.group(1))
            if v:
                own_ids.add(v)

    for m in re.finditer(r"/ID\s*\[\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\]", txt):
        for grp in (m.group(1), m.group(2)):
            v = _norm(grp)
            if v:
                own_ids.add(v)

    m = re.search(r'xmpMM:OriginalDocumentID(?:>|=")([^<"]+)', txt, re.I)
    if m:
        v = _norm(m.group(1))
        if v:
            ref_ids.add(v)

    for pattern, block_re in [
        (r"<xmpMM:DerivedFrom\b[^>]*>(.*?)</xmpMM:DerivedFrom>", (r'stRef:documentID(?:>|=")([^<"]+)', r'stRef:instanceID(?:>|=")([^<"]+)')),
        (r"<xmpMM:Ingredients\b[^>]*>(.*?)</xmpMM:Ingredients>", (r'stRef:documentID(?:>|=")([^<"]+)',)),
    ]:
        block_match = re.search(pattern, txt, re.I | re.S)
        if block_match:
            blk = block_match.group(1)
            for sub_re in block_re:
                for m in re.finditer(sub_re, blk, re.I):
                    v = _norm(m.group(1))
                    if v:
                        ref_ids.add(v)

    if exif_output:
        for m in re.finditer(r"Document\s*ID\s*:\s*(\S+)", exif_output, re.I):
            v = _norm(m.group(1))
            if v:
                own_ids.add(v)
        for m in re.finditer(r"Instance\s*ID\s*:\s*(\S+)", exif_output, re.I):
            v = _norm(m.group(1))
            if v:
                own_ids.add(v)
        for m in re.finditer(r"Original\s*Document\s*ID\s*:\s*(\S+)", exif_output, re.I):
            v = _norm(m.group(1))
            if v:
                ref_ids.add(v)

    ref_ids -= own_ids
    return {"own_ids": own_ids, "ref_ids": ref_ids}




# ---------------------------------------------------------------------------
# Config snapshot helper (called in the GUI process before spawning workers)
# ---------------------------------------------------------------------------

def build_scan_config() -> dict:
    """
    Snapshot the current PDFReconConfig into a plain serialisable dict.
    Call this in the GUI thread BEFORE submitting to ProcessPoolExecutor.
    """
    return {
        "max_file_size": PDFReconConfig.MAX_FILE_SIZE,
        "exiftool_timeout": PDFReconConfig.EXIFTOOL_TIMEOUT,
        "export_invalid_xref": PDFReconConfig.EXPORT_INVALID_XREF,
        "visual_diff_pages": PDFReconConfig.VISUAL_DIFF_PAGE_LIMIT,
        "exiftool_path": PDFReconConfig.EXIFTOOL_PATH,
    }


def _apply_scan_config(cfg: dict) -> None:
    """Apply a config snapshot to PDFReconConfig in the worker process."""
    PDFReconConfig.MAX_FILE_SIZE = cfg["max_file_size"]
    PDFReconConfig.EXIFTOOL_TIMEOUT = cfg["exiftool_timeout"]
    PDFReconConfig.EXPORT_INVALID_XREF = cfg["export_invalid_xref"]
    PDFReconConfig.VISUAL_DIFF_PAGE_LIMIT = cfg["visual_diff_pages"]
    if cfg.get("exiftool_path"):
        PDFReconConfig.EXIFTOOL_PATH = cfg["exiftool_path"]


# ---------------------------------------------------------------------------
# Worker-process initializer — called once per OS worker process
# ---------------------------------------------------------------------------

def _worker_init(cfg: dict) -> None:
    """
    Initializer for ProcessPoolExecutor worker processes.

    Called exactly once per spawned OS process.  Applies config and starts
    a persistent ExifToolHelper instance so every file handled by this
    worker reuses the same ExifTool background process instead of spawning
    a new one for each file.
    """
    global _et_process

    # Apply config snapshot in this process
    _apply_scan_config(cfg)

    # Set up logging once per worker process
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s [worker] %(message)s")

    if not _EXIFTOOL_MODULE_AVAILABLE:
        logging.warning("pyexiftool not available — using subprocess fallback for ExifTool.")
        return

    exe_path = _resolve_exiftool_path()
    if exe_path is None:
        logging.warning("ExifTool executable not found — using subprocess fallback.")
        return

    try:
        _et_process = _exiftool_module.ExifToolHelper(
            executable=str(exe_path),
            # Pass no common_args so we control all flags per execute() call.
            # This lets us toggle -struct on/off for detailed vs. non-detailed mode.
            common_args=[],
            # Suppress the console window on Windows
            win_shell=True,
        )
        # Trigger auto-start immediately so the first file isn't slow
        _et_process.run()
        logging.info(f"ExifToolHelper started (pid={_et_process.process.pid if hasattr(_et_process, 'process') else '?'})")
    except Exception as e:
        logging.warning(f"Could not start ExifToolHelper: {e} — using subprocess fallback.")
        _et_process = None


# ---------------------------------------------------------------------------
# Top-level worker function (must be module-level for pickling on Windows)
# ---------------------------------------------------------------------------

def process_single_file_worker(fp_str: str, cfg: dict) -> list:
    """
    Process one PDF file for forensic analysis.

    This is a module-level function so it can be pickled and sent to a
    ProcessPoolExecutor worker on Windows.

    Args:
        fp_str: Absolute path to the PDF file as a plain string.
        cfg:    Config snapshot from build_scan_config().

    Returns:
        A list of plain dicts (one for the original, one per revision).
        All Path objects are converted to strings so they survive pickling.
    """
    # Note: _apply_scan_config(cfg) is now called in _worker_init() (once per
    # worker process) rather than once per file.  When running outside of a
    # ProcessPoolExecutor (e.g. unit tests or direct calls), apply it here as
    # a safe fallback so the function still works standalone.
    if _et_process is None:
        _apply_scan_config(cfg)
    fp = Path(fp_str)

    # Set up basic logging in the subprocess so errors are visible
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s [worker] %(message)s")

    try:
        # --- Validate file size ---
        file_size = fp.stat().st_size
        if file_size > PDFReconConfig.MAX_FILE_SIZE:
            raise PDFTooLargeError(f"File size {file_size / (1024 ** 2):.1f} MB exceeds limit")

        # --- Read bytes and open document ---
        raw = fp.read_bytes()
        doc = safe_pdf_open(fp, raw_bytes=raw)

        # --- Extract raw text for indicator detection ---
        txt = _extract_text_for_scanning(raw)


        # --- ExifTool ---
        exif = _run_exiftool(fp, detailed=True)
        parsed_exif = _parse_exif_data(exif)

        # --- Document IDs ---
        document_ids = _extract_all_document_ids(txt, exif)

        # --- Forensic indicators ---
        indicator_keys = scanner_detect_indicators(fp, txt, doc, exif_output=exif, app_instance=None)

        # --- Embedded JavaScript extraction (for malicious file analysis) ---
        if "ContainsJavaScript" in indicator_keys:
            try:
                js_list = extract_embedded_javascript(raw)
                if js_list:
                    indicator_keys["ExtractedJavaScript"] = [
                        {"source": s.get("source"), "code": s.get("code", ""), "xref": s.get("xref")}
                        for s in js_list
                    ]
            except Exception as e:
                logging.warning("JS extraction failed for %s: %s", fp.name, e)

        # --- TouchUp text extraction (normally done via app_instance callback) ---
        # Since app_instance=None in worker mode, we call _extract_touchup_text directly.
        if "TouchUp_TextEdit" in indicator_keys:
            try:
                found_text = _extract_touchup_text(doc)
                indicator_keys["TouchUp_TextEdit"]["found_text"] = found_text
            except Exception as e:
                logging.warning(f"TouchUp text extraction failed for {fp.name}: {e}")

        # --- Layer indicators ---
        _add_layer_indicators(raw, fp, indicator_keys)

        # --- MD5 ---
        md5_hash = hashlib.md5(raw, usedforsecurity=False).hexdigest()

        # --- Timeline ---
        original_timeline = _generate_timeline(fp, txt, exif, parsed_exif)

        # --- Revisions ---
        revisions = _extract_revisions(raw, fp)

        doc.close()

        final_indicator_keys = dict(indicator_keys)
        if revisions:
            final_indicator_keys["HasRevisions"] = {"count": len(revisions)}

        results = [{
            "path": str(fp),
            "indicator_keys": final_indicator_keys,
            "md5": md5_hash,
            "exif": exif,
            "is_revision": False,
            "timeline": original_timeline,
            "status": "success",
            "document_ids": document_ids,
        }]

        # --- Process revisions ---
        for rev_path, basefile, rev_raw in revisions:
            try:
                rev_md5 = hashlib.md5(rev_raw, usedforsecurity=False).hexdigest()
                rev_exif = _run_exiftool(rev_path, detailed=True)
                rev_parsed_exif = _parse_exif_data(rev_exif)

                # Skip invalid XREF revisions if configured (copy is skipped in subprocess;
                # TODO: emit a "copy_request" queue message to restore copy in future PR)
                if (
                    PDFReconConfig.EXPORT_INVALID_XREF
                    and "Warning" in rev_exif
                    and "Invalid xref table" in rev_exif
                ):
                    logging.info(f"Skipping invalid XREF revision {rev_path.name}")
                    continue

                rev_txt = _extract_text_for_scanning(rev_raw)
                revision_timeline = _generate_timeline(rev_path, rev_txt, rev_exif, rev_parsed_exif)

                # Text comparison between revision and final for investigative reports
                revision_diff = None
                try:
                    orig_text = extract_text_from_pdf_bytes(raw)
                    rev_text = extract_text_from_pdf_bytes(rev_raw)
                    if orig_text or rev_text:
                        revision_diff = compute_highlighted_changes(rev_text, orig_text)
                except Exception as e:
                    logging.debug("Revision diff for %s: %s", rev_path.name, e)

                # Visual identity check
                is_identical = False
                try:
                    with fitz.open(fp) as doc_orig, fitz.open(rev_path) as doc_rev:
                        pages_to_compare = min(
                            doc_orig.page_count,
                            doc_rev.page_count,
                            PDFReconConfig.VISUAL_DIFF_PAGE_LIMIT,
                        )
                        if pages_to_compare > 0:
                            is_identical = True
                            for i in range(pages_to_compare):
                                page_orig = doc_orig.load_page(i)
                                page_rev = doc_rev.load_page(i)
                                if page_orig.rect != page_rev.rect:
                                    is_identical = False
                                    break
                                pix_orig = page_orig.get_pixmap(dpi=96)
                                pix_rev = page_rev.get_pixmap(dpi=96)
                                img_orig = Image.frombytes("RGB", [pix_orig.width, pix_orig.height], pix_orig.samples)
                                img_rev = Image.frombytes("RGB", [pix_rev.width, pix_rev.height], pix_rev.samples)
                                if img_orig.size != img_rev.size:
                                    is_identical = False
                                    break
                                if ImageChops.difference(img_orig, img_rev).getbbox() is not None:
                                    is_identical = False
                                    break
                except Exception as ve:
                    logging.warning(f"Visual compare failed for {rev_path.name}: {ve}")
                    is_identical = False

                rev_indicators = {"Revision": {}}
                if is_identical:
                    rev_indicators["VisuallyIdentical"] = {}

                results.append({
                    "path": str(rev_path),
                    "indicator_keys": rev_indicators,
                    "md5": rev_md5,
                    "exif": rev_exif,
                    "is_revision": True,
                    "timeline": revision_timeline,
                    "original_path": str(fp),
                    "is_identical": is_identical,
                    "status": "success",
                    "revision_diff": revision_diff,
                })
            except Exception as e:
                logging.warning(f"Error processing revision {rev_path.name}: {e}")

        return results

    except PDFTooLargeError as e:
        logging.warning(f"Skipping large file {fp.name}: {e}")
        return [{"path": str(fp), "status": "error", "error_type": "file_too_large", "error_message": str(e)}]
    except PDFEncryptedError as e:
        logging.warning(f"Skipping encrypted file {fp.name}: {e}")
        return [{"path": str(fp), "status": "error", "error_type": "file_encrypted", "error_message": str(e)}]
    except PDFCorruptionError as e:
        logging.warning(f"Skipping corrupt file {fp.name}: {e}")
        return [{"path": str(fp), "status": "error", "error_type": "file_corrupt", "error_message": str(e)}]
    except Exception as e:
        logging.exception(f"Unexpected error processing {fp.name}")
        return [{"path": str(fp), "status": "error", "error_type": "processing_error", "error_message": str(e)}]
