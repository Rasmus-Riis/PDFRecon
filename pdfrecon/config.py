"""
Configuration and Constants Module

Contains application settings, UI constants, custom exceptions, and compiled regex patterns.
"""

import re
import os

# --- Application Version ---
APP_VERSION = "17.3.0"

# --- UI Configuration Constants ---
UI_COLORS = {
    'red_row': '#4a0e0e',
    'red_fg': '#ffcccc',
    'yellow_row': '#4a3c0e',
    'yellow_fg': '#fff4cc',
    'blue_row': '#152a4f',
    'blue_fg': '#99badd',
    'gray_row': '#2a2a2a',
    'selection_blue': '#1F6AA5',
    'progress_blue': '#1F6AA5',
    'link_blue': '#1F6AA5',
    'text_green': '#4CAF50',
    'sidebar_bg': '#2b2b2b',
    'main_bg': '#1e1e1e',
    'accent_blue': '#1F6AA5',
    'accent_blue_hover': '#144870',
    'accent_green': '#2E7D32',
    'accent_green_hover': '#1B5E20',
}

UI_FONTS = {
    'default': ("Segoe UI", 9),
    'bold': ("Segoe UI", 9, "bold"),
    'console': ("Consolas", 10),
    'courier': ("Courier New", 10),
    'title': ("Segoe UI", 11, "bold"),
}

UI_DIMENSIONS = {
    'main_width': 1200,
    'main_height': 700,
    'window_scale_width': 0.75,
    'window_scale_height': 0.8,
    'detail_height': 10,
    'button_width': 25,
    'col_id_width': 40,
    'col_name_width': 150,
    'col_altered_width': 100,
    'col_revisions_width': 80,
    'col_note_width': 50,
}

# --- Application Configuration ---
class PDFReconConfig:
    """Configuration settings for PDFRecon. Values are loaded from config.ini."""
    MAX_FILE_SIZE = 1000 * 1024 * 1024  # 1000MB
    MAX_REVISIONS = 100
    EXIFTOOL_TIMEOUT = 30
    MAX_WORKER_THREADS = min(16, (os.cpu_count() or 4) * 2)
    VISUAL_DIFF_PAGE_LIMIT = 15
    EXPORT_INVALID_XREF = False
    
    # File processing timeouts (from hang prevention improvements)
    TEXT_EXTRACTION_TIMEOUT = 15  # seconds
    FILE_PROCESSING_TIMEOUT = 60  # seconds


# --- Custom Exceptions ---
class PDFProcessingError(Exception):
    """Base exception for PDF processing errors."""
    pass


class PDFCorruptionError(PDFProcessingError):
    """Exception for corrupt or unreadable PDF files."""
    pass


class PDFTooLargeError(PDFProcessingError):
    """Exception for files that exceed the size limit."""
    pass


class PDFEncryptedError(PDFProcessingError):
    """Exception for encrypted files that cannot be read."""
    pass


# --- Compiled Regex Patterns (for OCG/Layers detection and parsing) ---
LAYER_OCGS_BLOCK_RE = re.compile(rb"/OCGs\s*\[(.*?)\]", re.S)
OBJ_REF_RE = re.compile(rb"(\d+)\s+(\d+)\s+R")
LAYER_OC_REF_RE = re.compile(rb"/OC\s+(\d+)\s+(\d+)\s+R")
PDF_DATE_PATTERN = re.compile(r"\/([A-Z][a-zA-Z0-9_]+)\s*\(\s*D:(\d{14})")
KV_PATTERN = re.compile(r'^\[(?P<group>[^\]]+)\]\s*(?P<tag>[\w\-/ ]+?)\s*:\s*(?P<value>.+)$')
DATE_TZ_PATTERN = re.compile(r"^(?P<date>\d{4}[-:]\d{2}[-:]\d{2}[ T]\d{2}:\d{2}:\d{2})(?:\.\d+)?(?P<tz>[+\-]\d{2}:\d{2}|Z)?")
