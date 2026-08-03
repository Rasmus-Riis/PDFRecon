"""
Tiered CID / ToUnicode Decoder

Recovers the text behind a PDF string operand when the font's ``/ToUnicode``
CMap is missing, incomplete or non-standard - the situation that makes
TouchUp text extraction produce output like ``ZK,KZK,ZP=GZ``.  It automates
the manual procedure documented in the PDFRecon manual.

The single entry point is :func:`decode`.  It takes a PyMuPDF document, a
font reference and the raw encoded bytes, and returns a
:class:`DecodingResult` carrying the text, the method that produced it, a
confidence level, an evidence record and ranked alternatives.

Tiers, tried in order and stopping at the first certain result
--------------------------------------------------------------
====== ================= ============ =========================================
Tier   Method            Confidence   Basis
====== ================= ============ =========================================
0      ``tounicode``     CERTAIN      The font's own ``/ToUnicode`` CMap.
1      ``glyphnames``    CERTAIN      ``/Encoding /Differences`` or the
                                      embedded font's ``post`` table / CFF
                                      charset, resolved via the Adobe Glyph
                                      List.
2      ``shapematch``    PROBABLE     The rendered shape of the glyph, matched
                                      against a reference alphabet.  Upgraded
                                      to CERTAIN only on a wide score margin,
                                      and never for ambiguous characters.
====== ================= ============ =========================================

Tiers 3 to 6 described in the project plan (cross-document CMap transfer,
OCR, statistical substitution solving, optional local model) are not
implemented here.  The tier framework accommodates them without disturbing
tiers 0 to 2.

Rules the implementation holds to
---------------------------------
* **A lower tier never overwrites a higher tier's result for a character.**
  Decoding proceeds per character code; once a code is resolved by tier *n*,
  later tiers are not consulted for it.
* **The confidence of a string is the lowest confidence of its characters.**
  A run where nine characters come from the AGL and one from shape matching
  is PROBABLE, not CERTAIN, and ``per_char`` identifies which character is
  the weak one.
* **Probabilistic methods return ranked alternatives, never one answer.**
* **Nothing is invented.**  A code that no tier resolves is rendered with a
  placeholder in ``text`` and marked unresolved in ``per_char``; it is never
  filled with a plausible-looking guess.
* **Everything is offline and deterministic.**  No network access, no
  external process, no randomness.  Identical input yields identical output.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

try:  # pragma: no cover - import shape differs between package and script use
    from . import cid_shapes
    from .cid_fonts import FontContext, classify_glyph_name, glyph_name_to_text, \
        load_agl, resolve_font, split_codes
except ImportError:  # pragma: no cover
    import cid_shapes
    from cid_fonts import FontContext, classify_glyph_name, glyph_name_to_text, \
        load_agl, resolve_font, split_codes


CERTAIN = "CERTAIN"
PROBABLE = "PROBABLE"
SPECULATIVE = "SPECULATIVE"

#: Ordered weakest to strongest, so ``min`` over a run gives its confidence.
_CONFIDENCE_ORDER = {SPECULATIVE: 0, PROBABLE: 1, CERTAIN: 2}

#: Stands in for a character no tier could resolve.  U+FFFD is the Unicode
#: replacement character - it is deliberately not a plausible letter, so an
#: unresolved position can never be mistaken for a decoded one.
UNRESOLVED_PLACEHOLDER = "�"

METHOD_TOUNICODE = "tounicode"
METHOD_GLYPHNAMES = "glyphnames"
METHOD_SHAPEMATCH = "shapematch"
METHOD_NONE = "undecoded"


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class DecoderSettings:
    """
    Everything tunable about a decoding run.

    Defaults match :class:`src.config.PDFReconConfig`; :meth:`from_config`
    builds an instance from it.  Nothing here is locale-specific beyond
    ``character_inventory``, which is a documented default with an
    extension point rather than a hardcoded assumption.
    """

    enabled: bool = True
    tier0_tounicode: bool = True
    tier1_glyphnames: bool = True
    tier2_shapematch: bool = True

    character_inventory: str = cid_shapes.DEFAULT_INVENTORY
    reference_font_path: Optional[str] = None
    shape_certain_margin: float = cid_shapes.DEFAULT_CERTAIN_MARGIN
    shape_min_score: float = 0.45
    shape_bitmap_size: int = 32
    max_alternatives: int = 5
    confusable_groups: Sequence[str] = cid_shapes.DEFAULT_CONFUSABLE_GROUPS

    @classmethod
    def from_config(cls, config=None) -> "DecoderSettings":
        """Build settings from :class:`PDFReconConfig`, falling back to defaults."""
        if config is None:
            try:
                from .config import PDFReconConfig as config  # type: ignore
            except ImportError:  # pragma: no cover
                try:
                    from config import PDFReconConfig as config  # type: ignore
                except ImportError:
                    return cls()

        groups = getattr(config, "CID_CONFUSABLE_GROUPS", None)
        if isinstance(groups, str) and groups.strip():
            parsed: Sequence[str] = tuple(groups.split())
        elif isinstance(groups, (list, tuple)) and groups:
            parsed = tuple(groups)
        else:
            parsed = cid_shapes.DEFAULT_CONFUSABLE_GROUPS

        return cls(
            enabled=getattr(config, "CID_DECODE_ENABLED", True),
            tier0_tounicode=getattr(config, "CID_TIER0_TOUNICODE", True),
            tier1_glyphnames=getattr(config, "CID_TIER1_GLYPHNAMES", True),
            tier2_shapematch=getattr(config, "CID_TIER2_SHAPEMATCH", True),
            character_inventory=getattr(
                config, "CID_CHARACTER_INVENTORY", cid_shapes.DEFAULT_INVENTORY),
            reference_font_path=getattr(config, "CID_REFERENCE_FONT_PATH", None),
            shape_certain_margin=float(getattr(
                config, "CID_SHAPE_CERTAIN_MARGIN", cid_shapes.DEFAULT_CERTAIN_MARGIN)),
            shape_min_score=float(getattr(config, "CID_SHAPE_MIN_SCORE", 0.45)),
            shape_bitmap_size=int(getattr(config, "CID_SHAPE_BITMAP_SIZE", 32)),
            max_alternatives=int(getattr(config, "CID_MAX_ALTERNATIVES", 5)),
            confusable_groups=parsed,
        )


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class CharCandidate:
    """One character position in a decoded run."""

    code: int
    text: str
    method: str
    confidence: str
    resolved: bool
    score: Optional[float] = None
    margin: Optional[float] = None
    #: Other characters this position could be, best first.
    alternatives: tuple[str, ...] = ()
    #: Why the position is what it is, in terms an examiner can check.
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "code_hex": f"{self.code:04X}",
            "text": self.text,
            "method": self.method,
            "confidence": self.confidence,
            "resolved": self.resolved,
            "score": self.score,
            "margin": self.margin,
            "alternatives": list(self.alternatives),
            "note": self.note,
        }


@dataclass(frozen=True)
class Alternative:
    """A whole-string alternative reading."""

    text: str
    reason: str
    positions: tuple[int, ...] = ()

    def as_dict(self) -> dict:
        return {"text": self.text, "reason": self.reason,
                "positions": list(self.positions)}


@dataclass(frozen=True)
class TierOutcome:
    """What one tier did, for the chain-of-custody record."""

    tier: int
    method: str
    ran: bool
    resolved: int = 0
    detail: str = ""

    def as_dict(self) -> dict:
        return {"tier": self.tier, "method": self.method, "ran": self.ran,
                "resolved": self.resolved, "detail": self.detail}


@dataclass(frozen=True)
class DecodingResult:
    """
    The outcome of decoding one string operand.

    ``text`` always has one entry per character code, with
    :data:`UNRESOLVED_PLACEHOLDER` where no tier could resolve the code, so
    positions in ``text`` line up with ``per_char``.
    """

    text: str
    method: str
    confidence: str
    evidence: dict = field(default_factory=dict)
    alternatives: tuple[Alternative, ...] = ()
    per_char: tuple[CharCandidate, ...] = ()
    tiers_run: tuple[TierOutcome, ...] = ()

    @property
    def is_complete(self) -> bool:
        """True when every character code was resolved by some tier."""
        return all(candidate.resolved for candidate in self.per_char)

    @property
    def resolved_count(self) -> int:
        return sum(1 for candidate in self.per_char if candidate.resolved)

    def as_dict(self) -> dict:
        """A JSON-safe record for exports and the custody log."""
        return {
            "text": self.text,
            "method": self.method,
            "confidence": self.confidence,
            "complete": self.is_complete,
            "resolved": self.resolved_count,
            "length": len(self.per_char),
            "evidence": self.evidence,
            "alternatives": [alt.as_dict() for alt in self.alternatives],
            "per_char": [candidate.as_dict() for candidate in self.per_char],
            "tiers_run": [outcome.as_dict() for outcome in self.tiers_run],
        }


# --------------------------------------------------------------------------
# Per-document cache
# --------------------------------------------------------------------------

class DecoderCache:
    """
    Work shared across all runs in one document.

    Font resolution, the scratch rendering document and the reference
    alphabet are each built once.  A caller decoding many runs should pass
    the same cache to every :func:`decode` call and close it afterwards.
    """

    def __init__(self, pdf_bytes: Optional[bytes] = None,
                 settings: Optional[DecoderSettings] = None):
        self.settings = settings or DecoderSettings()
        self._pdf_bytes = pdf_bytes
        self._fonts: dict[int, FontContext] = {}
        self._renderer: Optional[cid_shapes.GlyphRenderer] = None
        self._reference: Optional[cid_shapes.ReferenceSet] = None
        self._shape_results: dict[tuple[int, int], Optional[tuple]] = {}
        self._confusable = cid_shapes.build_confusable_set(
            self.settings.confusable_groups)

    def font(self, doc, xref: int, resource_name: str = "") -> FontContext:
        context = self._fonts.get(xref)
        if context is None:
            context = resolve_font(doc, xref, resource_name)
            self._fonts[xref] = context
        return context

    def renderer(self) -> Optional[cid_shapes.GlyphRenderer]:
        if self._pdf_bytes is None:
            return None
        if self._renderer is None:
            self._renderer = cid_shapes.GlyphRenderer(
                self._pdf_bytes, size=self.settings.shape_bitmap_size)
        return self._renderer

    def reference(self) -> cid_shapes.ReferenceSet:
        if self._reference is None:
            self._reference = cid_shapes.build_reference_set(
                self.settings.character_inventory,
                size=self.settings.shape_bitmap_size,
                font_path=self.settings.reference_font_path,
            )
        return self._reference

    @property
    def confusable(self) -> frozenset:
        return self._confusable

    def close(self) -> None:
        if self._renderer is not None:
            self._renderer.close()
            self._renderer = None

    def __enter__(self) -> "DecoderCache":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


# --------------------------------------------------------------------------
# Tiers
# --------------------------------------------------------------------------

def _tier0_tounicode(codes: Sequence[int], context: FontContext,
                     pending: dict[int, None]) -> dict[int, CharCandidate]:
    """Resolve codes through the font's own ``/ToUnicode`` CMap."""
    resolved: dict[int, CharCandidate] = {}
    for code in list(pending):
        text = context.tounicode.get(code)
        if text is None:
            continue
        resolved[code] = CharCandidate(
            code=code, text=text, method=METHOD_TOUNICODE,
            confidence=CERTAIN, resolved=True,
            note=f"ToUnicode CMap in object {context.tounicode_xref}",
        )
        pending.pop(code, None)
    return resolved


