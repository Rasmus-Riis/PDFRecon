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
import subprocess
import sys
import shutil
import tempfile
import base64
import binascii
import zlib
import queue
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import fitz
except ImportError:
    fitz = None

try:
    from PIL import Image, ImageChops
except ImportError:
    Image = None
    ImageChops = None

from .config import (
    PDFReconConfig, PDFProcessingError, PDFCorruptionError, 
    PDFTooLargeError, PDFEncryptedError,
    LAYER_OCGS_BLOCK_RE, OBJ_REF_RE, LAYER_OC_REF_RE
)
from .pdf_processor import safe_pdf_open, safe_extract_text, validate_pdf_file, count_layers
from .utils import md5_file, resolve_path
from .advanced_forensics import run_advanced_forensics

# --- Regex Patterns ---
_PDF_DATE_PATTERN = re.compile(r"\/([A-Z][a-zA-Z0-9_]+)\s*\(\s*D:(\d{14})")
_KV_PATTERN = re.compile(r'^\[(?P<group>[^\]]+)\]\s*(?P<tag>[\w\-/ ]+?)\s*:\s*(?P<value>.+)$')
_DATE_TZ_PATTERN = re.compile(r"^(?P<date>\d{4}[-:]\d{2}[-:]\d{2}[ T]\d{2}:\d{2}:\d{2})(?:\.\d+)?(?P<tz>[+\-]\d{2}:\d{2}|Z)?")
_SOFTWARE_TOKENS = re.compile(
    r"(adobe|acrobat|billy|businesscentral|cairo|canva|chrome|chromium|clibpdf|dinero|dynamics|economic|edge|eboks|excel|firefox|"
    r"formpipe|foxit|fpdf|framemaker|ghostscript|illustrator|indesign|ilovepdf|itext|"
    r"kmd|lasernet|latex|libreoffice|microsoft|navision|netcompany|nitro|office|openoffice|pdflatex|pdf24|photoshop|powerpoint|prince|"
    r"quartz|reportlab|safari|skia|tcpdf|tex|visma|word|wkhtml|wkhtmltopdf|xetex)",
    re.IGNORECASE
)


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
    
    # Filter out invalid or unlikely offsets (revisions should be reasonable in size)
    valid_offsets = [o for o in sorted(offsets) if 1000 <= o <= len(raw) - 500]
    
    if valid_offsets:
        # Define subdirectory for potential revisions
        altered_dir = original_path.parent / "Altered_files"
        
        for i, offset in enumerate(valid_offsets, start=1):
            # The revision is the content from the start to the EOF marker
            rev_bytes = raw[:offset + 5]
            rev_filename = f"{original_path.stem}_rev{i}_@{offset}.pdf"
            rev_path = altered_dir / rev_filename
            revisions.append((rev_path, original_path.name, rev_bytes))
            logging.info(f"Found revision {i} in {original_path.name}: {len(rev_bytes)} bytes")
    
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
    indicators = {}

    try:
        # --- High-Confidence Indicators ---
        if re.search(r"touchup_textedit", txt, re.I):
            found_text = extract_touchup_text(doc)
            details = {'found_text': found_text, 'text_diff': None}
            
            # Try to extract TouchUp text and compute diff if revisions exist
            if doc and hasattr(doc, 'write'):
                try:
                    revisions = extract_revisions(doc.write(), filepath)
                    if revisions:
                        latest_rev_path, _, latest_rev_bytes = revisions[0]
                        logging.info(f"TouchUp found with revisions. Performing text diff for {filepath.name}.")
                        
                        original_text = get_text_for_comparison(filepath)
                        revision_text = get_text_for_comparison(latest_rev_bytes)

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
        creators = set(re.findall(r"/Creator\s*\((.*?)\)", txt, re.I))
        if len(creators) > 1:
            indicators['MultipleCreators'] = {'count': len(creators), 'values': list(creators)}
        
        producers = set(re.findall(r"/Producer\s*\((.*?)\)", txt, re.I))
        if len(producers) > 1:
            indicators['MultipleProducers'] = {'count': len(producers), 'values': list(producers)}

        if re.search(r'<xmpMM:History>', txt, re.I | re.S):
            indicators['XMPHistory'] = {}
            
        # NEW: Check for creator/producer mismatch with PDF features
        _detect_metadata_inconsistencies(txt, doc, indicators)

        # --- Structural and Content Indicators ---
        try:
            conflicting_fonts = analyze_fonts(filepath, doc)
            if conflicting_fonts:
                indicators['MultipleFontSubsets'] = {'fonts': conflicting_fonts}
        except Exception as e:
            logging.error(f"Error analyzing fonts for {filepath.name}: {e}")

        if (hasattr(doc, 'is_xfa') and doc.is_xfa) or "/XFA" in txt:
            indicators['HasXFAForm'] = {}

        if re.search(r"/Type\s*/Sig\b", txt):
            indicators['HasDigitalSignature'] = {}

        # --- Incremental Update Indicators ---
        startxref_count = txt.lower().count("startxref")
        if startxref_count > 1:
            indicators['MultipleStartxref'] = {'count': startxref_count}
        
        prevs = re.findall(r"/Prev\s+\d+", txt)
        if prevs:
            indicators['IncrementalUpdates'] = {'count': len(prevs) + 1}
        
        if re.search(r"/Linearized\s+\d+", txt):
            indicators['Linearized'] = {}
            if startxref_count > 1 or prevs:
                indicators['LinearizedUpdated'] = {}

        # --- Feature Indicators ---
        if re.search(r"/Redact\b", txt, re.I): 
            indicators['HasRedactions'] = {}
        if re.search(r"/Annots\b", txt, re.I): 
            indicators['HasAnnotations'] = {}
        if re.search(r"/PieceInfo\b", txt, re.I): 
            indicators['HasPieceInfo'] = {}
        if re.search(r"/AcroForm\b", txt, re.I):
            indicators['HasAcroForm'] = {}
            if re.search(r"/NeedAppearances\s+true\b", txt, re.I):
                indicators['AcroFormNeedAppearances'] = {}

        gen_gt_zero_matches = [m for m in re.finditer(r"\b(\d+)\s+(\d+)\s+obj\b", txt) if int(m.group(2)) > 0]
        if gen_gt_zero_matches:
            indicators['ObjGenGtZero'] = {'count': len(gen_gt_zero_matches)}

        # --- NEW: Advanced Detection Methods ---
        
        # Content stream anomalies
        _detect_content_stream_anomalies(txt, doc, indicators)
        
        # Object reference integrity
        _detect_object_anomalies(txt, indicators)
        
        # JavaScript detection
        _detect_javascript(txt, indicators)
        
        # Image forensics
        if doc:
            _detect_image_anomalies(doc, filepath, indicators)
        
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
            return re.sub(r"^(URN:UUID:|UUID:|XMP\.IID:|XMP\.DID:)", "", s).strip("<>")

        xmp_orig_match = re.search(r"xmpMM:OriginalDocumentID(?:>|=\")([^<\"]+)", txt, re.I)
        xmp_doc_match = re.search(r"xmpMM:DocumentID(?:>|=\")([^<\"]+)", txt, re.I)
        
        xmp_orig = _norm_uuid(xmp_orig_match.group(1) if xmp_orig_match else None)
        xmp_doc = _norm_uuid(xmp_doc_match.group(1) if xmp_doc_match else None)
        
        if xmp_orig and xmp_doc and xmp_doc != xmp_orig:
            indicators['XMPIDChange'] = {'from': xmp_orig, 'to': xmp_doc}

        trailer_match = re.search(r"/ID\s*\[\s*<\s*([0-9A-Fa-f]+)\s*>\s*<\s*([0-9A-Fa-f]+)\s*>\s*\]", txt)
        if trailer_match:
            trailer_orig, trailer_curr = _norm_uuid(trailer_match.group(1)), _norm_uuid(trailer_match.group(2))
            if trailer_orig and trailer_curr and trailer_curr != trailer_orig:
                indicators['TrailerIDChange'] = {'from': trailer_orig, 'to': trailer_curr}
        
        # --- Date Mismatch ---
        info_dates = dict(re.findall(r"/(ModDate|CreationDate)\s*\(\s*D:(\d{8,14})", txt))
        xmp_dates = {k: v for k, v in re.findall(r"<xmp:(ModifyDate|CreateDate)>([^<]+)</xmp:\1>", txt)}

        def _short(d: str) -> str: 
            return re.sub(r"[-:TZ]", "", d)[:14]

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
        # Iterate through each page to get the fonts used
        for page_num in range(len(doc)):
            try:
                fonts_on_page = doc.get_page_fonts(page_num)
                for font_info in fonts_on_page:
                    basefont_name = font_info[3]
                    if "+" in basefont_name:
                        try:
                            subset_prefix, full_font_name = basefont_name.split("+", 1)
                            # Keep the FULL font name including style (Arial-Bold, Arial-Regular, etc.)
                            # This way we track subsets per STYLE, not per base font
                            if full_font_name not in font_subsets:
                                font_subsets[full_font_name] = set()
                            font_subsets[full_font_name].add(basefont_name)
                        except ValueError:
                            continue
            except Exception as e:
                logging.debug(f"Error accessing page {page_num} fonts: {e}")
                continue
    except Exception as e:
        logging.error(f"Error accessing page fonts for {filepath.name}: {e}")
        return {}
    
    # Filter for only those font STYLES that have multiple subsets
    # This now correctly identifies: AAAAAA+Arial-Regular + BBBBBB+Arial-Regular (suspicious)
    # But ignores: AAAAAA+Arial-Bold + BBBBBB+Arial-Regular (normal)
    conflicting_fonts = {style: list(subsets) for style, subsets in font_subsets.items() if len(subsets) > 1}
    
    if conflicting_fonts:
        logging.info(f"Multiple font subsets of SAME STYLE found in {filepath.name}: {conflicting_fonts}")

    return conflicting_fonts


