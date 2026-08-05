"""
Tests for the tiered CID / ToUnicode decoder (Tiers 0-2).

All fixtures are synthesised in-memory. Nothing here reads a system font or
requires fontTools, so the suite runs identically on an isolated machine:
document fonts come from PyMuPDF's built-in base-14 set and from the bundled
reference font, and PDFs are assembled with pikepdf.

Coverage follows the four cases the feature has to handle -

  (a) a font with a valid ToUnicode CMap                -> Tier 0, CERTAIN
  (b) ToUnicode stripped, meaningful glyph names remain -> Tier 1, CERTAIN
  (c) a subset font with only /gNN-style names          -> falls through
  (d) a short fragment                                  -> still decodes

- and deliberately exercises more than one script and a font using non-ASCII
diacritics, so an implicitly English-only assumption would fail here.
"""

import io
import os
import pathlib
import shutil
import sys
import tempfile
import unittest

import fitz
import pikepdf

from src import cid_fonts, cid_shapes
from src.cid_decoder import (
    CERTAIN, METHOD_GLYPHNAMES, METHOD_NONE, METHOD_SHAPEMATCH,
    METHOD_TOUNICODE, PROBABLE, SPECULATIVE, UNRESOLVED_PLACEHOLDER,
    DecoderCache, DecoderSettings, decode, summarise_for_custody,
)
from src.cid_fonts import (
    classify_glyph_name, glyph_name_to_text, load_agl, parse_tounicode_cmap,
    resolve_font, split_codes,
)
from src.cid_shapes import (
    DEFAULT_INVENTORY, build_reference_set, bundled_reference_font,
    parse_inventory,
)


# --------------------------------------------------------------------------
# Fixture helpers
# --------------------------------------------------------------------------

def _builtin_font_buffer(name="tiro"):
    """A base-14 font buffer, usable as a *document* font.

    Times ("tiro") is deliberately not the bundled sans-serif reference font,
    so Tier 2 is never scored against itself.
    """
    return bytes(fitz.Font(name).buffer)


def build_pdf(text, *, fontbuffer=None, fontfile=None, subset=True, fontsize=12):
    """Render *text* into a one-page PDF and return its bytes."""
    doc = fitz.open()
    page = doc.new_page()
    if fontfile is not None:
        page.insert_font(fontname="DOC", fontfile=fontfile)
    else:
        page.insert_font(fontname="DOC", fontbuffer=fontbuffer or _builtin_font_buffer())
    page.insert_text((50, 100), text, fontname="DOC", fontsize=fontsize)
    if subset:
        doc.subset_fonts()
    data = doc.tobytes()
    doc.close()
    return data


def strip_tounicode(data):
    """Remove every /ToUnicode entry, simulating a stripped or absent CMap."""
    pdf = pikepdf.open(io.BytesIO(data))
    try:
        for obj in pdf.objects:
            try:
                if isinstance(obj, pikepdf.Dictionary) and obj.get("/Type") == "/Font":
                    if "/ToUnicode" in obj:
                        del obj["/ToUnicode"]
            except Exception:
                pass
        out = io.BytesIO()
        pdf.save(out)
    finally:
        pdf.close()
    return out.getvalue()


def operand_bytes(data):
    """The concatenated raw string operands of page 1, as the decoder sees them."""
    pdf = pikepdf.open(io.BytesIO(data))
    try:
        chunks = []
        for operands, operator in pikepdf.parse_content_stream(pdf.pages[0]):
            name = str(operator)
            if name == "Tj":
                chunks.append(bytes(operands[0]))
            elif name == "TJ":
                for item in operands[0]:
                    if isinstance(item, pikepdf.String):
                        chunks.append(bytes(item))
    finally:
        pdf.close()
    return b"".join(chunks)


def build_simple_font_pdf(differences, codes):
    """
    A simple (single-byte) font whose /Encoding /Differences names its glyphs.

    Returns ``(pdf_bytes, encoded_bytes)``.
    """
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 100), "placeholder", fontname="helv", fontsize=12)
    data = doc.tobytes()
    doc.close()

    pdf = pikepdf.open(io.BytesIO(data))
    try:
        font = next(
            obj for obj in pdf.objects
            if isinstance(obj, pikepdf.Dictionary) and obj.get("/Type") == "/Font"
        )
        font["/Encoding"] = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name("/Encoding"),
            Differences=pikepdf.Array(differences),
        ))
        font.get("/ToUnicode") and font.__delitem__("/ToUnicode")

        page = pdf.pages[0]
        resource_name = list(page.Resources.Font.keys())[0]
        page.Contents = pdf.make_stream(
            b"BT " + resource_name.encode() + b" 24 Tf 50 100 Td <"
            + bytes(codes).hex().upper().encode() + b"> Tj ET"
        )
        out = io.BytesIO()
        pdf.save(out)
    finally:
        pdf.close()
    return out.getvalue(), bytes(codes)


