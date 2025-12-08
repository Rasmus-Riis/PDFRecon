"""
Advanced Forensic Detection for PDFRecon
Extracts additional forensic indicators: emails, URLs, UNC paths, language,
encryption status, hidden text patterns, attachments, OCR layers, multimedia, etc.
"""

import re
import logging
import hashlib
from pathlib import Path
from .jpeg_forensics import analyze_pdf_images_qt


def detect_emails_and_urls(txt: str, indicators: dict):
    """Extract email addresses and URLs from PDF content."""
    try:
        # Email pattern
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = set(re.findall(email_pattern, txt))
        
        if emails and len(emails) > 0:
            indicators['EmailAddresses'] = {
                'count': len(emails),
                'emails': list(emails)[:10]  # Limit to first 10
            }
        
        # URL pattern (http, https, ftp)
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        urls = set(re.findall(url_pattern, txt, re.IGNORECASE))
        
        if urls and len(urls) > 0:
            # Categorize by domain
            domains = {}
            for url in urls:
                try:
                    domain = url.split('://')[1].split('/')[0]
                    if domain not in domains:
                        domains[domain] = []
                    domains[domain].append(url)
                except:
                    pass
            
            indicators['URLs'] = {
                'count': len(urls),
                'unique_domains': len(domains),
                'domains': list(domains.keys())[:10]  # Limit to first 10
            }
            
    except Exception as e:
        logging.debug(f"Error detecting emails/URLs: {e}")


def detect_unc_paths(txt: str, indicators: dict):
    """Extract UNC paths revealing internal network structure."""
    try:
        # UNC path pattern: \\servername\share\path
        unc_pattern = r'\\\\[a-zA-Z0-9_\-\.]+\\[a-zA-Z0-9_\-\.\$\\]+'
        unc_paths = set(re.findall(unc_pattern, txt))
        
        if unc_paths and len(unc_paths) > 0:
            indicators['UNCPaths'] = {
                'count': len(unc_paths),
                'paths': list(unc_paths)[:5]  # Limit to first 5
            }
            
    except Exception as e:
        logging.debug(f"Error detecting UNC paths: {e}")


def detect_language(doc, indicators: dict):
    """Detect document language(s)."""
    try:
        if not doc:
            return
            
        languages = set()
        
        # Check metadata for language
        metadata = doc.metadata
        if metadata and metadata.get('language'):
            languages.add(metadata['language'])
        
        # Try to extract from content
        # PDF language is typically in the document catalog
        # We'll check for /Lang in the catalog
        try:
            catalog = doc.pdf_catalog()
            if catalog and catalog.get('/Lang'):
                lang = str(catalog['/Lang'])
                languages.add(lang)
        except:
            pass
        
        if languages:
            indicators['Languages'] = {
                'count': len(languages),
                'languages': list(languages)
            }
            
    except Exception as e:
        logging.debug(f"Error detecting language: {e}")


def detect_encryption_status(doc, txt: str, indicators: dict):
    """Detect encryption and password protection."""
    try:
        # Check if encrypted
        if doc and hasattr(doc, 'is_encrypted') and doc.is_encrypted:
            indicators['Encrypted'] = {'status': 'Yes'}
            
            # Check if we could decrypt it (meaning user password was empty or known)
            if hasattr(doc, 'needs_pass') and doc.needs_pass:
                indicators['PasswordRequired'] = {'status': 'User password required'}
            else:
                indicators['EncryptedButOpen'] = {'status': 'Opened without password (empty or known)'}
        
        # Check for encryption dictionary in raw content
        if re.search(r'/Encrypt\s+\d+\s+\d+\s+R', txt):
            if 'Encrypted' not in indicators:
                indicators['EncryptionDictionary'] = {'status': 'Encryption dictionary present'}
                
        # Check for security settings
        if re.search(r'/P\s+-?\d+', txt):  # Permissions integer
            perm_match = re.search(r'/P\s+(-?\d+)', txt)
            if perm_match:
                perm_value = int(perm_match.group(1))
                restrictions = []
                
                # PDF permission bits (negative value = restrictions)
                if perm_value < 0:
                    if not (perm_value & 4):
                        restrictions.append('Printing restricted')
                    if not (perm_value & 8):
                        restrictions.append('Modification restricted')
                    if not (perm_value & 16):
                        restrictions.append('Copying restricted')
                    if not (perm_value & 32):
                        restrictions.append('Annotations restricted')
                    
                    if restrictions:
                        indicators['SecurityRestrictions'] = {
                            'permissions_value': perm_value,
                            'restrictions': restrictions
                        }
                        
    except Exception as e:
        logging.debug(f"Error detecting encryption: {e}")