def _glyph_name_for_code(code: int, context: FontContext) -> tuple[Optional[str], str]:
    """
    Find the glyph name for a character code, and say where it came from.

    Simple fonts name glyphs directly through ``/Encoding /Differences``.
    Composite fonts do not: the code is a CID, which maps to a glyph index,
    whose name comes from the embedded font program.  Where the code-to-glyph
    step is not knowable without parsing the font's own ``cmap`` - a simple
    font with no ``/Differences`` entry - no name is returned rather than a
    guess.
    """
    name = context.differences.get(code)
    if name:
        return name, "/Encoding /Differences"

    gid = context.gid_for_code(code)
    if gid is not None and context.glyph_names:
        name = context.glyph_names.get(gid)
        if name:
            source = ("TrueType post table" if context.glyph_name_source == "post"
                      else "CFF charset")
            return name, f"{source}, glyph {gid}"
    return None, ""


def _tier1_glyphnames(codes: Sequence[int], context: FontContext,
                      pending: dict[int, None]) -> tuple[dict[int, CharCandidate], dict]:
    """Resolve codes through glyph names and the Adobe Glyph List."""
    agl, agl_sha256 = load_agl()
    resolved: dict[int, CharCandidate] = {}
    rejected: dict[str, str] = {}

    for code in list(pending):
        name, source = _glyph_name_for_code(code, context)
        if not name:
            continue
        text = glyph_name_to_text(name, agl)
        if text is None:
            # Recorded so the evidence can say *why* the name was no help.
            rejected[f"{code:04X}"] = f"/{name} ({classify_glyph_name(name)})"
            continue
        resolved[code] = CharCandidate(
            code=code, text=text, method=METHOD_GLYPHNAMES,
            confidence=CERTAIN, resolved=True,
            note=f"glyph name /{name} from {source}",
        )
        pending.pop(code, None)

    evidence = {
        "agl_sha256": agl_sha256,
        "agl_entries": len(agl),
        "glyph_name_source": context.glyph_name_source or None,
        "uninformative_names": rejected or None,
    }
    return resolved, evidence


