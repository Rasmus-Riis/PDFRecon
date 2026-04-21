"""
Scanner Module: PDF discovery, processing, and forensic analysis.

Handles:
- Finding PDF files in directory trees
- Processing individual PDF files with hang prevention
- Detecting forensic indicators of alteration
- Analyzing font subsets for subsetting conflicts
- Extracting PDF revisions from %%EOF markers
"""

import logging
import time
import os
import re
import difflib
import hashlib
from pathlib import Path
from typing import Any
from concurrent.futures import ThreadPoolExecutor, as_completed

import fitz

from .config import (
    PDFReconConfig, PDFProcessingError, PDFCorruptionError, 
    PDFTooLargeError, PDFEncryptedError,
    LAYER_OCGS_BLOCK_RE, OBJ_REF_RE, LAYER_OC_REF_RE
)
from .pdf_processor import safe_pdf_open, safe_extract_text, validate_pdf_file, count_layers
from .utils import md5_file
from .xmp_relationship import XMPRelationshipManager
from .advanced_forensics import run_advanced_forensics


def find_pdf_files_generator(folder_path):
    """
    Generator that yields PDF file paths found in a directory tree.
    
    Args:
        folder_path (str or Path): Root folder to search for PDFs
        
    Yields:
        Path: Absolute path to each PDF file found
    """
    for base, _, files in os.walk(folder_path):
        for file in files:
            if file.lower().endswith('.pdf'):
                yield Path(base) / file


def extract_revisions(raw: bytes, original_path: Path):
    """
    Extracts revision PDFs from a PDF file by finding %%EOF markers.
    
    A PDF revision is appended after %%EOF, creating an incremental update.
    This function finds all %%EOF markers and extracts the bytes after each one.
    
    Args:
        raw (bytes): Raw PDF file content
        original_path (Path): Path to the original PDF (for logging)
        
    Returns:
        list: List of tuples (rev_path, original_name, content_bytes) for each revision found
    """
    revisions = []
    offsets = []
    pos = len(raw)
    
    # Find all '%%EOF' markers from the end of the file backwards
    while (pos := raw.rfind(b"%%EOF", 0, pos)) != -1:
        offsets.append(pos)
    
    # A typical final %%EOF is very close to the end of the file.
    # We want to keep all %%EOF markers EXCEPT the very last one (which corresponds to the final, current version).
    # Sort offsets so the largest (closest to end of file) is last.
    sorted_offsets = sorted(offsets)
    
    # Remove the last offset if it's the actual end of the file (or very close to it)
    if sorted_offsets and sorted_offsets[-1] > len(raw) - 100:
        sorted_offsets.pop()
        
    # Filter out invalid or unlikely offsets (e.g., too small to be a valid PDF)
    # Lowered minimum from 1000 to 500 to catch small test PDFs
    valid_offsets = [o for o in sorted_offsets if o >= 500]
    
    if valid_offsets:
        # Define subdirectory for potential revisions
        altered_dir = original_path.parent / "Altered_files"
        if not altered_dir.exists():
            altered_dir.mkdir(parents=True, exist_ok=True)
        
        for offset in valid_offsets:
            # The revision is the content from the start to the EOF marker
            # Add 5 bytes to include the '%%EOF' itself
            rev_bytes = raw[:offset + 5]
            
            # Check if this revision can actually be opened by PyMuPDF
            is_valid = False
            try:
                # Try to open the raw bytes as a PDF
                test_doc = fitz.open(stream=rev_bytes, filetype="pdf")
                if len(test_doc) > 0:
                    is_valid = True
                test_doc.close()
            except Exception:
                is_valid = False
                
            if is_valid:
                rev_idx = len(revisions) + 1
                rev_filename = f"{original_path.stem}_rev{rev_idx}_@{offset}.pdf"
                rev_path = altered_dir / rev_filename
                rev_path.write_bytes(rev_bytes)
                revisions.append((rev_path, original_path.name, rev_bytes))
                logging.info(f"Found valid revision {rev_idx} in {original_path.name}: {len(rev_bytes)} bytes")
            else:
                logging.debug(f"Skipped unrenderable revision at offset {offset} in {original_path.name}")
    
    return revisions