def detect_hidden_text_patterns(txt: str, doc, indicators: dict):
    """Detect patterns suggesting hidden text (white overlays, etc.)."""
    try:
        # Already have white rectangle detection in main scanner
        # Let's add more sophisticated patterns
        
        # Check for text rendering mode 3 (invisible text)
        if re.search(r'\s3\s+Tr\b', txt):
            indicators['InvisibleTextMode'] = {'status': 'Text rendering mode 3 (invisible) detected'}
        
        # Check for white color (1 1 1 RG or #FFFFFF)
        white_color_matches = len(re.findall(r'\b1\s+1\s+1\s+(rg|RG)\b', txt))
        if white_color_matches > 20:  # Threshold for suspicion
            indicators['ExcessiveWhiteColor'] = {
                'count': white_color_matches,
                'note': 'High usage of white color may indicate content hiding'
            }
        
        # Check for text outside MediaBox (hidden off-page)
        # This requires page-by-page analysis
        if doc:
            for page_num in range(min(len(doc), 10)):  # Check first 10 pages only
                try:
                    page = doc[page_num]
                    blocks = page.get_text("dict")["blocks"]
                    
                    mb = page.mediabox
                    mb_rect = (mb[0], mb[1], mb[2], mb[3])
                    
                    for block in blocks:
                        if "lines" in block:
                            for line in block["lines"]:
                                bbox = line["bbox"]
                                # Check if text is way outside mediabox
                                if (bbox[0] < mb_rect[0] - 100 or bbox[1] < mb_rect[1] - 100 or
                                    bbox[2] > mb_rect[2] + 100 or bbox[3] > mb_rect[3] + 100):
                                    indicators['TextOutsideMediaBox'] = {
                                        'page': page_num + 1,
                                        'note': 'Text positioned outside visible page area'
                                    }
                                    return  # Found one, that's enough
                except:
                    pass
                    
    except Exception as e:
        logging.debug(f"Error detecting hidden text patterns: {e}")


def detect_attachments(doc, txt: str, indicators: dict):
    """Detect embedded file attachments."""
    try:
        # Check for embedded files
        if re.search(r'/Type\s*/EmbeddedFile', txt, re.IGNORECASE):
            # Count embedded files
            embedded_count = len(re.findall(r'/Type\s*/EmbeddedFile', txt, re.IGNORECASE))
            
            indicators['EmbeddedFiles'] = {
                'count': embedded_count,
                'note': 'PDF contains embedded file attachments'
            }
            
            # Try to extract filenames
            filenames = re.findall(r'/F\s*\(([^)]+)\)', txt)
            if filenames:
                indicators['EmbeddedFiles']['filenames'] = filenames[:10]
        
        # Check for file attachment annotations
        if re.search(r'/Subtype\s*/FileAttachment', txt):
            indicators['FileAttachmentAnnotations'] = {
                'status': 'PDF has file attachment annotations'
            }
            
    except Exception as e:
        logging.debug(f"Error detecting attachments: {e}")


def detect_ocr_layer(doc, txt: str, indicators: dict):
    """Detect OCR layer (scanned documents with text layer)."""
    try:
        if not doc:
            return
        
        # Check if document has both images and text (characteristic of OCR PDFs)
        has_images = False
        has_text = False
        text_over_image_ratio = 0
        
        for page_num in range(min(len(doc), 5)):  # Check first 5 pages
            try:
                page = doc[page_num]
                
                # Check for images
                images = page.get_images()
                if images and len(images) > 0:
                    has_images = True
                
                # Check for text
                text = page.get_text()
                if text and len(text.strip()) > 50:
                    has_text = True
                
                # If both, check if text is suspiciously overlaid on images
                if has_images and has_text:
                    # Get image area
                    image_area = 0
                    for img in images:
                        try:
                            bbox = page.get_image_bbox(img[7])  # img[7] is xref
                            if bbox:
                                img_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
                                image_area += img_area
                        except:
                            pass
                    
                    # Get page area
                    page_area = (page.rect.width * page.rect.height)
                    
                    # If images cover > 80% of page, likely scanned
                    if page_area > 0 and (image_area / page_area) > 0.8:
                        text_over_image_ratio += 1
                        
            except:
                pass
        
        # If multiple pages have text over large images, likely OCR
        if has_images and has_text and text_over_image_ratio >= 2:
            indicators['OCRLayer'] = {
                'status': 'Suspected',
                'note': 'Document appears to be scanned with OCR text layer',
                'pages_with_pattern': text_over_image_ratio
            }
            
    except Exception as e:
        logging.debug(f"Error detecting OCR layer: {e}")