def _tier2_shapematch(codes: Sequence[int], context: FontContext,
                      pending: dict[int, None], cache: DecoderCache,
                      ) -> tuple[dict[int, CharCandidate], dict]:
    """Resolve codes by rendering the glyph and matching its shape."""
    settings = cache.settings
    renderer = cache.renderer()
    if renderer is None:
        return {}, {"skipped": "no document bytes available for rendering"}

    reference = cache.reference()
    if not reference.bitmaps:
        return {}, {
            "skipped": "reference alphabet is empty",
            "reference": reference.provenance(),
        }

    bitmaps = renderer.render_codes(context.xref, list(pending))
    failure = renderer.failure_for(context.xref)
    if failure and not bitmaps:
        return {}, {
            "skipped": f"glyph rendering failed: {failure}",
            "reference": reference.provenance(),
        }

    resolved: dict[int, CharCandidate] = {}
    glyph_images: dict[str, str] = {}
    weights = cid_shapes.ScoreWeights()

    for code in list(pending):
        bitmap = bitmaps.get(code)
        if bitmap is None:
            continue
        matches = cid_shapes.match_glyph(
            bitmap, reference, weights=weights,
            top_n=max(2, settings.max_alternatives),
        )
        if not matches:
            continue

        best = matches[0]
        if best.score < settings.shape_min_score:
            # A weak best match is worse than none: it would put a specific
            # wrong character on the page for an examiner to anchor on.
            continue

        margin = best.score - matches[1].score if len(matches) > 1 else 1.0
        alternatives = tuple(m.text for m in matches[1:settings.max_alternatives + 1])

        confidence = PROBABLE
        note_parts = [
            f"shape match against {reference.font_label}",
            f"score {best.score:.3f}",
            f"margin {margin:.3f}",
        ]

        if margin >= settings.shape_certain_margin:
            if best.is_ambiguous:
                note_parts.append(
                    "margin met but the reference font draws "
                    f"{'/'.join(best.equivalents)} identically")
            elif best.text in cache.confusable:
                note_parts.append(
                    "margin met but the character is in the confusable set")
            else:
                confidence = CERTAIN
                note_parts.append(
                    f"margin exceeds the {settings.shape_certain_margin:g} threshold")

        if best.is_ambiguous:
            # Every character in the group is an equally good reading.
            group = tuple(ch for ch in best.equivalents if ch != best.text)
            alternatives = group + tuple(
                ch for ch in alternatives if ch not in group)

        try:
            glyph_images[f"{code:04X}"] = _png_data_uri(bitmap)
        except Exception as exc:  # pragma: no cover - display only
            logging.debug("Could not encode glyph bitmap for %04X: %s", code, exc)

        resolved[code] = CharCandidate(
            code=code, text=best.text, method=METHOD_SHAPEMATCH,
            confidence=confidence, resolved=True,
            score=round(best.score, 6), margin=round(margin, 6),
            alternatives=alternatives[:settings.max_alternatives],
            note="; ".join(note_parts),
        )
        pending.pop(code, None)

    evidence = {
        "reference": reference.provenance(),
        "weights": {
            "correlation": weights.correlation, "overlap": weights.overlap,
            "aspect": weights.aspect, "metrics": weights.metrics,
        },
        "certain_margin": settings.shape_certain_margin,
        "min_score": settings.shape_min_score,
        "glyph_bitmaps": glyph_images or None,
        "render_failure": failure,
    }
    return resolved, evidence