def build_nameless_pdf(text):
    """
    A PDF whose font has neither a ToUnicode CMap nor any glyph names.

    This is the case Tier 2 exists for: PyMuPDF's subsetter drops the
    TrueType ``post`` table's names, so after stripping ToUnicode nothing is
    left but the shapes.
    """
    data = build_pdf(text, fontfile=str(bundled_reference_font()), subset=True)
    return strip_tounicode(data)


#: Isolates Tier 2 for tests that need shape matching to be what answers.
#: The base-14 fonts keep a CFF charset, so Tier 1 would otherwise resolve
#: them outright - correct behaviour, but it leaves Tier 2 unexercised.
SHAPE_ONLY = DecoderSettings(tier1_glyphnames=False)


def decode_first_font(data, encoded=None, settings=None):
    """Decode *encoded* (default: the page's own operands) with the first font."""
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        info = doc[0].get_fonts(full=True)[0]
        payload = operand_bytes(data) if encoded is None else encoded
        with DecoderCache(pdf_bytes=data,
                          settings=settings or DecoderSettings()) as cache:
            return decode(doc, info[0], payload, cache=cache, resource_name=info[4])
    finally:
        doc.close()


# --------------------------------------------------------------------------
# Glyph names and the Adobe Glyph List
# --------------------------------------------------------------------------

class TestGlyphNameResolution(unittest.TestCase):
    def test_agl_asset_loads(self):
        mapping, digest = load_agl()
        self.assertGreater(len(mapping), 4000)
        self.assertEqual(len(digest), 64)

    def test_plain_agl_names(self):
        for name, expected in [("A", "A"), ("space", " "), ("aacute", "á"),
                               ("oslash", "ø"), ("Aring", "Å"),
                               ("ae", "æ"), ("Euro", "€")]:
            self.assertEqual(glyph_name_to_text(name), expected, name)

    def test_non_latin_agl_names(self):
        """The AGL is not Latin-only, and neither is the lookup."""
        self.assertEqual(glyph_name_to_text("alpha"), "α")      # U+03B1
        self.assertEqual(glyph_name_to_text("Alpha"), "Α")      # U+0391
        self.assertEqual(glyph_name_to_text("afii10017"), "А")  # Cyrillic A

    def test_agl_quirks_are_preserved_not_corrected(self):
        """
        /Omega means U+2126 OHM SIGN in Adobe's published list, not U+03A9.

        The bundled table reproduces the AGL as published so that it can be
        diffed against it; silently "fixing" entries would make a decoding
        impossible to reproduce from the public source.
        """
        self.assertEqual(ord(glyph_name_to_text("Omega")), 0x2126)

    def test_uni_and_u_conventions(self):
        self.assertEqual(glyph_name_to_text("uni00E6"), "æ")
        self.assertEqual(glyph_name_to_text("u00E6"), "æ")
        self.assertEqual(glyph_name_to_text("uni004100420043"), "ABC")
        self.assertEqual(glyph_name_to_text("u01D400"), chr(0x01D400))

    def test_suffix_and_ligature(self):
        self.assertEqual(glyph_name_to_text("one.sc"), "1")
        self.assertEqual(glyph_name_to_text("f_i"), "fi")

    def test_uninformative_names_are_rejected(self):
        """A name carrying only a glyph index must never be guessed at."""
        for name in ["g43", "cid42", "glyph17", "index5", "C12", "G7", "42"]:
            self.assertIsNone(glyph_name_to_text(name), name)
            self.assertEqual(classify_glyph_name(name), "uninformative", name)

    def test_notdef_and_unknown(self):
        self.assertIsNone(glyph_name_to_text(".notdef"))
        self.assertEqual(classify_glyph_name(".notdef"), "notdef")
        self.assertIsNone(glyph_name_to_text("totallymadeupname"))
        self.assertEqual(classify_glyph_name("totallymadeupname"), "unknown")

    def test_surrogates_are_rejected(self):
        """A lone surrogate is not a character and must not be produced."""
        self.assertIsNone(glyph_name_to_text("uniD800"))
        self.assertIsNone(glyph_name_to_text("uDC00"))