def detect_indicators(filepath: Path, txt: str, doc, exif_output: str = "", app_instance=None):
    """
    Detects forensic indicators of PDF alteration.
    
    Analyzes the PDF for signs of editing including:
    - TouchUp text edits
    - Multiple creators/producers
    - XMP metadata anomalies
    - Font subset conflicts
    - Digital signatures
    - Incremental updates
    - Form fields and redactions
    - Content stream anomalies
    - Object reference integrity
    - Image forensics
    - JavaScript detection
    - Structural anomalies
    
    Args:
        filepath (Path): Path to the PDF file
        txt (str): Extracted text content from PDF
        doc: PyMuPDF document object
        exif_output (str): EXIF output (optional)
        app_instance: PDFReconApp instance (for callbacks, optional)
        
    Returns:
        dict: Dictionary of detected indicators with details
    """
    indicators: dict[str, Any] = {}

    try:
        # PERFORMANCE OPTIMIZATION (Bolt ⚡):
        # Caching `txt.lower()` allows us to use fast 'in' substring checks to
        # bypass expensive case-insensitive regex (re.I) scans on large PDF text.
        txt_lower = txt.lower()

        # --- High-Confidence Indicators ---
        if "touchup_textedit" in txt_lower and re.search(r"touchup_textedit", txt, re.I):
            found_text = None
            if app_instance and hasattr(app_instance, '_extract_touchup_text'):
                try:
                    found_text = app_instance._extract_touchup_text(doc)
                except Exception as e:
                    logging.warning(f"Error extracting TouchUp text: {e}")
            
            details = {'found_text': found_text, 'text_diff': None}
            
            # Try to extract TouchUp text and compute diff if revisions exist
            if doc and hasattr(doc, 'write') and app_instance:
                try:
                    if hasattr(app_instance, 'extract_revisions'):
                        revisions = app_instance.extract_revisions(doc.write(), filepath)
                    else:
                        revisions = extract_revisions(doc.write(), filepath)
                        
                    if revisions and hasattr(app_instance, '_get_text_for_comparison'):
                        latest_rev_path, _, latest_rev_bytes = revisions[0]
                        logging.info(f"TouchUp found with revisions. Performing text diff for {filepath.name}.")
                        
                        original_text = app_instance._get_text_for_comparison(filepath)
                        revision_text = app_instance._get_text_for_comparison(latest_rev_bytes)

                        if original_text and revision_text:
                            diff = difflib.unified_diff(
                                revision_text.splitlines(keepends=True),
                                original_text.splitlines(keepends=True),
                                fromfile='Previous Version',
                                tofile='Final Version',
                            )
                            details['text_diff'] = list(diff)
                except Exception as e:
                    logging.warning(f"Could not compute text diff for TouchUp indicator: {e}")
            
            indicators['TouchUp_TextEdit'] = details

        # --- Metadata Indicators ---
        creators = set()
        if "/creator" in txt_lower:
            creators = set(re.findall(r"/Creator\s*\((.*?)\)", txt, re.I))
            if len(creators) > 1:
                indicators['MultipleCreators'] = {'count': len(creators), 'values': list(creators)}
        
        producers = set()
        if "/producer" in txt_lower:
            producers = set(re.findall(r"/Producer\s*\((.*?)\)", txt, re.I))
            if len(producers) > 1:
                indicators['MultipleProducers'] = {'count': len(producers), 'values': list(producers)}

        if "<xmpmm:history>" in txt_lower and re.search(r'<xmpMM:History>', txt, re.I | re.S):
            indicators['XMPHistory'] = {}
            
        # NEW: Check for creator/producer mismatch with PDF features
        _detect_metadata_inconsistencies(txt, txt_lower, doc, indicators)

        # --- Structural and Content Indicators ---
        try:
            conflicting_fonts = analyze_fonts(filepath, doc)
            if conflicting_fonts:
                indicators['MultipleFontSubsets'] = {'fonts': conflicting_fonts}
            
            # Detect Malicious Font Character Remapping
            _detect_font_remapping(doc, indicators)
        except Exception as e:
            logging.error(f"Error analyzing fonts for {filepath.name}: {e}")

        if (hasattr(doc, 'is_xfa') and doc.is_xfa) or "/xfa" in txt_lower or "/XFA" in txt:
            indicators['HasXFAForm'] = {}

        if "/type" in txt_lower and "/sig" in txt_lower:
            if re.search(r"/Type\s*/Sig\b", txt):
                indicators['HasDigitalSignature'] = {}

        # --- Incremental Update Indicators ---
        startxrefs = [m.start() for m in re.finditer(r"startxref", txt_lower)]
        if len(startxrefs) > 1:
            indicators['MultipleStartxref'] = {'count': len(startxrefs), 'offsets': startxrefs}
        
        prevs = []
        if "/prev" in txt_lower:
            prevs = re.findall(r"/Prev\s+\d+", txt)
            if prevs:
                indicators['IncrementalUpdates'] = {'count': len(prevs) + 1}
        
        if "/linearized" in txt_lower:
            if re.search(r"/Linearized\s+\d+", txt):
                indicators['Linearized'] = {}
        
        if 'Linearized' in indicators and (len(startxrefs) > 1 or prevs):
            indicators['LinearizedUpdated'] = {}

        # --- Feature Indicators ---
        if "/redact" in txt_lower and re.search(r"/Redact\b", txt, re.I):
            indicators['HasRedactions'] = {}
        if "/annots" in txt_lower and re.search(r"/Annots\b", txt, re.I):
            if doc:
                annot_types = set()
                annot_count = 0
                for page in doc:
                    for annot in page.annots():
                        annot_count += 1
                        if annot.type and len(annot.type) > 1:
                            annot_types.add(annot.type[1])
                # Only add if count > 0, otherwise it might be a false positive /Annots dictionary
                if annot_count > 0:
                    indicators['HasAnnotations'] = {
                        'count': annot_count,
                        'types': sorted(list(annot_types))
                    }
            else:
                indicators['HasAnnotations'] = {}
        if "/pieceinfo" in txt_lower and re.search(r"/PieceInfo\b", txt, re.I):
            indicators['HasPieceInfo'] = {}
        if "/acroform" in txt_lower and re.search(r"/AcroForm\b", txt, re.I):
            indicators['HasAcroForm'] = {}
            if "needappearances" in txt_lower and re.search(r"/NeedAppearances\s+true\b", txt, re.I):
                indicators['AcroFormNeedAppearances'] = {}

        # PERFORMANCE OPTIMIZATION (Bolt ⚡): List comprehension with findall is faster
        gen_gt_zero_matches = [m for m in re.findall(r"\b(\d+)\s+(\d+)\s+obj\b", txt) if int(m[1]) > 0]
        if gen_gt_zero_matches:
            indicators['ObjGenGtZero'] = {'count': len(gen_gt_zero_matches)}

        # --- NEW: Advanced Detection Methods ---
        
        # Content stream anomalies
        _detect_content_stream_anomalies(txt, doc, indicators)
        
        # Object reference integrity
        _detect_object_anomalies(txt, doc, indicators)
        
        # JavaScript detection
        _detect_javascript(txt, indicators, txt_lower)
        
        # Structural anomalies
        if doc:
            _detect_structural_anomalies(doc, indicators)
        
        # Bookmark tampering
        if doc:
            _detect_bookmark_anomalies(doc, indicators)
        
        # --- Advanced Forensics (v1.3+) ---
        run_advanced_forensics(txt, doc, filepath, indicators)

        # --- ID Comparison ---
        def _norm_uuid(x):
            if x is None: 
                return None
            s = str(x).strip().upper()
            if s.startswith("URN:UUID:"):
                s = s[9:]
            elif s.startswith("UUID:"):
                s = s[5:]
            elif s.startswith("XMP.IID:"):
                s = s[8:]
            elif s.startswith("XMP.DID:"):
                s = s[8:]
            return s.strip("<>")

        xmp_orig_match = re.search(r"xmpMM:OriginalDocumentID(?:>|=\")([^<\"]+)", txt, re.I) if "xmpmm:originaldocumentid" in txt_lower else None
        xmp_doc_match = re.search(r"xmpMM:DocumentID(?:>|=\")([^<\"]+)", txt, re.I) if "xmpmm:documentid" in txt_lower else None
        
        xmp_orig = _norm_uuid(xmp_orig_match.group(1) if xmp_orig_match else None)
        xmp_doc = _norm_uuid(xmp_doc_match.group(1) if xmp_doc_match else None)
        
        if xmp_orig and xmp_doc and xmp_doc != xmp_orig:
            indicators['XMPIDChange'] = {'from': xmp_orig, 'to': xmp_doc}

        # --- Asset Relationship Forensics (v1.4+) ---
        # Look for XMP packet in the txt string (extract_text adds it)
        xmp_packet_match = re.search(r'<\?xpacket begin=.*?\?>(.*?)\<\?xpacket end=[^>]*\?\>', txt, re.S)
        if xmp_packet_match:
            xmp_str = xmp_packet_match.group(0)
            if app_instance and hasattr(app_instance, '_extract_xmp_relationships'):
                # Use the app instance if available (it handles indicator integration)
                app_instance._extract_xmp_relationships(xmp_str, indicators)
            else:
                # Fallback for worker processes or standalone use
                manager = XMPRelationshipManager()
                rel_data = manager.parse_xmp(xmp_str)
                if rel_data.get('derivation') or rel_data.get('ingredients') or rel_data.get('pantry'):
                    indicators['AssetRelationship'] = rel_data
                    # Add to RelatedFiles if not present
                    if 'RelatedFiles' not in indicators:
                        indicators['RelatedFiles'] = {'count': 0, 'files': []}
                    
                    # Add derivation to RelatedFiles
                    derivation = rel_data.get('derivation')
                    if isinstance(derivation, dict):
                        doc_id = derivation.get('documentID')
                        if doc_id and not any(f.get('id') == doc_id for f in indicators['RelatedFiles']['files']):
                            short_id = str(doc_id)[:8]
                            indicators['RelatedFiles']['files'].append({
                                'type': 'derived_from',
                                'name': f"ID: {short_id}...",
                                'id': doc_id
                            })
                            indicators['RelatedFiles']['count'] += 1

        trailer_match = re.search(r"/ID\s*\[\s*<\s*([0-9A-Fa-f]+)\s*>\s*<\s*([0-9A-Fa-f]+)\s*>\s*\]", txt)
        if trailer_match:
            trailer_orig, trailer_curr = _norm_uuid(trailer_match.group(1)), _norm_uuid(trailer_match.group(2))
            if trailer_orig and trailer_curr and trailer_curr != trailer_orig:
                indicators['TrailerIDChange'] = {'from': trailer_orig, 'to': trailer_curr}
        
        # --- Date Mismatch ---
        info_dates = dict(re.findall(r"/(ModDate|CreationDate)\s*\(\s*D:(\d{8,14})", txt))
        xmp_dates = {k: v for k, v in re.findall(r"<xmp:(ModifyDate|CreateDate)>([^<]+)</xmp:\1>", txt)}

        def _short(d: str) -> str: 
            return d.replace("-", "").replace(":", "").replace("T", "").replace("Z", "")[:14]

        if "CreationDate" in info_dates and "CreateDate" in xmp_dates and _short(info_dates["CreationDate"]) != _short(xmp_dates["CreateDate"]):
            indicators['CreateDateMismatch'] = {'info': info_dates["CreationDate"], 'xmp': xmp_dates["CreateDate"]}
        if "ModDate" in info_dates and "ModifyDate" in xmp_dates and _short(info_dates["ModDate"]) != _short(xmp_dates["ModifyDate"]):
            indicators['ModifyDateMismatch'] = {'info': info_dates["ModDate"], 'xmp': xmp_dates["ModifyDate"]}
        
        logging.info(f"Indicator detection completed for {filepath.name}: {len(indicators)} indicators found")
        
    except Exception as e:
        logging.warning(f"Error during indicator detection for {filepath.name}: {e}")
    
    return indicators


