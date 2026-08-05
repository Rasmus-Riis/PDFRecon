"""
Font Resolution for CID / ToUnicode Decoding

Reads everything the tiered decoder in :mod:`src.cid_decoder` needs to know
about one PDF font, and nothing else.  All of it is derived from the file
under examination; no assumption is made about the language, script or
locale of its content.

The module provides three independent capabilities:

* :func:`resolve_font` - builds a :class:`FontContext` from a PyMuPDF
  document and a font xref: encoding, code width, the ToUnicode CMap, the
  ``/Encoding /Differences`` name overrides, the embedded font program and
  its SHA-256.
* :func:`parse_tounicode_cmap` - a CMap reader for Tier 0.
* :func:`embedded_glyph_names` / :func:`glyph_name_to_text` - glyph-name
  recovery from an embedded TrueType ``post`` table or CFF charset, and
  Adobe Glyph List resolution, for Tier 1.

Deliberate limitations, because a forensic tool must not invent data:

* Glyph names that encode no character information (``g43``, ``cid42``,
  ``glyph17``, ``index5``) are rejected with a recorded reason rather than
  guessed at.
* A ToUnicode entry mapping to U+FFFD or U+0000 is treated as *absent*, not
  as a successful decoding.
* Where a code width has to be assumed rather than read from a codespace
  range, the assumption is recorded on the context so it can be reported.

No network access, no external tools, no runtime dependency on fontTools.
The bundled tables in ``src/assets/agl.txt`` and :mod:`src.cid_glyph_tables`
are generated offline by ``tools/generate_glyph_data.py``.
"""

from __future__ import annotations

import hashlib
import logging
import re
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

try:  # pragma: no cover - import shape differs between package and script use
    from .cid_glyph_tables import CFF_STANDARD_STRINGS, MAC_STANDARD_GLYPH_ORDER
except ImportError:  # pragma: no cover
    from cid_glyph_tables import CFF_STANDARD_STRINGS, MAC_STANDARD_GLYPH_ORDER


# --------------------------------------------------------------------------
# Bundled asset resolution
# --------------------------------------------------------------------------

def _asset_dir() -> Path:
    """Locate the bundled asset directory, both frozen and from source."""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidate = Path(meipass) / "src" / "assets"
            if candidate.is_dir():
                return candidate
            candidate = Path(meipass) / "assets"
            if candidate.is_dir():
                return candidate
    return Path(__file__).resolve().parent / "assets"


AGL_FILENAME = "agl.txt"

_agl_cache: Optional[tuple[dict[str, str], str]] = None