def _detect_metadata_inconsistencies(txt: str, doc, indicators: dict):
    """
    Detects inconsistencies between metadata claims and actual PDF features.
    
    Args:
        txt (str): Raw PDF content as text
        doc: PyMuPDF document object
        indicators (dict): Dictionary to add indicators to
    """
    try:
        # Check if metadata claims a specific creator but features suggest otherwise
        creator_match = re.search(r"/Creator\s*\((.*?)\)", txt, re.I)
        producer_match = re.search(r"/Producer\s*\((.*?)\)", txt, re.I)
        
        if creator_match or producer_match:
            creator = creator_match.group(1) if creator_match else ""
            producer = producer_match.group(1) if producer_match else ""
            
            # Check for mismatches with actual PDF version
            if doc and hasattr(doc, 'pdf_version'):
                version = doc.pdf_version()
                # If metadata claims old software but uses modern PDF features
                if (("Acrobat 4" in creator or "PDF 1.3" in txt) and version >= 17):  # PDF 1.7+
                    indicators['MetadataVersionMismatch'] = {
                        'claimed_version': 'Old (1.3-1.4)',
                        'actual_version': f'1.{version-10}'
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
        if re.search(r"(Tm|Td)\s+[^\n]*\s+(Tm|Td)", txt):
            # Multiple positioning commands in sequence (potential overlay)
            count = len(re.findall(r"(Tm|Td)\s+[^\n]*\s+(Tm|Td)", txt))
            if count > 5:  # Threshold for suspicious
                indicators['SuspiciousTextPositioning'] = {'count': count}
        
        # Detect white rectangles (common for hiding content)
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


def _detect_object_anomalies(txt: str, indicators: dict):
    """
    Detects object reference integrity issues.
    
    Args:
        txt (str): Raw PDF content as text
        indicators (dict): Dictionary to add indicators to
    """
    try:
        # Find all object definitions
        obj_defs = set()
        for match in re.finditer(r"\b(\d+)\s+\d+\s+obj\b", txt):
            obj_defs.add(int(match.group(1)))
        
        # Find all object references
        obj_refs = set()
        for match in re.finditer(r"\b(\d+)\s+\d+\s+R\b", txt):
            obj_refs.add(int(match.group(1)))
        
        # Find orphaned objects (defined but never referenced)
        orphaned = obj_defs - obj_refs
        if len(orphaned) > 5:  # Some orphans are normal, but many is suspicious
            indicators['OrphanedObjects'] = {'count': len(orphaned)}
        
        # Find missing objects (referenced but not defined)
        missing = obj_refs - obj_defs
        if len(missing) > 0:
            indicators['MissingObjects'] = {'count': len(missing)}
        
        # Detect suspicious object number gaps
        if obj_defs:
            max_obj = max(obj_defs)
            expected_count = max_obj
            actual_count = len(obj_defs)
            gap_ratio = (expected_count - actual_count) / expected_count if expected_count > 0 else 0
            
            if gap_ratio > 0.3:  # More than 30% gaps
                indicators['LargeObjectNumberGaps'] = {
                    'gap_percentage': f"{gap_ratio*100:.1f}%",
                    'max_object': max_obj,
                    'defined_objects': actual_count
                }
    except Exception as e:
        logging.debug(f"Error detecting object anomalies: {e}")


def _detect_javascript(txt: str, indicators: dict):
    """
    Detects JavaScript code in PDFs which can hide malicious alterations.
    
    Args:
        txt (str): Raw PDF content as text
        indicators (dict): Dictionary to add indicators to
    """
    try:
        # Check for JavaScript in the PDF
        if re.search(r"/JavaScript\b", txt, re.I):
            indicators['ContainsJavaScript'] = {}
            
            # Check for OpenAction (auto-execute on open)
            if re.search(r"/OpenAction\b", txt, re.I):
                indicators['JavaScriptAutoExecute'] = {}
            
            # Check for AA (Additional Actions)
            if re.search(r"/AA\s*<<", txt, re.I):
                indicators['AdditionalActions'] = {}
            
            # Try to count JavaScript actions
            js_count = len(re.findall(r"/JavaScript\b", txt, re.I))
            if js_count > 1:
                indicators['MultipleJavaScripts'] = {'count': js_count}
                
    except Exception as e:
        logging.debug(f"Error detecting JavaScript: {e}")


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
        
        for page_num in range(len(doc)):
            try:
                images = doc.get_page_images(page_num)
                for img_index, img in enumerate(images):
                    xref = img[0]  # Image xref number
                    
                    # Extract image data
                    try:
                        base_image = doc.extract_image(xref)
                        img_bytes = base_image["image"]
                        img_hash = hashlib.md5(img_bytes).hexdigest()
                        
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
                        if b"Exif" in img_bytes[:1000]:  # Check header
                            if 'ImagesWithEXIF' not in indicators:
                                indicators['ImagesWithEXIF'] = {'count': 0}
                            indicators['ImagesWithEXIF']['count'] += 1
                            
                    except Exception as e:
                        logging.debug(f"Could not extract image {xref}: {e}")
                        continue
                        
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

def decompress_stream(b):
    """Attempts to decompress a PDF stream using common filters."""
    for fn in (zlib.decompress, lambda d: base64.a85decode(re.sub(rb"\s", b"", d), adobe=True), lambda d: binascii.unhexlify(re.sub(rb"\s|>", b"", d))):
        try: return fn(b).decode("latin1", "ignore")
        except Exception: pass
    return ""

def extract_text_for_indicators(raw: bytes):
    """
    Extracts only what's needed for indicator hunting:
    - ~2 MB header/trailer
    - Small streams (skipping large image streams)
    - XMP xpacket (if present)
    """
    txt_segments = []

    # Cap: header/trailer/objects
    head_cap = raw[:2_000_000].decode("latin1", "ignore")
    txt_segments.append(head_cap)

    # Only process small streams (e.g., <= 256 KB) to avoid inflating large images
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S):
        body = m.group(1)
        if len(body) <= 256_000:
            try:
                txt_segments.append(decompress_stream(body))
            except Exception:
                try:
                    txt_segments.append(body.decode("latin1", "ignore"))
                except Exception:
                    pass

    # XMP xpacket (full content)
    m = re.search(rb"<\?xpacket begin=.*?\?>(.*?)<\?xpacket end=[^>]*\?>", raw, re.S)
    if m:
        try:
            txt_segments.append(m.group(1).decode("utf-8", "ignore"))
        except Exception:
            txt_segments.append(m.group(1).decode("latin1", "ignore"))

    # Ensure TouchUp_TextEdit is detectable even if it appears outside sampled text.
    if re.search(rb"touchup_textedit", raw, re.I):
        txt_segments.append("TouchUp_TextEdit")

    return "\n".join(txt_segments)