def detect_3d_and_multimedia(txt: str, indicators: dict):
    """Detect 3D objects and multimedia content."""
    try:
        # Check for 3D annotations
        if re.search(r'/Subtype\s*/3D', txt):
            indicators['3DObjects'] = {'status': 'PDF contains 3D objects'}
        
        # Check for multimedia (sound, video)
        if re.search(r'/Subtype\s*/Sound', txt):
            indicators['SoundAnnotations'] = {'status': 'PDF contains sound annotations'}
        
        if re.search(r'/Subtype\s*/Movie', txt) or re.search(r'/Subtype\s*/Screen', txt):
            indicators['VideoContent'] = {'status': 'PDF contains video/multimedia content'}
        
        # Check for RichMedia (Flash, etc.)
        if re.search(r'/Subtype\s*/RichMedia', txt):
            indicators['RichMedia'] = {
                'status': 'PDF contains RichMedia (potentially Flash)',
                'note': 'High security risk - may execute code'
            }
            
    except Exception as e:
        logging.debug(f"Error detecting 3D/multimedia: {e}")


def detect_temporal_anomalies(txt: str, indicators: dict):
    """Detect future-dated timestamps and temporal inconsistencies."""
    try:
        import datetime
        now = datetime.datetime.now()
        
        # Extract timestamps from PDF
        # Pattern: D:YYYYMMDDHHmmSS or D:YYYYMMDD
        date_pattern = r'D:(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?(\d{2})?'
        dates = re.findall(date_pattern, txt)
        
        future_dates = []
        for date_tuple in dates:
            try:
                year = int(date_tuple[0])
                month = int(date_tuple[1])
                day = int(date_tuple[2])
                
                # Basic validation
                if year > 1990 and year < 2100 and month >= 1 and month <= 12 and day >= 1 and day <= 31:
                    date_obj = datetime.datetime(year, month, day)
                    
                    if date_obj > now:
                        days_ahead = (date_obj - now).days
                        if days_ahead > 1:  # More than 1 day in future
                            future_dates.append({
                                'date': f"{year}-{month:02d}-{day:02d}",
                                'days_ahead': days_ahead
                            })
            except:
                pass
        
        if future_dates:
            indicators['FutureDatedTimestamps'] = {
                'count': len(future_dates),
                'dates': future_dates[:5]  # First 5
            }
            
    except Exception as e:
        logging.debug(f"Error detecting temporal anomalies: {e}")


def detect_pdf_a_compliance(txt: str, indicators: dict):
    """Check if PDF claims PDF/A compliance (archival format - should never change)."""
    try:
        # Check for PDF/A identifier in XMP metadata
        if re.search(r'pdfaid:part', txt, re.IGNORECASE):
            part_match = re.search(r'pdfaid:part>(\d+)</pdfaid:part', txt, re.IGNORECASE)
            conformance_match = re.search(r'pdfaid:conformance>([A-Z])</pdfaid:conformance', txt, re.IGNORECASE)
            
            part = part_match.group(1) if part_match else 'Unknown'
            conformance = conformance_match.group(1) if conformance_match else 'Unknown'
            
            indicators['PDFACompliance'] = {
                'part': f'PDF/A-{part}{conformance}',
                'note': 'PDF/A is archival format - any modification breaks compliance'
            }
            
    except Exception as e:
        logging.debug(f"Error detecting PDF/A compliance: {e}")