def analyze_fonts(filepath: Path, doc):
    """
    Analyzes fonts in the PDF to detect multiple subsets of the same font STYLE.
    
    IMPORTANT: Multiple subsets are ONLY suspicious when they're the same style:
    - SUSPICIOUS: AAAAAA+Arial-Regular AND BBBBBB+Arial-Regular (same style, different subsets)
    - NORMAL: AAAAAA+Arial-Bold AND BBBBBB+Arial-Regular (different styles = expected)
    
    Args:
        filepath (Path): Path to the PDF file (for logging)
        doc: PyMuPDF document object
        
    Returns:
        dict: Dictionary of base fonts with their conflicting subsets OF THE SAME STYLE.
              Example: {'Arial-Regular': ['ABC+Arial-Regular', 'DEF+Arial-Regular']}
    """
    font_subsets = {}
    
    try:
        # Iterate through xrefs instead of pages to find fonts.
        # This avoids O(N) page iteration and parsing, which is slow for large docs.
        for xref in range(1, doc.xref_length()):
            try:
                if doc.xref_is_font(xref):
                    res = doc.xref_get_key(xref, "BaseFont")
                    if res[0] == "name":
                        basefont_name = res[1]
                        # PDF names usually start with /, strip it
                        if basefont_name.startswith("/"):
                            basefont_name = basefont_name[1:]

                        # Decode PDF name (e.g. #20 -> space)
                        if "#" in basefont_name:
                            parts = basefont_name.split("#")
                            decoded_name = parts[0]
                            for part in parts[1:]:
                                if len(part) >= 2:
                                    try:
                                        decoded_name += chr(int(part[:2], 16)) + part[2:]
                                    except ValueError:
                                        decoded_name += "#" + part
                                else:
                                    decoded_name += "#" + part
                            basefont_name = decoded_name

                        if "+" in basefont_name:
                            try:
                                subset_prefix, full_font_name = basefont_name.split("+", 1)
                                if full_font_name not in font_subsets:
                                    font_subsets[full_font_name] = set()
                                font_subsets[full_font_name].add(basefont_name)
                            except ValueError:
                                continue
            except Exception as inner_e:
                logging.warning(f"Skipping problematic font xref {xref} in {filepath.name}: {inner_e}")
                continue
    except Exception as e:
        # If we hit a major error here, log it as a warning and return what we have
        logging.warning(f"Error during font analysis for {filepath.name}: {e}")
        return {}
    
    # Filter for only those font STYLES that have multiple subsets
    # This now correctly identifies: AAAAAA+Arial-Regular + BBBBBB+Arial-Regular (suspicious)
    # But ignores: AAAAAA+Arial-Bold + BBBBBB+Arial-Regular (normal)
    conflicting_fonts = {style: list(subsets) for style, subsets in font_subsets.items() if len(subsets) > 1}
    
    if conflicting_fonts:
        logging.info(f"Multiple font subsets of SAME STYLE found in {filepath.name}: {conflicting_fonts}")

    return conflicting_fonts


