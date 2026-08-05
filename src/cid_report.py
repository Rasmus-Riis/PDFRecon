"""
Presentation of CID decoding results.

The Inspector, the exports, the signed report and the CLI must describe a
decoding the same way.  Every formatter lives here so they cannot drift: a
run that reads PROBABLE on screen must read PROBABLE in the spreadsheet and
in the report handed to a court.

The one rule this module enforces everywhere: a reading is never presented
without its confidence.  :func:`labelled_text` is the only sanctioned way to
put decoded text in front of a reader, and it refuses to return a bare
string for anything below CERTAIN.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

CERTAIN = "CERTAIN"
PROBABLE = "PROBABLE"
SPECULATIVE = "SPECULATIVE"

_ORDER = {SPECULATIVE: 0, PROBABLE: 1, CERTAIN: 2}

#: Colours for the confidence badge.  SPECULATIVE is deliberately the odd one
#: out - red text on a dark red ground, so it cannot be skim-read as a
#: confirmed value the way an amber label can.
CONFIDENCE_COLOURS = {
    CERTAIN: {"fg": "#8ee9a8", "bg": "#173d23", "accent": "#2E7D32"},
    PROBABLE: {"fg": "#f5d98a", "bg": "#413212", "accent": "#B8860B"},
    SPECULATIVE: {"fg": "#ff9d9d", "bg": "#4a0e0e", "accent": "#B22222"},
}

#: Prefix used wherever colour is unavailable - spreadsheets, CSV, plain text,
#: signed reports.  Text and label travel together as one string.
CONFIDENCE_PREFIX = {
    CERTAIN: "[CERTAIN]",
    PROBABLE: "[PROBABLE]",
    SPECULATIVE: "[SPECULATIVE]",
}


def _confidence_of(record: dict) -> str:
    value = (record or {}).get("confidence") or SPECULATIVE
    return value if value in _ORDER else SPECULATIVE


def weakest_confidence(records: Iterable[dict]) -> Optional[str]:
    """The lowest confidence across records, or ``None`` when there are none."""
    levels = [_confidence_of(r) for r in records or []]
    if not levels:
        return None
    return min(levels, key=lambda level: _ORDER[level])


def labelled_text(record: dict, *, max_length: Optional[int] = None) -> str:
    """
    Decoded text with its confidence attached.

    CERTAIN text is returned as-is; anything less is prefixed with its level,
    so an inferred reading cannot be copied out of a report and quoted as a
    confirmed one.
    """
    if not record:
        return ""
    text = record.get("text")
    if text is None:
        reason = record.get("error") or "not decoded"
        return f"{CONFIDENCE_PREFIX[SPECULATIVE]} <{reason}>"

    if max_length and len(text) > max_length:
        text = text[:max_length] + "…"

    confidence = _confidence_of(record)
    if confidence == CERTAIN:
        return text
    return f"{CONFIDENCE_PREFIX[confidence]} {text}"


def method_of(record: dict) -> str:
    return (record or {}).get("method") or "undecoded"


def summarise(decoded_runs: Sequence[dict]) -> dict:
    """
    Condense a file's decoded runs for a table cell or a summary line.

    Returns counts per confidence level, the weakest level present, and how
    many characters no tier could resolve.
    """
    runs = [r for r in (decoded_runs or []) if r]
    counts = {CERTAIN: 0, PROBABLE: 0, SPECULATIVE: 0}
    unresolved = 0
    for record in runs:
        counts[_confidence_of(record)] += 1
        unresolved += len(
            (record.get("evidence") or {}).get("unresolved_codes") or [])
    return {
        "runs": len(runs),
        "counts": counts,
        "weakest": weakest_confidence(runs),
        "unresolved_characters": unresolved,
        "methods": sorted({method_of(r) for r in runs}),
    }


def summary_line(decoded_runs: Sequence[dict]) -> str:
    """One line describing a file's decoding, for a column or a log entry."""
    stats = summarise(decoded_runs)
    if not stats["runs"]:
        return ""
    parts = [f"{stats['runs']} run(s)"]
    for level in (CERTAIN, PROBABLE, SPECULATIVE):
        if stats["counts"][level]:
            parts.append(f"{stats['counts'][level]} {level.lower()}")
    if stats["unresolved_characters"]:
        parts.append(f"{stats['unresolved_characters']} unresolved char(s)")
    return ", ".join(parts)


def export_rows(decoded_runs: Sequence[dict]) -> list[dict]:
    """
    Flatten decoded runs into rows for a spreadsheet or CSV.

    Method and confidence are separate columns *and* baked into the text via
    :func:`labelled_text`, so a reading keeps its label even if someone
    copies a single cell out of the sheet.
    """
    rows = []
    for record in decoded_runs or []:
        if not record:
            continue
        evidence = record.get("evidence") or {}
        font = evidence.get("font") or {}
        shape = evidence.get("shape_match") or {}
        reference = shape.get("reference") or {}
        alternatives = [a.get("text", "") for a in (record.get("alternatives") or [])]
        rows.append({
            "page": record.get("page"),
            "text": labelled_text(record),
            "method": method_of(record),
            "confidence": _confidence_of(record),
            "resolved": f"{record.get('resolved', 0)}/{record.get('length', 0)}",
            "font": font.get("base_font") or record.get("font_resource") or "",
            "font_xref": record.get("font_xref"),
            "font_sha256": font.get("font_program_sha256") or "",
            "encoded_hex": evidence.get("encoded_hex") or "",
            "unresolved_codes": ", ".join(evidence.get("unresolved_codes") or []),
            "reference_font": reference.get("reference_font") or "",
            "alternatives": " | ".join(alternatives[:5]),
            "tiers": "; ".join(
                f"{t['tier']}:{t['method']}"
                f"={'skipped' if not t['ran'] else t['resolved']}"
                for t in record.get("tiers_run") or []
            ),
        })
    return rows