# --------------------------------------------------------------------------
# ToUnicode CMap parsing
# --------------------------------------------------------------------------

class TestToUnicodeCMap(unittest.TestCase):
    CMAP = b"""
    1 begincodespacerange
    <0000> <FFFF>
    endcodespacerange
    2 beginbfchar
    <0003> <0020>
    <0047> <0041>
    endbfchar
    2 beginbfrange
    <0048> <004A> <0042>
    <0050> <0052> [<00E6> <00F8> <00E5>]
    endbfrange
    """

    def test_bfchar(self):
        cmap = parse_tounicode_cmap(self.CMAP)
        self.assertEqual(cmap.mapping[0x03], " ")
        self.assertEqual(cmap.mapping[0x47], "A")

    def test_bfrange_scalar_form(self):
        cmap = parse_tounicode_cmap(self.CMAP)
        self.assertEqual(cmap.mapping[0x48], "B")
        self.assertEqual(cmap.mapping[0x49], "C")
        self.assertEqual(cmap.mapping[0x4A], "D")

    def test_bfrange_array_form_with_diacritics(self):
        cmap = parse_tounicode_cmap(self.CMAP)
        self.assertEqual(cmap.mapping[0x50], "æ")
        self.assertEqual(cmap.mapping[0x51], "ø")
        self.assertEqual(cmap.mapping[0x52], "å")

    def test_codespace_range_drives_code_width(self):
        cmap = parse_tounicode_cmap(self.CMAP)
        self.assertEqual(cmap.codespace, ((2, 0x0000, 0xFFFF),))
        self.assertEqual(cmap.code_widths(), (2,))

    def test_placeholder_targets_are_not_decodings(self):
        """U+FFFD and U+0000 mean 'unmapped', not 'decoded to this'."""
        cmap = parse_tounicode_cmap(
            b"1 beginbfchar <0001> <FFFD> endbfchar\n"
            b"1 beginbfchar <0002> <0000> endbfchar"
        )
        self.assertNotIn(0x01, cmap.mapping)
        self.assertNotIn(0x02, cmap.mapping)

    def test_empty_input(self):
        cmap = parse_tounicode_cmap(b"")
        self.assertEqual(cmap.mapping, {})
        self.assertEqual(cmap.entry_count, 0)


# --------------------------------------------------------------------------
# Character inventory and reference alphabet
# --------------------------------------------------------------------------

class TestCharacterInventory(unittest.TestCase):
    def test_default_inventory(self):
        chars = parse_inventory(DEFAULT_INVENTORY)
        for ch in "Aa0 ":
            self.assertIn(ch, chars)
        self.assertIn("æ", chars)   # Latin-1 Supplement
        self.assertIn("ł", chars)   # Latin Extended-A, Polish l-stroke

    def test_inventory_is_extensible_to_other_scripts(self):
        """Adding a script is a settings change, not a code change."""
        greek = parse_inventory("0020-007E,0370-03FF")
        self.assertIn("α", greek)
        cyrillic = parse_inventory("0020-007E,0400-04FF")
        self.assertIn("Ж", cyrillic)

    def test_single_codepoint_entry(self):
        self.assertIn("€", parse_inventory("20AC"))

    def test_bad_entries_are_skipped_not_fatal(self):
        chars = parse_inventory("0020-0022,not-hex,,0041")
        self.assertIn("A", chars)
        self.assertIn(" ", chars)

    def test_control_and_surrogates_excluded(self):
        chars = parse_inventory("0000-001F,D800-DFFF")
        self.assertEqual(chars, ())