def _detect_font_remapping(doc, indicators: dict):
    """
    Inspects /ToUnicode CMap streams for suspicious character remapping.
    
    A common attack is to map a glyph to a completely different Unicode value
    (e.g., mapping the visual 'A' to Unicode 'B') so that text extraction
    yields different results than what is visually rendered.
    """
    try:
        font_remapping = []
        for xref in range(1, doc.xref_length()):
            if doc.xref_is_font(xref):
                tounicode_xref = doc.xref_get_key(xref, "ToUnicode")
                if tounicode_xref[0] == "xref":
                    unicode_xref = int(tounicode_xref[1].split()[0])
                    try:
                        cmap_bytes = doc.xref_stream(unicode_xref)
                        cmap_str = cmap_bytes.decode('latin-1', errors='ignore')
                        
                        # Look for suspicious mappings: e.g., <0041> <0042> (A to B)
                        # This is a simplified check for obvious remapping patterns
                        # bfchar mappings look like: <01> <0041>
                        bfchar_matches = re.findall(r'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', cmap_str)
                        for src, dst in bfchar_matches:
                            src_val = int(src, 16)
                            dst_val = int(dst, 16)
                            
                            font_name = doc.xref_get_key(xref, "BaseFont")[1]
                            # Exclude subset fonts (prefix XXXXXX+) because they use custom
                            # glyph indices, meaning 0x20 is just an index (32nd character used)
                            # and not the ASCII space character.
                            if re.match(r'^/[A-Z]{6}\+', font_name):
                                continue
                                
                            # If src is a standard ASCII but dst is different and not a common variation
                            if 32 <= src_val <= 126 and src_val != dst_val:
                                font_remapping.append({
                                    'font': font_name,
                                    'from_hex': src,
                                    'to_unicode': chr(dst_val) if 32 <= dst_val <= 126 else f"U+{dst:04}"
                                })
                                break # Found one, that's enough for this font
                    except Exception:
                        continue
        
        if font_remapping:
            indicators['FontCharacterRemapping'] = {
                'count': len(font_remapping),
                'details': font_remapping[:5]
            }
    except Exception as e:
        logging.debug(f"Error detecting font remapping: {e}")