def load_agl() -> tuple[dict[str, str], str]:
    """
    Load the bundled Adobe Glyph List.

    Returns ``(mapping, sha256)`` where *mapping* is glyph name -> text and
    *sha256* is the digest of the asset file.  The digest goes into the
    evidence record so a Tier 1 decoding can be tied to an exact table.

    A missing or unreadable asset yields an empty mapping; Tier 1 then
    reports that it could not run rather than failing the scan.
    """
    global _agl_cache
    if _agl_cache is not None:
        return _agl_cache

    path = _asset_dir() / AGL_FILENAME
    mapping: dict[str, str] = {}
    digest = ""
    try:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        for line in raw.decode("utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            name, _, codes = line.partition(";")
            if not name or not codes:
                continue
            try:
                mapping[name] = "".join(chr(int(c, 16)) for c in codes.split())
            except ValueError:
                continue
    except Exception as exc:  # pragma: no cover - depends on deployment
        logging.warning("Could not load Adobe Glyph List from %s: %s", path, exc)

    _agl_cache = (mapping, digest)
    return _agl_cache


# --------------------------------------------------------------------------
# Glyph name -> text (Adobe Glyph List algorithm)
# --------------------------------------------------------------------------

# Names produced by subsetters that carry no character information.  These are
# matched only to explain *why* a name was rejected; they would fail the AGL
# algorithm anyway.
_UNINFORMATIVE_NAME_RE = re.compile(
    r"^(?:g|glyph|cid|c|index|G|Glyph|CID|C|Index)\d+$"
)
_ORDINAL_NAME_RE = re.compile(r"^\d+$")
_UNI_NAME_RE = re.compile(r"^uni((?:[0-9A-Fa-f]{4})+)$")
_U_NAME_RE = re.compile(r"^u([0-9A-Fa-f]{4,6})$")

# Reserved for UTF-16 surrogate halves; never a character in its own right.
_SURROGATE_RANGE = range(0xD800, 0xE000)


def classify_glyph_name(name: str) -> str:
    """
    Describe why a glyph name is or is not usable, for the evidence record.

    Returns one of ``"agl"``, ``"uni"``, ``"u"``, ``"ligature"``,
    ``"uninformative"``, ``"notdef"`` or ``"unknown"``.
    """
    if not name:
        return "unknown"
    if name in (".notdef", ".null", "nonmarkingreturn"):
        return "notdef"
    if _UNINFORMATIVE_NAME_RE.match(name) or _ORDINAL_NAME_RE.match(name):
        return "uninformative"

    base = name.split(".", 1)[0]
    if not base:
        return "unknown"
    if "_" in base:
        return "ligature"

    agl, _ = load_agl()
    if base in agl:
        return "agl"
    if _UNI_NAME_RE.match(base):
        return "uni"
    if _U_NAME_RE.match(base):
        return "u"
    return "unknown"


def _component_to_text(component: str, agl: dict[str, str]) -> Optional[str]:
    """Resolve one non-ligature glyph-name component to text."""
    if component in agl:
        return agl[component]

    match = _UNI_NAME_RE.match(component)
    if match:
        digits = match.group(1)
        chars = []
        for i in range(0, len(digits), 4):
            cp = int(digits[i:i + 4], 16)
            if cp in _SURROGATE_RANGE:
                return None
            chars.append(chr(cp))
        return "".join(chars)

    match = _U_NAME_RE.match(component)
    if match:
        cp = int(match.group(1), 16)
        if cp in _SURROGATE_RANGE or cp > 0x10FFFF:
            return None
        return chr(cp)

    return None


def glyph_name_to_text(name: str, agl: Optional[dict[str, str]] = None) -> Optional[str]:
    """
    Map a PostScript glyph name to the text it represents, or ``None``.

    Implements the Adobe Glyph List algorithm: an optional ``.suffix`` is
    dropped, ``_`` separates ligature components, and each component is
    resolved through the AGL or the ``uniXXXX`` / ``uXXXX[XX]`` conventions.

    Names that encode only a glyph index (``g43``, ``cid42``) return
    ``None``: the mapping is genuinely unknown and must not be guessed.
    """
    if not name:
        return None
    if name in (".notdef", ".null", "nonmarkingreturn"):
        return None
    if _UNINFORMATIVE_NAME_RE.match(name) or _ORDINAL_NAME_RE.match(name):
        return None

    if agl is None:
        agl, _ = load_agl()

    base = name.split(".", 1)[0]
    if not base:
        return None

    parts = []
    for component in base.split("_"):
        text = _component_to_text(component, agl)
        if text is None:
            return None
        parts.append(text)

    result = "".join(parts)
    return result or None


# --------------------------------------------------------------------------
# ToUnicode CMap
# --------------------------------------------------------------------------

_CODESPACE_BLOCK_RE = re.compile(
    rb"begincodespacerange(.*?)endcodespacerange", re.S)
_BFCHAR_BLOCK_RE = re.compile(rb"beginbfchar(.*?)endbfchar", re.S)
_BFRANGE_BLOCK_RE = re.compile(rb"beginbfrange(.*?)endbfrange", re.S)
_HEX_TOKEN_RE = re.compile(rb"<([0-9A-Fa-f\s]*)>")
_BFRANGE_ARRAY_RE = re.compile(
    rb"<([0-9A-Fa-f\s]*)>\s*<([0-9A-Fa-f\s]*)>\s*\[(.*?)\]", re.S)

# A ToUnicode entry pointing at these is a placeholder, not a decoding.
_NON_DECODINGS = {"�", "\x00"}


def _utf16be_to_text(raw: bytes) -> Optional[str]:
    """Decode a CMap destination value (UTF-16BE) to text."""
    if not raw:
        return None
    if len(raw) % 2:
        raw = raw + b"\x00"
    try:
        text = raw.decode("utf-16-be")
    except UnicodeDecodeError:
        return None
    text = text.rstrip("\x00")
    if not text or text in _NON_DECODINGS:
        return None
    return text


def _hex_bytes(token: bytes) -> bytes:
    digits = bytes(token).replace(b" ", b"").replace(b"\n", b"")
    digits = digits.replace(b"\r", b"").replace(b"\t", b"")
    if len(digits) % 2:
        digits += b"0"
    try:
        return bytes.fromhex(digits.decode("ascii"))
    except ValueError:
        return b""


@dataclass(frozen=True)
class CMapData:
    """A parsed ToUnicode CMap."""

    mapping: dict[int, str]
    codespace: tuple[tuple[int, int, int], ...]  # (byte length, low, high)
    entry_count: int

    def code_widths(self) -> tuple[int, ...]:
        return tuple(sorted({length for length, _, _ in self.codespace}))


def parse_tounicode_cmap(data: bytes) -> CMapData:
    """
    Parse a ``/ToUnicode`` CMap stream into a code -> text mapping.

    Handles ``beginbfchar`` / ``beginbfrange`` in both the
    ``<src> <dstLow>`` and ``<srcLow> <srcHigh> [<dst> ...]`` forms, and
    records the declared ``codespacerange`` entries so the caller can
    determine how many bytes make up one code.
    """
    mapping: dict[int, str] = {}
    codespace: list[tuple[int, int, int]] = []
    entries = 0

    if not data:
        return CMapData({}, (), 0)

    for block in _CODESPACE_BLOCK_RE.findall(data):
        tokens = _HEX_TOKEN_RE.findall(block)
        for i in range(0, len(tokens) - 1, 2):
            low_raw = _hex_bytes(tokens[i])
            high_raw = _hex_bytes(tokens[i + 1])
            if not low_raw or len(low_raw) != len(high_raw):
                continue
            codespace.append((
                len(low_raw),
                int.from_bytes(low_raw, "big"),
                int.from_bytes(high_raw, "big"),
            ))

    for block in _BFCHAR_BLOCK_RE.findall(data):
        tokens = _HEX_TOKEN_RE.findall(block)
        for i in range(0, len(tokens) - 1, 2):
            src = _hex_bytes(tokens[i])
            dst = _utf16be_to_text(_hex_bytes(tokens[i + 1]))
            if not src or dst is None:
                continue
            entries += 1
            mapping[int.from_bytes(src, "big")] = dst

    for block in _BFRANGE_BLOCK_RE.findall(data):
        # Array form first, then remove it so the scalar scan cannot mis-pair.
        remainder = block
        for low_tok, high_tok, array in _BFRANGE_ARRAY_RE.findall(block):
            low_raw = _hex_bytes(low_tok)
            high_raw = _hex_bytes(high_tok)
            if not low_raw or not high_raw:
                continue
            low = int.from_bytes(low_raw, "big")
            high = int.from_bytes(high_raw, "big")
            values = _HEX_TOKEN_RE.findall(array)
            for offset, value in enumerate(values):
                code = low + offset
                if code > high:
                    break
                dst = _utf16be_to_text(_hex_bytes(value))
                if dst is None:
                    continue
                entries += 1
                mapping[code] = dst
        remainder = _BFRANGE_ARRAY_RE.sub(b" ", block)

        tokens = _HEX_TOKEN_RE.findall(remainder)
        for i in range(0, len(tokens) - 2, 3):
            low_raw = _hex_bytes(tokens[i])
            high_raw = _hex_bytes(tokens[i + 1])
            dst_raw = _hex_bytes(tokens[i + 2])
            if not low_raw or not high_raw or not dst_raw:
                continue
            low = int.from_bytes(low_raw, "big")
            high = int.from_bytes(high_raw, "big")
            if high < low or high - low > 0xFFFF:
                continue
            base = _utf16be_to_text(dst_raw)
            if base is None:
                continue
            # Only the final UTF-16 code unit increments across a bfrange.
            prefix, last = base[:-1], ord(base[-1])
            for offset in range(high - low + 1):
                cp = last + offset
                if cp in _SURROGATE_RANGE or cp > 0x10FFFF:
                    break
                text = prefix + chr(cp)
                if text in _NON_DECODINGS:
                    continue
                entries += 1
                mapping[low + offset] = text

    return CMapData(mapping, tuple(codespace), entries)


# --------------------------------------------------------------------------
# Embedded font programs: glyph names
# --------------------------------------------------------------------------

def _sfnt_tables(data: bytes) -> dict[bytes, tuple[int, int]]:
    """Return ``{tag: (offset, length)}`` for an sfnt-wrapped font."""
    if len(data) < 12:
        return {}
    tag = data[:4]
    base = 0
    if tag == b"ttcf":
        if len(data) < 16:
            return {}
        first = struct.unpack(">I", data[12:16])[0]
        if first + 12 > len(data):
            return {}
        base = first
    elif tag not in (b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1"):
        return {}

    try:
        num_tables = struct.unpack(">H", data[base + 4:base + 6])[0]
    except struct.error:
        return {}

    tables: dict[bytes, tuple[int, int]] = {}
    for i in range(num_tables):
        rec = base + 12 + i * 16
        if rec + 16 > len(data):
            break
        name = data[rec:rec + 4]
        offset, length = struct.unpack(">II", data[rec + 8:rec + 16])
        if offset < len(data):
            tables[name] = (offset, min(length, len(data) - offset))
    return tables


def truetype_post_glyph_names(data: bytes) -> dict[int, str]:
    """
    Read glyph names from a TrueType ``post`` table (format 2.0).

    Other ``post`` formats carry no per-glyph names and yield an empty map.
    """
    tables = _sfnt_tables(data)
    if b"post" not in tables:
        return {}
    offset, length = tables[b"post"]
    block = data[offset:offset + length]
    if len(block) < 34:
        return {}

    version = struct.unpack(">I", block[:4])[0]
    if version != 0x00020000:
        return {}

    num_glyphs = struct.unpack(">H", block[32:34])[0]
    index_end = 34 + num_glyphs * 2
    if index_end > len(block):
        return {}
    indices = struct.unpack(f">{num_glyphs}H", block[34:index_end])

    # Pascal strings follow the index array.
    custom: list[str] = []
    pos = index_end
    while pos < len(block):
        size = block[pos]
        pos += 1
        if pos + size > len(block):
            break
        custom.append(block[pos:pos + size].decode("latin-1"))
        pos += size

    names: dict[int, str] = {}
    for gid, index in enumerate(indices):
        if index < len(MAC_STANDARD_GLYPH_ORDER):
            names[gid] = MAC_STANDARD_GLYPH_ORDER[index]
        else:
            custom_index = index - len(MAC_STANDARD_GLYPH_ORDER)
            if 0 <= custom_index < len(custom):
                names[gid] = custom[custom_index]
    return names


def _cff_index(data: bytes, pos: int) -> tuple[list[bytes], int]:
    """Read a CFF INDEX at *pos*; return its items and the position after it."""
    if pos + 2 > len(data):
        return [], pos
    count = struct.unpack(">H", data[pos:pos + 2])[0]
    if count == 0:
        return [], pos + 2
    off_size = data[pos + 2]
    if off_size < 1 or off_size > 4:
        return [], pos + 2

    offsets_start = pos + 3
    offsets: list[int] = []
    for i in range(count + 1):
        start = offsets_start + i * off_size
        if start + off_size > len(data):
            return [], len(data)
        offsets.append(int.from_bytes(data[start:start + off_size], "big"))

    data_start = offsets_start + (count + 1) * off_size - 1
    items: list[bytes] = []
    for i in range(count):
        begin = data_start + offsets[i]
        end = data_start + offsets[i + 1]
        if begin < 0 or end > len(data) or end < begin:
            items.append(b"")
            continue
        items.append(data[begin:end])
    return items, data_start + offsets[-1]


def _cff_top_dict(block: bytes) -> dict[int, list[float]]:
    """Parse a CFF DICT into ``{operator: operands}``."""
    result: dict[int, list[float]] = {}
    operands: list[float] = []
    pos = 0
    while pos < len(block):
        b0 = block[pos]
        if b0 <= 21:  # operator
            op = b0
            pos += 1
            if b0 == 12 and pos < len(block):
                op = 1200 + block[pos]
                pos += 1
            result[op] = operands
            operands = []
        elif b0 == 28:
            operands.append(struct.unpack(">h", block[pos + 1:pos + 3])[0])
            pos += 3
        elif b0 == 29:
            operands.append(struct.unpack(">i", block[pos + 1:pos + 5])[0])
            pos += 5
        elif b0 == 30:  # real number; operand value is irrelevant here
            pos += 1
            while pos < len(block):
                byte = block[pos]
                pos += 1
                if (byte & 0x0F) == 0x0F or (byte >> 4) == 0x0F:
                    break
            operands.append(0.0)
        elif 32 <= b0 <= 246:
            operands.append(b0 - 139)
            pos += 1
        elif 247 <= b0 <= 250:
            operands.append((b0 - 247) * 256 + block[pos + 1] + 108)
            pos += 2
        elif 251 <= b0 <= 254:
            operands.append(-(b0 - 251) * 256 - block[pos + 1] - 108)
            pos += 2
        else:
            pos += 1
    return result


def cff_charset_glyph_names(data: bytes) -> dict[int, str]:
    """
    Read glyph names from a CFF charset.

    Accepts a bare CFF font program or one wrapped in an OpenType ``CFF ``
    table.  CID-keyed CFF fonts map glyphs to CIDs rather than names; those
    yield an empty map because the "names" would be bare numbers.
    """
    tables = _sfnt_tables(data)
    if b"CFF " in tables:
        offset, length = tables[b"CFF "]
        data = data[offset:offset + length]

    if len(data) < 4:
        return {}
    hdr_size = data[2]
    if hdr_size < 4 or hdr_size > len(data):
        return {}

    pos = hdr_size
    _names, pos = _cff_index(data, pos)          # Name INDEX
    top_dicts, pos = _cff_index(data, pos)       # Top DICT INDEX
    strings, pos = _cff_index(data, pos)         # String INDEX
    if not top_dicts:
        return {}

    top = _cff_top_dict(top_dicts[0])
    if 1230 in top:  # ROS -> CID-keyed font, charset holds CIDs not names
        return {}

    charset_op = top.get(15)
    charstrings_op = top.get(17)
    if not charset_op or not charstrings_op:
        return {}

    charset_offset = int(charset_op[0])
    charstrings_offset = int(charstrings_op[0])
    # Offsets 0, 1, 2 select the predefined ISOAdobe/Expert charsets, whose
    # names we do not attempt to reconstruct.
    if charset_offset in (0, 1, 2) or charset_offset >= len(data):
        return {}

    charstrings, _ = _cff_index(data, charstrings_offset)
    num_glyphs = len(charstrings)
    if num_glyphs == 0:
        return {}

    def sid_to_name(sid: int) -> Optional[str]:
        if sid < len(CFF_STANDARD_STRINGS):
            return CFF_STANDARD_STRINGS[sid]
        index = sid - len(CFF_STANDARD_STRINGS)
        if 0 <= index < len(strings):
            return strings[index].decode("latin-1")
        return None

    names: dict[int, str] = {0: ".notdef"}
    fmt = data[charset_offset]
    pos = charset_offset + 1

    if fmt == 0:
        for gid in range(1, num_glyphs):
            if pos + 2 > len(data):
                break
            sid = struct.unpack(">H", data[pos:pos + 2])[0]
            pos += 2
            name = sid_to_name(sid)
            if name:
                names[gid] = name
    elif fmt in (1, 2):
        n_left_size = 1 if fmt == 1 else 2
        gid = 1
        while gid < num_glyphs and pos + 2 + n_left_size <= len(data):
            first = struct.unpack(">H", data[pos:pos + 2])[0]
            pos += 2
            if fmt == 1:
                n_left = data[pos]
                pos += 1
            else:
                n_left = struct.unpack(">H", data[pos:pos + 2])[0]
                pos += 2
            for offset in range(n_left + 1):
                if gid >= num_glyphs:
                    break
                name = sid_to_name(first + offset)
                if name:
                    names[gid] = name
                gid += 1
    else:
        return {}

    return names


def embedded_glyph_names(font_bytes: Optional[bytes], ext: Optional[str]) -> tuple[dict[int, str], str]:
    """
    Recover glyph names from an embedded font program.

    Returns ``(gid -> name, source)`` where *source* is ``"post"``,
    ``"cff_charset"`` or ``""`` when no names could be read.
    """
    if not font_bytes:
        return {}, ""

    ext = (ext or "").lower()
    # Try the format the extension suggests first, then the other, because a
    # PDF's /FontFile subtype and the actual program can disagree.
    attempts = (
        [cff_charset_glyph_names, truetype_post_glyph_names]
        if ext in ("cff", "otf", "pfa", "pfb", "t1", "type1")
        else [truetype_post_glyph_names, cff_charset_glyph_names]
    )
    labels = {
        truetype_post_glyph_names: "post",
        cff_charset_glyph_names: "cff_charset",
    }

    for reader in attempts:
        try:
            names = reader(font_bytes)
        except Exception as exc:
            logging.debug("Glyph name reader %s failed: %s", labels[reader], exc)
            continue
        # A map containing only .notdef tells us nothing.
        if names and any(n not in ("", ".notdef") for n in names.values()):
            return names, labels[reader]

    return {}, ""


# --------------------------------------------------------------------------
# Font context
# --------------------------------------------------------------------------

_XREF_NUM_RE = re.compile(r"(\d+)\s+\d+\s+R")
_DIFF_TOKEN_RE = re.compile(r"(\d+)|/([^\s/\[\]<>()]+)")


@dataclass
class FontContext:
    """Everything the decoder knows about one font in one document."""

    xref: int
    resource_name: str = ""
    base_font: str = ""
    subtype: str = ""
    encoding_name: Optional[str] = None
    is_identity: bool = False
    is_embedded: bool = False

    code_byte_width: int = 1
    code_width_source: str = "assumed"  # "codespacerange" | "identity" | "assumed"
    codespace: tuple[tuple[int, int, int], ...] = ()

    tounicode: dict[int, str] = field(default_factory=dict)
    tounicode_xref: Optional[int] = None
    tounicode_entries: int = 0

    differences: dict[int, str] = field(default_factory=dict)

    descendant_xref: Optional[int] = None
    cid_to_gid: Optional[dict[int, int]] = None  # None means Identity

    font_program: Optional[bytes] = None
    font_ext: Optional[str] = None
    font_sha256: Optional[str] = None

    glyph_names: dict[int, str] = field(default_factory=dict)
    glyph_name_source: str = ""

    notes: list[str] = field(default_factory=list)

    def provenance(self) -> dict:
        """Identifying facts an examiner can re-derive from the file itself."""
        return {
            "font_xref": self.xref,
            "resource_name": self.resource_name,
            "base_font": self.base_font,
            "subtype": self.subtype,
            "encoding": self.encoding_name,
            "embedded": self.is_embedded,
            "font_program_sha256": self.font_sha256,
            "font_program_bytes": len(self.font_program) if self.font_program else 0,
            "tounicode_xref": self.tounicode_xref,
            "tounicode_entries": self.tounicode_entries,
            "code_byte_width": self.code_byte_width,
            "code_width_source": self.code_width_source,
            "glyph_name_source": self.glyph_name_source,
            "glyph_names_read": len(self.glyph_names),
            "differences_entries": len(self.differences),
        }

    def gid_for_code(self, code: int) -> Optional[int]:
        """
        Map a character code to a glyph index, where that is knowable.

        Only defined for Identity-encoded composite fonts, where the code is
        the CID and ``/CIDToGIDMap`` gives the glyph.  For simple fonts the
        code-to-glyph step runs through the font's own ``cmap``, which this
        module does not parse; ``None`` is returned rather than a guess.
        """
        if not self.is_identity:
            return None
        if self.cid_to_gid is None:
            return code
        return self.cid_to_gid.get(code)


def _key(doc, xref: int, name: str) -> tuple[str, str]:
    try:
        return doc.xref_get_key(xref, name)
    except Exception:
        return ("null", "null")


def _first_xref(value: str) -> Optional[int]:
    match = _XREF_NUM_RE.search(value or "")
    return int(match.group(1)) if match else None


def _clean_name(value: Optional[str]) -> str:
    if not value:
        return ""
    return value[1:] if value.startswith("/") else value


def _parse_differences(array_text: str) -> dict[int, str]:
    """Parse an ``/Encoding /Differences`` array into ``{code: glyph name}``."""
    result: dict[int, str] = {}
    current = 0
    for number, name in _DIFF_TOKEN_RE.findall(array_text or ""):
        if number:
            current = int(number)
        elif name:
            result[current] = name
            current += 1
    return result


def _load_differences(doc, xref: int) -> dict[int, str]:
    kind, value = _key(doc, xref, "Encoding")
    if kind == "xref":
        enc_xref = _first_xref(value)
        if enc_xref is None:
            return {}
        sub_kind, sub_value = _key(doc, enc_xref, "Differences")
        if sub_kind == "array":
            return _parse_differences(sub_value)
        return {}
    if kind == "dict":
        match = re.search(r"/Differences\s*(\[.*?\])", value, re.S)
        if match:
            return _parse_differences(match.group(1))
    return {}


def _load_cid_to_gid(doc, descendant_xref: int) -> tuple[Optional[dict[int, int]], list[str]]:
    """Read ``/CIDToGIDMap``.  ``None`` means the identity mapping."""
    notes: list[str] = []
    kind, value = _key(doc, descendant_xref, "CIDToGIDMap")
    if kind == "name" or kind == "null":
        return None, notes
    if kind == "xref":
        stream_xref = _first_xref(value)
        if stream_xref is None:
            return None, notes
        try:
            raw = doc.xref_stream(stream_xref)
        except Exception as exc:
            notes.append(f"CIDToGIDMap stream {stream_xref} unreadable: {exc}")
            return None, notes
        mapping = {
            cid: int.from_bytes(raw[i:i + 2], "big")
            for cid, i in enumerate(range(0, len(raw) - 1, 2))
        }
        return mapping, notes
    return None, notes


def _codespace_width(codespace: Iterable[tuple[int, int, int]]) -> Optional[int]:
    widths = {length for length, _, _ in codespace}
    if len(widths) == 1:
        return widths.pop()
    return None


def resolve_font(doc, xref: int, resource_name: str = "") -> FontContext:
    """
    Build a :class:`FontContext` for the font at *xref* in *doc*.

    *doc* is a PyMuPDF document.  Every field is read from the document; a
    field that cannot be read stays at its default and the reason is
    appended to ``notes``.  This function never raises for a malformed
    font - a decoder tier is expected to report that it could not run.
    """
    ctx = FontContext(xref=xref, resource_name=resource_name)

    ctx.subtype = _clean_name(_key(doc, xref, "Subtype")[1])
    ctx.base_font = _clean_name(_key(doc, xref, "BaseFont")[1])

    enc_kind, enc_value = _key(doc, xref, "Encoding")
    if enc_kind == "name":
        ctx.encoding_name = _clean_name(enc_value)
    elif enc_kind in ("dict", "xref"):
        ctx.encoding_name = "(dictionary)"
    ctx.is_identity = bool(ctx.encoding_name) and ctx.encoding_name.startswith("Identity")

    is_composite = ctx.subtype == "Type0"
    if is_composite:
        desc_kind, desc_value = _key(doc, xref, "DescendantFonts")
        if desc_kind in ("array", "xref"):
            ctx.descendant_xref = _first_xref(desc_value)
        if ctx.descendant_xref is not None:
            ctx.cid_to_gid, notes = _load_cid_to_gid(doc, ctx.descendant_xref)
            ctx.notes.extend(notes)
    else:
        ctx.differences = _load_differences(doc, xref)

    # --- ToUnicode -------------------------------------------------------
    tu_kind, tu_value = _key(doc, xref, "ToUnicode")
    if tu_kind == "xref":
        ctx.tounicode_xref = _first_xref(tu_value)
        if ctx.tounicode_xref is not None:
            try:
                cmap = parse_tounicode_cmap(doc.xref_stream(ctx.tounicode_xref))
                ctx.tounicode = cmap.mapping
                ctx.tounicode_entries = cmap.entry_count
                ctx.codespace = cmap.codespace
            except Exception as exc:
                ctx.notes.append(
                    f"ToUnicode stream {ctx.tounicode_xref} unreadable: {exc}")

    # --- Code width ------------------------------------------------------
    width = _codespace_width(ctx.codespace)
    if width in (1, 2, 3, 4):
        ctx.code_byte_width = width
        ctx.code_width_source = "codespacerange"
    elif ctx.is_identity:
        ctx.code_byte_width = 2
        ctx.code_width_source = "identity"
    elif is_composite:
        ctx.code_byte_width = 2
        ctx.code_width_source = "assumed"
        ctx.notes.append(
            "Composite font without a readable codespace range; assumed 2-byte codes.")
    else:
        ctx.code_byte_width = 1
        ctx.code_width_source = "assumed"

    # --- Embedded font program ------------------------------------------
    try:
        _name, ext, _ftype, buffer = doc.extract_font(xref)
        if buffer:
            ctx.font_program = bytes(buffer)
            ctx.font_ext = (ext or "").lower() or None
            ctx.font_sha256 = hashlib.sha256(ctx.font_program).hexdigest()
            ctx.is_embedded = True
    except Exception as exc:
        ctx.notes.append(f"Font program not extractable: {exc}")

    if ctx.font_program:
        ctx.glyph_names, ctx.glyph_name_source = embedded_glyph_names(
            ctx.font_program, ctx.font_ext)

    return ctx


def split_codes(data: bytes, ctx: FontContext) -> list[int]:
    """
    Split a raw string operand into character codes.

    Uses the declared codespace ranges when they are unambiguous, otherwise
    the fixed width recorded on the context.  Codes are returned in document
    order so a caller can align them with decoded characters.
    """
    if not data:
        return []

    widths = sorted({length for length, _, _ in ctx.codespace})
    if len(widths) > 1:
        codes: list[int] = []
        pos = 0
        while pos < len(data):
            for width in widths:
                if pos + width > len(data):
                    continue
                value = int.from_bytes(data[pos:pos + width], "big")
                if any(length == width and low <= value <= high
                       for length, low, high in ctx.codespace):
                    codes.append(value)
                    pos += width
                    break
            else:
                # No codespace range matches; consume the narrowest width so
                # the scan terminates, and let the tiers report the gap.
                width = widths[0]
                codes.append(int.from_bytes(data[pos:pos + width], "big"))
                pos += width
        return codes

    width = ctx.code_byte_width
    return [
        int.from_bytes(data[i:i + width], "big")
        for i in range(0, len(data) - width + 1, width)
    ]