class TestReferenceAlphabet(unittest.TestCase):
    def test_bundled_font_is_present(self):
        self.assertIsNotNone(bundled_reference_font())

    def test_default_inventory_is_fully_comparable(self):
        """
        The bundled font must actually cover the documented default.

        PyMuPDF's built-in Helvetica does not: it draws all of Latin
        Extended-A as the same .notdef box while reporting the glyphs as
        present, which is why a reference font is bundled at all.
        """
        reference = build_reference_set(DEFAULT_INVENTORY, size=32)
        self.assertEqual(reference.unrenderable, ())
        self.assertGreater(len(reference.bitmaps), 300)

    def test_placeholder_rendering_is_detected(self):
        """A script the font lacks must be reported, not silently compared."""
        reference = build_reference_set("0590-05FF", size=32)  # Hebrew
        self.assertEqual(len(reference.bitmaps), 0)
        self.assertTrue(reference.missing or reference.unrenderable)

    def test_homoglyphs_are_grouped_not_guessed(self):
        """Latin A, Greek Alpha and Cyrillic A are one shape; say so."""
        reference = build_reference_set("0020-007E,0370-03FF,0400-04FF", size=32)
        groups = {
            rep: group for rep, group in reference.equivalents.items()
            if len(group) > 1
        }
        self.assertTrue(groups, "expected cross-script homoglyph groups")
        latin_a = reference.group_for("A")
        self.assertIn("Α", latin_a)  # Greek capital alpha
        self.assertIn("А", latin_a)  # Cyrillic capital A

    def test_provenance_identifies_the_reference(self):
        reference = build_reference_set(DEFAULT_INVENTORY, size=32)
        provenance = reference.provenance()
        self.assertEqual(len(provenance["reference_font_sha256"]), 64)
        self.assertEqual(provenance["inventory"], DEFAULT_INVENTORY)


# --------------------------------------------------------------------------
# (a) Valid ToUnicode -> Tier 0
# --------------------------------------------------------------------------

class TestTier0ToUnicode(unittest.TestCase):
    def test_valid_tounicode_is_certain(self):
        data = build_pdf("Hello World 123")
        result = decode_first_font(data)
        self.assertEqual(result.method, METHOD_TOUNICODE)
        self.assertEqual(result.confidence, CERTAIN)
        self.assertTrue(result.is_complete)
        self.assertIn("Hello", result.text)

    def test_diacritics_survive_tier_0(self):
        """Danish and Polish text, to catch an ASCII-only assumption."""
        data = build_pdf("Beløb æøå Zażółć")
        result = decode_first_font(data)
        self.assertEqual(result.confidence, CERTAIN)
        for ch in "øæåżó":
            self.assertIn(ch, result.text)

    def test_only_tier_0_runs_when_it_succeeds(self):
        """Later tiers must not be consulted once a code is certain."""
        data = build_pdf("Hello")
        result = decode_first_font(data)
        self.assertEqual([t.tier for t in result.tiers_run], [0])

    def test_evidence_records_reproducible_provenance(self):
        data = build_pdf("Hello")
        result = decode_first_font(data)
        font = result.evidence["font"]
        self.assertEqual(len(font["font_program_sha256"]), 64)
        self.assertIsNotNone(font["tounicode_xref"])
        self.assertGreater(font["tounicode_entries"], 0)
        self.assertEqual(
            result.evidence["encoded_hex"], operand_bytes(data).hex().upper())


# --------------------------------------------------------------------------
# (b) Stripped ToUnicode, meaningful glyph names -> Tier 1
# --------------------------------------------------------------------------

class TestTier1GlyphNames(unittest.TestCase):
    def test_differences_names_are_certain(self):
        differences = [65, pikepdf.Name("/aacute"), pikepdf.Name("/oslash"),
                       pikepdf.Name("/Aring"), pikepdf.Name("/adieresis")]
        data, encoded = build_simple_font_pdf(differences, [65, 66, 67, 68])
        result = decode_first_font(data, encoded)
        self.assertEqual(result.method, METHOD_GLYPHNAMES)
        self.assertEqual(result.confidence, CERTAIN)
        self.assertEqual(result.text, "áøÅä")

    def test_embedded_post_table_names_are_certain(self):
        """An embedded font that kept its post table decodes without a CMap."""
        data = strip_tounicode(build_pdf(
            "Zażółć gęślą", fontfile=str(bundled_reference_font()), subset=False))
        result = decode_first_font(data)
        self.assertEqual(result.method, METHOD_GLYPHNAMES)
        self.assertEqual(result.confidence, CERTAIN)
        self.assertEqual(result.text, "Zażółć gęślą")

    def test_tier_1_records_its_table(self):
        data = strip_tounicode(build_pdf(
            "Beløb", fontfile=str(bundled_reference_font()), subset=False))
        result = decode_first_font(data)
        names = result.evidence["glyph_names"]
        self.assertEqual(len(names["agl_sha256"]), 64)
        self.assertEqual(names["glyph_name_source"], "post")


