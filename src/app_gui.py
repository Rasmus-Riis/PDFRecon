import customtkinter as ctk
from tkinter import filedialog, messagebox, Menu
import tkinter as tk
from tkinter import ttk, Toplevel
import os
import sys
import logging
import tempfile
import multiprocessing
import configparser
import json
from pathlib import Path

# --- Helper function for safe dependency imports ---
from .utils import _import_with_fallback, md5_file

TkinterDnD = _import_with_fallback('tkinterdnd2', 'TkinterDnD', 'tkinterdnd2')
from tkinterdnd2 import DND_FILES, TkinterDnD

# --- Import configuration and version ---
from .config import PDFReconConfig, PDFProcessingError, PDFCorruptionError, \
    PDFTooLargeError, PDFEncryptedError, APP_VERSION, UI_COLORS, UI_FONTS, UI_DIMENSIONS, \
    KV_PATTERN, DATE_TZ_PATTERN

from .ui_layout import UILayoutMixin
from .actions import ActionsMixin
from .popups import PopupsMixin
from .export_logic import ExportMixin
from .data_processing import DataProcessingMixin

class PDFReconApp(UILayoutMixin, ActionsMixin, PopupsMixin, ExportMixin, DataProcessingMixin):

    def __init__(self, root):
        """Initialize the PDFRecon application."""
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")
        
        self.app_version = APP_VERSION
        self.root = root

        # Ensure correct Windows taskbar grouping/icon (exe icon alone is not enough for Tk apps)
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PDFRecon")
            except Exception:
                pass
        
        self.is_reader_mode = "reader" in Path(sys.executable).stem.lower()
        
        self.config_path = self._resolve_path("config.ini", base_is_parent=True)
        self._load_or_create_config()
        
        self._setup_window()
        self._initialize_data()
        self._initialize_state()
        
        self.language = tk.StringVar(value=self.default_language)
        self.filter_var = tk.StringVar()
        self.search_var = tk.StringVar()
        
        self._setup_logging()
        self.translations = self.get_translations() 
        self._setup_styles()
        self._setup_menu()
        self._setup_main_frame()
        self._setup_drag_and_drop()
        
        logging.info(f"PDFRecon v{self.app_version} started in {'Reader' if self.is_reader_mode else 'Full'} mode.")

        self._check_exiftool_availability()

        if self.is_reader_mode:
            self.root.after(100, self._autoload_case_in_reader)

    def _check_exiftool_availability(self):
        if getattr(sys, 'frozen', False):
            base_dir = Path(sys.executable).parent
        else:
            base_dir = Path(__file__).parent.parent
        
        exiftool_exe = base_dir / "exiftool.exe"
        exiftool_dir = base_dir / "exiftool_files"
        
        missing_items = []
        if not exiftool_exe.exists():
            missing_items.append("exiftool.exe")
        if not exiftool_dir.exists() or not exiftool_dir.is_dir():
            missing_items.append("exiftool_files directory")
        
        if missing_items:
            lang = self.language.get() if hasattr(self, 'language') else self.default_language
            trans = self.translations.get(lang, self.translations.get('en', {}))
            
            title = trans.get("exiftool_warning_title", "ExifTool Not Found")
            message = trans.get("exiftool_warning_message", 
                "ExifTool components are missing for best results:\n\n{items}\n\nPlease ensure exiftool.exe and the exiftool_files directory are in the same folder as PDFRecon.exe.")
            
            missing_text = "\n".join([f"• {item}" for item in missing_items])
            messagebox.showwarning(title, message.format(items=missing_text))
            logging.warning(f"ExifTool components missing: {', '.join(missing_items)}")

    def _setup_window(self):
        title = f"PDFRecon Reader v{self.app_version}" if self.is_reader_mode else f"PDFRecon v{self.app_version}"
        self.base_title = title
        self.root.title(title)
        self.root.geometry("1600x900")
        self.inspector_window = None
        self.inspector_doc = None
        self.inspector_pdf_update_job = None
        
        try:
            icon_path = self._resolve_path('icon.ico')
            if icon_path.exists():
                # Title bar icon (and often taskbar icon)
                self.root.iconbitmap(default=str(icon_path))
                # Some Tk builds prefer explicit iconbitmap call too
                try:
                    self.root.iconbitmap(str(icon_path))
                except Exception:
                    pass
            else:
                logging.warning("icon.ico not found. Using default icon.")
        except tk.TclError:
            logging.warning("Could not load icon.ico. Using default icon.")
        except Exception as e:
            logging.error(f"Unexpected error when loading icon: {e}")

    def _initialize_data(self):
        self.report_data = [] 
        self.all_scan_data = {}
        self.last_scan_folder = None 
        self.case_root_path = None
        self.current_case_filepath = None
        self.file_annotations = {}
        self.dirty_notes = set()
        self.evidence_hashes = {}
        self.exif_outputs = {}
        self.timeline_data = {}
        self.path_to_id = {}
        self.scan_start_time = 0

    def _initialize_state(self):
        self.revision_counter = 0
        self.scan_queue = multiprocessing.Queue() if hasattr(multiprocessing, 'Queue') else None
        # Use queue.Queue as fallback which is defined in actions
        self.copy_executor = None
        self.case_is_dirty = False       
        self.tree_sort_column = None
        self.tree_sort_reverse = False
        self.exif_popup = None
        self.indicator_popup = None
        self._progress_max = 1
        self._progress_current = 0

    def _center_window(self, window, width_scale=0.5, height_scale=0.5):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = int(sw * width_scale)
        h = int(sh * height_scale)
        x = (sw - w) // 2
        y = (sh - h) // 2
        window.geometry(f"{w}x{h}+{x}+{y}")
        return w, h

    def _show_message(self, msg_type, title, message, parent=None):
        if parent is None:
            parent = self.root
        message_funcs = {
            "error": messagebox.showerror,
            "warning": messagebox.showwarning,
            "info": messagebox.showinfo
        }
        msg_func = message_funcs.get(msg_type, messagebox.showinfo)
        return msg_func(title, message, parent=parent)

    def _safe_read_file(self, filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            logging.error(f"File not found: {filepath}")
            return None
        except Exception as e:
            logging.error(f"Error reading {filepath}: {e}")
            return None

    def _safe_write_file(self, filepath, content):
        try:
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            logging.info(f"File written successfully: {filepath}")
            return True
        except Exception as e:
            logging.error(f"Error writing to {filepath}: {e}")
            return False

    def _handle_file_processing_error(self, filepath, error_type, error):
        error_log = f"Error processing {filepath.name}: {error}"
        logging.warning(error_log)
        return {
            "path": filepath,
            "status": "error",
            "error_type": error_type,
            "error_message": str(error)
        }

    def _update_menu_state(self, menu_item_index, state="normal"):
        try:
            if hasattr(self, 'file_menu'):
                self.file_menu.entryconfig(menu_item_index, state=state)
        except Exception as e:
            logging.debug(f"Could not update menu state: {e}")

    def _safe_pdf_open(self, filepath, raw_bytes=None, timeout_seconds=10):
        try:
            import fitz
            if raw_bytes:
                doc = fitz.open(stream=raw_bytes, filetype="pdf")
            else:
                doc = fitz.open(filepath)
            return doc
        except Exception as e:
            logging.error(f"Error opening PDF {filepath}: {e}")
            raise PDFCorruptionError(f"Could not open PDF: {str(e)}")

    def _safe_extract_text(self, raw_bytes=None, doc=None, max_size_mb=50, timeout_seconds=15):
        try:
            import time
            import fitz
            if raw_bytes and len(raw_bytes) > max_size_mb * 1024 * 1024:
                logging.warning(f"PDF too large for text extraction: {len(raw_bytes) / (1024*1024):.1f}MB")
                return ""
            
            if raw_bytes and (b"/ObjStm" in raw_bytes or raw_bytes.count(b"stream") > 100):
                logging.warning(f"PDF contains suspicious patterns (streams or object streams), skipping full extraction")
                return ""
            
            should_close_doc = False
            if doc is None:
                if not raw_bytes:
                    return ""
                doc = fitz.open(stream=raw_bytes, filetype="pdf")
                should_close_doc = True
            
            start_time = time.time()
            txt = ""
            page_count = len(doc)
            
            for page_num in range(min(1000, page_count)):
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
                    
                if len(txt) > 50 * 1024 * 1024: 
                    logging.warning(f"Text extraction exceeded 50MB limit, stopping at page {page_num}/{page_count}")
                    break
            
            if should_close_doc and doc:
                doc.close()
                
            logging.info(f"Successfully extracted {len(txt)} characters from {page_count} pages")
            return txt
        except Exception as e:
            logging.warning(f"Could not extract text from PDF: {e}")
            return ""

    def _(self, key):
        return self.translations[self.language.get()].get(key, key)

    def get_translations(self):
        base_path = Path(__file__).parent.parent
        json_path = base_path / "lang" / "translations.json"
        manual_paths = {
            "da": base_path / "lang" / "manual_da.md",
            "en": base_path / "lang" / "manual_en.md"
        }

        translations = {}

        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                translations = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logging.error(f"Could not load or parse translations.json: {e}")
            translations = {"da": {}, "en": {}}

        for lang, manual_path in manual_paths.items():
            try:
                with open(manual_path, 'r', encoding='utf-8') as f:
                    if lang not in translations:
                        translations[lang] = {}
                    translations[lang]["full_manual"] = f.read()
            except FileNotFoundError:
                logging.error(f"{lang.upper()} manual not found at {manual_path}")
                if lang not in translations:
                    translations[lang] = {}
                translations[lang]["full_manual"] = "Manual not found."
            
        version_string = f"PDFRecon v{self.app_version}"
        for lang in translations:
            translations[lang]["about_version"] = version_string

        return translations
  
    def _save_config(self):
        if not getattr(self, '_config_writable', True):
            return 
        try:
            parser = configparser.ConfigParser()
            parser.read(self.config_path)
            if 'Settings' not in parser:
                parser['Settings'] = {}
            parser['Settings']['Language'] = self.language.get()
            with open(self.config_path, 'w') as configfile:
                configfile.write("# PDFRecon Configuration File\n")
                parser.write(configfile)
        except Exception:
            pass 
  
    def _load_or_create_config(self):
        parser = configparser.ConfigParser()
        self.default_language = "en"
        self._config_writable = False 
        
        if self.config_path.exists():
            try:
                parser.read(self.config_path)
                settings = parser['Settings']
                PDFReconConfig.MAX_FILE_SIZE = settings.getint('MaxFileSizeMB', 500) * 1024 * 1024
                PDFReconConfig.EXIFTOOL_TIMEOUT = settings.getint('ExifToolTimeout', 30)
                PDFReconConfig.MAX_WORKER_THREADS = settings.getint('MaxWorkerThreads', PDFReconConfig.MAX_WORKER_THREADS)
                PDFReconConfig.VISUAL_DIFF_PAGE_LIMIT = settings.getint('VisualDiffPageLimit', 5)
                PDFReconConfig.EXPORT_INVALID_XREF = settings.getboolean('ExportInvalidXREF', False)

                PDFReconConfig.EXIFTOOL_PATH = settings.get('ExifToolPath', None)
                if PDFReconConfig.EXIFTOOL_PATH == "": PDFReconConfig.EXIFTOOL_PATH = None
                PDFReconConfig.EXIFTOOL_HASH = settings.get('ExifToolHash', None)
                if PDFReconConfig.EXIFTOOL_HASH == "": PDFReconConfig.EXIFTOOL_HASH = None
                PDFReconConfig.SIGNING_KEY_PATH = settings.get('SigningKeyPath', None)
                if PDFReconConfig.SIGNING_KEY_PATH == "": PDFReconConfig.SIGNING_KEY_PATH = None
                self.default_language = settings.get('Language', 'en')
                self._config_writable = True
                return
            except Exception:
                pass 
        
        try:
            parser['Settings'] = {
                'MaxFileSizeMB': '500',
                'ExifToolTimeout': '30',
                'MaxWorkerThreads': str(PDFReconConfig.MAX_WORKER_THREADS),
                'Language': self.default_language,
                'VisualDiffPageLimit': str(PDFReconConfig.VISUAL_DIFF_PAGE_LIMIT),
                'ExportInvalidXREF': 'False'
            }
            with open(self.config_path, 'w') as configfile:
                configfile.write("# PDFRecon Configuration File\n")
                parser.write(configfile)
            self._config_writable = True
        except Exception:
            self._config_writable = False

    def _setup_logging(self):
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        
        if logger.hasHandlers():
            logger.handlers.clear()
            
        log_locations = [
            self._resolve_path("pdfrecon.log", base_is_parent=True), 
            Path(tempfile.gettempdir()) / "pdfrecon.log", 
        ]
        
        self.log_file_path = None
        for log_path in log_locations:
            try:
                fh = logging.FileHandler(log_path, mode='a', encoding='utf-8')
                formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
                fh.setFormatter(formatter)
                logger.addHandler(fh)
                self.log_file_path = log_path
                break 
            except Exception:
                continue 
        
        if self.log_file_path is None:
            logger.addHandler(logging.NullHandler())

    def _autoload_case_in_reader(self):
        try:
            exe_dir = Path(sys.executable).parent
            case_files = list(exe_dir.glob('*.prc'))
            
            if len(case_files) == 1:
                logging.info(f"Reader mode: Found case file to auto-load: {case_files[0]}")
                self._open_case(filepath=case_files[0])
            elif len(case_files) > 1:
                logging.warning("Reader mode: Found multiple .prc files. Aborting auto-load.")
            else:
                logging.info("Reader mode: No .prc file found for auto-loading.")
        except Exception as e:
            logging.error(f"Error during case auto-load: {e}")

    def _resolve_case_path(self, path_from_case):
        if not path_from_case:
            return None
        p = Path(path_from_case)
        if p.is_absolute():
            return p
        if self.case_root_path:
            return self.case_root_path / p
        return p    

    def _resolve_path(self, filename, base_is_parent=False):
        if getattr(sys, 'frozen', False):
            base_path = Path(sys.executable).parent
            if base_is_parent:
                return base_path / filename
            return Path(getattr(sys, '_MEIPASS', base_path)) / filename
        else:
            base_path = Path(__file__).resolve().parent
        
        if base_is_parent:
            base_path = base_path.parent
        
        return base_path / filename

if __name__ == "__main__":
    if sys.platform.startswith('win'):
        multiprocessing.freeze_support()
        
    root = TkinterDnD.Tk()
    app = PDFReconApp(root)
    root.mainloop()