#: Column order and headings for tabular exports.
EXPORT_COLUMNS = [
    ("page", "Page"),
    ("text", "Decoded text"),
    ("method", "Decoding method"),
    ("confidence", "Confidence"),
    ("resolved", "Characters resolved"),
    ("font", "Font"),
    ("font_xref", "Font object"),
    ("font_sha256", "Font SHA-256"),
    ("encoded_hex", "Raw operand (hex)"),
    ("unresolved_codes", "Unresolved codes"),
    ("reference_font", "Reference font"),
    ("alternatives", "Alternative readings"),
    ("tiers", "Tiers run"),
]


def format_plain(decoded_runs: Sequence[dict], *, verbose: bool = False,
                 indent: str = "") -> str:
    """
    Render decoded runs as plain text, for the CLI and signed reports.

    With *verbose*, every character is listed with its score and margin so a
    reader can see exactly which position is weak.
    """
    runs = [r for r in (decoded_runs or []) if r]
    if not runs:
        return ""

    lines = []
    for record in runs:
        confidence = _confidence_of(record)
        lines.append(
            f"{indent}{CONFIDENCE_PREFIX[confidence]} page {record.get('page')}"
            f" /{record.get('font_resource')}"
        )
        if record.get("error"):
            lines.append(f"{indent}    error: {record['error']}")
            continue
        lines.append(f"{indent}    text   : {record.get('text')!r}")
        lines.append(
            f"{indent}    method : {method_of(record)}"
            f"   resolved {record.get('resolved')}/{record.get('length')}")

        for tier in record.get("tiers_run") or []:
            state = "ran" if tier["ran"] else "skipped"
            lines.append(
                f"{indent}      tier {tier['tier']} {tier['method']:<11} {state:<8}"
                f" resolved={tier['resolved']:<4} {tier['detail']}")

        evidence = record.get("evidence") or {}
        font = evidence.get("font") or {}
        if font:
            lines.append(
                f"{indent}    font   : {font.get('base_font')} "
                f"[{font.get('subtype')}/{font.get('encoding')}] "
                f"sha256={(font.get('font_program_sha256') or '')[:16]}")
        unresolved = evidence.get("unresolved_codes")
        if unresolved:
            lines.append(f"{indent}    UNRESOLVED: {', '.join(unresolved)}")

        for alternative in (record.get("alternatives") or [])[:3]:
            lines.append(f"{indent}    alt    : {alternative.get('text')!r}")
            lines.append(f"{indent}             {alternative.get('reason')}")

        if verbose:
            for char in record.get("per_char") or []:
                score = "" if char.get("score") is None else f" score={char['score']:.3f}"
                margin = "" if char.get("margin") is None else f" margin={char['margin']:.3f}"
                alts = "".join(char.get("alternatives") or [])[:6]
                lines.append(
                    f"{indent}      {char['code_hex']} {char['text']!r:6} "
                    f"{char['method']:<11} {char['confidence']:<11}{score}{margin}"
                    f"{('  alts=' + repr(alts)) if alts else ''}")
    return "\n".join(lines)


def glyph_bitmaps(record: dict) -> dict[str, str]:
    """Rendered glyph bitmaps for a run, as ``{code hex: data URI}``."""
    return ((record or {}).get("evidence", {})
            .get("shape_match", {})
            .get("glyph_bitmaps")) or {}


def custody_details(decode_custody: Optional[dict],
                    decoded_runs: Sequence[dict]) -> Optional[dict]:
    """
    Build the chain-of-custody payload for a file's decoding.

    Records what ran and against which tables, so a decoding in the log can
    be tied to the exact inputs that produced it.
    """
    if not decode_custody and not decoded_runs:
        return None
    stats = summarise(decoded_runs)
    details = {
        "description": "Text decoded from fonts lacking a usable ToUnicode CMap",
        "runs_decoded": stats["runs"],
        "confidence_counts": {k: v for k, v in stats["counts"].items() if v},
        "weakest_confidence": stats["weakest"],
        "unresolved_characters": stats["unresolved_characters"],
        "methods": stats["methods"],
    }
    if decode_custody:
        details.update({
            "tiers": decode_custody.get("tiers"),
            "agl_sha256": decode_custody.get("agl_sha256"),
            "reference_fonts": decode_custody.get("reference_fonts"),
            "document_font_sha256": decode_custody.get("document_font_sha256"),
        })
    return details
