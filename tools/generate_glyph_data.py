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
REFERENCE_FONT_PATH = REPO_ROOT / "src" / "assets" / "reference_font.ttf"
REFERENCE_LICENSE_PATH = REPO_ROOT / "src" / "assets" / "reference_font_LICENSE.txt"

#: Unicode blocks kept in the bundled reference font.  These are the blocks a
#: shape comparison can be asked to cover out of the box; anything beyond
#: them needs a reference font of the user's own, which is a setting.
REFERENCE_BLOCKS = [
    (0x0020, 0x007E, "Basic Latin (printable)"),
    (0x00A0, 0x00FF, "Latin-1 Supplement"),
    (0x0100, 0x017F, "Latin Extended-A"),
    (0x0180, 0x024F, "Latin Extended-B"),
    (0x0370, 0x03FF, "Greek and Coptic"),
    (0x0400, 0x04FF, "Cyrillic"),
    (0x2000, 0x206F, "General Punctuation"),
    (0x20A0, 0x20BF, "Currency Symbols"),
]

#: The Bitstream Vera licence permits modification only if the result is
#: renamed away from the protected names.  A subset is a modification.
REFERENCE_FONT_NAME = "PDFReconReference"


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


def _find_dejavu() -> tuple[Path, Path]:
    """
    Locate DejaVu Sans and its licence on this machine.

    matplotlib ships both, and is a common development-environment package.
    Nothing is downloaded: if the font is not already present locally the
    script says so and stops.
    """
    candidates: list[Path] = []
    try:
        import matplotlib
        ttf_dir = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        candidates.append(ttf_dir)
    except Exception:
        pass
    candidates.extend([
        Path(sys.prefix) / "share" / "fonts" / "truetype" / "dejavu",
        Path("/usr/share/fonts/truetype/dejavu"),
    ])

    for directory in candidates:
        font = directory / "DejaVuSans.ttf"
        licence = directory / "LICENSE_DEJAVU"
        if font.is_file():
            return font, licence if licence.is_file() else Path()

    sys.exit(
        "DejaVuSans.ttf was not found locally.\n"
        "It is needed only to regenerate the bundled reference font.\n"
        "Install it via matplotlib (pip install matplotlib) or place\n"
        "DejaVuSans.ttf and LICENSE_DEJAVU somewhere this script can find it.\n"
        "This script never downloads anything."
    )


def build_reference_font() -> None:
    """
    Subset DejaVu Sans to the blocks a shape comparison may need.

    The full font is around 750 kB; the subset is a fraction of that, which
    keeps the packaged executable essentially unchanged while making the
    documented default character inventory actually work.  PyMuPDF's built-in
    Helvetica cannot be used for this: it covers only Latin-1 and silently
    draws everything else, including all of Latin Extended-A, as the same
    .notdef box.
    """
    try:
        from fontTools import subset
        from fontTools.ttLib import TTFont
    except ImportError:
        sys.exit("fontTools is required to regenerate the reference font.")

    source, licence = _find_dejavu()
    font = TTFont(str(source))

    codepoints = [
        cp
        for low, high, _ in REFERENCE_BLOCKS
        for cp in range(low, high + 1)
    ]

    options = subset.Options()
    options.name_IDs = ["*"]
    options.name_legacy = True
    options.recommended_glyphs = True
    options.drop_tables += ["DSIG"]
    options.layout_features = []
    options.hinting = False
    options.desubroutinize = True
    options.glyph_names = True  # keep post names so Tier 1 can be tested

    subsetter = subset.Subsetter(options=options)
    subsetter.populate(unicodes=codepoints)
    subsetter.subset(font)

    # Renaming is a licence condition for any modified copy.
    name_table = font["name"]
    for record in name_table.names:
        if record.nameID in (1, 3, 4, 6, 16, 18):
            name_table.setName(
                REFERENCE_FONT_NAME, record.nameID,
                record.platformID, record.platEncID, record.langID)

    REFERENCE_FONT_PATH.parent.mkdir(parents=True, exist_ok=True)
    font.save(str(REFERENCE_FONT_PATH))
    font.close()

    data = REFERENCE_FONT_PATH.read_bytes()
    covered = sum(1 for _ in codepoints)
    print(f"Wrote {REFERENCE_FONT_PATH.relative_to(REPO_ROOT)}")
    print(f"  source  : {source}")
    print(f"  blocks  : {len(REFERENCE_BLOCKS)} ({covered} code points requested)")
    print(f"  bytes   : {len(data)}")
    print(f"  sha256  : {hashlib.sha256(data).hexdigest()}")

    if licence and licence.is_file():
        header = (
            "The PDFRecon reference font (src/assets/reference_font.ttf) is a\n"
            "subset of DejaVu Sans, renamed to \"PDFReconReference\" as the\n"
            "licence below requires for modified copies.  It is used only to\n"
            "render comparison glyphs for Tier 2 shape matching; it is never\n"
            "embedded in output.  Regenerate it with tools/generate_glyph_data.py.\n"
            "\n"
            + "=" * 70 + "\n\n"
        )
        REFERENCE_LICENSE_PATH.write_text(
            header + licence.read_text(encoding="utf-8"),
            encoding="utf-8", newline="\n")
        print(f"Wrote {REFERENCE_LICENSE_PATH.relative_to(REPO_ROOT)}")
    else:
        print("WARNING: LICENSE_DEJAVU not found; the licence text must be "
              "shipped alongside the font.")


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
    build_reference_font()


if __name__ == "__main__":
    main()
