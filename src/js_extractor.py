"""
Embedded JavaScript Extraction Module

Extracts and decompresses JavaScript from PDF streams for analysis of
potentially malicious files. Works on raw PDF bytes (no GUI dependency).
"""

import re
import zlib
import base64
import binascii
import logging
from pathlib import Path
from typing import List, Optional

import fitz


def _decompress_stream(raw: bytes) -> Optional[str]:
    """Attempt to decompress a PDF stream body."""
    for fn in (
        lambda d: zlib.decompress(d),
        lambda d: zlib.decompress(d, -zlib.MAX_WBITS),
        lambda d: base64.a85decode(re.sub(rb"\s", b"", d), adobe=True),
        lambda d: binascii.unhexlify(re.sub(rb"\s|>", b"", d)),
    ):
        try:
            return fn(raw).decode("utf-8", errors="replace")
        except Exception:
            continue
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return None


def extract_embedded_javascript(raw_pdf: bytes) -> List[dict]:
    """
    Extract all embedded JavaScript from PDF raw bytes.

    Returns list of dicts:
        {"source": str, "code": str, "xref": int or None, "auto_run": bool}
    """
    results = []
    try:
        doc = fitz.open(stream=raw_pdf, filetype="pdf")
        try:
            xref_count = doc.xref_length()
            for xref in range(1, xref_count):
                try:
                    if not doc.xref_is_stream(xref):
                        continue
                    obj_text = doc.xref_object(xref, compressed=False)
                    if isinstance(obj_text, bytes):
                        obj_text = obj_text.decode("latin-1", errors="replace")
                    if "/JavaScript" not in obj_text and "/JS " not in obj_text and "/JS(" not in obj_text:
                        continue
                    stream = doc.xref_stream(xref)
                    if not stream:
                        stream = doc.xref_stream_raw(xref)
                        if stream:
                            decoded = _decompress_stream(stream)
                            if decoded:
                                stream = decoded.encode("utf-8", errors="replace")
                    if stream:
                        code = stream.decode("utf-8", errors="replace") if isinstance(stream, bytes) else str(stream)
                    else:
                        code = _decompress_stream(doc.xref_stream_raw(xref)) if doc.xref_stream_raw(xref) else ""
                    if code and code.strip():
                        results.append({
                            "source": f"xref_{xref}",
                            "code": code.strip(),
                            "xref": xref,
                            "auto_run": None,
                        })
                except Exception as e:
                    logging.debug("JS extract xref %s: %s", xref, e)
        finally:
            doc.close()
    except Exception as e:
        logging.warning("JS extraction failed: %s", e)

    # Fallback: raw scan for /JS followed by stream
    if not results:
        stream_re = re.compile(rb"stream\s*\r?\n(.*?)\r?\nendstream", re.DOTALL)
        for m in re.finditer(rb"/JS\s*[<(]", raw_pdf):
            start = m.start()
            for stream_m in stream_re.finditer(raw_pdf, max(start - 2000, 0), min(start + 5000, len(raw_pdf))):
                stream_body = stream_m.group(1).strip()
                if len(stream_body) > 10:
                    code = _decompress_stream(stream_body)
                    if code and ("function" in code or "app." in code or "this." in code or "util." in code):
                        results.append({
                            "source": "raw_scan",
                            "code": code,
                            "xref": None,
                            "auto_run": None,
                        })
                        break
    return results


def extract_javascript_from_file(filepath: Path) -> List[dict]:
    """Load PDF from file and extract embedded JavaScript."""
    raw = filepath.read_bytes()
    return extract_embedded_javascript(raw)
