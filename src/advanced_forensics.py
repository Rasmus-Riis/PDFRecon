"""
Advanced Forensic Detection for PDFRecon
Extracts additional forensic indicators: emails, URLs, UNC paths, language,
encryption status, hidden text patterns, attachments, OCR layers, multimedia, etc.
"""

import re
import io
import logging
import hashlib
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image, ImageChops, ImageStat
except ImportError:
    Image = None

from .jpeg_forensics import analyze_pdf_images_qt


def detect_emails_and_urls(txt: str, indicators: dict):
    """Extract email addresses and URLs from PDF content."""
    try:
        # Email pattern (more restrictive)
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'
        raw_emails = set()
        if "@" in txt:
            raw_emails = set(re.findall(email_pattern, txt))
        
        # Validation: Filter out garbage (random binary strings often look like short emails)
        emails = []
        valid_tlds = {
            'com', 'org', 'net', 'edu', 'gov', 'mil', 'int', 'info', 'biz', 'app', 'dev', 'io', 'co', 'me', 'ai', 'tv', 'mobi', 'name', 'pro', 'aero', 'asia', 'jobs', 'museum', 'tel', 'travel',
            'ac', 'ad', 'ae', 'af', 'ag', 'ai', 'al', 'am', 'ao', 'aq', 'ar', 'as', 'at', 'au', 'aw', 'ax', 'az', 'ba', 'bb', 'bd', 'be', 'bf', 'bg', 'bh', 'bi', 'bj', 'bl', 'bm', 'bn', 'bo', 'bq', 'br', 'bs', 'bt', 'bv', 'bw', 'by', 'bz', 'ca', 'cc', 'cd', 'cf', 'cg', 'ch', 'ci', 'ck', 'cl', 'cm', 'cn', 'co', 'cr', 'cu', 'cv', 'cw', 'cx', 'cy', 'cz', 'de', 'dj', 'dk', 'dm', 'do', 'dz', 'ec', 'ee', 'eg', 'eh', 'er', 'es', 'et', 'eu', 'fi', 'fj', 'fk', 'fm', 'fo', 'fr', 'ga', 'gb', 'gd', 'ge', 'gf', 'gg', 'gh', 'gi', 'gl', 'gm', 'gn', 'gp', 'gq', 'gr', 'gs', 'gt', 'gu', 'gw', 'gy', 'hk', 'hm', 'hn', 'hr', 'ht', 'hu', 'id', 'ie', 'il', 'im', 'in', 'io', 'iq', 'ir', 'is', 'it', 'je', 'jm', 'jo', 'jp', 'ke', 'kg', 'kh', 'ki', 'km', 'kn', 'kp', 'kr', 'kw', 'ky', 'kz', 'la', 'lb', 'lc', 'li', 'lk', 'lr', 'ls', 'lt', 'lu', 'lv', 'ly', 'ma', 'mc', 'md', 'me', 'mf', 'mg', 'mh', 'mk', 'ml', 'mm', 'mn', 'mo', 'mp', 'mq', 'mr', 'ms', 'mt', 'mu', 'mv', 'mw', 'mx', 'my', 'mz', 'na', 'nc', 'ne', 'nf', 'ng', 'ni', 'nl', 'no', 'np', 'nr', 'nu', 'nz', 'om', 'pa', 'pe', 'pf', 'pg', 'ph', 'pk', 'pl', 'pm', 'pn', 'pr', 'ps', 'pt', 'pw', 'py', 'qa', 're', 'ro', 'rs', 'ru', 'rw', 'sa', 'sb', 'sc', 'sd', 'se', 'sg', 'sh', 'si', 'sj', 'sk', 'sl', 'sm', 'sn', 'so', 'sr', 'ss', 'st', 'su', 'sv', 'sx', 'sy', 'sz', 'tc', 'td', 'tf', 'tg', 'th', 'tj', 'tk', 'tl', 'tm', 'tn', 'to', 'tr', 'tt', 'tv', 'tw', 'tz', 'ua', 'ug', 'uk', 'um', 'us', 'uy', 'uz', 'va', 'vc', 've', 'vg', 'vi', 'vn', 'vu', 'wf', 'ws', 'ye', 'yt', 'za', 'zm', 'zw'
        }
        
        for email in raw_emails:
            # Must be at least 7 chars (e.g. a@b.com is 7)
            if len(email) < 7: continue
            
            # Must have a dot in the domain part
            parts = email.split('@')
            if len(parts) != 2 or '.' not in parts[1]: continue
            
            username = parts[0]
            domain_part = parts[1]
            tld = domain_part.split('.')[-1].lower()
            domain_body = domain_part.rsplit('.', 1)[0]
            
            # Basic boundary checks
            if username.startswith('-') or username.endswith('-'): continue
            if domain_body.startswith('-') or domain_body.endswith('-'): continue
            
            # TLD allowlist approach ensures random bytes like .TX or .ZU are dropped completely
            if tld not in valid_tlds: continue

            # Heuristics to catch random binary interpretations
            # 1. Too many numbers
            if sum(1 for c in email if c.isdigit()) > len(email) * 0.4: continue
            
            # 2. Vowel-to-consonant ratio
            vowels = sum(1 for c in email if c.lower() in 'aeiouy')
            consonants = sum(1 for c in email if c.lower() in 'bcdfghjklmnpqrstvwxz')
            if vowels == 0: continue
            if (consonants / len(email)) > 0.8: continue
            
            # 3. Random mixed case (e.g., aBcDeF)
            domain_letters = [c for c in domain_part if c.isalpha()]
            uppers = sum(1 for c in domain_letters if c.isupper())
            lowers = sum(1 for c in domain_letters if c.islower())
            if uppers >= 2 and lowers >= 2: continue # Real domains are rarely camelCase in extracted text
            
            # 4. Filter out obviously repetitive patterns
            if re.search(r'(.)\1{3,}', email): continue
            
            emails.append(email)
        
        if emails:
            indicators['EmailAddresses'] = {
                'count': len(emails),
                'emails': sorted(emails)[:20]  # Show more to user
            }
        
        # URL pattern (http, https, ftp)
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        raw_urls = set()
        txt_lower = txt.lower()
        if "http" in txt_lower:
            raw_urls = set(re.findall(url_pattern, txt, re.IGNORECASE))

        # Clean URLs and filter common metadata namespaces
        urls = set()
        exclude_domains = {'ns.adobe.com', 'www.w3.org', 'purl.org', 'xml.org', 'schemas.microsoft.com', 'iptc.org'}
        for url in raw_urls:
            clean_url = url.rstrip('.,;:?!)]')
            if clean_url:
                try:
                    domain = clean_url.split('://')[1].split('/')[0].lower()
                    if domain not in exclude_domains:
                        urls.add(clean_url)
                except Exception:
                    urls.add(clean_url)
        
        if urls:
            # Categorize by domain
            domains = {}
            for url in urls:
                try:
                    domain = url.split('://')[1].split('/')[0]
                    if domain not in domains:
                        domains[domain] = []
                    domains[domain].append(url)
                except Exception:
                    pass
            
            indicators['URLs'] = {
                'count': len(urls),
                'unique_domains': len(domains),
                'domains': sorted(list(domains.keys()))[:20]  # Show more
            }
            
    except Exception as e:
        logging.debug(f"Error detecting emails/URLs: {e}")


