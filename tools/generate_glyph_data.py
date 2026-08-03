"""
Development-time generator for the bundled glyph-name data used by Tier 1.

Two artefacts are produced, both offline, from the ``fontTools`` package:

* ``src/assets/agl.txt``      - the Adobe Glyph List (name -> Unicode).
* ``src/cid_glyph_tables.py`` - the two fixed ordering tables defined by the
  OpenType and CFF specifications: the 258-entry standard Macintosh glyph
  order (needed to read a TrueType ``post`` table) and the 391 CFF standard
  strings (needed to read a CFF charset).

fontTools is intentionally a *development* dependency only: it is not
imported at runtime and is not bundled into PDFRecon.exe.  Running this
script is the only time it is needed.

The AGL output uses the upstream AGL format so that an examiner can diff it
against Adobe's published ``glyphlist.txt``:

    # comment
    NAME;XXXX
    NAME;XXXX YYYY

Usage:
    python tools/generate_glyph_data.py

The script prints the SHA-256 of each generated file.  The AGL hash is
recorded in the chain-of-custody log whenever Tier 1 runs, so a decoding can
be tied to the exact table that produced it.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "src" / "assets" / "agl.txt"
TABLES_PATH = REPO_ROOT / "src" / "cid_glyph_tables.py"


def build_table() -> dict[str, list[int]]:
    """Merge the legacy (full) AGL with AGLFN into one name -> codepoints map."""
    try:
        import fontTools.agl as agl
    except ImportError:
        sys.exit(
            "fontTools is required to regenerate the AGL asset.\n"
            "It is a development-only dependency:  pip install fonttools"
        )

    table: dict[str, list[int]] = {}

    # LEGACY_AGL2UV is the full historical list (includes afiiNNNNN names used
    # by older Cyrillic/Greek fonts).  Values may be int or list-of-int.
    for name, value in agl.LEGACY_AGL2UV.items():
        table[name] = [value] if isinstance(value, int) else list(value)

    # AGL For New Fonts; only fills gaps, never overrides the legacy list.
    for name, value in agl.AGL2UV.items():
        table.setdefault(name, [value] if isinstance(value, int) else list(value))

    return table


def render(table: dict[str, list[int]]) -> str:
    lines = [
        "# Adobe Glyph List, as used by PDFRecon Tier 1 (glyph-name decoding).",
        "# Generated offline by tools/generate_agl.py from the fontTools package.",
        "# Format: <glyph name>;<space-separated uppercase hex Unicode scalar values>",
        "# This file is plain text so that it can be audited and diffed against",
        "# Adobe's published glyphlist.txt without running PDFRecon.",
    ]
    for name in sorted(table):
        codepoints = " ".join(f"{cp:04X}" for cp in table[name])
        lines.append(f"{name};{codepoints}")
    return "\n".join(lines) + "\n"


def _format_string_list(name: str, values: list[str], comment: str) -> str:
    """Emit a Python list literal, wrapped at a readable width."""
    lines = [comment, f"{name} = ("]
    row: list[str] = []
    row_len = 0
    for value in values:
        item = repr(value) + ","
        if row and row_len + len(item) + 1 > 92:
            lines.append("    " + " ".join(row))
            row, row_len = [], 0
        row.append(item)
        row_len += len(item) + 1
    if row:
        lines.append("    " + " ".join(row))
    lines.append(")")
    return "\n".join(lines)


def render_tables() -> str:
    from fontTools.cffLib import cffStandardStrings
    from fontTools.ttLib.tables._p_o_s_t import standardGlyphOrder

    header = '''"""
Fixed glyph-ordering tables required to read embedded font programs.

GENERATED FILE - do not edit by hand.  Regenerate with:

    python tools/generate_glyph_data.py

Both tables are constants defined by their respective specifications, not
configuration: they are the same for every font in the world and carry no
locale assumptions.

* MAC_STANDARD_GLYPH_ORDER - the 258 standard Macintosh glyph names.  A
  TrueType ``post`` table of format 2.0 stores a name index per glyph; an
  index below 258 refers into this table instead of the font's own string
  data.  (OpenType specification, ``post`` table.)

* CFF_STANDARD_STRINGS - the 391 predefined CFF strings.  A CFF charset
  stores a SID (string identifier) per glyph; a SID below 391 refers into
  this table instead of the font's String INDEX.  (Adobe CFF specification,
  Appendix A.)
"""
'''
    parts = [
        header,
        _format_string_list(
            "MAC_STANDARD_GLYPH_ORDER",
            list(standardGlyphOrder),
            "# OpenType 'post' format 2.0 standard Macintosh ordering (258 entries).",
        ),
        _format_string_list(
            "CFF_STANDARD_STRINGS",
            list(cffStandardStrings),
            "# Adobe CFF specification Appendix A, standard strings (391 entries).",
        ),
    ]
    return "\n\n".join(parts) + "\n"


def _write(path: Path, text: str, label: str, extra: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    print(f"Wrote {path.relative_to(REPO_ROOT)}")
    if extra:
        print(f"  {extra}")
    print(f"  bytes   : {len(text.encode('utf-8'))}")
    print(f"  sha256  : {digest}")


def main() -> None:
    table = build_table()
    _write(OUTPUT_PATH, render(table), "AGL", extra=f"entries : {len(table)}")
    _write(TABLES_PATH, render_tables(), "tables")


if __name__ == "__main__":
    main()