def run_exiftool(path, detailed=False, translator=None):
    """Runs ExifTool safely with a timeout and improved error handling."""
    def _(key):
        if translator: return translator(key)
        return key

    exe_path = resolve_path("exiftool.exe", base_is_parent=True)
    if not exe_path.is_file(): return _("exif_err_notfound")

    try:
        file_content = path.read_bytes()
        # Suppress console window on Windows
        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        # Build the command-line arguments for ExifTool
        command = [str(exe_path)]
        if detailed: command.extend(["-a", "-u", "-s", "-G1", "-struct"])
        else: command.extend(["-a", "-u", "-s", "-G1"])
        command.append("-") # Read from stdin

        # Run the process
        process = subprocess.run(
            command,
            input=file_content,
            capture_output=True,
            check=False,
            startupinfo=startupinfo,
            timeout=PDFReconConfig.EXIFTOOL_TIMEOUT
        )

        # Handle non-zero exit codes or stderr output
        if process.returncode != 0 or process.stderr:
            error_message = process.stderr.decode('latin-1', 'ignore').strip()
            if not process.stdout.strip(): return f"{_('exif_err_prefix')}\n{error_message}"
            logging.warning(f"ExifTool stderr for {path.name}: {error_message}")

        # Decode the output, trying UTF-8 first, then latin-1 as a fallback
        try: raw_output = process.stdout.decode('utf-8').strip()
        except UnicodeDecodeError: raw_output = process.stdout.decode('latin-1', 'ignore').strip()

        # Remove empty lines from the output
        return "\n".join([line for line in raw_output.splitlines() if line.strip()])

    except subprocess.TimeoutExpired:
        logging.error(f"ExifTool timed out for file {path.name}")
        return _("exif_err_prefix") + f"\nTimeout after {PDFReconConfig.EXIFTOOL_TIMEOUT} seconds."
    except Exception as e:
        logging.error(f"Error running exiftool for file {path}: {e}")
        return _("exif_err_run").format(e=e)

def parse_exif_data(exiftool_output: str):
    """
    Parses EXIFTool output into a structured dictionary for reuse.
    """
    data = {
        "producer_pdf": "", "producer_xmppdf": "", "softwareagent": "",
        "application": "", "software": "", "creatortool": "", "xmptoolkit": "",
        "create_dt": None, "modify_dt": None, "history_events": [], "all_dates": []
    }
    lines = exiftool_output.splitlines()

    # --- Regex Patterns (reuse module-level constants) ---
    history_pattern = re.compile(r"\[XMP-xmpMM\]\s+History\s+:\s+(.*)")

    def looks_like_software(s: str) -> bool:
        return bool(s and _SOFTWARE_TOKENS.search(s))

    # --- First Pass: Collect Key-Value Pairs for Tools ---
    for ln in lines:
        m = _KV_PATTERN.match(ln)
        if not m:
            continue

        group = m.group("group").strip().lower()
        tag = m.group("tag").strip().lower().replace(" ", "")
        val = m.group("value").strip()

        # Map tags to data dictionary keys for software detection
        if tag == "producer":
            if group == "pdf" and not data["producer_pdf"]:
                data["producer_pdf"] = val
            elif group in ("xmp-pdf", "xmp_pdf") and not data["producer_xmppdf"]:
                data["producer_xmppdf"] = val
        elif tag == "softwareagent" and not data["softwareagent"]:
            data["softwareagent"] = val
        elif tag == "application" and not data["application"]:
            data["application"] = val
        elif tag == "software" and not data["software"]:
            data["software"] = val
        elif tag == "creatortool" and not data["creatortool"] and looks_like_software(val):
            data["creatortool"] = val
        elif tag == "xmptoolkit" and not data["xmptoolkit"]:
            data["xmptoolkit"] = val

    # Fallback for producer fields
    if not data["producer_pdf"] and data["producer_xmppdf"]:
        data["producer_pdf"] = data["producer_xmppdf"]
    if not data["producer_xmppdf"] and data["producer_pdf"]:
        data["producer_xmppdf"] = data["producer_pdf"]

    # --- Second Pass: Collect All Dates and History Events ---
    for ln in lines:
        # History events
        hist_match = history_pattern.match(ln)
        if hist_match:
            history_str = hist_match.group(1)
            event_blocks = re.findall(r'\{([^}]+)\}', history_str)
            for block in event_blocks:
                details = {k.strip(): v.strip() for k, v in (pair.split('=', 1) for pair in block.split(',') if '=' in pair)}
                if 'When' in details:
                    try:
                        dt_obj = datetime.fromisoformat(details['When'].replace('Z', '+00:00'))
                        data["history_events"].append((dt_obj, details))
                    except (ValueError, IndexError):
                        pass
            continue

        # Generic date lines
        kv_match = _KV_PATTERN.match(ln)
        if not kv_match:
            continue

        val_str = kv_match.group("value").strip()
        match = _DATE_TZ_PATTERN.match(val_str)

        if match:
            parts = match.groupdict()
            # Massage date into ISO format: YYYY-MM-DDTHH:MM:SS
            date_part = parts.get("date").replace(":", "-", 2).replace(" ", "T")
            tz_part = parts.get("tz")

            try:
                full_date_str = date_part
                if tz_part:
                    full_date_str += tz_part.replace('Z', '+00:00')

                dt = datetime.fromisoformat(full_date_str)

                tag = kv_match.group("tag").strip().lower().replace(" ", "")
                group = kv_match.group("group").strip()
                data["all_dates"].append({"dt": dt, "tag": tag, "group": group, "full_str": val_str})

            except ValueError:
                continue

    # Find first create date and latest modify date
    for d in data["all_dates"]:
        if d["tag"] in {"createdate", "creationdate"}:
            if data["create_dt"] is None or d["dt"] < data["create_dt"]:
                data["create_dt"] = d["dt"]
        elif d["tag"] in {"modifydate", "metadatadate"}:
            if data["modify_dt"] is None or d["dt"] > data["modify_dt"]:
                data["modify_dt"] = d["dt"]

    return data