# --------------------------------------------------------------------------
# (c) Subset font with /gNN names only -> nothing invented
# --------------------------------------------------------------------------

class TestTier1RejectsUninformativeNames(unittest.TestCase):
    def setUp(self):
        differences = [65, pikepdf.Name("/g65"), pikepdf.Name("/g66"),
                       pikepdf.Name("/cid67"), pikepdf.Name("/glyph68")]
        self.data, self.encoded = build_simple_font_pdf(
            differences, [65, 66, 67, 68])

    def test_tier_1_resolves_nothing(self):
        result = decode_first_font(self.data, self.encoded)
        tier1 = next(t for t in result.tiers_run if t.tier == 1)
        self.assertTrue(tier1.ran)
        self.assertEqual(tier1.resolved, 0)

    def test_rejection_reason_is_recorded(self):
        """An examiner must be able to see *why* the names were no help."""
        result = decode_first_font(self.data, self.encoded)
        rejected = result.evidence["glyph_names"]["uninformative_names"]
        self.assertEqual(len(rejected), 4)
        self.assertTrue(all("uninformative" in v for v in rejected.values()))

    def test_falls_through_to_tier_2(self):
        result = decode_first_font(self.data, self.encoded)
        self.assertEqual(result.method, METHOD_SHAPEMATCH)
        self.assertEqual(result.confidence, PROBABLE)

    def test_disabling_tier_2_yields_no_guess(self):
        """With shape matching off, unresolved codes stay unresolved."""
        settings = DecoderSettings(tier2_shapematch=False)
        result = decode_first_font(self.data, self.encoded, settings=settings)
        self.assertEqual(result.method, METHOD_NONE)
        self.assertEqual(result.confidence, SPECULATIVE)
        self.assertEqual(result.text, UNRESOLVED_PLACEHOLDER * 4)
        self.assertFalse(result.is_complete)
        self.assertEqual(len(result.evidence["unresolved_codes"]), 4)


# --------------------------------------------------------------------------
# Tier 2 shape matching
# --------------------------------------------------------------------------