def _png_data_uri(bitmap: cid_shapes.GlyphBitmap) -> str:
    """Encode a glyph bitmap for display beside the character it is read as."""
    import base64
    return "data:image/png;base64," + base64.b64encode(bitmap.to_png()).decode("ascii")


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def decode(doc, font_ref, encoded_bytes: bytes, *,
           settings: Optional[DecoderSettings] = None,
           cache: Optional[DecoderCache] = None,
           resource_name: str = "") -> DecodingResult:
    """
    Decode one PDF string operand to text.

    :param doc: a PyMuPDF document.
    :param font_ref: the font's xref, or a resolved
        :class:`~src.cid_fonts.FontContext`.
    :param encoded_bytes: the raw operand bytes, exactly as they appear in
        the content stream.
    :param settings: decoder settings; defaults to
        :meth:`DecoderSettings.from_config`.
    :param cache: per-document cache.  Strongly recommended when decoding
        more than one run: without it the font is re-resolved and the
        reference alphabet re-rendered for every call.
    :param resource_name: the content-stream resource name (``C2_0``), used
        only to make the evidence record readable.

    :returns: a :class:`DecodingResult`.  Never raises for a malformed font
        or an unrenderable glyph; those become recorded tier outcomes.
    """
    owns_cache = cache is None
    if cache is None:
        cache = DecoderCache(settings=settings or DecoderSettings.from_config())
    elif settings is not None:
        cache.settings = settings
    active = cache.settings

    try:
        if isinstance(font_ref, FontContext):
            context = font_ref
        else:
            context = cache.font(doc, int(font_ref), resource_name)

        codes = split_codes(encoded_bytes, context)
        evidence: dict = {
            "font": context.provenance(),
            "encoded_hex": encoded_bytes.hex().upper(),
            "code_count": len(codes),
        }
        if context.notes:
            evidence["font_notes"] = list(context.notes)

        if not codes:
            return DecodingResult(
                text="", method=METHOD_NONE, confidence=SPECULATIVE,
                evidence=evidence, tiers_run=(),
            )

        # dict preserves order and gives O(1) removal; the value is unused.
        pending: dict[int, None] = {code: None for code in dict.fromkeys(codes)}
        resolved: dict[int, CharCandidate] = {}
        outcomes: list[TierOutcome] = []

        # --- Tier 0 ------------------------------------------------------
        if active.tier0_tounicode:
            found = _tier0_tounicode(codes, context, pending)
            resolved.update(found)
            outcomes.append(TierOutcome(
                0, METHOD_TOUNICODE, ran=True, resolved=len(found),
                detail=(f"{context.tounicode_entries} CMap entries"
                        if context.tounicode else "no usable ToUnicode CMap"),
            ))
        else:
            outcomes.append(TierOutcome(0, METHOD_TOUNICODE, ran=False,
                                        detail="disabled in settings"))

        # --- Tier 1 ------------------------------------------------------
        if pending and active.tier1_glyphnames:
            found, tier1_evidence = _tier1_glyphnames(codes, context, pending)
            resolved.update(found)
            evidence["glyph_names"] = tier1_evidence
            outcomes.append(TierOutcome(
                1, METHOD_GLYPHNAMES, ran=True, resolved=len(found),
                detail=(f"names from {context.glyph_name_source}"
                        if context.glyph_name_source
                        else "no glyph names available"),
            ))
        elif pending:
            outcomes.append(TierOutcome(1, METHOD_GLYPHNAMES, ran=False,
                                        detail="disabled in settings"))

        # --- Tier 2 ------------------------------------------------------
        if pending and active.tier2_shapematch:
            found, tier2_evidence = _tier2_shapematch(codes, context, pending, cache)
            resolved.update(found)
            evidence["shape_match"] = tier2_evidence
            outcomes.append(TierOutcome(
                2, METHOD_SHAPEMATCH, ran=True, resolved=len(found),
                detail=tier2_evidence.get("skipped")
                or f"{len(found)} of {len(found) + len(pending)} codes matched",
            ))
        elif pending:
            outcomes.append(TierOutcome(2, METHOD_SHAPEMATCH, ran=False,
                                        detail="disabled in settings"))

        # --- Assemble ----------------------------------------------------
        per_char: list[CharCandidate] = []
        for code in codes:
            candidate = resolved.get(code)
            if candidate is None:
                candidate = CharCandidate(
                    code=code, text=UNRESOLVED_PLACEHOLDER, method=METHOD_NONE,
                    confidence=SPECULATIVE, resolved=False,
                    note="no tier could resolve this code",
                )
            per_char.append(candidate)

        text = "".join(candidate.text for candidate in per_char)
        methods = {c.method for c in per_char if c.resolved}
        if not methods:
            method = METHOD_NONE
        elif len(methods) == 1:
            method = methods.pop()
        else:
            method = "mixed:" + "+".join(
                m for m in (METHOD_TOUNICODE, METHOD_GLYPHNAMES, METHOD_SHAPEMATCH)
                if m in methods)

        if any(not c.resolved for c in per_char):
            confidence = SPECULATIVE
        else:
            confidence = min(
                (c.confidence for c in per_char),
                key=lambda level: _CONFIDENCE_ORDER[level],
                default=SPECULATIVE,
            )

        evidence["unresolved_codes"] = [
            f"{c.code:04X}" for c in per_char if not c.resolved
        ] or None

        return DecodingResult(
            text=text, method=method, confidence=confidence,
            evidence=evidence,
            alternatives=_string_alternatives(per_char, active.max_alternatives),
            per_char=tuple(per_char),
            tiers_run=tuple(outcomes),
        )
    finally:
        if owns_cache:
            cache.close()