def detect_tool_change_from_exif(exiftool_output: str):
    """
    Determines if the primary tool changed between creation and last modification.
    """
    data = parse_exif_data(exiftool_output)

    create_tool = data["producer_pdf"] or data["producer_xmppdf"] or data["application"] or data["software"] or data["creatortool"] or ""
    modify_tool = data["softwareagent"] or data["producer_pdf"] or data["producer_xmppdf"] or data["application"] or data["software"] or data["creatortool"] or ""

    create_engine = modify_engine = ""
    if data["xmptoolkit"]:
        if data["create_dt"]: create_engine = data["xmptoolkit"]
        if data["modify_dt"]: modify_engine = data["xmptoolkit"]

    changed_tool = bool(create_tool and modify_tool and create_tool.strip() != modify_tool.strip())
    changed_engine = bool(create_engine and modify_engine and create_engine.strip() != modify_engine.strip())

    reason = ""
    if changed_tool and changed_engine: reason = "mixed"
    elif changed_tool: reason = "producer" if (data["producer_pdf"] or data["producer_xmppdf"]) else "software"
    elif changed_engine: reason = "engine"

    return {
        "changed": changed_tool or changed_engine,
        "create_tool": create_tool, "modify_tool": modify_tool,
        "create_engine": create_engine, "modify_engine": modify_engine,
        "modify_dt": data["modify_dt"],
        "reason": reason
    }

def get_filesystem_times(filepath, translator=None):
    """Helper function to get created/modified timestamps from the file system."""
    def _(key):
        if translator: return translator(key)
        return key

    events = []
    try:
        stat = filepath.stat()
        # Make the datetime object timezone-aware using the system's local timezone
        mtime = datetime.fromtimestamp(stat.st_mtime).astimezone()
        events.append((mtime, f"File System: {_('col_modified')}"))
        # Make the datetime object timezone-aware using the system's local timezone
        ctime = datetime.fromtimestamp(stat.st_ctime).astimezone()
        events.append((ctime, f"File System: {_('col_created')}"))
    except FileNotFoundError:
        pass
    return events

def extract_all_document_ids(txt: str, exif_output: str) -> dict:
    """
    Extracts all document IDs from a PDF for cross-referencing.
    Returns a dict with 'own_ids' (this file's identifiers) and 'ref_ids' (references to other documents).
    """
    def _norm(val):
        if val is None:
            return None
        if isinstance(val, (bytes, bytearray)):
            val = val.decode("utf-8", "ignore")
        s = str(val).strip()
        s = re.sub(r"^urn:uuid:", "", s, flags=re.I)
        s = re.sub(r"^(uuid:|xmp\.iid:|xmp\.did:)", "", s, flags=re.I)
        s = s.strip("<>").strip()
        return s.upper() if s else None

    own_ids = set()  # IDs that identify THIS document
    ref_ids = set()  # IDs that reference OTHER documents (ancestors, derived from, etc.)

    # Extract this document's own IDs
    # XMP DocumentID
    m = re.search(r'xmpMM:DocumentID(?:>|=")([^<"]+)', txt, re.I)
    if m:
        v = _norm(m.group(1))
        if v: own_ids.add(v)

    # XMP InstanceID
    m = re.search(r'xmpMM:InstanceID(?:>|=")([^<"]+)', txt, re.I)
    if m:
        v = _norm(m.group(1))
        if v: own_ids.add(v)

    # PDF Trailer IDs (first and second)
    for m in re.finditer(r"/ID\s*\[\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\]", txt):
        v1, v2 = _norm(m.group(1)), _norm(m.group(2))
        if v1: own_ids.add(v1)
        if v2: own_ids.add(v2)

    # Extract referenced IDs (ancestors, derived from, etc.)
    # XMP OriginalDocumentID (reference to original)
    m = re.search(r'xmpMM:OriginalDocumentID(?:>|=")([^<"]+)', txt, re.I)
    if m:
        v = _norm(m.group(1))
        if v: ref_ids.add(v)

    # DerivedFrom block
    df = re.search(r"<xmpMM:DerivedFrom\b[^>]*>(.*?)</xmpMM:DerivedFrom>", txt, re.I | re.S)
    if df:
        blk = df.group(1)
        for m in re.finditer(r'stRef:documentID(?:>|=")([^<"]+)', blk, re.I):
            v = _norm(m.group(1))
            if v: ref_ids.add(v)
        for m in re.finditer(r'stRef:instanceID(?:>|=")([^<"]+)', blk, re.I):
            v = _norm(m.group(1))
            if v: ref_ids.add(v)

    # Ingredients block (embedded/linked documents)
    ing = re.search(r"<xmpMM:Ingredients\b[^>]*>(.*?)</xmpMM:Ingredients>", txt, re.I | re.S)
    if ing:
        blk = ing.group(1)
        for m in re.finditer(r'stRef:documentID(?:>|=")([^<"]+)', blk, re.I):
            v = _norm(m.group(1))
            if v: ref_ids.add(v)

    # Photoshop DocumentAncestors
    ps = re.search(r"<photoshop:DocumentAncestors\b[^>]*>(.*?)</photoshop:DocumentAncestors>", txt, re.I | re.S)
    if ps:
        for m in re.finditer(r"<rdf:li[^>]*>([^<]+)</rdf:li>", ps.group(1), re.I):
            v = _norm(m.group(1))
            if v: ref_ids.add(v)

    # History references (past versions)
    hist = re.search(r"<xmpMM:History\b[^>]*>(.*?)</xmpMM:History>", txt, re.I | re.S)
    if hist:
        blk = hist.group(1)
        for m in re.finditer(r'stRef:documentID(?:>|=")([^<"]+)', blk, re.I):
            v = _norm(m.group(1))
            if v: ref_ids.add(v)

    # Also check ExifTool output for any DocumentID/InstanceID
    if exif_output:
        for m in re.finditer(r"Document\s*ID\s*:\s*(\S+)", exif_output, re.I):
            v = _norm(m.group(1))
            if v: own_ids.add(v)
        for m in re.finditer(r"Instance\s*ID\s*:\s*(\S+)", exif_output, re.I):
            v = _norm(m.group(1))
            if v: own_ids.add(v)
        for m in re.finditer(r"Original\s*Document\s*ID\s*:\s*(\S+)", exif_output, re.I):
            v = _norm(m.group(1))
            if v: ref_ids.add(v)

    # Remove any overlap (don't count own IDs as references)
    ref_ids = ref_ids - own_ids

    return {
        "own_ids": own_ids,
        "ref_ids": ref_ids
    }