class TestTier2ShapeMatch(unittest.TestCase):
    def test_subset_font_with_no_names_falls_through_naturally(self):
        """The real case: no CMap, no names, only shapes."""
        data = build_nameless_pdf("Hello World")
        result = decode_first_font(data)
        tier1 = next(t for t in result.tiers_run if t.tier == 1)
        self.assertEqual(tier1.resolved, 0)
        self.assertEqual(tier1.detail, "no glyph names available")
        self.assertEqual(result.method, METHOD_SHAPEMATCH)
        self.assertEqual(result.confidence, PROBABLE)
        self.assertTrue(result.is_complete)

    def test_serif_document_against_sans_reference_keeps_truth_in_range(self):
        """
        A serif document matched against the sans-serif bundled reference.

        Top-1 accuracy is poor here and that is expected rather than a
        defect: serifs change the proportions of narrow letters
        substantially, so a Times 'l' is nearly three times as wide relative
        to its height as a DejaVu Sans 'l'. What must hold is that the
        correct reading stays among the ranked candidates, and that the
        result is never presented as certain.
        """
        text = "Hello World"
        data = strip_tounicode(build_pdf(text))
        result = decode_first_font(data, settings=SHAPE_ONLY)
        self.assertEqual(result.method, METHOD_SHAPEMATCH)
        self.assertEqual(result.confidence, PROBABLE)
        self.assertTrue(result.is_complete)

        in_range = 0
        for expected, candidate in zip(text, result.per_char):
            if expected == candidate.text or expected in candidate.alternatives:
                in_range += 1
        self.assertGreaterEqual(
            in_range, len(text) - 2,
            f"truth fell outside the ranked candidates: {result.text!r}")

    def test_matching_the_reference_font_improves_the_reading(self):
        """
        Reference-font similarity dominates Tier 2 accuracy.

        The same run, decoded twice, differing only in which font the
        comparison alphabet is drawn from. This is why the reference font is
        a documented setting and not a fixed choice.
        """
        text = "Hello World"
        data = strip_tounicode(build_pdf(text))

        with tempfile.TemporaryDirectory() as tmpdir:
            serif = os.path.join(tmpdir, "serif_reference.ttf")
            with open(serif, "wb") as handle:
                handle.write(_builtin_font_buffer("tiro"))

            default = decode_first_font(data, settings=SHAPE_ONLY)
            matched = decode_first_font(data, settings=DecoderSettings(
                tier1_glyphnames=False, reference_font_path=serif))

        def exact(result):
            return sum(1 for a, b in zip(result.text, text) if a == b)

        self.assertGreater(
            exact(matched), exact(default),
            f"default={default.text!r} matched={matched.text!r}")
        # Still not certain: a closer reference improves the reading but does
        # not turn shape evidence into proof.
        self.assertEqual(matched.confidence, PROBABLE)

    def test_never_certain_without_margin(self):
        """A shape match is PROBABLE unless the margin clears the threshold."""
        data = strip_tounicode(build_pdf("Hello World"))
        result = decode_first_font(data, settings=SHAPE_ONLY)
        for candidate in result.per_char:
            if candidate.method == METHOD_SHAPEMATCH:
                if candidate.confidence == CERTAIN:
                    self.assertGreaterEqual(
                        candidate.margin,
                        DecoderSettings().shape_certain_margin)

    def test_reports_ranked_alternatives(self):
        """A probabilistic method must not present a single answer."""
        data = strip_tounicode(build_pdf("Hello World"))
        result = decode_first_font(data, settings=SHAPE_ONLY)
        shape_chars = [c for c in result.per_char
                       if c.method == METHOD_SHAPEMATCH and not c.text.isspace()]
        self.assertTrue(shape_chars)
        self.assertTrue(any(c.alternatives for c in shape_chars))
        self.assertTrue(result.alternatives)
        for alternative in result.alternatives:
            self.assertEqual(len(alternative.text), len(result.text))
            self.assertTrue(alternative.reason)

    def test_scores_and_bitmaps_are_evidence(self):
        data = strip_tounicode(build_pdf("Hello"))
        result = decode_first_font(data, settings=SHAPE_ONLY)
        shape = result.evidence["shape_match"]
        self.assertIn("reference", shape)
        self.assertIn("certain_margin", shape)
        bitmaps = shape["glyph_bitmaps"]
        self.assertTrue(bitmaps)
        for uri in bitmaps.values():
            self.assertTrue(uri.startswith("data:image/png;base64,"))
        for candidate in result.per_char:
            if candidate.method == METHOD_SHAPEMATCH:
                self.assertIsNotNone(candidate.score)
                self.assertIsNotNone(candidate.margin)

    def test_non_latin_script_via_inventory_setting(self):
        """Greek decodes when the inventory says Greek - no code change."""
        data = build_nameless_pdf("ΑΒΓ")
        settings = DecoderSettings(
            tier1_glyphnames=False,
            character_inventory="0020-007E,0370-03FF")
        result = decode_first_font(data, settings=settings)
        self.assertEqual(result.method, METHOD_SHAPEMATCH)
        self.assertEqual(len(result.per_char), 3)
        self.assertTrue(result.is_complete)

    def test_diacritics_are_in_range(self):
        """Latin Extended-A characters must be candidates at all."""
        reference = build_reference_set(DEFAULT_INVENTORY, size=32)
        comparable = set()
        for group in reference.equivalents.values():
            comparable.update(group)
        for ch in "łżćę":  # ł ż ć ę
            self.assertIn(ch, comparable)


# --------------------------------------------------------------------------
# (d) Short fragments
# --------------------------------------------------------------------------

class TestShortFragment(unittest.TestCase):
    def test_single_character_with_cmap(self):
        data = build_pdf("A")
        result = decode_first_font(data)
        self.assertEqual(result.text, "A")
        self.assertEqual(result.confidence, CERTAIN)

    def test_short_fragment_without_cmap(self):
        """A one-character run still yields a result, with its confidence."""
        data = strip_tounicode(build_pdf("A"))
        result = decode_first_font(data, settings=SHAPE_ONLY)
        self.assertEqual(len(result.per_char), 1)
        self.assertEqual(result.method, METHOD_SHAPEMATCH)
        self.assertEqual(result.confidence, PROBABLE)

    def test_empty_operand(self):
        data = build_pdf("A")
        result = decode_first_font(data, b"")
        self.assertEqual(result.text, "")
        self.assertEqual(result.method, METHOD_NONE)
        self.assertEqual(result.per_char, ())