def detect_unc_paths(txt: str, indicators: dict):
    """Extract UNC paths revealing internal network structure."""
    try:
        # UNC path pattern: \\servername\share\path
        # Require server name and share name (at least 2 slashes total including prefix)
        unc_pattern = r'\\\\[a-zA-Z0-9_\-\.]+\\[a-zA-Z0-9_\-\.\$\\]+'
        raw_paths = set()
        if "\\\\" in txt:
            raw_paths = set(re.findall(unc_pattern, txt))
        
        unc_paths = []
        for path in raw_paths:
            # Validation: Legitimate share names are usually > 2 chars, and don't look like base64 junk
            parts = path.lstrip('\\').split('\\')
            if len(parts) >= 2 and len(parts[0]) >= 3 and len(parts[1]) >= 3:
                # Check for random garbage characteristics
                letters = [c for c in path if c.isalpha()]
                vowels = sum(1 for c in letters if c.lower() in 'aeiouy')
                if len(letters) > 0 and vowels == 0: continue
                
                # Mixed case is suspicious in UNC paths unless it's predictable
                uppers = sum(1 for c in letters if c.isupper())
                lowers = sum(1 for c in letters if c.islower())
                if uppers >= 2 and lowers >= 2: continue
                
                # Too many numbers?
                if sum(1 for c in path if c.isdigit()) > len(path) * 0.4: continue
                
                unc_paths.append(path)
        
        if unc_paths:
            indicators['UNCPaths'] = {
                'count': len(unc_paths),
                'paths': sorted(unc_paths)[:10]
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
        except Exception:
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
        if "/Encrypt" in txt and re.search(r'/Encrypt\s+\d+\s+\d+\s+R', txt):
            if 'Encrypted' not in indicators:
                indicators['EncryptionDictionary'] = {'status': 'Encryption dictionary present'}
                
        # Check for security settings
        if "/P" in txt and re.search(r'/P\s+-?\d+', txt):  # Permissions integer
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
        if "Tr" in txt and re.search(r'\s3\s+Tr\b', txt):
            indicators['InvisibleTextMode'] = {'status': 'Text rendering mode 3 (invisible) detected'}
        
        # Check for white color (1 1 1 RG or #FFFFFF)
        white_color_matches = 0
        if "rg" in txt or "RG" in txt:
            white_color_matches = len(re.findall(r'\b1\s+1\s+1\s+(rg|RG)\b', txt))
        if white_color_matches > 20:  # Threshold for suspicion
            indicators['ExcessiveWhiteColor'] = {
                'count': white_color_matches,
                'note': 'High usage of white color may indicate content hiding'
            }
        
        # Check for text outside MediaBox (hidden off-page) and Hidden Annotations
        # This requires page-by-page analysis
        if doc:
            hidden_annots = []
            for page_num in range(min(len(doc), 10)):  # Check first 10 pages only
                try:
                    page = doc[page_num]
                    blocks = page.get_text("dict")["blocks"]
                    
                    # 1. Overlay Annotation Check
                    for annot in page.annots():
                        flags = annot.flags
                        # Flags reference: Bit 1 (Invisible: 1), Bit 2 (Hidden: 2), Bit 6 (NoView: 32)
                        # https://pymupdf.readthedocs.io/en/latest/annotation.html#annotation-flags
                        is_hidden = flags & 2
                        is_invisible = flags & 1
                        is_noview = flags & 32
                        
                        if is_hidden or is_invisible or is_noview:
                            hidden_annots.append({
                                'page': page_num + 1,
                                'type': annot.type[1],
                                'flags': flags,
                                'rect': [(int(x)) for x in annot.rect]
                            })
                            
                    # 2. MediaBox Boundary Check
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
                except Exception:
                    pass
                    
            if hidden_annots:
                indicators['HiddenAnnotations'] = {
                    'count': len(hidden_annots),
                    'details': hidden_annots[:5] # Show limits for GUI
                }
                    
    except Exception as e:
        logging.debug(f"Error detecting hidden text patterns: {e}")


def detect_attachments(doc, txt: str, indicators: dict):
    """Detect embedded file attachments."""
    try:
        txt_lower = txt.lower()
        # Check for embedded files
        if "embeddedfile" in txt_lower and re.search(r'/Type\s*/EmbeddedFile', txt, re.IGNORECASE):
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
        if "fileattachment" in txt_lower and re.search(r'/Subtype\s*/FileAttachment', txt):
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
                        except Exception:
                            pass
                    
                    # Get page area
                    page_area = (page.rect.width * page.rect.height)
                    
                    # If images cover > 80% of page, likely scanned
                    if page_area > 0 and (image_area / page_area) > 0.8:
                        text_over_image_ratio += 1
                        
            except Exception:
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
        if "/3D" in txt and re.search(r'/Subtype\s*/3D', txt):
            indicators['3DObjects'] = {'status': 'PDF contains 3D objects'}
        
        # Check for multimedia (sound, video)
        if "/Sound" in txt and re.search(r'/Subtype\s*/Sound', txt):
            indicators['SoundAnnotations'] = {'status': 'PDF contains sound annotations'}
        
        if ("/Movie" in txt or "/Screen" in txt) and (re.search(r'/Subtype\s*/Movie', txt) or re.search(r'/Subtype\s*/Screen', txt)):
            indicators['VideoContent'] = {'status': 'PDF contains video/multimedia content'}
        
        # Check for RichMedia (Flash, etc.)
        if "/RichMedia" in txt and re.search(r'/Subtype\s*/RichMedia', txt):
            indicators['RichMedia'] = {
                'status': 'PDF contains RichMedia (potentially Flash)',
                'note': 'High security risk - may execute code'
            }
            
    except Exception as e:
        logging.debug(f"Error detecting 3D/multimedia: {e}")


def detect_temporal_anomalies(txt: str, indicators: dict):
    """Detect future-dated timestamps and temporal inconsistencies."""
    try:
        now = datetime.now()
        
        # Extract timestamps from PDF
        # Pattern: D:YYYYMMDDHHmmSS or D:YYYYMMDD
        dates = []
        if "D:" in txt:
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
            except Exception:
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
        txt_lower = txt.lower()
        # Check for PDF/A identifier in XMP metadata
        if "pdfaid:part" in txt_lower and re.search(r'pdfaid:part', txt, re.IGNORECASE):
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
        
        detect_ela_anomalies(doc, indicators)
        detect_text_operator_anomalies(txt, indicators)
        detect_timestamp_mismatches(txt, doc, indicators)
        detect_page_inconsistencies(doc, indicators)
        detect_color_space_anomalies(doc, indicators)

        # New Forensic Features (v17.6)
        detect_non_embedded_fonts(doc, indicators)
        detect_xmp_history_gaps(txt, indicators)
        detect_structural_scrubbing(pdf_bytes, indicators)
        detect_pdfa_violations(doc, txt, indicators)

        # Suspicious JPEG Analysis
        analyze_pdf_images_qt(doc, filepath, indicators)
        
        logging.info(f"Advanced forensics completed for {filepath.name}")
        
    except Exception as e:
        logging.warning(f"Error in advanced forensics for {filepath.name}: {e}")

def detect_ela_anomalies(doc, indicators: dict):
    """
    Performs Error Level Analysis (ELA) on embedded images to detect manipulation.
    Resaves the image at 95% JPEG quality and computes the difference.
    """
    if not doc or Image is None:
        return
    try:
        ela_findings = []
        for page_num in range(min(len(doc), 50)):  # Cap at 50 pages for performance
            page = doc[page_num]
            for img_info in page.get_images():
                xref = img_info[0]
                try:
                    img_dict = doc.extract_image(xref)
                    if not img_dict:
                        continue
                    
                    img = Image.open(io.BytesIO(img_dict["image"])).convert("RGB")
                    
                    tmp_io = io.BytesIO()
                    img.save(tmp_io, 'JPEG', quality=95)
                    tmp_io.seek(0)
                    
                    resaved_img = Image.open(tmp_io)
                    diff = ImageChops.difference(img, resaved_img)
                    
                    extrema = diff.getextrema()
                    max_diff = max([ex[1] for ex in extrema])
                    
                    if max_diff == 0: continue
                    
                    scale = 255.0 / max_diff
                    diff = diff.point(lambda i: i * scale)
                    
                    stat = ImageStat.Stat(diff)
                    avg_error = sum(stat.mean) / len(stat.mean)
                    std_dev = sum(stat.stddev) / len(stat.stddev)
                    
                    # Thresholds for ELA anomalies finding local hotspots
                    if std_dev > 45 and avg_error > 15:
                        ela_findings.append({
                            'page': page_num + 1,
                            'xref': xref,
                            'variance': round(std_dev, 2)
                        })
                except Exception:
                    pass
        if ela_findings:
            indicators['ErrorLevelAnalysis'] = {
                'count': len(ela_findings),
                'findings': ela_findings[:10]
            }
    except Exception as e:
        logging.debug(f"ELA error: {e}")

def detect_text_operator_anomalies(txt: str, indicators: dict):
    """Detect text positioning operations used to obscure or misalign text."""
    try:
        # Detect large negative values in TJ arrays (e.g., [ (T) -2000 (e) ])
        tj_anomalies = 0
        if "-" in txt:
            tj_anomalies = len(re.findall(r"-\d{4,}\s+(?=\(|<)", txt))
        
        # Word spacing (Tw) or Character spacing (Tc) being excessively large
        tw_anomalies = 0
        if "Tw" in txt:
            tw_anomalies = len(re.findall(r"(?:^|[^0-9\.])(1[0-9]{2,}|-[1-9][0-9]+)\s+Tw\b", txt))
        tc_anomalies = 0
        if "Tc" in txt:
            tc_anomalies = len(re.findall(r"(?:^|[^0-9\.])(1[0-9]{2,}|-[1-9][0-9]+)\s+Tc\b", txt))
        
        total = tj_anomalies + tw_anomalies + tc_anomalies
        if total > 0:
            indicators['TextOperatorAnomaly'] = {
                'count': total,
                'tj_large_kerning': tj_anomalies,
                'extreme_spacing': tw_anomalies + tc_anomalies
            }
    except Exception as e:
        logging.debug(f"Text Operator error: {e}")

def detect_timestamp_mismatches(txt: str, doc, indicators: dict):
    """Compare document Info dictionary dates with XMP creation/modify dates."""
    try:
        def parse_pdf_date(date_str):
            if not date_str: return None
            clean = re.sub(r"[^0-9]", "", date_str)
            if len(clean) >= 14:
                try:
                    return datetime.strptime(clean[:14], "%Y%m%d%H%M%S")
                except Exception:
                    pass
            return None

        info_create = None
        info_mod = None
        if doc and hasattr(doc, 'metadata') and isinstance(doc.metadata, dict):
            info_create = parse_pdf_date(doc.metadata.get('creationDate', ''))
            info_mod = parse_pdf_date(doc.metadata.get('modDate', ''))
            
        xmp_create_match = re.search(r"<xmp:CreateDate>([^<]+)", txt) if "CreateDate" in txt else None
        xmp_mod_match = re.search(r"<xmp:ModifyDate>([^<]+)", txt) if "ModifyDate" in txt else None
        
        xmp_create = parse_pdf_date(xmp_create_match.group(1)) if xmp_create_match else None
        xmp_mod = parse_pdf_date(xmp_mod_match.group(1)) if xmp_mod_match else None
        
        mismatches = []
        if info_create and xmp_create and abs((info_create - xmp_create).total_seconds()) > 60:
            mismatches.append(f"Creation: Info({info_create.strftime('%Y-%m-%d')}) != XMP({xmp_create.strftime('%Y-%m-%d')})")
            
        if info_mod and xmp_mod and abs((info_mod - xmp_mod).total_seconds()) > 60:
            mismatches.append(f"Modify: Info({info_mod.strftime('%Y-%m-%d')}) != XMP({xmp_mod.strftime('%Y-%m-%d')})")
            
        # Timestamp Spoofing Sanity Check
        # A file cannot be modified before it was created
        if info_create and info_mod and info_create > info_mod:
            # Allow a tiny drift of a few seconds for timezone/system clock edge cases
            if (info_create - info_mod).total_seconds() > 60:
                indicators['TimestampSpoofing'] = {
                    'note': f"CRITICAL: CreationDate ({info_create.strftime('%Y-%m-%d %H:%M:%S')}) occurs AFTER ModDate ({info_mod.strftime('%Y-%m-%d %H:%M:%S')})."
                }
            
        if mismatches:
            indicators['TimestampMismatch'] = {
                'count': len(mismatches),
                'details': mismatches
            }
    except Exception as e:
        logging.debug(f"Timestamp mismatch computing error: {e}")

def detect_page_inconsistencies(doc, indicators: dict):
    """Detect individual pages that deviate starkly from the document's dimensions or rotation."""
    if not doc or len(doc) <= 1:
        return
    try:
        dimensions = {}
        rotations = {}
        for i in range(len(doc)):
            page = doc[i]
            r = page.rect
            w_h = round(r.width, 1), round(r.height, 1)
            dimensions[w_h] = dimensions.get(w_h, 0) + 1
            
            rot = page.rotation
            rotations[rot] = rotations.get(rot, 0) + 1
            
        dominant_dim = max(dimensions, key=dimensions.get)
        dominant_rot = max(rotations, key=rotations.get)
        
        anomalous_pages = []
        if dimensions[dominant_dim] / len(doc) >= 0.75:
            for i in range(len(doc)):
                r = doc[i].rect
                w_h = round(r.width, 1), round(r.height, 1)
                if w_h != dominant_dim:
                    anomalous_pages.append({'page': i+1, 'type': f'Dimensions {w_h}'})
                    
        if rotations[dominant_rot] / len(doc) >= 0.75:
            for i in range(len(doc)):
                rot = doc[i].rotation
                if rot != dominant_rot:
                    anomalous_pages.append({'page': i+1, 'type': f'Rotation {rot}° (expected {dominant_rot}°)'})
                    
        if anomalous_pages:
            indicators['PageInconsistency'] = {
                'count': len(anomalous_pages),
                'pages': anomalous_pages[:10]
            }
    except Exception as e:
        logging.debug(f"Page inconsistency check error: {e}")

def detect_color_space_anomalies(doc, indicators: dict):
    """Identify manually inserted graphics by anomalous color spaces."""
    if not doc: return
    try:
        color_spaces = {'DeviceRGB': 0, 'DeviceCMYK': 0, 'DeviceGray': 0, 'Indexed': 0, 'Other': 0}
        anomalies = []
        
        for i in range(min(len(doc), 50)):
            for img in doc[i].get_images():
                cs = img[5]
                if not cs: 
                    color_spaces['Other'] += 1
                elif 'RGB' in cs:
                    color_spaces['DeviceRGB'] += 1
                elif 'CMYK' in cs:
                    color_spaces['DeviceCMYK'] += 1
                elif 'Gray' in cs:
                    color_spaces['DeviceGray'] += 1
                elif 'Indexed' in cs:
                    color_spaces['Indexed'] += 1
                else:
                    color_spaces['Other'] += 1
                    
        total = sum(color_spaces.values())
        if total > 5:
            dominant = max(color_spaces, key=color_spaces.get)
            if color_spaces[dominant] / total > 0.8:
                for cs, count in color_spaces.items():
                    if cs != dominant and count > 0 and count <= total * 0.15:
                        anomalies.append(f"{count} {cs} image(s) vs dominant {dominant}")
                        
        if anomalies:
            indicators['ColorSpaceAnomaly'] = {
                'count': len(anomalies),
                'details': anomalies
            }
    except Exception as e:
        logging.debug(f"Color space check error: {e}")


def detect_non_embedded_fonts(doc, indicators: dict):
    """Scrutinize fonts to ensure they are embedded in the PDF."""
    if not doc: return
    try:
        non_embedded = []
        for xref in range(1, doc.xref_length()):
            if doc.xref_is_font(xref):
                # Font dictionaries for embedded fonts should contain FontFile, FontFile2, or FontFile3
                font_dict = doc.xref_object(xref)
                if not any(f in font_dict for f in {"/FontFile", "/FontFile2", "/FontFile3"}):
                    # Get font name
                    res = doc.xref_get_key(xref, "BaseFont")
                    name = res[1][1:] if res[0] == "name" else f"xref {xref}"
                    non_embedded.append(name)
        
        if non_embedded:
            indicators['NonEmbeddedFont'] = {
                'count': len(non_embedded),
                'fonts': list(set(non_embedded))[:10]
            }
    except Exception as e:
        logging.debug(f"Error detecting non-embedded fonts: {e}")


def detect_xmp_history_gaps(txt: str, indicators: dict):
    """Detect missing links or unusual time jumps in XMP metadata history."""
    try:
        # Extract XMP history items
        items = []
        if "stEvt:when" in txt:
            items = re.findall(r"<rdf:li[^>]*stEvt:instanceID=\"([^\"]+)\"[^>]*stEvt:when=\"([^\"]+)\"", txt)
            if not items:
                # Try alternate XML format
                items = re.findall(r"<stEvt:instanceID>([^<]+)</stEvt:instanceID>.*?<stEvt:when>([^<]+)</stEvt:when>", txt, re.S)
        
        if len(items) > 1:
            gaps = []
            for i in range(len(items) - 1):
                try:
                    # Check for ID sequence gaps if they look like v1, v2, v3...
                    # (Note: Many tools use random UUIDs, so we prioritize timestamp gaps)
                    d1_str = items[i][1].replace('Z', '+00:00').split('.')[0]
                    d2_str = items[i+1][1].replace('Z', '+00:00').split('.')[0]
                    
                    # Convert to datetime
                    fmt = "%Y-%m-%dT%H:%M:%S"
                    dt1 = datetime.strptime(d1_str[:19], fmt)
                    dt2 = datetime.strptime(d2_str[:19], fmt)
                    
                    # If time jumps backwards or has a huge multi-year gap unexpectedly
                    diff = (dt2 - dt1).total_seconds()
                    if diff < 0:
                        gaps.append(f"Reverse sequence: {items[i+1][1]} occurs before {items[i][1]}")
                    elif diff > 31536000 * 2: # 2 years
                        gaps.append(f"Large history gap (>2 years) between revisions")
                except Exception:
                    continue
            
            if gaps:
                indicators['XMPHistoryGap'] = {
                    'count': len(gaps),
                    'details': gaps
                }
    except Exception as e:
        logging.debug(f"Error detecting XMP history gaps: {e}")


def detect_structural_scrubbing(pdf_bytes: bytes, indicators: dict):
    """Detect large blocks of nulls or spaces suggestive of manual data scrubbing."""
    try:
        findings = []
        # Look for 200+ consecutive null bytes
        null_runs = 0
        if b"\x00" * 200 in pdf_bytes:
            null_runs = len(re.findall(b"\x00{200,}", pdf_bytes))
        if null_runs > 0:
            findings.append(f"Found {null_runs} block(s) of 200+ null bytes (potential scrubbing)")
            
        # Look for 1000+ consecutive space characters
        space_runs = 0
        if b" " * 1000 in pdf_bytes:
            space_runs = len(re.findall(b" {1000,}", pdf_bytes))
        if space_runs > 0:
            findings.append(f"Found {space_runs} block(s) of 1000+ spaces (potential manual white-out)")
            
        if findings:
            indicators['StructuralScrubbing'] = {
                'count': len(findings),
                'details': findings
            }
    except Exception as e:
        logging.debug(f"Error detecting structural scrubbing: {e}")


def detect_pdfa_violations(doc, txt: str, indicators: dict):
    """Check if a self-proclaimed PDF/A file violates its own strict standards."""
    if 'PDFACompliance' not in indicators:
        return
    
    try:
        violations = []
        # 1. PDF/A must not be encrypted
        if doc.is_encrypted:
            violations.append("Document claims PDF/A but is encrypted")
            
        # 2. PDF/A must not have JavaScript
        if 'ContainsJavaScript' in indicators:
            violations.append("Document claims PDF/A but contains JavaScript")
            
        # 3. PDF/A must embed all fonts
        if 'NonEmbeddedFont' in indicators:
            violations.append("Document claims PDF/A but has non-embedded fonts")
            
        if violations:
            indicators['PDFAViolation'] = {
                'count': len(violations),
                'details': violations,
                'note': "PDF/A status is falsified or broken"
            }
    except Exception as e:
        logging.debug(f"Error detecting PDF/A violations: {e}")