def _detect_metadata_inconsistencies(txt: str, txt_lower: str, doc, indicators: dict):
    """
    Detects inconsistencies between metadata claims and actual PDF features.
    
    Args:
        txt (str): Raw PDF content as text
        txt_lower (str): Lowercased raw PDF content for fast checks
        doc: PyMuPDF document object
        indicators (dict): Dictionary to add indicators to
    """
    try:
        # Check if metadata claims a specific creator but features suggest otherwise
        creator_match = None
        producer_match = None
        if "/creator" in txt_lower:
            creator_match = re.search(r"/Creator\s*\((.*?)\)", txt, re.I)
        if "/producer" in txt_lower:
            producer_match = re.search(r"/Producer\s*\((.*?)\)", txt, re.I)
        
        if creator_match or producer_match:
            creator = creator_match.group(1) if creator_match else ""
            producer = producer_match.group(1) if producer_match else ""
            
            # Check for mismatches with actual PDF version
            if doc and hasattr(doc, 'pdf_version'):
                version_str = doc.pdf_version()  # e.g., "1.4"
                try:
                    version = float(version_str)
                except (ValueError, TypeError):
                    version = 1.4 # Default
                
                # If metadata claims old software but uses modern PDF features
                if (("Acrobat 4" in creator or "PDF 1.3" in txt) and version >= 1.7):
                    indicators['MetadataVersionMismatch'] = {
                        'claimed_version': 'Old (1.3-1.4)',
                        'actual_version': version_str
                    }

                # NEW: Specification Contradictions (Version vs Feature)
                contradictions = []
                if version < 1.5:
                    if "/ObjStm" in txt: contradictions.append("Object Streams (/ObjStm) require PDF 1.5+")
                    if "/XRef" in txt and "stream" in txt_lower: contradictions.append("XRef Streams require PDF 1.5+")
                    if "/OCG" in txt: contradictions.append("Optional Content Groups (/OCG) require PDF 1.5+")
                if version < 1.4:
                    if "/JBIG2Decode" in txt: contradictions.append("JBIG2Decode requires PDF 1.4+")
                    if "/Metadata" in txt: contradictions.append("Metadata streams require PDF 1.4+")
                
                if contradictions:
                    indicators['VersionFeatureContradiction'] = {
                        'version': version_str,
                        'contradictions': contradictions
                    }

    except Exception as e:
        logging.debug(f"Error detecting metadata inconsistencies: {e}")


