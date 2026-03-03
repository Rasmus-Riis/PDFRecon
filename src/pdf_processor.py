"""
PDF Processing Module

Contains PDF-specific operations like opening, text extraction, and validation.
"""

import logging
import time
from pathlib import Path
import fitz

from .config import (
    PDFReconConfig, PDFProcessingError, PDFCorruptionError, 
    PDFTooLargeError, PDFEncryptedError
)


def safe_pdf_open(filepath: Path, raw_bytes=None, timeout_seconds=10):
    """
    Safely open a PDF with error handling.
    
    Args:
        filepath: Path to the PDF file
        raw_bytes: Optional raw PDF bytes instead of reading from filepath
        timeout_seconds: Timeout for opening (not strictly enforced by fitz)
        
    Returns:
        fitz.Document: The opened PDF document
        
    Raises:
        PDFCorruptionError: If PDF cannot be opened
    """
    try:
        if raw_bytes:
            doc = fitz.open(stream=raw_bytes, filetype="pdf")
        else:
            doc = fitz.open(str(filepath))
        return doc
    except Exception as e:
        logging.error(f"Error opening PDF {filepath.name}: {e}")
        raise PDFCorruptionError(f"Cannot open PDF: {str(e)}")


def safe_extract_text(raw_bytes=None, doc=None, max_size_mb=50, timeout_seconds=15):
    """
    Safely extract text from PDF with size limits and timeout to prevent hangs.
    
    Args:
        raw_bytes: PDF file bytes
        doc: Already-opened fitz.Document (preferred to avoid double-opening)
        max_size_mb: Maximum file size to extract (skip larger files)
        timeout_seconds: Maximum seconds for extraction before stopping
        
    Returns:
        str: Extracted text or empty string on error
    """
    try:
        # Skip if file is suspiciously large
        if raw_bytes and len(raw_bytes) > max_size_mb * 1024 * 1024:
            logging.warning(f"PDF too large for text extraction: {len(raw_bytes) / (1024*1024):.1f}MB")
            return ""
        
        # Check for suspicious patterns in PDF that might cause hangs
        if raw_bytes and (b"/ObjStm" in raw_bytes or raw_bytes.count(b"stream") > 100):
            logging.warning(f"PDF contains suspicious patterns (streams or object streams), skipping full extraction")
            return ""
        
        # If no doc provided, open it from raw_bytes
        should_close_doc = False
        if doc is None:
            if not raw_bytes:
                return ""
            doc = fitz.open(stream=raw_bytes, filetype="pdf")
            should_close_doc = True
        
        start_time = time.time()
        txt = ""
        page_count = len(doc)
        
        # Limit extraction to first 1000 pages or first 50MB of text
        for page_num in range(min(1000, page_count)):
            # Check timeout every 10 pages
            if page_num % 10 == 0 and time.time() - start_time > timeout_seconds:
                logging.warning(f"Text extraction timeout after {time.time() - start_time:.1f}s, stopping at page {page_num}/{page_count}")
                break
                
            try:
                page = doc[page_num]
                page_text = page.get_text()
                txt += page_text
            except Exception as page_error:
                logging.warning(f"Error extracting page {page_num}: {page_error}")
                continue
                
            if len(txt) > 50 * 1024 * 1024:  # 50MB of text
                logging.warning(f"Text extraction exceeded 50MB limit, stopping at page {page_num}/{page_count}")
                break
        
        if should_close_doc and doc:
            doc.close()
            
        logging.info(f"Successfully extracted {len(txt)} characters from {page_count} pages")
        return txt
    except Exception as e:
        logging.warning(f"Could not extract text from PDF: {e}")
        return ""


def validate_pdf_file(filepath: Path) -> bool:
    """
    Validates a PDF file based on size, header, and encryption.
    
    Args:
        filepath: Path to the PDF file to validate
        
    Returns:
        bool: True if valid
        
    Raises:
        PDFTooLargeError: If file exceeds MAX_FILE_SIZE
        PDFEncryptedError: If file is encrypted and unreadable
        PDFCorruptionError: If file is corrupt or invalid
        PDFProcessingError: For other validation errors
    """
    try:
        # Check file size
        file_size = filepath.stat().st_size
        if file_size > PDFReconConfig.MAX_FILE_SIZE:
            raise PDFTooLargeError(f"File size {file_size / (1024**2):.1f}MB exceeds limit of {PDFReconConfig.MAX_FILE_SIZE / (1024**2):.1f}MB")
        
        # Check if file starts with PDF header
        with filepath.open("rb") as f:
            header = f.read(4)
            if header != b"%PDF":
                raise PDFCorruptionError("Invalid PDF header")
        
        # Try to open the PDF to check for encryption and basic validity
        try:
            doc = fitz.open(str(filepath))
            if doc.is_encrypted:
                doc.close()
                raise PDFEncryptedError("PDF is password-encrypted and cannot be read")
            doc.close()
        except fitz.FileError:
            raise PDFCorruptionError("File is not a valid PDF")
        
        return True
        
    except PDFProcessingError:
        raise
    except Exception as e:
        raise PDFProcessingError(f"Unexpected error validating PDF: {str(e)}")


def count_layers(pdf_bytes: bytes) -> int:
    """
    Conservatively counts OCGs (layers) in PDF bytes.
    
    1) Finds /OCGs [ ... ] and collects all indirect refs "n m R".
    2) Also finds /OC n m R in content/resources.
    3) Deduplicates (n, gen).
    
    Args:
        pdf_bytes: Raw PDF file bytes
        
    Returns:
        int: Count of unique layers found
    """
    from .config import LAYER_OCGS_BLOCK_RE, OBJ_REF_RE, LAYER_OC_REF_RE
    
    refs = set()
    
    m = LAYER_OCGS_BLOCK_RE.search(pdf_bytes)
    if m:
        for n, g in OBJ_REF_RE.findall(m.group(1)):
            refs.add((int(n), int(g)))
    
    for n, g in LAYER_OC_REF_RE.findall(pdf_bytes):
        refs.add((int(n), int(g)))
    
    return len(refs)