# --------------------------------------------------------------------------
# Cross-tier rules
# --------------------------------------------------------------------------

class TestTierPrecedenceAndConfidence(unittest.TestCase):
    def test_string_confidence_is_the_weakest_character(self):
        """One shape-matched character makes the whole string PROBABLE."""
        data = build_pdf("Hello World")
        doc = fitz.open(stream=data, filetype="pdf")
        try:
            info = doc[0].get_fonts(full=True)[0]
            context = resolve_font(doc, info[0], info[4])
            encoded = operand_bytes(data)
            codes = split_codes(encoded, context)
            # Drop one code from the CMap so exactly one character has to
            # fall through to shape matching.
            victim = codes[0]
            context.tounicode = {
                code: text for code, text in context.tounicode.items()
                if code != victim
            }
            with DecoderCache(pdf_bytes=data, settings=SHAPE_ONLY) as cache:
                result = decode(doc, context, encoded, cache=cache)
        finally:
            doc.close()

        methods = {c.method for c in result.per_char}
        self.assertIn(METHOD_TOUNICODE, methods)
        self.assertIn(METHOD_SHAPEMATCH, methods)
        self.assertTrue(result.method.startswith("mixed:"))
        self.assertEqual(result.confidence, PROBABLE)

    def test_lower_tier_cannot_overwrite_a_certain_result(self):
        """Every code the CMap resolves keeps its tier-0 attribution."""
        data = build_pdf("Hello World")
        result = decode_first_font(data)
        self.assertTrue(
            all(c.method == METHOD_TOUNICODE for c in result.per_char))
        self.assertEqual(result.confidence, CERTAIN)

    def test_unresolved_codes_are_marked_not_invented(self):
        settings = DecoderSettings(tier1_glyphnames=False, tier2_shapematch=False)
        data = strip_tounicode(build_pdf("Hello"))
        result = decode_first_font(data, settings=settings)
        self.assertEqual(set(result.text), {UNRESOLVED_PLACEHOLDER})
        self.assertEqual(result.confidence, SPECULATIVE)
        self.assertFalse(result.is_complete)
        self.assertEqual(result.resolved_count, 0)

    def test_disabled_tiers_are_recorded_as_not_run(self):
        settings = DecoderSettings(tier1_glyphnames=False, tier2_shapematch=False)
        data = strip_tounicode(build_pdf("Hello"))
        result = decode_first_font(data, settings=settings)
        for tier in (1, 2):
            outcome = next(t for t in result.tiers_run if t.tier == tier)
            self.assertFalse(outcome.ran)
            self.assertIn("disabled", outcome.detail)


class TestDeterminism(unittest.TestCase):
    def test_identical_input_gives_identical_output(self):
        """Tiers 0-2 carry no randomness; identical input must reproduce."""
        data = build_nameless_pdf("Beløb 1.250 kr")
        first = decode_first_font(data)
        second = decode_first_font(data)
        self.assertEqual(first.text, second.text)
        self.assertEqual(first.confidence, second.confidence)
        self.assertEqual(
            [c.as_dict() for c in first.per_char],
            [c.as_dict() for c in second.per_char],
        )


class TestCustodySummary(unittest.TestCase):
    def test_summary_carries_verifiable_hashes(self):
        results = [
            decode_first_font(build_pdf("Hello")),
            decode_first_font(build_nameless_pdf("Hello")),
        ]
        summary = summarise_for_custody(results)
        self.assertEqual(summary["runs_decoded"], 2)
        self.assertEqual(summary["confidence_counts"][CERTAIN], 1)
        self.assertEqual(summary["confidence_counts"][PROBABLE], 1)
        self.assertIn("tier0_tounicode", summary["tiers"])
        self.assertIn("tier2_shapematch", summary["tiers"])
        self.assertTrue(summary["document_font_sha256"])
        self.assertTrue(summary["reference_fonts"])