def _detect_content_stream_anomalies(txt: str, doc, indicators: dict):
    """
    Detects suspicious patterns in PDF content streams.
    
    Args:
        txt (str): Raw PDF content as text
        doc: PyMuPDF document object
        indicators (dict): Dictionary to add indicators to
    """
    try:
        # Detect text positioning operations that might overlay content
        # PERFORMANCE OPTIMIZATION (Bolt ⚡): Fast substring pre-check avoids expensive regex
        if "Tm" in txt or "Td" in txt:
            # Multiple positioning commands in sequence (potential overlay)
            count = len(re.findall(r"(Tm|Td)\s+[^\n]*\s+(Tm|Td)", txt))
            if count > 5:  # Threshold for suspicious
                indicators['SuspiciousTextPositioning'] = {'count': count}
        
        # Detect white rectangles (common for hiding content)
        # PERFORMANCE OPTIMIZATION (Bolt ⚡): Fast substring pre-check avoids expensive regex
        if "rg" in txt and "re" in txt and "f" in txt:
            white_rect_pattern = r"/DeviceRGB\s+1\s+1\s+1\s+rg.*?re\s+f"
            white_rects = re.findall(white_rect_pattern, txt, re.DOTALL)
            if len(white_rects) > 3:
                indicators['WhiteRectangleOverlay'] = {'count': len(white_rects)}
        
        # Detect repeated drawing operations in the same area
        if doc and len(doc) > 0:
            try:
                for page_num in range(min(len(doc), 10)):  # Check first 10 pages
                    page = doc[page_num]
                    drawings = page.get_drawings()
                    if len(drawings) > 50:  # Unusually high number of drawing operations
                        indicators['ExcessiveDrawingOperations'] = {
                            'page': page_num + 1,
                            'count': len(drawings)
                        }
                        break
            except Exception as e:
                logging.debug(f"Error analyzing drawings: {e}")
                
    except Exception as e:
        logging.debug(f"Error detecting content stream anomalies: {e}")


def _detect_object_anomalies(txt: str, doc, indicators: dict):
    """
    Detects object reference integrity issues by comparing raw byte definitions against the XREF table.
    
    Args:
        txt (str): Raw PDF content as text
        doc: PyMuPDF document object
        indicators (dict): Dictionary to add indicators to
    """
    try:
        # PERFORMANCE OPTIMIZATION (Bolt ⚡): List comprehension with findall is implemented
        # in C and faster than python-level iteration with finditer

        # Find all object definitions
        obj_defs = {int(m) for m in re.findall(r"\b(\d+)\s+\d+\s+obj\b", txt)}
        
        # Find all object references
        obj_refs = {int(m) for m in re.findall(r"\b(\d+)\s+\d+\s+R\b", txt)}
        
        # Find orphaned objects (defined in body but unreferenced/deleted in XREF table)
        orphaned = set()
        if doc and hasattr(doc, 'xref_length'):
            for obj_id in obj_defs:
                try:
                    # If object is outside XREF bounds, or its XREF entry is marked free ("")
                    if obj_id >= doc.xref_length() or not doc.xref_object(obj_id):
                        orphaned.add(obj_id)
                except Exception:
                    orphaned.add(obj_id)
        else:
            orphaned = obj_defs - obj_refs
            
        if len(orphaned) > 0:
            indicators['OrphanedObjects'] = {
                'count': len(orphaned),
                'ids': sorted(list(orphaned))[:50]  # List specific IDs
            }
        
        # Find missing objects (Dangling References - referenced but deleted/missing from XREF)
        missing = set()
        if doc and hasattr(doc, 'xref_length'):
            # Only check references that point to objects higher than 0
            for obj_id in obj_refs:
                if obj_id == 0: continue
                try:
                    if obj_id >= doc.xref_length() or not doc.xref_object(obj_id):
                        missing.add(obj_id)
                except Exception:
                    missing.add(obj_id)
        else:
            missing = obj_refs - obj_defs
            
        if len(missing) > 0:
            indicators['MissingObjects'] = {
                'count': len(missing),
                'ids': sorted(list(missing))[:50]
            }
        
        # Detect suspicious object number gaps
        if obj_defs:
            max_obj = max(obj_defs)
            actual_count = len(obj_defs)
            # A gap is when max ID is much larger than the count of defined objects
            gap_count = max_obj - actual_count
            gap_ratio = gap_count / max_obj if max_obj > 0 else 0
            
            if gap_ratio > 0.1:  # Lowered threshold to 10% for reporting
                indicators['LargeObjectNumberGaps'] = {
                    'gap_percentage': f"{gap_ratio*100:.1f}%",
                    'max_object': max_obj,
                    'defined_objects_count': actual_count,
                    'gap_count': gap_count,
                    'note': "High gap suggests objects were deleted or hidden"
                }

        # NEW: Unbalanced obj/endobj Structures
        obj_count = len(re.findall(r"\b\d+\s+\d+\s+obj\b", txt))
        endobj_count = len(re.findall(r"\bendobj\b", txt))
        if obj_count != endobj_count:
            indicators['UnbalancedObjects'] = {
                'obj_count': obj_count,
                'endobj_count': endobj_count
            }

        # NEW: Duplicate Object IDs in Xref (Shadow Attacks)
        # Using a raw scan for multiple xref tables that redefine the same objects
        xref_sections = re.findall(r"xref\s*\n0\s+\d+\s*\n(.*?)(?=\btrailer\b|xref|$)", txt, re.DOTALL)
        if len(xref_sections) > 1:
            all_objects = []
            duplicates = set()
            for section in xref_sections:
                ids = re.findall(r"^(\d+)\s+\d+\s+[nf]\b", section, re.MULTILINE)
                for i in ids:
                    if i in all_objects:
                        duplicates.add(i)
                    all_objects.append(i)
            if duplicates:
                indicators['DuplicateObjectIDs'] = {
                    'count': len(duplicates),
                    'ids': sorted(list(duplicates))[:50],
                    'note': 'Detected duplicate object IDs across multiple XREF tables (Potential Shadow Attack)'
                }

    except Exception as e:
        logging.debug(f"Error detecting object anomalies: {e}")


