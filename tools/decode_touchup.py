"""
Run the tiered CID decoder over the TouchUp text of one or more PDFs.

This is the review tool for the feature branch: the decoder is wired into the
scan path, but nothing surfaces its results in the Inspector yet, so this
script prints them in a readable form and can write out the rendered glyph
bitmaps for visual verification.

Usage:
    py -3.12 tools/decode_touchup.py CASE.pdf [MORE.pdf ...]
    py -3.12 tools/decode_touchup.py -v CASE.pdf          # per-character detail
    py -3.12 tools/decode_touchup.py --glyphs out/ CASE.pdf
    py -3.12 tools/decode_touchup.py --json result.json CASE.pdf
    py -3.12 tools/decode_touchup.py --reference-font C:/Windows/Fonts/times.ttf CASE.pdf
    py -3.12 tools/decode_touchup.py --inventory 0020-007E,0400-04FF CASE.pdf

Nothing is written to the PDF and no network access occurs.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    import fitz
except ImportError:
    sys.exit(
        "PyMuPDF is not available to this interpreter.\n"
        "Use the environment PDFRecon runs in, e.g.:  py -3.12 tools/decode_touchup.py ..."
    )

from src.cid_decoder import DecoderSettings
from src.data_processing import DataProcessingMixin


CONFIDENCE_MARK = {"CERTAIN": "[CERTAIN ]", "PROBABLE": "[PROBABLE]",
                   "SPECULATIVE": "[SPECULATIVE]"}


class _Runner(DataProcessingMixin):
    """Exposes the two extraction methods without starting the GUI."""


def analyse(path: Path, settings: DecoderSettings, verbose: bool,
            glyph_dir: Path | None) -> dict:
    runner = _Runner()
    doc = None
    try:
        doc = fitz.open(path)
        page_text, captured, pdf_bytes = runner._extract_touchup_text(
            doc, capture_runs=True)
        decoded, custody = runner._decode_touchup_runs(captured, pdf_bytes)
    finally:
        if doc is not None:
            doc.close()

    print(f"\n{'=' * 78}\n{path.name}\n{'=' * 78}")

    if not captured:
        print("  No TouchUp-marked text found.")
        if page_text:
            print("  (The masked extraction still returned text; the region "
                  "markers may use a form this build does not recognise.)")
        return {"file": str(path), "runs": [], "custody": None}

    print(f"  TouchUp runs captured : {len(captured)}")
    print(f"  Text via ToUnicode    : "
          f"{ {k: v for k, v in page_text.items()} if page_text else '(none)'}")
    print()

    for record in decoded:
        confidence = record.get("confidence", "?")
        mark = CONFIDENCE_MARK.get(confidence, f"[{confidence}]")
        print(f"  {mark} page {record['page']} "
              f"/{record.get('font_resource')} (xref {record.get('font_xref')})")
        if record.get("error"):
            print(f"      error  : {record['error']}")
            continue

        print(f"      text   : {record.get('text')!r}")
        print(f"      method : {record.get('method')}   "
              f"resolved {record.get('resolved')}/{record.get('length')}")

        for tier in record.get("tiers_run", []):
            state = "ran" if tier["ran"] else "skipped"
            print(f"        tier {tier['tier']} {tier['method']:<11} {state:<8}"
                  f" resolved={tier['resolved']:<4} {tier['detail']}")

        font = record.get("evidence", {}).get("font", {})
        if font:
            print(f"      font   : {font.get('base_font')} "
                  f"[{font.get('subtype')}/{font.get('encoding')}] "
                  f"sha256={(font.get('font_program_sha256') or '')[:16]}")
            if font.get("tounicode_xref"):
                print(f"      cmap   : object {font['tounicode_xref']}, "
                      f"{font.get('tounicode_entries')} entries")

        unresolved = record.get("evidence", {}).get("unresolved_codes")
        if unresolved:
            print(f"      UNRESOLVED codes: {', '.join(unresolved)}")

        for alternative in (record.get("alternatives") or [])[:3]:
            print(f"      alt    : {alternative['text']!r}")
            print(f"               {alternative['reason']}")

        if verbose:
            print("      per character:")
            for char in record.get("per_char", []):
                score = "" if char["score"] is None else f" score={char['score']:.3f}"
                margin = "" if char["margin"] is None else f" margin={char['margin']:.3f}"
                alts = "".join(char["alternatives"][:4])
                print(f"        {char['code_hex']}  {char['text']!r:6} "
                      f"{char['method']:<11} {char['confidence']:<11}"
                      f"{score}{margin}"
                      f"{('  alts=' + repr(alts)) if alts else ''}")
                if char.get("note"):
                    print(f"                {char['note']}")

        if glyph_dir is not None:
            written = _write_glyphs(record, path, glyph_dir)
            if written:
                print(f"      glyphs : {written} PNG(s) in {glyph_dir}")
        print()

    if custody:
        print("  Chain-of-custody summary:")
        for line in json.dumps(custody, indent=2, ensure_ascii=False).splitlines():
            print(f"    {line}")

    return {"file": str(path), "runs": decoded, "custody": custody}


def _write_glyphs(record: dict, pdf_path: Path, glyph_dir: Path) -> int:
    """Write the rendered glyph bitmaps so they can be eyeballed."""
    bitmaps = (record.get("evidence", {})
               .get("shape_match", {})
               .get("glyph_bitmaps")) or {}
    if not bitmaps:
        return 0

    # Which character each code was read as, so the filename carries the claim.
    claimed = {c["code_hex"]: c["text"] for c in record.get("per_char", [])}
    glyph_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for code_hex, uri in bitmaps.items():
        if not uri.startswith("data:image/png;base64,"):
            continue
        char = claimed.get(code_hex, "")
        safe = "".join(ch if ch.isalnum() else f"u{ord(ch):04X}" for ch in char)
        name = (f"{pdf_path.stem}_p{record['page']}"
                f"_code{code_hex}_read-as-{safe or 'unknown'}.png")
        data = base64.b64decode(uri.split(",", 1)[1])
        (glyph_dir / name).write_bytes(data)
        count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Decode TouchUp text with the tiered CID decoder.")
    parser.add_argument("pdfs", nargs="+", type=Path)
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="show every character with its score and margin")
    parser.add_argument("--glyphs", type=Path, metavar="DIR",
                        help="write rendered glyph bitmaps here for visual checking")
    parser.add_argument("--json", type=Path, metavar="FILE",
                        help="write the full records, including all evidence")
    parser.add_argument("--reference-font", metavar="TTF",
                        help="reference typeface for Tier 2; use one resembling "
                             "the document's, it matters more than any threshold")
    parser.add_argument("--inventory", metavar="RANGES",
                        help="character inventory, e.g. 0020-007E,0400-04FF")
    parser.add_argument("--certain-margin", type=float, metavar="X",
                        help="margin required before Tier 2 reports CERTAIN")
    parser.add_argument("--no-tier1", action="store_true",
                        help="disable glyph-name decoding")
    parser.add_argument("--no-tier2", action="store_true",
                        help="disable shape matching")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        format="%(levelname)s %(message)s")

    base = DecoderSettings.from_config()
    settings = DecoderSettings(
        enabled=True,
        tier0_tounicode=base.tier0_tounicode,
        tier1_glyphnames=not args.no_tier1,
        tier2_shapematch=not args.no_tier2,
        character_inventory=args.inventory or base.character_inventory,
        reference_font_path=args.reference_font or base.reference_font_path,
        shape_certain_margin=(args.certain_margin
                              if args.certain_margin is not None
                              else base.shape_certain_margin),
        shape_min_score=base.shape_min_score,
        shape_bitmap_size=base.shape_bitmap_size,
        max_alternatives=base.max_alternatives,
        confusable_groups=base.confusable_groups,
    )

    # The scan path reads settings from PDFReconConfig, so mirror the
    # overrides there for the duration of this run.
    from src.config import PDFReconConfig
    PDFReconConfig.CID_TIER1_GLYPHNAMES = settings.tier1_glyphnames
    PDFReconConfig.CID_TIER2_SHAPEMATCH = settings.tier2_shapematch
    PDFReconConfig.CID_CHARACTER_INVENTORY = settings.character_inventory
    PDFReconConfig.CID_REFERENCE_FONT_PATH = settings.reference_font_path
    PDFReconConfig.CID_SHAPE_CERTAIN_MARGIN = settings.shape_certain_margin

    results = []
    for pdf in args.pdfs:
        if not pdf.is_file():
            print(f"\nSkipping {pdf}: not a file")
            continue
        try:
            results.append(analyse(pdf, settings, args.verbose, args.glyphs))
        except Exception as exc:
            print(f"\n{pdf.name}: FAILED - {type(exc).__name__}: {exc}")
            if args.debug:
                raise

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nWrote full records to {args.json}")


if __name__ == "__main__":
    main()