def _string_alternatives(per_char: Sequence[CharCandidate],
                         limit: int) -> tuple[Alternative, ...]:
    """
    Build whole-string alternative readings.

    One alternative is produced per uncertain position, substituting that
    position's next-best candidate.  Enumerating the full combinatorial
    product would be useless to a reader; showing which single position is
    doubtful, and what else it could be, is what an examiner needs in order
    to challenge the reading.
    """
    uncertain = [
        (index, candidate)
        for index, candidate in enumerate(per_char)
        if candidate.alternatives and candidate.confidence != CERTAIN
    ]
    if not uncertain:
        return ()

    # Least confident positions first: lowest margin, then lowest score.
    uncertain.sort(key=lambda item: (
        item[1].margin if item[1].margin is not None else 1.0,
        item[1].score if item[1].score is not None else 1.0,
    ))

    base = [candidate.text for candidate in per_char]
    alternatives: list[Alternative] = []
    for index, candidate in uncertain[:limit]:
        substitute = candidate.alternatives[0]
        variant = list(base)
        variant[index] = substitute
        alternatives.append(Alternative(
            text="".join(variant),
            reason=(f"position {index + 1} read as {candidate.text!r} "
                    f"(margin {candidate.margin:.3f}); "
                    f"{substitute!r} is the next-best shape match"
                    if candidate.margin is not None else
                    f"position {index + 1} read as {candidate.text!r}; "
                    f"{substitute!r} is an equally plausible reading"),
            positions=(index,),
        ))
    return tuple(alternatives)


