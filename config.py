import os
import sys
import re
import configparser
import logging
from pathlib import Path

# --- Constants & Regex ---
_LAYER_OCGS_BLOCK_RE = re.compile(rb"/OCGs\s*\[(.*?)\]", re.S)
_OBJ_REF_RE = re.compile(rb"(\d+)\s+(\d+)\s+R")
_LAYER_OC_REF_RE = re.compile(rb"/OC\s+(\d+)\s+(\d+)\s+R")

class PDFReconConfig:
    """Configuration settings for PDFRecon."""
    MAX_FILE_SIZE = 1000 * 1024 * 1024  # 500MB
    MAX_REVISIONS = 100
    EXIFTOOL_TIMEOUT = 30
    MAX_WORKER_THREADS = min(16, (os.cpu_count() or 4) * 2)
    VISUAL_DIFF_PAGE_LIMIT = 15
    EXPORT_INVALID_XREF = False

def resolve_path(filename, base_is_parent=False):
    """
    Resolves the correct path for a resource file, whether running as a script
    or as a frozen executable.
    """
    if getattr(sys, 'frozen', False):
        base_path = Path(sys.executable).parent
        if not base_is_parent:
            return Path(getattr(sys, '_MEIPASS', base_path)) / filename
    else:
        base_path = Path(__file__).resolve().parent
    return base_path / filename

def load_or_create_config(config_path):
    """Loads configuration from config.ini or creates default."""
    parser = configparser.ConfigParser()
    default_lang = "en"
    
    if not config_path.exists():
        logging.info("config.ini not found. Creating with default values.")
        parser['Settings'] = {
            'MaxFileSizeMB': '500',
            'ExifToolTimeout': '30',
            'MaxWorkerThreads': str(PDFReconConfig.MAX_WORKER_THREADS),
            'Language': default_lang,
            'VisualDiffPageLimit': str(PDFReconConfig.VISUAL_DIFF_PAGE_LIMIT),
            'ExportInvalidXREF': 'False'
        }
        try:
            with open(config_path, 'w') as configfile:
                configfile.write("# PDFRecon Configuration File\n")
                parser.write(configfile)
        except IOError as e:
            logging.error(f"Could not write to config.ini: {e}")
            return default_lang

    try:
        parser.read(config_path)
        settings = parser['Settings']
        PDFReconConfig.MAX_FILE_SIZE = settings.getint('MaxFileSizeMB', 500) * 1024 * 1024
        PDFReconConfig.EXIFTOOL_TIMEOUT = settings.getint('ExifToolTimeout', 30)
        PDFReconConfig.MAX_WORKER_THREADS = settings.getint('MaxWorkerThreads', PDFReconConfig.MAX_WORKER_THREADS)
        PDFReconConfig.VISUAL_DIFF_PAGE_LIMIT = settings.getint('VisualDiffPageLimit', 5)
        PDFReconConfig.EXPORT_INVALID_XREF = settings.getboolean('ExportInvalidXREF', False)
        return settings.get('Language', 'en')
    except Exception as e:
        logging.error(f"Could not read config.ini: {e}")
        return default_lang