def _detect_javascript(txt: str, indicators: dict, txt_lower: str = None):
    """
    Detects JavaScript code in PDFs which can hide malicious alterations,
    as well as phishing or local machine execution directives.
    
    Args:
        txt (str): Raw PDF content as text
        txt_lower (str): Lowercased raw PDF content for fast checks
        indicators (dict): Dictionary to add indicators to
        txt_lower (str, optional): Pre-computed lowercase text for fast substring checks
    """
    try:
        # PERFORMANCE OPTIMIZATION (Bolt ⚡):
        # Use fast substring check on cached lowercase text before expensive regex
        if txt_lower is None:
            txt_lower = txt.lower()

        # Check for JavaScript in the PDF
        js_matches = []
        if "/javascript" in txt_lower:
            js_matches = re.findall(r"/JavaScript\b", txt, re.I)
            if js_matches:
                indicators['ContainsJavaScript'] = {}
                
                # Check for OpenAction (auto-execute on open)
                if "/openaction" in txt_lower and re.search(r"/OpenAction\b", txt, re.I):
                    indicators['JavaScriptAutoExecute'] = {}
                
                # Check for AA (Additional Actions)
                if "/aa" in txt_lower and re.search(r"/AA\s*<<", txt, re.I):
                    indicators['AdditionalActions'] = {}
                
        # Try to count JavaScript actions
        js_count = len(js_matches)
        if js_count > 1:
            indicators['MultipleJavaScripts'] = {'count': js_count}
                
        # Explicit Phishing Directives
        submit_forms = re.findall(r"/SubmitForm\b", txt, re.I)
        if submit_forms:
            indicators['SubmitFormAction'] = {'count': len(submit_forms)}
            
        # Explicit Malicious / Shell Execution
        launch_actions = re.findall(r"/Launch\b", txt, re.I)
        if launch_actions:
            indicators['LaunchShellAction'] = {'count': len(launch_actions)}
            
    except Exception as e:
        logging.debug(f"Error detecting JavaScript or malicious directives: {e}")


def _detect_image_anomalies(doc, filepath: Path, indicators: dict):
    """
    Detects image-related forensic indicators.
    
    Args:
        doc: PyMuPDF document object
        filepath (Path): Path to PDF file
        indicators (dict): Dictionary to add indicators to
    """
    try:
        image_info = {}
        duplicate_check = {}
        image_cache = {}  # Cache to store processed image data: xref -> (hash, has_exif)

        for page_num in range(len(doc)):
            try:
                images = doc.get_page_images(page_num)
                for img_index, img in enumerate(images):
                    xref = img[0]  # Image xref number
                    
                    # Check cache first
                    if xref in image_cache:
                        img_hash, has_exif = image_cache[xref]
                    else:
                        # Extract image data
                        try:
                            # OPTIMIZATION: Use xref_stream_raw instead of extract_image for 1.5x-4x speedup
                            # extract_image parses and decodes the image dictionary, while xref_stream_raw
                            # simply grabs the raw bytes. For deduplication, raw byte comparison is identical.
                            img_bytes = doc.xref_stream_raw(xref)
                            img_hash = hashlib.md5(img_bytes, usedforsecurity=False).hexdigest()
                            has_exif = b"Exif" in img_bytes[:1000]
                            image_cache[xref] = (img_hash, has_exif)

                        except Exception as e:
                            logging.debug(f"Could not extract image {xref}: {e}")
                            continue

                    # Check for duplicate images with different compression
                    if img_hash in duplicate_check:
                        prev_xref = duplicate_check[img_hash]
                        if prev_xref != xref:
                            indicators['DuplicateImagesWithDifferentXrefs'] = {
                                'hash': img_hash,
                                'xrefs': [prev_xref, xref]
                            }
                    else:
                        duplicate_check[img_hash] = xref
                        
                    # Check if image has EXIF data
                    if has_exif:
                        if 'ImagesWithEXIF' not in indicators:
                            indicators['ImagesWithEXIF'] = {'count': 0}
                        indicators['ImagesWithEXIF']['count'] += 1

            except Exception as e:
                logging.debug(f"Error analyzing images on page {page_num}: {e}")
                continue
                
    except Exception as e:
        logging.debug(f"Error in image forensics: {e}")