class TestBundledAssetResolution(unittest.TestCase):
    """
    The assets must be findable inside a PyInstaller bundle.

    If they are not, Tier 1 loses the Adobe Glyph List and Tier 2 falls back
    to a reference font that cannot render Latin Extended-A - both quietly.
    These tests pin the layout that PDFRecon.spec has to produce.
    """

    def setUp(self):
        self._agl_cache = cid_fonts._agl_cache
        self._ref_cache = dict(cid_shapes._reference_cache)

    def tearDown(self):
        cid_fonts._agl_cache = self._agl_cache
        cid_shapes._reference_cache.clear()
        cid_shapes._reference_cache.update(self._ref_cache)
        for attr in ("frozen", "_MEIPASS"):
            if hasattr(sys, attr):
                delattr(sys, attr)

    def test_assets_exist_in_the_source_tree(self):
        asset_dir = cid_fonts._asset_dir()
        self.assertTrue((asset_dir / cid_fonts.AGL_FILENAME).is_file())
        self.assertTrue(
            (asset_dir / cid_shapes.REFERENCE_FONT_FILENAME).is_file())
        self.assertTrue((asset_dir / "reference_font_LICENSE.txt").is_file(),
                        "the reference font's licence must ship with it")

    def test_frozen_layout_is_found(self):
        """Simulate the bundle layout PDFRecon.spec creates."""
        source = cid_fonts._asset_dir()
        with tempfile.TemporaryDirectory() as meipass:
            staged = os.path.join(meipass, "src", "assets")
            shutil.copytree(source, staged)

            sys.frozen = True
            sys._MEIPASS = meipass
            cid_fonts._agl_cache = None

            self.assertEqual(cid_fonts._asset_dir(), pathlib.Path(staged))
            mapping, digest = cid_fonts.load_agl()
            self.assertGreater(len(mapping), 4000)
            self.assertEqual(len(digest), 64)

            font = cid_shapes.bundled_reference_font()
            self.assertIsNotNone(font)
            self.assertEqual(font.parent, pathlib.Path(staged))

    def test_frozen_falls_back_to_the_module_directory(self):
        """
        A bundle without the assets still finds the ones beside the module.

        This is why a source-tree run works with no bundling at all, and it
        means the frozen lookup is a preference rather than a requirement.
        """
        with tempfile.TemporaryDirectory() as meipass:
            sys.frozen = True
            sys._MEIPASS = meipass  # contains no assets
            cid_fonts._agl_cache = None

            self.assertEqual(
                cid_fonts._asset_dir(),
                pathlib.Path(cid_fonts.__file__).resolve().parent / "assets")
            mapping, _digest = cid_fonts.load_agl()
            self.assertGreater(len(mapping), 4000)

    def test_both_modules_share_one_asset_resolver(self):
        """
        One source of truth for where the assets live.

        Two copies of this logic would be free to drift, and the symptom
        would be a tier quietly losing its table rather than an error.
        """
        self.assertIs(cid_shapes._asset_dir, cid_fonts._asset_dir)

    def test_unreachable_assets_degrade_visibly(self):
        """A missing table must be evident in the record, not silent."""
        original = cid_fonts._asset_dir
        with tempfile.TemporaryDirectory() as empty:
            patched = lambda: pathlib.Path(empty)
            cid_fonts._asset_dir = patched
            cid_shapes._asset_dir = patched
            cid_fonts._agl_cache = None
            try:
                mapping, digest = cid_fonts.load_agl()
                # An empty hash in the evidence is the signal that no table
                # was used, so a Tier 1 result can never be mistaken for one
                # backed by a verified glyph list.
                self.assertEqual(mapping, {})
                self.assertEqual(digest, "")
                self.assertIsNone(cid_shapes.bundled_reference_font())
            finally:
                cid_fonts._asset_dir = original
                cid_shapes._asset_dir = original


class TestRobustness(unittest.TestCase):
    def test_malformed_font_reference_does_not_raise(self):
        data = build_pdf("Hello")
        doc = fitz.open(stream=data, filetype="pdf")
        try:
            with DecoderCache(pdf_bytes=data, settings=DecoderSettings()) as cache:
                result = decode(doc, 99999, b"\x00\x41", cache=cache)
        finally:
            doc.close()
        self.assertIsNotNone(result)
        self.assertIn(result.confidence, (SPECULATIVE, PROBABLE, CERTAIN))

    def test_odd_length_operand_does_not_raise(self):
        data = build_pdf("Hello")
        result = decode_first_font(data, b"\x00\x24\x00")
        self.assertIsNotNone(result.text)


if __name__ == "__main__":
    unittest.main()