def detect_polyglot_file(pdf_bytes: bytes, indicators: dict):
    """
    Detect polyglot files - files that are valid as multiple formats simultaneously.
    
    A legitimate PDF should have %PDF header at or very near offset 0.
    If the header appears at a suspicious offset (e.g., 512+ bytes), the file may be
    a polyglot attempting to be both a ZIP and PDF to evade security scanners.
    
    Args:
        pdf_bytes (bytes): Raw PDF file content
        indicators (dict): Dictionary to add indicators to
    """
    try:
        # PDF spec allows %PDF within first 1024 bytes, but legitimate files use offset 0
        pdf_header = b'%PDF-'
        
        # Find the position of the PDF header
        header_offset = pdf_bytes.find(pdf_header)
        
        if header_offset == -1:
            indicators['PolyglotFile'] = {
                'status': 'CRITICAL: No PDF header found',
                'note': 'File may be corrupted or not a valid PDF'
            }
            return
        
        if header_offset == 0:
            # Normal PDF - header at start
            return
        
        if header_offset > 0 and header_offset <= 1024:
            # Check what's before the PDF header
            prefix = pdf_bytes[:header_offset]
            
            # Check for common file signatures
            signatures = {
                b'PK\x03\x04': 'ZIP/Office/JAR',
                b'PK\x05\x06': 'ZIP (empty)',
                b'\x1f\x8b\x08': 'GZIP',
                b'Rar!': 'RAR',
                b'\x89PNG': 'PNG',
                b'\xff\xd8\xff': 'JPEG',
                b'GIF8': 'GIF',
                b'BM': 'BMP',
                b'\x00\x00\x00': 'Possible video/binary',
            }
            
            detected_format = None
            for sig, format_name in signatures.items():
                if prefix.startswith(sig):
                    detected_format = format_name
                    break
            
            # Suspicious if offset is large or another format is detected
            if header_offset >= 512 or detected_format:
                indicators['PolyglotFile'] = {
                    'status': 'SUSPICIOUS',
                    'pdf_header_offset': header_offset,
                    'detected_prefix_format': detected_format if detected_format else 'Unknown binary data',
                    'note': f'PDF header at byte {header_offset} - may be polyglot file to evade security'
                }
                logging.warning(f"Polyglot file detected: PDF header at offset {header_offset}")
            elif header_offset > 0:
                # Small offset, might be legitimate but worth noting
                indicators['PolyglotFile'] = {
                    'status': 'Minor offset',
                    'pdf_header_offset': header_offset,
                    'note': f'PDF header at byte {header_offset} (within spec but unusual)'
                }
        
        elif header_offset > 1024:
            # Beyond PDF spec - definitely suspicious
            indicators['PolyglotFile'] = {
                'status': 'CRITICAL: Header beyond spec',
                'pdf_header_offset': header_offset,
                'note': f'PDF header at byte {header_offset} - exceeds 1024 byte limit, likely malicious'
            }
            
    except Exception as e:
        logging.debug(f"Error detecting polyglot file: {e}")


def run_advanced_forensics(txt: str, doc, filepath: Path, indicators: dict):
    """
    Main entry point for advanced forensic detection.
    
    Args:
        txt (str): Raw PDF content as text
        doc: PyMuPDF document object
        filepath (Path): Path to PDF file
        indicators (dict): Dictionary to add indicators to
    """
    try:
        # Get raw bytes for polyglot detection
        pdf_bytes = filepath.read_bytes() if filepath and filepath.exists() else txt.encode('latin-1', errors='ignore')
        
        detect_emails_and_urls(txt, indicators)
        detect_unc_paths(txt, indicators)
        detect_language(doc, indicators)
        detect_encryption_status(doc, txt, indicators)
        detect_hidden_text_patterns(txt, doc, indicators)
        detect_attachments(doc, txt, indicators)
        detect_ocr_layer(doc, txt, indicators)
        detect_3d_and_multimedia(txt, indicators)
        detect_temporal_anomalies(txt, indicators)
        detect_pdf_a_compliance(txt, indicators)
        detect_polyglot_file(pdf_bytes, indicators)
        analyze_pdf_images_qt(doc, filepath, indicators)
        
        logging.info(f"Advanced forensics completed for {filepath.name}")
        
    except Exception as e:
        logging.warning(f"Error in advanced forensics for {filepath.name}: {e}")
