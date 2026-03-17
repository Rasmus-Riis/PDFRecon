"""
Revision Text Comparison Module

Produces structured diffs between extracted incremental revisions and the final
version to highlight manipulated content for investigative reports.
"""

import difflib
from typing import List, Optional, Tuple


def extract_text_from_pdf_bytes(raw: bytes) -> str:
    """Extract full text from PDF bytes using PyMuPDF (for use in scanner/worker)."""
    try:
        import fitz
        doc = fitz.open(stream=raw, filetype="pdf")
        try:
            parts = []
            for i in range(len(doc)):
                try:
                    parts.append(doc[i].get_text("text", sort=True))
                except Exception:
                    parts.append("")
            return "\n".join(parts)
        finally:
            doc.close()
    except Exception:
        return ""


def compute_revision_diff(
    revision_text: str,
    final_text: str,
    from_label: str = "Previous Version",
    to_label: str = "Final Version",
) -> List[str]:
    """
    Compute unified diff lines between revision and final text for reports.

    Returns list of diff lines (with +/- and context) suitable for inclusion
    in investigative reports.
    """
    rev_lines = revision_text.splitlines(keepends=True)
    final_lines = final_text.splitlines(keepends=True)
    diff = difflib.unified_diff(
        rev_lines,
        final_lines,
        fromfile=from_label,
        tofile=to_label,
        lineterm="",
    )
    return list(diff)


def compute_highlighted_changes(
    revision_text: str,
    final_text: str,
) -> dict:
    """
    Return structured added/removed content for investigative reports.

    Returns:
        {
            "additions": [{"line_no": int, "text": str}, ...],
            "deletions": [{"line_no": int, "text": str}, ...],
            "unified_diff_lines": [...],
        }
    """
    additions = []
    deletions = []
    rev_lines = revision_text.splitlines()
    final_lines = final_text.splitlines()
    matcher = difflib.SequenceMatcher(None, rev_lines, final_lines)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "delete":
            for idx, line in enumerate(rev_lines[i1:i2], start=i1 + 1):
                deletions.append({"line_no": idx, "text": line})
        elif tag == "insert":
            for idx, line in enumerate(final_lines[j1:j2], start=j1 + 1):
                additions.append({"line_no": idx, "text": line})
        elif tag == "replace":
            for idx, line in enumerate(rev_lines[i1:i2], start=i1 + 1):
                deletions.append({"line_no": idx, "text": line})
            for idx, line in enumerate(final_lines[j1:j2], start=j1 + 1):
                additions.append({"line_no": idx, "text": line})

    unified_lines = compute_revision_diff(revision_text, final_text)
    return {
        "additions": additions,
        "deletions": deletions,
        "unified_diff_lines": unified_lines,
    }