def extract_touchup_text(doc):
    """
    Parses a PDF's internal objects to find any text associated with a TouchUp_TextEdit flag.
    Returns a list of extracted text strings.
    """
    def _clean_text_segment(raw_bytes):
        try:
            text = raw_bytes.decode("latin-1", errors="ignore")
            replacements = {"Õ": "å", "ã": "å", "°": "ø", "¯": "ø", "µ": "æ", "\xa0": " "}
            for old, new in replacements.items():
                text = text.replace(old, new)
            text = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", text)
            text = re.sub(r" +", " ", text)
            return text.strip()
        except Exception:
            return ""

    def _is_probably_junk(text):
        if not text or len(text) < 3:
            return True
        allowed = 0
        for ch in text:
            if ch.isalnum() or ch.isspace() or ch in ".,:;!?-()'\"/":
                allowed += 1
        if allowed / max(len(text), 1) < 0.7:
            return True
        if len(set(text)) <= 3 and len(text) > 10:
            return True
        return False

    # First try pikepdf-based extraction (TouchUp blocks).
    try:
        import pikepdf
        from pikepdf import String
        from io import BytesIO

        pdf = None
        try:
            original_filepath = doc.name if doc and hasattr(doc, "name") else None
            if original_filepath and Path(original_filepath).exists():
                pdf = pikepdf.open(original_filepath)
            elif doc and not doc.is_closed and hasattr(doc, "write"):
                pdf = pikepdf.open(BytesIO(doc.write()))
        except Exception as e:
            logging.debug(f"Pikepdf open failed for TouchUp extraction: {e}")
            pdf = None

        if pdf is not None:
            # Group results by page number: {page_num: [text1, text2, ...]}
            page_results = {}
            with pdf:
                for i, page in enumerate(pdf.pages):
                    page_num = i + 1
                    try:
                        commands = pikepdf.parse_content_stream(page)
                    except Exception:
                        continue

                    active_search = False
                    current_block_buffer = []

                    for operands, operator in commands:
                        op_name = str(operator)
                        if any("TouchUp" in str(arg) for arg in operands):
                            active_search = True
                        elif active_search and op_name in ["Tj", "TJ"]:
                            chunks = operands[0] if op_name == "TJ" else operands
                            for chunk in chunks:
                                if isinstance(chunk, String):
                                    try:
                                        raw_text = chunk.decode()
                                        cleaned = _clean_text_segment(raw_text.encode("latin-1", errors="ignore"))
                                    except Exception:
                                        cleaned = _clean_text_segment(bytes(chunk))
                                    if cleaned and not _is_probably_junk(cleaned):
                                        current_block_buffer.append(cleaned)
                        elif op_name in ["ET", "EMC"]:
                            if active_search and current_block_buffer:
                                # Join with visible separator so user can see segment boundaries
                                # Use │ (box drawing character) as delimiter
                                combined = " │ ".join([b for b in current_block_buffer if b])
                                if combined:
                                    if page_num not in page_results:
                                        page_results[page_num] = []
                                    page_results[page_num].append(combined)
                                current_block_buffer = []
                            active_search = False

            if page_results:
                # Return as dictionary grouped by page
                return page_results
    except ImportError:
        logging.debug("pikepdf not installed, falling back to legacy TouchUp extraction.")
    except Exception as e:
        logging.warning(f"TouchUp pikepdf extraction failed: {e}")

    # Fallback: legacy extraction from xref streams.
    # Returns dict format: {0: [text1, text2, ...]} (page 0 = unknown page)
    found_text = {}
    if not doc or doc.is_closed:
        return found_text

    for xref in range(1, doc.xref_length()):
        try:
            obj_source = doc.xref_object(xref, compressed=False)
            if "/TouchUp_TextEdit" in obj_source:
                stream = doc.xref_stream(xref)
                if stream:
                    matches = re.findall(rb"\((.*?)\)\s*Tj", stream)
                    for match in matches:
                        try:
                            decoded_text = fitz.utils.pdfdoc_decode(match)
                            if decoded_text.strip():
                                # Use page 0 as "unknown page" for legacy extraction
                                if 0 not in found_text:
                                    found_text[0] = []
                                found_text[0].append(decoded_text.strip())
                        except Exception:
                            continue
        except Exception as e:
            logging.warning(f"Could not process object {xref} for TouchUp text: {e}")
            continue
    return found_text

def get_text_for_comparison(source):
    """
    Performs a robust, layout-preserving text extraction on a PDF.
    Source can be bytes, a string path, or a Path object.
    """
    full_text = []
    doc = None
    try:
        if isinstance(source, bytes):
            doc = fitz.open(stream=source, filetype="pdf")
        else:
            resolved_path = Path(source) # source should be absolute or Path
            doc = fitz.open(resolved_path)

        for page in doc:
            full_text.append(page.get_text("text", sort=True))
        return "\n".join(full_text)
    except Exception as e:
        logging.error(f"Robust text extraction failed: {e}")
        return ""
    finally:
        if doc:
            doc.close()

def parse_exiftool_timeline(exiftool_output, translator=None):
    """
    Generates a list of timeline events from parsed EXIF data.
    """
    def _(key):
        if translator: return translator(key)
        return key

    events = []
    data = parse_exif_data(exiftool_output)

    create_tool = data["producer_pdf"] or data["producer_xmppdf"] or data["application"] or data["software"] or data["creatortool"] or ""
    modify_tool = data["softwareagent"] or create_tool # Fallback to create_tool if no specific modify tool

    # --- Add History Events ---
    for dt_obj, details in data["history_events"]:
        action = details.get('Action', 'N/A')
        agent = details.get('SoftwareAgent', '')
        changed = details.get('Changed', '')
        desc = [f"Action: {action}"]
        if agent: desc.append(f"Agent: {agent}")
        if changed: desc.append(f"Changed: {changed}")
        events.append((dt_obj, f"XMP History   - {' | '.join(desc)}"))

    # --- Add Generic Date Events ---
    def _ts_label(tag: str) -> str:
        t = tag.replace(" ", "").lower()
        return {"createdate": "Created", "creationdate": "Created", "modifydate": "Modified", "metadatadate": "Metadata"}.get(t, tag)

    for d in data["all_dates"]:
        label = _(_ts_label(d["tag"]).lower())
        tool = create_tool if d["tag"] in {"createdate", "creationdate"} else modify_tool
        tool_part = f" | Tool: {tool}" if tool else ""
        events.append((d["dt"], f"ExifTool ({d['group']}) - {label}: {d['full_str']}{tool_part}"))

    # --- Add XMP Engine Information ---
    if data["xmptoolkit"]:
        anchor_dt = data["create_dt"] or (data["all_dates"][0]["dt"] if data["all_dates"] else datetime.now())
        events.append((anchor_dt, f"XMP Engine: {data['xmptoolkit']}"))

    return events