def _detect_structural_anomalies(doc, indicators: dict):
    """
    Detects structural anomalies in the PDF.
    
    Args:
        doc: PyMuPDF document object
        indicators (dict): Dictionary to add indicators to
    """
    try:
        # Check for MediaBox/CropBox mismatches
        for page_num in range(len(doc)):
            try:
                page = doc[page_num]
                mediabox = page.mediabox
                cropbox = page.cropbox
                
                # If cropbox differs significantly from mediabox, content may be hidden
                if cropbox and mediabox:
                    mb_area = (mediabox[2] - mediabox[0]) * (mediabox[3] - mediabox[1])
                    cb_area = (cropbox[2] - cropbox[0]) * (cropbox[3] - cropbox[1])
                    
                    if mb_area > 0 and cb_area > 0:
                        ratio = cb_area / mb_area
                        if ratio < 0.8:  # CropBox is significantly smaller
                            indicators['CropBoxMediaBoxMismatch'] = {
                                'page': page_num + 1,
                                'visible_ratio': f"{ratio*100:.1f}%"
                            }
                            break
                            
            except Exception as e:
                logging.debug(f"Error checking page {page_num} boxes: {e}")
                continue
        
        # Check for form field anomalies
        try:
            if hasattr(doc, 'is_form_pdf') and doc.is_form_pdf:
                # Count form fields
                field_count = 0
                for page in doc:
                    widgets = page.widgets()
                    field_count += len(list(widgets)) if widgets else 0
                
                if field_count > 50:  # Unusually high number of form fields
                    indicators['ExcessiveFormFields'] = {'count': field_count}
                
                # NEW: Form Field Discrepancies (/V vs /BBox used in Overlay Attacks)
                overlay_fields = []
                for page in doc:
                    for widget in page.widgets():
                        val = widget.field_value
                        rect = widget.rect
                        # If field has a value but rect is invisible or extremely small
                        if val and (rect.width < 1 or rect.height < 1):
                            overlay_fields.append({
                                'page': page.number + 1,
                                'field': widget.field_name,
                                'value': str(val)[:30] + "..." if len(str(val)) > 30 else str(val),
                                'rect': [round(x, 1) for x in rect]
                            })
                if overlay_fields:
                    indicators['FormFieldOverlay'] = {
                        'count': len(overlay_fields),
                        'details': overlay_fields[:10]
                    }
                    
        except Exception as e:
            logging.debug(f"Error analyzing form fields: {e}")
            
    except Exception as e:
        logging.debug(f"Error detecting structural anomalies: {e}")


def _detect_bookmark_anomalies(doc, indicators: dict):
    """
    Detects bookmark/outline tampering.
    
    Args:
        doc: PyMuPDF document object
        indicators (dict): Dictionary to add indicators to
    """
    try:
        toc = doc.get_toc()
        if toc and len(toc) > 0:
            # Check for suspicious bookmark patterns
            bookmark_titles = [item[1] for item in toc]
            
            # Check for duplicate bookmark titles (potential tampering)
            unique_titles = set(bookmark_titles)
            if len(bookmark_titles) != len(unique_titles):
                duplicate_count = len(bookmark_titles) - len(unique_titles)
                indicators['DuplicateBookmarks'] = {'count': duplicate_count}
            
            # Check if bookmarks point to non-existent pages
            page_count = len(doc)
            for item in toc:
                level, title, page_num = item[0], item[1], item[2]
                if page_num > page_count or page_num < 1:
                    indicators['InvalidBookmarkDestinations'] = {
                        'bookmark': title,
                        'target_page': page_num,
                        'max_page': page_count
                    }
                    break
                    
    except Exception as e:
        logging.debug(f"Error detecting bookmark anomalies: {e}")


# NOTE: The following large methods remain in PDFReconApp for now and should be
# extracted into this module during Phase 5 completion:
# - _process_single_file() - Process a single PDF file
# - _scan_worker_parallel() - Parallel scan with timeout protection
# - generate_comprehensive_timeline() - Timeline generation
# - _parse_exif_data() - Parse EXIF metadata
# - _parse_exiftool_timeline() - Parse timeline from EXIF
# - _parse_raw_content_timeline() - Parse timeline from raw PDF content
# - extract_additional_xmp_ids() - Extract XMP identifiers
# - _process_and_validate_revisions() - Validate and process revision PDFs
# 
# These will be moved in subsequent refactoring passes to complete Phase 5.
