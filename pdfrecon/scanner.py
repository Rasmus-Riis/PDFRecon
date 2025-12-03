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
from concurrent.futures import ThreadPoolExecutor, as_completed

from .config import (
    PDFReconConfig, PDFProcessingError, PDFCorruptionError, 
    PDFTooLargeError, PDFEncryptedError,
    LAYER_OCGS_BLOCK_RE, OBJ_REF_RE, LAYER_OC_REF_RE
)
from .pdf_processor import safe_pdf_open, safe_extract_text, validate_pdf_file, count_layers
from .utils import md5_file


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
            found_text = None
            details = {'found_text': found_text, 'text_diff': None}
            
            # Try to extract TouchUp text and compute diff if revisions exist
            if doc and hasattr(doc, 'write') and app_instance:
                try:
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
    Analyzes fonts in the PDF to detect multiple subsets of the same base font.
    
    When a PDF includes custom fonts, they may be split into multiple subsets
    (e.g., "ABC+Calibri", "DEF+Calibri"). Multiple subsets of the same font
    can indicate editing or assembly from different sources.
    
    Args:
        filepath (Path): Path to the PDF file (for logging)
        doc: PyMuPDF document object
        
    Returns:
        dict: Dictionary of base fonts with their conflicting subsets.
              Example: {'Calibri': ['ABC+Calibri', 'DEF+Calibri-Bold']}
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
                            _, actual_base_font = basefont_name.split("+", 1)
                            normalized_base = actual_base_font.split('-')[0]
                            if normalized_base not in font_subsets:
                                font_subsets[normalized_base] = set()
                            font_subsets[normalized_base].add(basefont_name)
                        except ValueError:
                            continue
            except Exception as e:
                logging.debug(f"Error accessing page {page_num} fonts: {e}")
                continue
    except Exception as e:
        logging.error(f"Error accessing page fonts for {filepath.name}: {e}")
        return {}
    
    # Filter for only those fonts that actually have multiple subsets
    conflicting_fonts = {base: list(subsets) for base, subsets in font_subsets.items() if len(subsets) > 1}
    
    if conflicting_fonts:
        logging.info(f"Multiple font subsets found in {filepath.name}: {conflicting_fonts}")

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