def parse_raw_content_timeline(file_content_string):
    """Helper function to parse timestamps directly from the file's raw content."""
    events = []

    # Extended PDF date pattern that captures optional timezone: D:YYYYMMDDHHmmss+HH'mm' or Z
    pdf_date_extended = re.compile(
        r"\/([A-Z][a-zA-Z0-9_]+)\s*\(\s*D:(\d{14})([+\-]\d{2}'\d{2}'|[+\-]\d{2}:\d{2}|[+\-]\d{4}|Z)?"
    )

    for match in pdf_date_extended.finditer(file_content_string):
        label, date_str, tz_str = match.groups()
        try:
            # Parse the base datetime
            dt_obj = datetime.strptime(date_str, "%Y%m%d%H%M%S")

            # Handle timezone if present
            if tz_str:
                if tz_str == 'Z':
                    dt_obj = dt_obj.replace(tzinfo=timezone.utc)
                else:
                    # Normalize: +01'00' or +01:00 or +0100 -> +01:00
                    tz_clean = tz_str.replace("'", "").replace(":", "")
                    if len(tz_clean) == 5:  # e.g., +0100
                        tz_clean = tz_clean[:3] + ":" + tz_clean[3:]
                    try:
                        dt_obj = datetime.fromisoformat(dt_obj.strftime("%Y-%m-%dT%H:%M:%S") + tz_clean)
                    except ValueError:
                        pass  # Keep as naive if parsing fails

            tz_display = tz_str if tz_str else ""
            display_line = f"Raw File: /{label}: {dt_obj.strftime('%Y-%m-%d %H:%M:%S')}{tz_display}"
            events.append((dt_obj, display_line))
        except ValueError:
            continue

    # Look for XMP-style dates: <xmp:CreateDate>2023-01-01T12:00:00Z</xmp:CreateDate>
    xmp_date_pattern = re.compile(r"<([a-zA-Z0-9:]+)[^>]*?>\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[^\s<]*)\s*<\/([a-zA-Z0-9:]+)>")
    for match in xmp_date_pattern.finditer(file_content_string):
        label, date_str, closing_label = match.groups()
        if label != closing_label:
            continue
        try:
            # Normalize the date string for fromisoformat
            # Handle Z -> +00:00, strip milliseconds but keep timezone
            normalized = date_str.strip()

            # Check if there's timezone info
            has_tz = 'Z' in normalized or '+' in normalized[10:] or (normalized.count('-') > 2 and '-' in normalized[10:])

            # Replace Z with +00:00 for fromisoformat
            normalized = normalized.replace('Z', '+00:00')

            # Remove milliseconds but keep timezone
            if '.' in normalized:
                dot_pos = normalized.index('.')
                # Find where timezone starts (+ or - after the dot)
                tz_start = -1
                for i, c in enumerate(normalized[dot_pos:]):
                    if c in '+-':
                        tz_start = dot_pos + i
                        break
                if tz_start > 0:
                    normalized = normalized[:dot_pos] + normalized[tz_start:]
                else:
                    normalized = normalized[:dot_pos]

            dt_obj = datetime.fromisoformat(normalized)
            display_line = f"Raw File: <{label}>: {date_str}"
            events.append((dt_obj, display_line))
        except (ValueError, IndexError):
            continue
    return events

def generate_comprehensive_timeline(filepath, raw_file_content, exiftool_output, translator=None):
    """
    Combines events from all sources, separating them into timezone-aware and naive lists.
    """
    all_events = []

    # 1) Get File System, ExifTool, and Raw Content timestamps
    all_events.extend(get_filesystem_times(filepath, translator))
    all_events.extend(parse_exiftool_timeline(exiftool_output, translator))
    all_events.extend(parse_raw_content_timeline(raw_file_content))

    # 2) Add a special event if a tool change was detected
    try:
        info = detect_tool_change_from_exif(exiftool_output)
        if info.get("changed"):
            when = info.get("modify_dt")
            if not when and all_events:
                # Find a datetime object to anchor the event, prioritizing naive ones if present
                naive_dts = [e[0] for e in all_events if e[0].tzinfo is None]
                when = max(naive_dts) if naive_dts else max(e[0] for e in all_events)
            if not when:
                when = datetime.now()

            # Format the description of the tool change
            # Assuming English default
            label = "Tool changed"
            parts = [f"{info.get('create_tool','?')} -> {info.get('modify_tool','?')}"]
            if info.get("reason") == "engine":
                parts.append(f"(XMP engine: {info.get('create_engine','?')} -> {info.get('modify_engine','?')})")
            line = f"{label}: " + " ".join(parts)
            all_events.append((when, line))
    except Exception:
        pass

    # 3) Separate events into two lists based on timezone info
    aware_events = []
    naive_events = []
    for dt_obj, description in all_events:
        if dt_obj.tzinfo is not None:
            aware_events.append((dt_obj, description))
        else:
            naive_events.append((dt_obj, description))

    # 4) Sort each list independently
    aware_events.sort(key=lambda x: x[0])
    naive_events.sort(key=lambda x: x[0])

    return {"aware": aware_events, "naive": naive_events}

