"""
Tests for non-embedded font detection.

A font program lives in /FontFile, /FontFile2 or /FontFile3 inside the font's
/FontDescriptor - never in the font dictionary itself. Composite (Type0) fonts
add a step, because the descriptor belongs to the descendant CIDFont named in
/DescendantFonts.

An earlier version looked for those keys in the font dictionary, found them
nowhere, and reported every embedded font as missing. That is a false positive
in a forensic indicator: "Non-Embedded Font" suggests a document was produced
or edited where the original font was unavailable, so asserting it about an
embedded font is a claim the file does not support. It was reported from
casework evaluation, against a file whose Type0 font carried a perfectly good
FontFile2 on its descendant.
"""

import io
import os
import sys

import fitz
import pikepdf
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.advanced_forensics import detect_non_embedded_fonts

EMBEDDABLE_FONT = r"C:\Windows\Fonts\arial.ttf"


def _reported(data):
    """Run the detector over PDF bytes and return (count, fonts)."""
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        indicators = {}
        detect_non_embedded_fonts(doc, indicators)
    finally:
        doc.close()
    entry = indicators.get("NonEmbeddedFont")
    return (entry["count"], entry["fonts"]) if entry else (0, [])


def _embedded_pdf(set_simple):
    """A PDF whose only font is genuinely embedded."""
    if not os.path.exists(EMBEDDABLE_FONT):
        pytest.skip("no embeddable system font available")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_font(fontname="F", fontfile=EMBEDDABLE_FONT, set_simple=set_simple)
    page.insert_text((50, 80), "Embedded sample", fontname="F", fontsize=12)
    doc.subset_fonts()
    data = doc.tobytes()
    doc.close()
    return data


def _base14_pdf():
    """A PDF using a standard-14 font, which is genuinely not embedded."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 80), "Base 14 sample", fontname="helv", fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


def _strip_font_files(data):
    """Remove every embedded font program, leaving the descriptors behind."""
    pdf = pikepdf.open(io.BytesIO(data))
    try:
        for obj in pdf.objects:
            try:
                if not isinstance(obj, pikepdf.Dictionary):
                    continue
                for key in ("/FontFile", "/FontFile2", "/FontFile3"):
                    if key in obj:
                        del obj[key]
            except Exception:
                pass
        out = io.BytesIO()
        pdf.save(out)
    finally:
        pdf.close()
    return out.getvalue()


# --------------------------------------------------------------------------
# Embedded fonts must not be reported
# --------------------------------------------------------------------------

def test_embedded_simple_font_is_not_reported():
    """The descriptor hangs directly off a simple font."""
    count, fonts = _reported(_embedded_pdf(set_simple=True))
    assert count == 0, "embedded simple font wrongly reported: %s" % (fonts,)


def test_embedded_composite_font_is_not_reported():
    """
    The descriptor hangs off the descendant CIDFont.

    This is the shape from the report: Type0 -> DescendantFonts ->
    CIDFontType2 -> FontDescriptor -> FontFile2.
    """
    count, fonts = _reported(_embedded_pdf(set_simple=False))
    assert count == 0, "embedded composite font wrongly reported: %s" % (fonts,)


def test_the_fixture_really_is_composite_and_embedded():
    """Guards the test above against silently checking the wrong shape."""
    doc = fitz.open(stream=_embedded_pdf(set_simple=False), filetype="pdf")
    try:
        subtypes = set()
        has_descendant = False
        font_file_found = False
        for xref in range(1, doc.xref_length()):
            if not doc.xref_is_font(xref):
                continue
            subtypes.add(doc.xref_get_key(xref, "Subtype")[1])
            if doc.xref_get_key(xref, "DescendantFonts")[0] != "null":
                has_descendant = True
            descriptor = doc.xref_get_key(xref, "FontDescriptor")
            if descriptor[0] == "xref":
                dxref = int(descriptor[1].split()[0])
                if doc.xref_get_key(dxref, "FontFile2")[0] != "null":
                    font_file_found = True
    finally:
        doc.close()
    assert "/Type0" in subtypes
    assert has_descendant
    assert font_file_found


# --------------------------------------------------------------------------
# Genuinely missing fonts must still be reported
# --------------------------------------------------------------------------

def test_base14_font_is_reported():
    count, fonts = _reported(_base14_pdf())
    assert count == 1
    assert any("Helvetica" in name for name in fonts)


def test_simple_font_stripped_of_its_program_is_reported():
    count, fonts = _reported(_strip_font_files(_embedded_pdf(set_simple=True)))
    assert count == 1, "expected the stripped font to be reported, got %s" % (fonts,)


def test_composite_font_stripped_of_its_program_is_reported():
    """The descendant must be followed when concluding a font is absent, too."""
    count, fonts = _reported(_strip_font_files(_embedded_pdf(set_simple=False)))
    assert count == 1, "expected the stripped font to be reported, got %s" % (fonts,)


# --------------------------------------------------------------------------
# One entry per logical font
# --------------------------------------------------------------------------

def test_composite_font_is_counted_once():
    """
    A Type0 font and its descendant CIDFont are one font, not two.

    Both are /Type /Font objects, so scanning objects blindly lists the pair -
    which is how "AZFWVZ+ArialUnicodeMS" and "AZFWVZ+ArialUnicodeMS-Identity-H"
    both appeared in the report that prompted this.
    """
    count, fonts = _reported(_strip_font_files(_embedded_pdf(set_simple=False)))
    assert count == 1
    assert len(fonts) == 1


def test_count_matches_the_listed_fonts():
    """The count once included duplicates while the list was deduplicated."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 60), "One", fontname="helv", fontsize=12)
    page.insert_text((50, 90), "Two", fontname="tiro", fontsize=12)
    page.insert_text((50, 120), "Three", fontname="cour", fontsize=12)
    data = doc.tobytes()
    doc.close()

    count, fonts = _reported(data)
    assert count == len(fonts) == 3


# --------------------------------------------------------------------------
# Fonts with no font program to miss
# --------------------------------------------------------------------------

def test_type3_font_is_not_reported():
    """
    A Type3 font defines its glyphs as content streams inside the document,
    so there is no external font program that could be missing.
    """
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    charproc = pdf.make_stream(b"1000 0 0 0 750 750 d1 0 0 750 750 re f")
    type3 = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name("/Font"),
        Subtype=pikepdf.Name("/Type3"),
        FontBBox=pikepdf.Array([0, 0, 750, 750]),
        FontMatrix=pikepdf.Array([0.001, 0, 0, 0.001, 0, 0]),
        CharProcs=pikepdf.Dictionary(square=charproc),
        Encoding=pikepdf.Dictionary(
            Type=pikepdf.Name("/Encoding"),
            Differences=pikepdf.Array([97, pikepdf.Name("/square")]),
        ),
        FirstChar=97,
        LastChar=97,
        Widths=pikepdf.Array([1000]),
    ))
    page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(T3=type3))
    page.Contents = pdf.make_stream(b"BT /T3 24 Tf 20 100 Td (a) Tj ET")
    out = io.BytesIO()
    pdf.save(out)
    pdf.close()

    count, fonts = _reported(out.getvalue())
    assert count == 0, "Type3 font wrongly reported as non-embedded: %s" % (fonts,)


# --------------------------------------------------------------------------
# Robustness
# --------------------------------------------------------------------------

def test_document_without_fonts_reports_nothing():
    doc = fitz.open()
    doc.new_page()
    data = doc.tobytes()
    doc.close()
    assert _reported(data) == (0, [])


def test_none_document_does_not_raise():
    indicators = {}
    detect_non_embedded_fonts(None, indicators)
    assert indicators == {}
