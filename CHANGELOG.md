# Changelog

## 17.7.0

### ⚠️ Read this first if you have existing TouchUp findings

This release fixes defects in TouchUp text extraction that were present in
earlier versions and that affected what was reported. **Findings that relied on
extracted TouchUp text should be re-run with this version before being relied
upon.** The extraction itself was wrong in two different ways depending on how
you ran PDFRecon:

| | What earlier versions reported |
|---|---|
| **From the .exe** | No TouchUp text at all. `pikepdf` was never bundled, so extraction failed silently and the field stayed empty. Files with TouchUp edits could look as though nothing was recoverable. |
| **From source** | The text of the **entire page**, not just the edited region. The masking step never ran, so untouched text was presented in the field labelled "Extracted altered text". |

In addition, TouchUp regions marked indirectly through `/Properties` — rather
than with the tag spelled out inline — were never detected at all, so some
edited documents were not flagged.

All three are fixed. Detection and extraction now behave the same whether you
run the executable, the GUI from source, or the CLI.

### New: automatic decoding of garbled TouchUp text

When a font's `/ToUnicode` CMap is missing, incomplete or non-standard,
extracted TouchUp text came out as nonsense such as `ZK,KZK,ZP=GZ`. The manual
described a five-step procedure for decoding it by hand. That is now automated.

Decoding runs in tiers and stops at the first result it can stand behind:

| Tier | Method | Evidence | Confidence |
|------|--------|----------|------------|
| 0 | `tounicode` | The font's own `/ToUnicode` CMap | CERTAIN |
| 1 | `glyphnames` | `/Encoding /Differences`, or the embedded font's `post` table / CFF charset, via the Adobe Glyph List | CERTAIN |
| 2 | `shapematch` | The shape the PDF actually draws, matched against a reference alphabet | PROBABLE |

**Confidence is part of the result, never an afterthought.** CERTAIN means the
mapping was read from something the file states explicitly — it does *not* mean
the text is genuine, since a falsified CMap yields a confident reading of the
wrong characters. PROBABLE means the reading was inferred from glyph shapes and
is an investigative lead. SPECULATIVE means at least one character could not be
resolved at all; those positions show as `�` and are never guessed.

A reading below CERTAIN carries its label everywhere it appears — on screen, in
every export, and in signed reports — so it cannot be quoted as a confirmed
finding by accident.

### Where you see it

- **Inspector** — decoded text with a colour-coded confidence badge, and a
  **Decoding evidence** button opening the full record: method, which tiers ran
  and what each resolved, the font and its SHA-256, the raw operand, ranked
  alternative readings with the margin behind each, and the glyph the document
  actually draws shown next to the character it was read as. That last part is
  the fastest way to audit a result — a glyph captioned "read as 4" that is
  plainly a 1 gives itself away immediately.
- **Exports** — method and confidence columns in Excel, CSV, HTML and JSON,
  plus a dedicated *Text Decoding* worksheet carrying the raw operand, font
  hash, tiers and alternatives.
- **Chain of custody** — a `TEXT_DECODED` entry recording which tiers ran, the
  confidence reached, and the SHA-256 of the Adobe Glyph List, the reference
  font and the document's own embedded font.
- **CLI** — `pdfrecon scan` prints a decoding block; `--decoding-detail` lists
  every character with its score and margin.
- **Manual** — a new *CID Text Decoding* section in English and Danish
  explaining each tier, what the confidence levels mean, and how to verify or
  challenge a decoding by hand.

### Settings

New options in `config.ini`, all with documented defaults:

| Setting | Default | Purpose |
|---|---|---|
| `CIDReferenceFontPath` | bundled font | Typeface Tier 2 compares against. **The single most effective adjustment available** — see below. |
| `CIDCharacterInventory` | `0020-007E,00A0-00FF,0100-017F` | Characters Tier 2 may propose. The bundled font also covers Latin Extended-B, Greek, Cyrillic, punctuation and currency, so adding `0370-03FF` or `0400-04FF` needs no extra files. |
| `CIDShapeCertainMargin` | `0.25` | How far a match must beat its runner-up to be called CERTAIN. |
| `CIDShapeMinScore` | `0.45` | Below this, no candidate is offered and the code is reported unresolved. |
| `CIDTier0ToUnicode` / `CIDTier1GlyphNames` / `CIDTier2ShapeMatch` | on | Per-tier switches; a disabled tier is recorded in the result. |

**On the reference font.** Tier 2 accuracy depends more on how closely the
reference typeface resembles the document's than on any threshold. The same
serif-set line decoded 5 of 11 characters correctly against the bundled
sans-serif reference and 11 of 11 against a serif one. If a document is set in
a serif face, point `CIDReferenceFontPath` at something similar.

### Reproducibility

Tiers 0–2 contain no randomness, no sampling and no network access. The same
file with the same settings produces byte-identical output on any machine. The
certain-margin default is empirical: measured over 131 glyphs from nine
typefaces and three scripts, the top candidate was correct 82% of the time at
any margin, 97.9% above a 0.15 margin and 100% above 0.20. The default sits at
0.25, one step stricter than the measurement requires, because a wrongly
CERTAIN reading is the most damaging error the tool can make.

### Also fixed

- **The packaged executable failed to start** with `No module named
  'src.popups'`. A backslash inside an f-string expression is only valid from
  Python 3.12; the build interpreter was 3.11, so the module never compiled and
  was silently omitted from the build.
- **`pikepdf` was missing from `requirements.txt`** and from the bundle, which
  is what disabled TouchUp extraction in the executable. It is now declared and
  bundled, and `build.bat` aborts with a readable error if the build
  interpreter cannot import what gets shipped.
- **`PDFRecon.spec` is now tracked in git.** It was listed in `.gitignore`, so
  build fixes could not be committed and a fresh clone built a broken
  executable.

### Notes for maintainers

- Requires Python 3.10+ to run and to build. `build.bat` now takes the
  interpreter from a `PY` variable at the top of the script.
- Bundled assets add roughly 170 kB: the Adobe Glyph List and a subset of
  DejaVu Sans used as the shape-comparison reference, renamed as its licence
  requires and shipped with that licence.
- `tools/decode_touchup.py` runs the decoder over given PDFs and can write the
  rendered glyph bitmaps out as PNGs for visual review.

---

## 17.6.4 and earlier

See the commit history.