def extract_additional_xmp_ids(txt: str) -> dict:
    """
    Harvest XMP IDs beyond basic xmpMM:{Original,Document,Instance}.
    Returns a dict of sets with normalized uppercase IDs.
    """
    def _norm(val):
        """Normalizes a UUID/GUID value for consistent comparison."""
        if val is None:
            return None
        if isinstance(val, (bytes, bytearray)):
            val = val.decode("utf-8", "ignore")
        s = str(val).strip()
        # strip known prefixes & wrappers
        s = re.sub(r"^urn:uuid:", "", s, flags=re.I)
        s = re.sub(r"^(uuid:|xmp\.iid:|xmp\.did:)", "", s, flags=re.I)
        s = s.strip("<>").strip()
        return s.upper() if s else None

    out = {
        "stref_doc_ids": set(),
        "stref_inst_ids": set(),
        "derived_doc_ids": set(),
        "derived_inst_ids": set(),
        "derived_orig_ids": set(),
        "ingredient_doc_ids": set(),
        "ingredient_inst_ids": set(),
        "history_inst_ids": set(),
        "history_doc_ids": set(),
        "ps_doc_ancestors": set(),
    }

    # ---------------- stRef anywhere (attribute form) ----------------
    for m in re.finditer(r'stRef:documentID="([^"]+)"', txt, re.I):
        v = _norm(m.group(1));  out["stref_doc_ids"].add(v) if v else None
    for m in re.finditer(r'stRef:instanceID="([^"]+)"', txt, re.I):
        v = _norm(m.group(1));  out["stref_inst_ids"].add(v) if v else None

    # ---------------- stRef anywhere (element form) ----------------
    for m in re.finditer(r"<stRef:documentID>([^<]+)</stRef:documentID>", txt, re.I):
        v = _norm(m.group(1));  out["history_doc_ids"].add(v) if v else None
    for m in re.finditer(r"<stRef:instanceID>([^<]+)</stRef:instanceID>", txt, re.I):
        v = _norm(m.group(1));  out["history_inst_ids"].add(v) if v else None

    # ---------------- DerivedFrom block ----------------
    df = re.search(r"<xmpMM:DerivedFrom\b[^>]*>(.*?)</xmpMM:DerivedFrom>", txt, re.I | re.S)
    if df:
        blk = df.group(1)
        # stRef:* within DerivedFrom
        for m in re.finditer(r'stRef:documentID="([^"]+)"', blk, re.I):
            v = _norm(m.group(1)); out["derived_doc_ids"].add(v) if v else None
        for m in re.finditer(r'stRef:instanceID="([^"]+)"', blk, re.I):
            v = _norm(m.group(1)); out["derived_inst_ids"].add(v) if v else None
        for m in re.finditer(r"<stRef:documentID>([^<]+)</stRef:documentID>", blk, re.I):
            v = _norm(m.group(1)); out["derived_doc_ids"].add(v) if v else None
        for m in re.finditer(r"<stRef:instanceID>([^<]+)</stRef:instanceID>", blk, re.I):
            v = _norm(m.group(1)); out["derived_inst_ids"].add(v) if v else None
        # OriginalDocumentID sometimes appears explicitly inside DerivedFrom
        for m in re.finditer(r"(?:xmpMM:|)OriginalDocumentID(?:>|=\")([^<\">]+)", blk, re.I):
            v = _norm(m.group(1)); out["derived_orig_ids"].add(v) if v else None

    # ---------------- Ingredients block ----------------
    ing = re.search(r"<xmpMM:Ingredients\b[^>]*>(.*?)</xmpMM:Ingredients>", txt, re.I | re.S)
    if ing:
        blk = ing.group(1)
        for m in re.finditer(r'stRef:documentID="([^"]+)"', blk, re.I):
            v = _norm(m.group(1)); out["ingredient_doc_ids"].add(v) if v else None
        for m in re.finditer(r'stRef:instanceID="([^"]+)"', blk, re.I):
            v = _norm(m.group(1)); out["ingredient_inst_ids"].add(v) if v else None
        for m in re.finditer(r"<stRef:documentID>([^<]+)</stRef:documentID>", blk, re.I):
            v = _norm(m.group(1)); out["ingredient_doc_ids"].add(v) if v else None
        for m in re.finditer(r"<stRef:instanceID>([^<]+)</stRef:instanceID>", blk, re.I):
            v = _norm(m.group(1)); out["ingredient_inst_ids"].add(v) if v else None

    # ---------------- History block ----------------
    hist = re.search(r"<xmpMM:History\b[^>]*>(.*?)</xmpMM:History>", txt, re.I | re.S)
    if hist:
        blk = hist.group(1)
        # attribute-style summary sometimes exists in certain producers
        for m in re.finditer(r'(?:InstanceID|stRef:instanceID)="([^"]+)"', blk, re.I):
            v = _norm(m.group(1)); out["history_inst_ids"].add(v) if v else None
        for m in re.finditer(r'(?:DocumentID|stRef:documentID)="([^"]+)"', blk, re.I):
            v = _norm(m.group(1)); out["history_doc_ids"].add(v) if v else None
        # element-style
        for m in re.finditer(r"<stRef:instanceID>([^<]+)</stRef:instanceID>", blk, re.I):
            v = _norm(m.group(1)); out["history_inst_ids"].add(v) if v else None
        for m in re.finditer(r"<stRef:documentID>([^<]+)</stRef:documentID>", blk, re.I):
            v = _norm(m.group(1)); out["history_doc_ids"].add(v) if v else None
        # catch any xmp.iid/xmp.did that appear as plain text within History
        for m in re.finditer(r"(uuid:[0-9a-f\-]+|xmp\.iid:[^,<>} \]]+|xmp\.did:[^,<>} \]]+)", blk, re.I):
            v = _norm(m.group(1)); out["history_inst_ids"].add(v) if v else None

    # ---------------- Photoshop DocumentAncestors ----------------
    ps = re.search(r"<photoshop:DocumentAncestors\b[^>]*>(.*?)</photoshop:DocumentAncestors>", txt, re.I | re.S)
    if ps:
        for m in re.finditer(r"<rdf:li[^>]*>([^<]+)</rdf:li>", ps.group(1), re.I):
            v = _norm(m.group(1)); out["ps_doc_ancestors"].add(v) if v else None

    # Deduplicate and purge empty values
    for k in out:
        out[k] = {v for v in out[k] if v}

    return out

def process_and_validate_revisions(potential_revisions, original_fp, scan_root_folder, copy_executor=None, translator=None):
    """
    Processes, validates, and compares a list of potential PDF revisions.
    Returns a list of dictionaries for valid revisions that should be reported.
    """
    valid_revision_results = []
    invalid_xref_dir = scan_root_folder / "Invalid XREF"

    def _perform_copy_local(source, dest_path):
        """Local helper or call to external copier."""
        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(source, Path):
                shutil.copy2(source, dest_path)
            elif isinstance(source, bytes):
                dest_path.write_bytes(source)
            logging.info(f"Copied to: {dest_path}")
        except Exception as e:
            logging.error(f"Error copying to {dest_path}: {e}")

    for rev_path, basefile, rev_raw in potential_revisions:
        tmp_path = None
        try:
            # Use a temporary file to run ExifTool without writing to the final destination first
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                tmp_file.write(rev_raw)
                tmp_path = Path(tmp_file.name)

            rev_exif = run_exiftool(tmp_path, detailed=True, translator=translator)

            # Conditionally copy revisions with invalid XREF tables if the setting is enabled
            if PDFReconConfig.EXPORT_INVALID_XREF and "Warning" in rev_exif and "Invalid xref table" in rev_exif:
                logging.info(f"Submitting invalid XREF revision for {basefile} to be copied.")
                dest_path = invalid_xref_dir / rev_path.name
                if copy_executor:
                    # We define a lambda or partial to adapt to executor
                    copy_executor.submit(_perform_copy_local, rev_raw, dest_path)
                else:
                    _perform_copy_local(rev_raw, dest_path)
                continue  # Skip adding this invalid revision to the results

            # If valid, write the revision to its final destination
            rev_path.parent.mkdir(exist_ok=True)
            rev_path.write_bytes(rev_raw)

            rev_md5 = hashlib.md5(rev_raw).hexdigest()
            rev_txt = extract_text_for_indicators(rev_raw)
            revision_timeline = generate_comprehensive_timeline(rev_path, rev_txt, rev_exif, translator=translator)

            # Perform a visual comparison to see if the revision is identical to the original
            is_identical = False
            try:
                if fitz and Image and ImageChops:
                    with fitz.open(original_fp) as doc_orig, fitz.open(rev_path) as doc_rev:
                        pages_to_compare = min(doc_orig.page_count, doc_rev.page_count, PDFReconConfig.VISUAL_DIFF_PAGE_LIMIT)
                        if pages_to_compare > 0:
                            is_identical = True
                            for i in range(pages_to_compare):
                                page_orig, page_rev = doc_orig.load_page(i), doc_rev.load_page(i)
                                if page_orig.rect != page_rev.rect:
                                    is_identical = False
                                    break
                                pix_orig, pix_rev = page_orig.get_pixmap(dpi=96), page_rev.get_pixmap(dpi=96)
                                img_orig = Image.frombytes("RGB", [pix_orig.width, pix_orig.height], pix_orig.samples)
                                img_rev = Image.frombytes("RGB", [pix_rev.width, pix_rev.height], pix_rev.samples)
                                # Ensure images are same size before comparison
                                if img_orig.size != img_rev.size:
                                    is_identical = False
                                    break
                                if ImageChops.difference(img_orig, img_rev).getbbox() is not None:
                                    is_identical = False
                                    break
            except Exception as e:
                logging.warning(f"Could not visually compare {rev_path.name}, keeping it. Error: {e}")

            revision_row_data = {
                "path": rev_path, "indicator_keys": {"Revision": {}}, "md5": rev_md5, "exif": rev_exif,
                "is_revision": True, "timeline": revision_timeline, "original_path": original_fp,
                "is_identical": is_identical, "status": "success"
            }
            valid_revision_results.append(revision_row_data)
        finally:
            if tmp_path and tmp_path.exists():
                os.remove(tmp_path)

    return valid_revision_results