def decode_runs(doc, pdf_bytes: bytes, runs: Iterable,
                settings: Optional[DecoderSettings] = None) -> list:
    """
    Decode many runs from one document, sharing all the expensive work.

    *runs* yields ``(font_xref, resource_name, encoded_bytes)`` triples.
    Returns a list of ``(run, DecodingResult)`` pairs in input order.
    """
    active = settings or DecoderSettings.from_config()
    results = []
    if not active.enabled:
        return results

    with DecoderCache(pdf_bytes=pdf_bytes, settings=active) as cache:
        for run in runs:
            font_xref, resource_name, encoded = run
            try:
                result = decode(doc, font_xref, encoded, cache=cache,
                                resource_name=resource_name)
            except Exception as exc:
                logging.warning("CID decoding failed for font %s: %s", font_xref, exc)
                continue
            results.append((run, result))
    return results


def summarise_for_custody(results: Iterable[DecodingResult]) -> dict:
    """
    Condense decoding results for the chain-of-custody log.

    Records which tiers ran, what each produced, and the identifying hashes
    of the tables and fonts involved, so a decoding recorded in the log can
    be tied to the exact inputs that produced it.
    """
    tiers: dict[str, dict] = {}
    confidences: dict[str, int] = {}
    agl_hashes: set[str] = set()
    reference_fonts: dict[str, str] = {}
    font_hashes: set[str] = set()
    total = 0

    for result in results:
        total += 1
        confidences[result.confidence] = confidences.get(result.confidence, 0) + 1
        for outcome in result.tiers_run:
            entry = tiers.setdefault(
                f"tier{outcome.tier}_{outcome.method}",
                {"ran": False, "runs": 0, "characters_resolved": 0},
            )
            entry["ran"] = entry["ran"] or outcome.ran
            entry["runs"] += 1 if outcome.ran else 0
            entry["characters_resolved"] += outcome.resolved

        names = result.evidence.get("glyph_names") or {}
        if names.get("agl_sha256"):
            agl_hashes.add(names["agl_sha256"])
        shape = result.evidence.get("shape_match") or {}
        reference = shape.get("reference") or {}
        if reference.get("reference_font"):
            reference_fonts[reference["reference_font"]] = \
                reference.get("reference_font_sha256", "")
        font = result.evidence.get("font") or {}
        if font.get("font_program_sha256"):
            font_hashes.add(font["font_program_sha256"])

    return {
        "runs_decoded": total,
        "confidence_counts": confidences,
        "tiers": tiers,
        "agl_sha256": sorted(agl_hashes) or None,
        "reference_fonts": reference_fonts or None,
        "document_font_sha256": sorted(font_hashes) or None,
    }
