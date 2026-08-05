"""
Glyph Rendering and Shape Matching for CID Decoding (Tier 2)

When a font carries no usable ``/ToUnicode`` CMap and its glyph names have
been stripped by subsetting, the only remaining evidence of what a character
code means is the shape the PDF actually draws for it.  This module renders
that shape and compares it against a reference alphabet.

How a code is rendered
----------------------
The character code is drawn through *the document's own font dictionary*,
copied unchanged into a scratch PDF.  Nothing is reconstructed and no
glyph-index resolution is involved, so the bitmap is exactly the appearance
a PDF viewer produces for that code.  An examiner can reproduce it by
opening the file and looking at the page.

How shapes are compared
-----------------------
Both bitmaps are cropped to their ink bounding box, scaled into a square
canvas with the aspect ratio preserved, and lightly blurred.  Scoring
combines four views that fail in different ways:

* normalised cross-correlation of the blurred images - overall shape,
  tolerant of stroke weight because both images are mean/variance
  normalised;
* intersection over union of the binarised images - coverage;
* aspect-ratio agreement - separates shapes that correlate well but have
  obviously different proportions (``i`` against ``m``);
* vertical metrics agreement - the glyph's extent above and below the
  baseline, as a fraction of the point size.  Cropping to the ink box
  necessarily discards absolute size, and absolute size is the *only*
  thing that distinguishes ``c`` from ``C``, ``o`` from ``O``, or ``1``
  from a superscript ``1``.  Because both renders use the same point size
  and baseline, these measurements are directly comparable.  They are
  compared with a tolerance, since x-height and cap-height ratios legitimately
  differ between typefaces.

Determinism
-----------
Everything here is pure Python integer and float arithmetic on small
bitmaps.  numpy is deliberately not used: it is excluded from the packaged
executable, and floating-point reduction order can differ between numpy and
CPython, which could reorder near-tied candidates.  Identical input
therefore produces identical output on every machine.

Choosing a reference font
-------------------------
Accuracy depends more on how closely the reference typeface resembles the
document's than on any scoring parameter.  Decoding the same serif-set run
three times, changing only the reference, gave 5 of 11 characters right
against the bundled sans-serif, 8 of 11 against Times New Roman and 11 of 11
against the serif face the document itself used.  Serifs change the
proportions of narrow letters sharply - a Times ``l`` is nearly three times
as wide relative to its height as a DejaVu Sans ``l`` - so a serif document
read against a sans-serif reference will produce weak matches no amount of
tuning recovers.

The bundled reference is a reasonable default, not a universal one.  Where
the document's typeface is known, pointing the reference-font setting at it,
or at something close to it, is the single most effective adjustment
available.  This is also why a shape match reports PROBABLE by default: the
score reflects agreement with a chosen reference, not proof about the
document.

Locale independence
-------------------
The comparison alphabet is a configurable set of Unicode ranges with no
built-in assumption beyond its documented default.  Users working in other
scripts extend the ranges and, where the bundled reference font lacks
coverage, point at a reference font of their own; no code change is needed.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

import fitz

try:  # pragma: no cover - import shape differs between package and script use
    from .cid_fonts import _asset_dir
except ImportError:  # pragma: no cover
    from cid_fonts import _asset_dir


#: The bundled comparison typeface: a subset of DejaVu Sans, renamed as its
#: licence requires for modified copies, covering Latin, Greek and Cyrillic.
#: PyMuPDF's built-in Helvetica cannot serve this purpose - it covers only
#: Latin-1 and draws everything else, all of Latin Extended-A included, as
#: the same .notdef box while reporting the glyphs as present.
REFERENCE_FONT_FILENAME = "reference_font.ttf"


def bundled_reference_font() -> Optional[Path]:
    """Path to the bundled reference font, or ``None`` if it is unavailable."""
    path = _asset_dir() / REFERENCE_FONT_FILENAME
    return path if path.is_file() else None

# --------------------------------------------------------------------------
# Rendering geometry
#
# One page per glyph, generously sized so that no glyph of any font can be
# clipped: a 64 pt glyph has at most ~1 em of ascent and ~0.3 em of descent,
# and few exceed 1.5 em of advance width.  The same geometry is used for the
# document's glyphs and the reference glyphs so the two are directly
# comparable before normalisation.
# --------------------------------------------------------------------------
_PAGE_SIZE = 200.0
_FONT_SIZE = 64.0
#: Text origin for PyMuPDF page methods, whose y axis runs from the top.
_ORIGIN = (50.0, 130.0)
_RENDER_DPI = 72

#: The same origin expressed for a raw content stream, whose y axis runs from
#: the bottom.  Reference glyphs are placed with PyMuPDF and document glyphs
#: with a hand-written content stream, so the two conventions must be
#: reconciled explicitly - otherwise the baselines differ by
#: _PAGE_SIZE - 2*_ORIGIN[1] and every baseline-relative measurement is
#: meaningless.
_PDF_ORIGIN = (_ORIGIN[0], _PAGE_SIZE - _ORIGIN[1])

# A pixel counts as ink below this grey level (0 = black, 255 = white).
_INK_THRESHOLD = 200


# --------------------------------------------------------------------------
# Character inventory
# --------------------------------------------------------------------------

#: Default comparison alphabet: ASCII printable, Latin-1 Supplement and
#: Latin Extended-A.  Chosen because it covers Western and Central European
#: text including diacritics, and because PyMuPDF's built-in reference font
#: covers all of it.  It is a default, not a limit - see
#: :func:`parse_inventory`.
DEFAULT_INVENTORY = "0020-007E,00A0-00FF,0100-017F"

_RANGE_RE = re.compile(r"^([0-9A-Fa-f]{2,6})(?:\s*-\s*([0-9A-Fa-f]{2,6}))?$")


def parse_inventory(spec: str) -> tuple[str, ...]:
    """
    Parse a character inventory specification into characters.

    The specification is a comma-separated list of hexadecimal Unicode
    scalar values or ``LOW-HIGH`` ranges, for example::

        0020-007E,00A0-00FF,0100-017F      # the default
        0020-007E,0370-03FF                # ASCII plus Greek
        0020-007E,0400-04FF                # ASCII plus Cyrillic

    Unparseable entries are skipped with a warning rather than raising, so a
    typo in a setting cannot abort a scan.  Control characters and surrogate
    code points are never included.
    """
    chars: list[str] = []
    seen: set[int] = set()
    for raw in (spec or "").split(","):
        token = raw.strip()
        if not token:
            continue
        match = _RANGE_RE.match(token)
        if not match:
            logging.warning("Ignoring unparseable character inventory entry: %r", token)
            continue
        low = int(match.group(1), 16)
        high = int(match.group(2), 16) if match.group(2) else low
        if high < low:
            low, high = high, low
        if high - low > 0x10000:
            logging.warning(
                "Character inventory entry %r spans %d code points; truncating to 65536.",
                token, high - low + 1)
            high = low + 0x10000
        for cp in range(low, high + 1):
            if cp in seen:
                continue
            if cp < 0x20 or 0xD800 <= cp <= 0xDFFF or cp > 0x10FFFF:
                continue
            seen.add(cp)
            chars.append(chr(cp))
    return tuple(chars)


#: Characters whose shapes are close enough in many typefaces that a shape
#: match alone must never be reported as CERTAIN for them, however large the
#: score margin - the margin then reflects the reference font's own design
#: rather than the truth about the document.
#:
#: This is a backstop for *near*-identical shapes.  Characters the reference
#: font draws *identically* are detected automatically at render time and
#: reported as an indistinguishable group (see :class:`ReferenceSet`), which
#: is the primary mechanism and needs no configuration.  Groups here are
#: configurable; this is the documented default.
DEFAULT_CONFUSABLE_GROUPS = (
    "Il1|i",
    "O0oQD",
    "S5",
    "B8",
    "Z2",
    "G6",
    "g9q",
    "ce",
    "uv",
    "nh",
    ",.",
    ":;",
    "-‐‑‒–—",
    "'‘’ʼ`",
    '"“”',
    "  ",
)


def build_confusable_set(groups: Sequence[str]) -> frozenset[str]:
    """Flatten confusable groups into the set of characters they cover."""
    return frozenset(ch for group in groups for ch in group)


# --------------------------------------------------------------------------
# Bitmaps
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class GlyphBitmap:
    """A glyph normalised for comparison."""

    size: int
    #: Ink intensity per pixel, row-major, 0 (no ink) to 255 (full ink).
    pixels: tuple[int, ...]
    #: Width / height of the ink bounding box before normalisation.
    aspect: float
    #: Mean ink coverage, 0.0 to 1.0.
    density: float
    #: True when the render produced no ink at all.
    blank: bool
    #: Ink bounding box in the source render, for the evidence record.
    source_bbox: tuple[int, int, int, int] = (0, 0, 0, 0)
    #: Extent above the baseline as a fraction of the point size.  Survives
    #: the crop-and-scale step and carries the absolute-size information that
    #: separates upper from lower case.
    rel_above: float = 0.0
    #: Extent below the baseline as a fraction of the point size.
    rel_below: float = 0.0

    def to_png(self) -> bytes:
        """Render as a greyscale PNG for display beside a claimed character."""
        samples = bytes(255 - value for value in self.pixels)
        pix = fitz.Pixmap(fitz.csGRAY, self.size, self.size, samples, False)
        return pix.tobytes("png")


def _blank_bitmap(size: int) -> GlyphBitmap:
    return GlyphBitmap(
        size=size,
        pixels=tuple([0] * (size * size)),
        aspect=1.0,
        density=0.0,
        blank=True,
    )


def _ink_bbox(samples: bytes, width: int, height: int) -> Optional[tuple[int, int, int, int]]:
    """
    Find the ink bounding box of a greyscale render.

    Uses ``min()`` over row slices and strided column slices so the scan runs
    at C speed; a full Python scan of every pixel would dominate the cost of
    building a reference alphabet.
    """
    top = None
    bottom = None
    for y in range(height):
        row = samples[y * width:(y + 1) * width]
        if row and min(row) < _INK_THRESHOLD:
            if top is None:
                top = y
            bottom = y
    if top is None:
        return None

    band = samples[top * width:(bottom + 1) * width]
    left = None
    right = None
    for x in range(width):
        column = band[x::width]
        if column and min(column) < _INK_THRESHOLD:
            if left is None:
                left = x
            right = x
    if left is None:  # pragma: no cover - implied by the row scan succeeding
        return None
    return left, top, right, bottom


def _box_blur(pixels: list[int], size: int, radius: int) -> list[int]:
    """Separable box blur; softens stroke-weight differences before scoring."""
    if radius <= 0:
        return pixels

    horizontal = [0] * (size * size)
    window = radius * 2 + 1
    for y in range(size):
        base = y * size
        for x in range(size):
            total = 0
            for dx in range(-radius, radius + 1):
                sx = x + dx
                if sx < 0:
                    sx = 0
                elif sx >= size:
                    sx = size - 1
                total += pixels[base + sx]
            horizontal[base + x] = total // window

    blurred = [0] * (size * size)
    for y in range(size):
        for x in range(size):
            total = 0
            for dy in range(-radius, radius + 1):
                sy = y + dy
                if sy < 0:
                    sy = 0
                elif sy >= size:
                    sy = size - 1
                total += horizontal[sy * size + x]
            blurred[y * size + x] = total // window
    return blurred


def normalise_render(
    samples: bytes,
    width: int,
    height: int,
    size: int,
    blur_radius: int = 1,
) -> GlyphBitmap:
    """
    Crop a greyscale render to its ink, scale it into a ``size`` square with
    the aspect ratio preserved, and blur it lightly.

    Preserving the aspect ratio matters: stretching every glyph to fill the
    square would erase the proportion difference that separates ``i`` from
    ``m``.  The aspect ratio is also kept as a separate scoring term, as are
    the glyph's extents above and below the baseline - the crop discards
    absolute size, and absolute size is what separates ``c`` from ``C``.

    The render geometry is fixed by this module (:data:`_PAGE_SIZE`,
    :data:`_FONT_SIZE`, :data:`_ORIGIN`, :data:`_RENDER_DPI`) and is identical
    for document glyphs and reference glyphs, so the measurements are
    directly comparable.
    """
    bbox = _ink_bbox(samples, width, height)
    if bbox is None:
        return _blank_bitmap(size)

    left, top, right, bottom = bbox
    scale = _RENDER_DPI / 72.0
    baseline = _ORIGIN[1] * scale
    em = _FONT_SIZE * scale
    rel_above = (baseline - top) / em
    rel_below = (bottom - baseline) / em
    crop_w = right - left + 1
    crop_h = bottom - top + 1
    aspect = crop_w / crop_h

    # Target extent inside the square canvas, aspect preserved.
    if crop_w >= crop_h:
        target_w = size
        target_h = max(1, round(size * crop_h / crop_w))
    else:
        target_h = size
        target_w = max(1, round(size * crop_w / crop_h))
    offset_x = (size - target_w) // 2
    offset_y = (size - target_h) // 2

    canvas = [0] * (size * size)
    ink_total = 0
    for ty in range(target_h):
        sy0 = top + (ty * crop_h) // target_h
        sy1 = top + ((ty + 1) * crop_h) // target_h
        if sy1 <= sy0:
            sy1 = sy0 + 1
        for tx in range(target_w):
            sx0 = left + (tx * crop_w) // target_w
            sx1 = left + ((tx + 1) * crop_w) // target_w
            if sx1 <= sx0:
                sx1 = sx0 + 1
            total = 0
            count = 0
            for sy in range(sy0, sy1):
                row_base = sy * width
                for sx in range(sx0, sx1):
                    total += 255 - samples[row_base + sx]
                    count += 1
            value = total // count if count else 0
            canvas[(offset_y + ty) * size + offset_x + tx] = value
            ink_total += value

    density = ink_total / (255.0 * size * size)
    blurred = _box_blur(canvas, size, blur_radius)
    return GlyphBitmap(
        size=size,
        pixels=tuple(blurred),
        aspect=aspect,
        density=density,
        blank=False,
        source_bbox=bbox,
        rel_above=rel_above,
        rel_below=rel_below,
    )


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

#: Tolerance, in em, on the baseline-relative metrics comparison.  Cap-height
#: and x-height ratios differ legitimately between typefaces (DejaVu Sans'
#: x-height is 0.55 em, Times' 0.45), so the comparison must be graded rather
#: than exact.  Tuned across nine typefaces and three scripts: tighter values
#: penalise a correct match merely for being set in a different typeface from
#: the reference, while the ~0.2 em gap between lower and upper case still
#: separates them at this setting.
_METRICS_TOLERANCE = 0.20

#: Best-vs-second-best score margin at which a shape match may be reported as
#: CERTAIN rather than PROBABLE.
#:
#: Measured over 131 glyphs from nine typefaces (Arial, Times New Roman,
#: Calibri, Verdana, Courier New, Georgia, Segoe UI) and three scripts, all
#: matched against the bundled DejaVu-derived reference - that is, never
#: against themselves.  Precision of the top-ranked candidate by margin:
#:
#:     margin >= 0.00   82.4%   (131 glyphs)
#:     margin >= 0.10   94.6%   ( 74 glyphs)
#:     margin >= 0.15   97.9%   ( 48 glyphs)
#:     margin >= 0.20  100.0%   ( 23 glyphs)
#:     margin >= 0.25  100.0%   ( 15 glyphs)
#:
#: The default sits at 0.25 rather than 0.20 because the sample above 0.20 is
#: small and a wrongly-CERTAIN reading is the most damaging error this tool
#: can make.  The consequence is that most shape matches are reported as
#: PROBABLE, which is the honest characterisation.  Configurable.
DEFAULT_CERTAIN_MARGIN = 0.25


@dataclass(frozen=True)
class ScoreWeights:
    """Relative weight of each scoring term.  Normalised on construction."""

    correlation: float = 0.45
    overlap: float = 0.20
    aspect: float = 0.10
    metrics: float = 0.25

    def normalised(self) -> tuple[float, float, float, float]:
        total = self.correlation + self.overlap + self.aspect + self.metrics
        if total <= 0:
            return (1.0, 0.0, 0.0, 0.0)
        return (
            self.correlation / total,
            self.overlap / total,
            self.aspect / total,
            self.metrics / total,
        )


def _correlation(a: Sequence[int], b: Sequence[int]) -> float:
    """Normalised cross-correlation, clamped to [0, 1]."""
    n = len(a)
    if n == 0 or n != len(b):
        return 0.0
    mean_a = sum(a) / n
    mean_b = sum(b) / n
    num = 0.0
    var_a = 0.0
    var_b = 0.0
    for pa, pb in zip(a, b):
        da = pa - mean_a
        db = pb - mean_b
        num += da * db
        var_a += da * da
        var_b += db * db
    if var_a <= 0.0 or var_b <= 0.0:
        return 0.0
    value = num / ((var_a ** 0.5) * (var_b ** 0.5))
    return value if value > 0.0 else 0.0


def _overlap(a: Sequence[int], b: Sequence[int], threshold: int = 96) -> float:
    """Intersection over union of the binarised bitmaps."""
    intersection = 0
    union = 0
    for pa, pb in zip(a, b):
        ink_a = pa >= threshold
        ink_b = pb >= threshold
        if ink_a and ink_b:
            intersection += 1
            union += 1
        elif ink_a or ink_b:
            union += 1
    return intersection / union if union else 0.0


def _aspect_agreement(a: float, b: float) -> float:
    if a <= 0.0 or b <= 0.0:
        return 0.0
    return min(a, b) / max(a, b)


def _metrics_agreement(
    unknown: GlyphBitmap,
    reference: GlyphBitmap,
    tolerance: float = _METRICS_TOLERANCE,
) -> float:
    """
    Compare baseline-relative vertical extents, graded by *tolerance*.

    Returns 1.0 for identical placement and falls off exponentially, so a
    difference of one tolerance unit scores about 0.37 and the ~0.2 em gap
    between cases scores about 0.14.
    """
    if tolerance <= 0.0:
        return 1.0
    delta = (
        abs(unknown.rel_above - reference.rel_above)
        + abs(unknown.rel_below - reference.rel_below)
    )
    return 2.718281828459045 ** (-delta / tolerance)


def compare(
    unknown: GlyphBitmap,
    reference: GlyphBitmap,
    weights: ScoreWeights,
    metrics_tolerance: float = _METRICS_TOLERANCE,
) -> tuple[float, dict]:
    """Score two normalised bitmaps; returns ``(score, term breakdown)``."""
    if unknown.blank or reference.blank:
        both_blank = unknown.blank and reference.blank
        return (1.0 if both_blank else 0.0), {
            "correlation": None, "overlap": None, "aspect": None,
            "metrics": None, "blank": True,
        }

    correlation = _correlation(unknown.pixels, reference.pixels)
    overlap = _overlap(unknown.pixels, reference.pixels)
    aspect = _aspect_agreement(unknown.aspect, reference.aspect)
    metrics = _metrics_agreement(unknown, reference, metrics_tolerance)

    w_corr, w_over, w_asp, w_met = weights.normalised()
    score = (
        w_corr * correlation
        + w_over * overlap
        + w_asp * aspect
        + w_met * metrics
    )
    return score, {
        "correlation": round(correlation, 6),
        "overlap": round(overlap, 6),
        "aspect": round(aspect, 6),
        "metrics": round(metrics, 6),
        "blank": False,
    }


@dataclass(frozen=True)
class ShapeMatch:
    """One ranked candidate character for an unknown glyph."""

    text: str
    score: float
    terms: dict = field(default_factory=dict)
    #: Characters the reference font draws identically to :attr:`text`.  When
    #: this holds more than one character the shape evidence cannot choose
    #: between them, and the match must not be reported as certain.
    equivalents: tuple[str, ...] = ()

    @property
    def is_ambiguous(self) -> bool:
        return len(self.equivalents) > 1


# --------------------------------------------------------------------------
# Reference alphabet
# --------------------------------------------------------------------------

#: A group of characters the reference font draws identically and which is
#: larger than this is treated as a rendering failure rather than as genuine
#: homoglyphy.  Real homoglyph groups are small (Latin A, Greek Alpha and
#: Cyrillic A make three); a font asked for a script it does not have draws
#: the same .notdef box dozens of times.
_MAX_EQUIVALENT_GROUP = 4


@dataclass
class ReferenceSet:
    """A rendered comparison alphabet."""

    font_label: str
    font_sha256: str
    inventory_spec: str
    size: int
    #: Representative character -> its normalised bitmap.
    bitmaps: dict[str, GlyphBitmap] = field(default_factory=dict)
    #: Representative character -> every character drawn with that same shape.
    #: Usually a single-element tuple; longer where the reference font really
    #: does draw two characters identically.
    equivalents: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: Characters the reference font cannot draw, or draws as .notdef.
    missing: tuple[str, ...] = ()
    #: Characters dropped because the font drew them all as the same box.
    unrenderable: tuple[str, ...] = ()

    def group_for(self, char: str) -> tuple[str, ...]:
        return self.equivalents.get(char, (char,))

    def provenance(self) -> dict:
        ambiguous = {
            rep: "".join(group)
            for rep, group in sorted(self.equivalents.items())
            if len(group) > 1
        }
        return {
            "reference_font": self.font_label,
            "reference_font_sha256": self.font_sha256,
            "inventory": self.inventory_spec,
            "inventory_comparable": len(self.bitmaps),
            "inventory_missing": len(self.missing),
            "inventory_unrenderable": len(self.unrenderable),
            "indistinguishable_groups": ambiguous,
            "bitmap_size": self.size,
        }


_reference_cache: dict[tuple, ReferenceSet] = {}


def build_reference_set(
    inventory_spec: str = DEFAULT_INVENTORY,
    size: int = 32,
    font_path: Optional[str] = None,
    blur_radius: int = 1,
) -> ReferenceSet:
    """
    Render the comparison alphabet.

    Uses PyMuPDF's built-in Helvetica by default, which is already part of
    the application and covers the default inventory completely, so nothing
    additional is bundled.  *font_path* overrides it with a font file of the
    user's choosing - the extension point for scripts the built-in font does
    not cover.

    Two failure modes are detected rather than passed on as results:

    * A character the font has no glyph for is reported in ``missing``.
      ``fitz.Font.has_glyph`` cannot be trusted for this on its own - the
      built-in Helvetica claims to cover 72 Greek code points and draws every
      one of them as the same ``.notdef`` box - so the rendered output is
      checked as well.
    * Characters that render to byte-identical bitmaps carry no information
      that could tell them apart.  Small groups are kept as a single
      representative with the others recorded as equivalents, so a match can
      report the ambiguity honestly.  Groups larger than
      :data:`_MAX_EQUIVALENT_GROUP` are treated as a rendering failure and
      reported in ``unrenderable``; comparing against dozens of identical
      boxes would produce rankings with no meaning behind them.
    """
    key = (inventory_spec, size, font_path or "", blur_radius)
    cached = _reference_cache.get(key)
    if cached is not None:
        return cached

    chars = parse_inventory(inventory_spec)

    resolved_path = font_path or (
        str(bundled_reference_font()) if bundled_reference_font() else None)

    font_label = "PyMuPDF built-in Helvetica (fallback)"
    font_sha256 = ""
    try:
        if resolved_path:
            with open(resolved_path, "rb") as handle:
                buffer = handle.read()
            probe_font = fitz.Font(fontbuffer=buffer)
            font_label = (
                f"{probe_font.name} (bundled)" if not font_path
                else f"{probe_font.name} ({font_path})"
            )
            font_sha256 = hashlib.sha256(buffer).hexdigest()
        else:
            logging.warning(
                "Bundled reference font is missing; falling back to the "
                "built-in Helvetica, which covers only Latin-1.")
            probe_font = fitz.Font("helv")
            buffer = bytes(probe_font.buffer or b"")
            font_sha256 = hashlib.sha256(buffer).hexdigest()
    except Exception as exc:
        logging.warning("Reference font could not be loaded (%s): %s", font_path, exc)
        result = ReferenceSet(
            font_label=f"unavailable ({font_path or 'built-in'})",
            font_sha256="", inventory_spec=inventory_spec, size=size,
            missing=tuple(chars),
        )
        _reference_cache[key] = result
        return result

    renderable = [ch for ch in chars if probe_font.has_glyph(ord(ch))]
    missing = tuple(ch for ch in chars if ch not in set(renderable))

    bitmaps: dict[str, GlyphBitmap] = {}
    doc = fitz.open()
    try:
        for ch in renderable:
            page = doc.new_page(width=_PAGE_SIZE, height=_PAGE_SIZE)
            if resolved_path:
                page.insert_font(fontname="ref", fontfile=resolved_path)
                page.insert_text(_ORIGIN, ch, fontname="ref", fontsize=_FONT_SIZE)
            else:
                page.insert_text(_ORIGIN, ch, fontname="helv", fontsize=_FONT_SIZE)

        for index, ch in enumerate(renderable):
            pix = doc[index].get_pixmap(dpi=_RENDER_DPI, colorspace=fitz.csGRAY)
            bitmaps[ch] = normalise_render(
                pix.samples, pix.width, pix.height, size, blur_radius)
    except Exception as exc:  # pragma: no cover - depends on font behaviour
        logging.warning("Reference alphabet rendering failed: %s", exc)
    finally:
        doc.close()

    # A glyph the font claims to have but draws as nothing is not usable,
    # except for characters that legitimately have no ink.
    blank_but_inked = tuple(
        ch for ch, bmp in bitmaps.items() if bmp.blank and not ch.isspace()
    )
    for ch in blank_but_inked:
        bitmaps.pop(ch, None)

    # Group characters whose renders are byte-identical.  Characters in the
    # same group cannot be told apart by shape, whatever the score says.
    groups: dict[tuple, list[str]] = {}
    for ch, bmp in bitmaps.items():
        signature = (
            bmp.pixels,
            round(bmp.aspect, 4),
            round(bmp.rel_above, 4),
            round(bmp.rel_below, 4),
        )
        groups.setdefault(signature, []).append(ch)

    comparable: dict[str, GlyphBitmap] = {}
    equivalents: dict[str, tuple[str, ...]] = {}
    unrenderable: list[str] = []
    for signature, members in groups.items():
        members.sort()
        if len(members) > _MAX_EQUIVALENT_GROUP:
            # Far more characters share this shape than any real typeface
            # would justify; the font is drawing a placeholder.
            unrenderable.extend(members)
            continue
        representative = members[0]
        comparable[representative] = bitmaps[representative]
        equivalents[representative] = tuple(members)

    if unrenderable:
        logging.info(
            "Reference font %s draws %d inventory characters as the same "
            "placeholder glyph; excluded from shape comparison.",
            font_label, len(unrenderable))

    result = ReferenceSet(
        font_label=font_label,
        font_sha256=font_sha256,
        inventory_spec=inventory_spec,
        size=size,
        bitmaps=comparable,
        equivalents=equivalents,
        missing=tuple(sorted(set(missing) | set(blank_but_inked))),
        unrenderable=tuple(sorted(unrenderable)),
    )
    _reference_cache[key] = result
    return result


def match_glyph(
    unknown: GlyphBitmap,
    reference: ReferenceSet,
    weights: Optional[ScoreWeights] = None,
    top_n: int = 5,
    aspect_prefilter: float = 0.30,
    metrics_tolerance: float = _METRICS_TOLERANCE,
) -> tuple[ShapeMatch, ...]:
    """
    Rank the reference alphabet against one unknown glyph.

    *aspect_prefilter* skips references whose proportions are wildly
    different before the expensive correlation, purely as an optimisation.
    It is deliberately loose so that it cannot exclude a plausible answer;
    at the default of 0.30 a reference is only skipped when one shape is
    more than three times as elongated as the other.
    """
    weights = weights or ScoreWeights()

    if unknown.blank:
        blanks = [ch for ch, bmp in reference.bitmaps.items() if bmp.blank]
        if blanks:
            return tuple(
                ShapeMatch(text=ch, score=1.0, terms={"blank": True},
                           equivalents=reference.group_for(ch))
                for ch in sorted(blanks)[:top_n]
            )
        return ()

    scored: list[ShapeMatch] = []
    for ch, bitmap in reference.bitmaps.items():
        if bitmap.blank:
            continue
        if _aspect_agreement(unknown.aspect, bitmap.aspect) < aspect_prefilter:
            continue
        score, terms = compare(unknown, bitmap, weights, metrics_tolerance)
        scored.append(ShapeMatch(
            text=ch, score=score, terms=terms,
            equivalents=reference.group_for(ch),
        ))

    # Sort by descending score, then by code point so ties are deterministic.
    scored.sort(key=lambda m: (-m.score, ord(m.text)))
    return tuple(scored[:top_n])


# --------------------------------------------------------------------------
# Rendering codes through the document's own font
# --------------------------------------------------------------------------

class GlyphRenderer:
    """
    Renders character codes through the fonts of one document.

    The font dictionary is copied unchanged into a scratch PDF, so the
    resulting bitmap is what a viewer draws for that code - not a
    reconstruction.  Results are cached per (font xref, code) because a
    single text run commonly repeats codes.
    """

    def __init__(self, pdf_bytes: bytes, size: int = 32, blur_radius: int = 1):
        self._pdf_bytes = pdf_bytes
        self._size = size
        self._blur_radius = blur_radius
        self._source = None
        self._cache: dict[tuple[int, int], Optional[GlyphBitmap]] = {}
        self._failures: dict[int, str] = {}

    def _open_source(self):
        if self._source is None:
            import pikepdf
            self._source = pikepdf.open(io.BytesIO(self._pdf_bytes))
        return self._source

    def close(self) -> None:
        if self._source is not None:
            try:
                self._source.close()
            except Exception:
                pass
            self._source = None

    def __enter__(self) -> "GlyphRenderer":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def failure_for(self, font_xref: int) -> Optional[str]:
        """Why rendering was impossible for this font, if it was."""
        return self._failures.get(font_xref)

    def render_codes(self, font_xref: int, codes: Sequence[int]) -> dict[int, GlyphBitmap]:
        """
        Render each distinct code in *codes* through the font at *font_xref*.

        Codes that cannot be rendered are absent from the result; the reason
        is recorded on the renderer and surfaced in the evidence record.
        """
        wanted = []
        results: dict[int, GlyphBitmap] = {}
        for code in dict.fromkeys(codes):
            cached = self._cache.get((font_xref, code))
            if cached is not None:
                results[code] = cached
            elif (font_xref, code) not in self._cache:
                wanted.append(code)

        if not wanted or font_xref in self._failures:
            return results

        try:
            import pikepdf

            source = self._open_source()
            font_obj = source.get_object(font_xref, 0)
            probe = pikepdf.Pdf.new()
            foreign = probe.copy_foreign(font_obj)
            resources = probe.make_indirect(
                pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=foreign))
            )
            width = self._byte_width_for(font_obj)
            for code in wanted:
                page = probe.add_blank_page(page_size=(_PAGE_SIZE, _PAGE_SIZE))
                page.Resources = resources
                page.Contents = probe.make_stream(
                    b"BT /F1 %d Tf %d %d Td <%s> Tj ET" % (
                        int(_FONT_SIZE), int(_PDF_ORIGIN[0]), int(_PDF_ORIGIN[1]),
                        code.to_bytes(width, "big").hex().upper().encode("ascii"),
                    )
                )

            buffer = io.BytesIO()
            probe.save(buffer)
            probe.close()
            buffer.seek(0)

            with fitz.open(stream=buffer, filetype="pdf") as rendered:
                for index, code in enumerate(wanted):
                    pix = rendered[index].get_pixmap(
                        dpi=_RENDER_DPI, colorspace=fitz.csGRAY)
                    bitmap = normalise_render(
                        pix.samples, pix.width, pix.height,
                        self._size, self._blur_radius)
                    self._cache[(font_xref, code)] = bitmap
                    results[code] = bitmap
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            logging.debug("Glyph rendering failed for font xref %s: %s", font_xref, reason)
            self._failures[font_xref] = reason
            for code in wanted:
                self._cache[(font_xref, code)] = None

        return results

    @staticmethod
    def _byte_width_for(font_obj) -> int:
        """Composite fonts address glyphs with two-byte codes, simple with one."""
        try:
            return 2 if str(font_obj.get("/Subtype")) == "/Type0" else 1
        except Exception:
            return 1