def process_single_file(fp, scan_root_folder, copy_executor=None, translator=None):
    """
    Processes a single PDF file, submitting copy jobs to a dedicated thread pool.
    """
    def _(key):
        if translator: return translator(key)
        return key

    def _handle_file_processing_error(filepath, error_type, error):
        """Centralized error handler for file processing errors."""
        error_log = f"Error processing {filepath.name}: {error}"
        logging.warning(error_log)
        return {
            "path": filepath,
            "status": "error",
            "error_type": error_type,
            "error_message": str(error)
        }

    try:
        validate_pdf_file(fp)

        raw = fp.read_bytes()
        logging.info(f"Processing file: {fp.name} ({len(raw) / (1024*1024):.1f}MB)")

        # Use safer PDF opening
        try:
            doc = safe_pdf_open(fp, raw_bytes=raw)
        except Exception as e:
            logging.error(f"Failed to open PDF {fp.name}: {e}")
            raise PDFCorruptionError(f"Cannot open PDF: {str(e)}")

        # Extract text for indicator detection (must capture raw PDF structure)
        logging.info(f"Extracting text from {fp.name}...")
        txt = extract_text_for_indicators(raw)
        logging.info(f"Text extraction complete for {fp.name}: {len(txt)} characters")

        # Detect indicators with error handling
        logging.info(f"Detecting indicators in {fp.name}...")
        try:
            indicators = detect_indicators(fp, txt, doc)
            logging.info(f"Indicator detection complete for {fp.name}")
        except Exception as e:
            logging.warning(f"Error detecting indicators in {fp.name}: {e}")
            indicators = {}

        logging.info(f"Computing MD5 and EXIF for {fp.name}...")
        md5_hash = md5_file(fp)
        exif = run_exiftool(fp, detailed=True, translator=translator)

        # Extract document IDs for cross-referencing
        document_ids = extract_all_document_ids(txt, exif)

        def _perform_copy_local(source, dest_path):
            try:
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(source, Path):
                    shutil.copy2(source, dest_path)
                elif isinstance(source, bytes):
                    dest_path.write_bytes(source)
                logging.info(f"Copied to: {dest_path}")
            except Exception as e:
                logging.error(f"Error copying to {dest_path}: {e}")

        # Conditionally submit invalid XREF originals to the copy pool if setting is enabled
        if PDFReconConfig.EXPORT_INVALID_XREF and "Warning" in exif and "Invalid xref table" in exif:
            invalid_xref_dir = scan_root_folder / "Invalid XREF"
            dest_path = invalid_xref_dir / fp.name
            if copy_executor:
                copy_executor.submit(_perform_copy_local, fp, dest_path)
            else:
                _perform_copy_local(fp, dest_path)

        tool_change_info = detect_tool_change_from_exif(exif)
        if tool_change_info.get("changed"):
            indicators['ToolChange'] = {}

        logging.info(f"Generating timeline for {fp.name}...")
        original_timeline = generate_comprehensive_timeline(fp, txt, exif, translator=translator)

        logging.info(f"Extracting revisions from {fp.name}...")
        potential_revisions = extract_revisions(raw, fp)
        doc.close()

        # _add_layer_indicators logic integrated here
        try:
            layers_cnt = count_layers(raw)
        except Exception:
            layers_cnt = 0

        if layers_cnt > 0:
            indicators['HasLayers'] = {'count': layers_cnt}
            page_count = 0
            try:
                with fitz.open(fp) as _doc:
                    page_count = _doc.page_count
            except Exception:
                pass
            if page_count and layers_cnt > page_count:
                indicators['MoreLayersThanPages'] = {'layers': layers_cnt, 'pages': page_count}

        # Delegate all revision processing
        valid_revision_results = process_and_validate_revisions(potential_revisions, fp, scan_root_folder, copy_executor=copy_executor, translator=translator)

        if valid_revision_results:
            indicators['HasRevisions'] = {'count': len(valid_revision_results)}

        original_row_data = {
            "path": fp,
            "indicator_keys": indicators,
            "md5": md5_hash,
            "exif": exif,
            "is_revision": False,
            "timeline": original_timeline,
            "status": "success",
            "document_ids": document_ids
        }

        results = [original_row_data] + valid_revision_results
        return results

    except PDFTooLargeError as e:
        return [_handle_file_processing_error(fp, "file_too_large", e)]
    except PDFEncryptedError as e:
        return [_handle_file_processing_error(fp, "file_encrypted", e)]
    except PDFCorruptionError as e:
        return [_handle_file_processing_error(fp, "file_corrupt", e)]
    except Exception as e:
        logging.exception(f"Unexpected error processing file {fp.name}")
        return [_handle_file_processing_error(fp, "processing_error", e)]

def scan_worker_parallel(folder, q, copy_executor=None, translator=None):
    """
    Finds PDF files and processes them in parallel using a ThreadPoolExecutor.
    Results are sent back to the main thread via a queue.
    """
    def _(key):
        if translator: return translator(key)
        return key

    try:
        q.put(("scan_status", _("preparing_analysis")))

        pdf_files = list(find_pdf_files_generator(folder))
        if not pdf_files:
            q.put(("finished", None))
            return

        q.put(("progress_mode_determinate", len(pdf_files)))
        files_processed = 0
        scan_start_time = time.time()

        # Use a timeout of 60 seconds per file to prevent hangs
        FILE_TIMEOUT = 60  # seconds

        with ThreadPoolExecutor(max_workers=PDFReconConfig.MAX_WORKER_THREADS) as executor:
            # Pass the scan root 'folder' to each file processing job
            future_to_path = {executor.submit(process_single_file, fp, folder, copy_executor, translator): fp for fp in pdf_files}

            try:
                for future in as_completed(future_to_path):
                    path = future_to_path[future]
                    files_processed += 1
                    try:
                        results = future.result(timeout=FILE_TIMEOUT)
                        for result_data in results:
                            q.put(("file_row", result_data))
                    except TimeoutError:
                        logging.error(f"TIMEOUT processing file {path.name} - exceeded {FILE_TIMEOUT} seconds")
                        q.put(("file_row", {"path": path, "status": "error", "error_type": "processing_timeout", "error_message": f"File processing timed out after {FILE_TIMEOUT} seconds"}))
                    except Exception as e:
                        logging.error(f"Unexpected error from thread pool for file {path.name}: {e}")
                        q.put(("file_row", {"path": path, "status": "error", "error_type": "unknown_error", "error_message": str(e)}))

                    elapsed_time = time.time() - scan_start_time
                    fps = files_processed / elapsed_time if elapsed_time > 0 else 0
                    eta_seconds = (len(pdf_files) - files_processed) / fps if fps > 0 else 0
                    q.put(("detailed_progress", {"file": path.name, "fps": fps, "eta": time.strftime('%M:%S', time.gmtime(eta_seconds))}))
            except TimeoutError as te:
                # Handle case where as_completed itself times out (shouldn't happen now without timeout param)
                logging.warning(f"Some futures did not complete: {te}")
                # Process any remaining unfinished futures
                for future, path in future_to_path.items():
                    if not future.done():
                        future.cancel()
                        q.put(("file_row", {"path": path, "status": "error", "error_type": "cancelled", "error_message": "Processing was cancelled due to timeout"}))

    except Exception as e:
        logging.error(f"Error in scan worker: {e}")
        q.put(("error", f"A critical error occurred: {e}"))
    finally:
        q.put(("finished", None))
