import tkinter as tk
from tkinter import ttk, filedialog, messagebox, Toplevel
import hashlib
import os
import re
import subprocess
import zlib
from pathlib import Path
from datetime import datetime, timezone
import threading
import queue
import webbrowser
import sys
import logging
import tempfile
import multiprocessing
from concurrent.futures import ThreadPoolExecutor, as_completed
import configparser
import csv
import json
import time
import re as _re
import base64
import binascii

# --- Optional library imports with error handling ---
try:
    from PIL import Image, ImageTk, ImageChops, ImageOps
except ImportError:
    messagebox.showerror("Missing Library", "The Pillow library is not installed.\n\nPlease run 'pip install Pillow' in your terminal to use this program.")
    sys.exit(1)

try:
    import fitz  # PyMuPDF
except ImportError:
    messagebox.showerror("Missing Library", "PyMuPDF is not installed.\n\nPlease run 'pip install PyMuPDF' in your terminal to use this program.")
    sys.exit(1)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:
    messagebox.showerror("Missing Library", "tkinterdnd2 is not installed.\n\nPlease run 'pip install tkinterdnd2' in your terminal to use this program.")
    sys.exit(1)

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill
except ImportError:
    messagebox.showerror("Missing Library", "The openpyxl library is not installed.\n\nPlease run 'pip install openpyxl' in your terminal to use this program.")
    sys.exit(1)


# --- OCG (layers) detection helpers ---
_LAYER_OCGS_BLOCK_RE = _re.compile(rb"/OCGs\s*\[(.*?)\]", _re.S)
_OBJ_REF_RE          = _re.compile(rb"(\d+)\s+(\d+)\s+R")
_LAYER_OC_REF_RE     = _re.compile(rb"/OC\s+(\d+)\s+(\d+)\s+R")

def count_layers(pdf_bytes: bytes) -> int:
    """
    Conservatively counts OCGs (layers) in PDF bytes.
    1) Finds /OCGs [ ... ] and collects all indirect refs "n m R".
    2) Also finds /OC n m R in content/resources.
    3) Deduplicates (n, gen).
    """
    refs = set()

    m = _LAYER_OCGS_BLOCK_RE.search(pdf_bytes)
    if m:
        for n, g in _OBJ_REF_RE.findall(m.group(1)):
            refs.add((int(n), int(g)))

    for n, g in _LAYER_OC_REF_RE.findall(pdf_bytes):
        refs.add((int(n), int(g)))

    return len(refs)


# --- PHASE 1/3: Configuration and Custom Exceptions ---
class PDFReconConfig:
    """Configuration settings for PDFRecon. Values are loaded from config.ini."""
    MAX_FILE_SIZE = 1000 * 1024 * 1024  # 500MB
    MAX_REVISIONS = 100
    EXIFTOOL_TIMEOUT = 30
    MAX_WORKER_THREADS = min(16, (os.cpu_count() or 4) * 2)
    VISUAL_DIFF_PAGE_LIMIT = 5

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
# --- End Phase 1/3 ---
def md5_file(fp: Path, buf_size: int = 4 * 1024 * 1024) -> str:
    """
    Fast MD5 with reusable buffer (fewer allocations).
    """
    h = hashlib.md5()
    with fp.open("rb", buffering=0) as f:
        buf = bytearray(buf_size)
        mv = memoryview(buf)
        while True:
            n = f.readinto(mv)
            if not n:
                break
            h.update(mv[:n])
    return h.hexdigest()


def fmt_times_pair(ts: float):
    """Return ('DD-MM-YYYY HH:MM:SS±ZZZZ', 'YYYY-mm-ddTHH:MM:SSZ')."""
    local = datetime.fromtimestamp(ts).astimezone()
    utc = datetime.fromtimestamp(ts, tz=timezone.utc)
    return local.strftime("%d-%m-%Y %H:%M:%S%z"), utc.strftime("%Y-%m-%dT%H:%M:%SZ")

def safe_stat_times(path: Path):
    try:
        st = path.stat()
        return st.st_ctime, st.st_mtime
    except Exception:
        return None, None



class PDFReconApp:
    def __init__(self, root):
        # --- Application Configuration ---
        self.app_version = "16.1.2"
        self.config_path = self._resolve_path("config.ini", base_is_parent=True)
        self._load_or_create_config()
        
        # --- Root Window Setup ---
        self.root = root
        self.root.title(f"PDFRecon v{self.app_version}")
        self.root.geometry("1200x700")

        # --- Set Application Icon ---
        try:
            icon_path = self._resolve_path('icon.ico')
            if icon_path.exists():
                self.root.iconbitmap(icon_path)
            else:
                logging.warning("icon.ico was not found. Using default icon.")
        except tk.TclError:
            logging.warning("Could not load icon.ico. Using default icon.")
        except Exception as e:
            logging.error(f"Unexpected error when loading icon: {e}")


        # --- Application Data ---
        self.report_data = [] 
        self.all_scan_data = []
        self.exif_outputs = {}
        self.timeline_data = {}
        self.path_to_id = {}
        self.scan_start_time = 0

        # --- State Variables ---
        self.revision_counter = 0
        self.scan_queue = queue.Queue()
        self.tree_sort_column = None
        self.tree_sort_reverse = False
        self.exif_popup = None
        self.indicator_popup = None

        # --- Language and Filter Setup ---
        self.language = tk.StringVar(value=self.default_language)
        self.filter_var = tk.StringVar()
        
        # --- Compile regex for software detection once ---
        self.software_tokens = re.compile(
            r"(adobe|acrobat|billy|businesscentral|cairo|canva|chrome|chromium|clibpdf|dinero|dynamics|economic|edge|eboks|excel|firefox|"
            r"formpipe|foxit|fpdf|framemaker|ghostscript|illustrator|indesign|ilovepdf|itext|"
            r"kmd|lasernet|latex|libreoffice|microsoft|navision|netcompany|nitro|office|openoffice|pdflatex|pdf24|photoshop|powerpoint|prince|"
            r"quartz|reportlab|safari|skia|tcpdf|tex|visma|word|wkhtml|wkhtmltopdf|xetex)",
            re.IGNORECASE
        )
        
        # --- GUI Setup ---
        self._setup_logging()
        self.translations = self.get_translations() 
        self._setup_styles()
        self._setup_menu()
        self._setup_main_frame()
        self._setup_drag_and_drop()
        
        logging.info(f"PDFRecon v{self.app_version} started.")

    def _(self, key):
        """Returns the translated text for a given key."""
        # Fallback for keys that might not exist in a language
        return self.translations[self.language.get()].get(key, key)

    def get_translations(self):
        """Contains all translations for the application."""
        version_string = f"PDFRecon v{self.app_version}"
        
        # --- Manual Texts ---
        MANUAL_DA = f"""
# PDFRecon - Manual

## Introduktion
PDFRecon er et værktøj designet til at assistere i efterforskningen af PDF-filer. Programmet analyserer filer for en række tekniske indikatorer, der kan afsløre ændring, redigering eller skjult indhold. Resultaterne præsenteres i en overskuelig tabel, der kan eksporteres til Excel for videre dokumentation.

## Vigtig bemærkning om tidsstempler
Kolonnerne 'Fil oprettet' og 'Fil sidst ændret' viser tidsstempler fra computerens filsystem. Vær opmærksom på, at disse tidsstempler kan være upålidelige. En simpel handling som at kopiere en fil fra én placering til en anden vil typisk opdatere disse datoer til tidspunktet for kopieringen. For en mere pålidelig tidslinje, brug funktionen 'Vis Tidslinje', som er baseret på metadata inde i selve filen.

## Klassificeringssystem
Programmet klassificerer hver fil baseret på de fundne indikatorer. Dette gøres for hurtigt at kunne prioritere, hvilke filer der kræver nærmere undersøgelse.

<red><b>JA (Høj Risiko):</b></red> Tildeles filer, hvor der er fundet stærke beviser for ændring. Disse filer bør altid undersøges grundigt. Indikatorer, der udløser dette flag, er typisk svære at forfalske og peger direkte på en ændring i filens indhold eller struktur.

<yellow><b>Indikationer Fundet (Mellem Risiko):</b></yellow> Tildeles filer, hvor der er fundet en eller flere tekniske spor, der afviger fra en standard, 'ren' PDF. Disse spor er ikke i sig selv et endegyldigt bevis på ændring, men de viser, at filen har en historik eller struktur, der berettiger et nærmere kig.

<green><b>IKKE PÅVIST (Lav Risiko):</b></green> Tildeles filer, hvor programmet ikke har fundet nogen af de kendte indikatorer. Dette betyder ikke, at filen med 100% sikkerhed er uændret, men at den ikke udviser de typiske tegn på ændring, som værktøjet leder efter.

## Forklaring af Indikatorer
Nedenfor er en detaljeret forklaring af hver indikator, som PDFRecon leder efter.

<b>Has Revisions</b>
*<i>Ændret:</i>* <red>JA</red>
• Hvad det betyder: PDF-standarden tillader, at man gemmer ændringer oven i en eksisterende fil (inkrementel lagring). Dette efterlader den oprindelige version af dokumentet intakt inde i filen. PDFRecon har fundet og udtrukket en eller flere af disse tidligere versioner. Dette er et utvetydigt bevis på, at filen er blevet ændret efter sin oprindelige oprettelse.

<b>TouchUp_TextEdit</b>
*<i>Ændret:</i>* <red>JA</red>
• Hvad det betyder: Dette er et specifikt metadata-flag, som Adobe Acrobat efterlader, når en bruger manuelt har redigeret tekst direkte i PDF-dokumentet. Det er et meget stærkt bevis på direkte ændring af indholdet.

<b>Multiple Font Subsets</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Når tekst tilføjes til en PDF, indlejres ofte kun de tegn fra en skrifttype, der rent faktisk bruges (et 'subset'). Hvis en fil redigeres med et andet program, der ikke har adgang til præcis samme skrifttype, kan der opstå et nyt subset af den samme grundlæggende skrifttype. At finde flere subsets (f.eks. Multiple Font Subsets: 'Arial':F1+ArialMT', 'F2+Arial-BoldMT er en stærk indikation på, at tekst er blevet tilføjet eller ændret på forskellige tidspunkter eller med forskellige værktøjer.

<b>Multiple Creators / Producers</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: PDF-filer indeholder metadata om, hvilket program der har oprettet (/Creator) og genereret (/Producer) filen. Hvis der findes flere forskellige navne i disse felter (f.eks. Multiple Creators (Fundet 2): "Microsoft Word", "Adobe Acrobat Pro"), indikerer det, at filen er blevet behandlet af mere end ét program. Dette sker typisk, når en fil oprettes i ét program og derefter redigeres i et andet.

<b>xmpMM:History / DerivedFrom / DocumentAncestors</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Dette er forskellige typer af XMP-metadata, som gemmer information om filens historik. De kan indeholde tidsstempler for, hvornår filen er gemt, ID'er fra tidligere versioner, og hvilket software der er brugt. Fund af disse felter beviser, at filen har en redigeringshistorik.

<b>Multiple DocumentID / Different InstanceID</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Hver PDF har et unikt DocumentID, der ideelt set er det samme for alle versioner. InstanceID ændres derimod for hver gang, filen gemmes. Hvis der findes flere forskellige DocumentID'er (f.eks. Trailer ID Changed: Fra [ID1...] til [ID2...]), eller hvis der er et unormalt højt antal InstanceID'er, peger det på en kompleks redigeringshistorik, potentielt hvor dele fra forskellige dokumenter er blevet kombineret.

<b>Multiple startxref</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: 'startxref' er et nøgleord, der fortæller en PDF-læser, hvor den skal begynde at læse filens struktur. En standard, uændret fil har kun ét. Hvis der er flere, er det et tegn på, at der er foretaget inkrementelle ændringer (se 'Has Revisions').

<b>Objekter med generation > 0</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Hvert objekt i en PDF-fil har et versionsnummer (generation). I en original, uændret fil er dette nummer typisk 0 for alle objekter. Hvis der findes objekter med et højere generationsnummer (f.eks. '12 1 obj'), er det et tegn på, at objektet er blevet overskrevet i en senere, inkrementel gemning. Dette indikerer, at filen er blevet opdateret.

<b>Flere Lag End Sider</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Dokumentets struktur indeholder flere lag (Optional Content Groups) end der er sider. Hvert lag er en container for indhold, som kan vises eller skjules. Selvom det er teknisk muligt, er det usædvanligt at have flere lag end sider. Det kan indikere et komplekst dokument, en fil der er blevet kraftigt redigeret, eller potentielt at information er skjult på lag, som ikke er knyttet til synligt indhold. Filer med denne indikation bør undersøges nærmere i en PDF-læser, der understøtter lag-funktionalitet.

<b>Linearized / Linearized + updated</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: En "linearized" PDF er optimeret til hurtig webvisning. Hvis en sådan fil efterfølgende er blevet ændret (updated), vil PDFRecon markere det. Det kan indikere, at et ellers færdigt dokument er blevet redigeret senere.

<b>Has PieceInfo</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Nogle programmer, især fra Adobe, gemmer ekstra tekniske spor (PieceInfo) om ændringer eller versioner. Det kan afsløre, at filen har været behandlet i bestemte værktøjer som f.eks. Illustrator.

<b>Has Redactions</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Dokumentet indeholder tekniske felter for sløring/sletning af indhold. I nogle tilfælde kan den skjulte tekst stadig findes i filen. Derfor bør redaktioner altid vurderes kritisk.

<b>Has Annotations</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Dokumentet rummer kommentarer, noter eller markeringer. De kan være tilføjet senere og kan indeholde oplysninger, der ikke fremgår af det viste indhold.

<b>AcroForm NeedAppearances=true</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Formularfelter kan kræve, at visningen genskabes, når dokumentet åbnes. Felt-tekster kan derfor ændre udseende eller udfyldes automatisk. Det kan skjule eller forplumre det oprindelige indhold.

<b>Has Digital Signature</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Dokumentet indeholder en digital signatur. En gyldig signatur kan bekræfte, at dokumentet ikke er ændret siden signering. En ugyldig/brudt signatur kan være et stærkt tegn på efterfølgende ændring.

<b>Dato-inkonsistens (Info vs. XMP)</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Oprettelses- og ændringsdatoer i PDF’ens Info-felt stemmer ikke overens med datoerne i XMP-metadata (f.eks. Creation Date Mismatch: Info='20230101...', XMP='2023-01-02...'). Sådanne uoverensstemmelser kan pege på skjulte eller uautoriserede ændringer.
"""

        MANUAL_EN = f"""
# PDFRecon - Manual

## Introduction
PDFRecon is a tool designed to assist in the investigation of PDF files. The program analyzes files for a range of technical indicators that can reveal alteration, editing, or hidden content. The results are presented in a clear table that can be exported to Excel for further documentation.

## Important Note on Timestamps
The 'File Created' and 'File Modified' columns show timestamps from the computer's file system. Be aware that these timestamps can be unreliable. A simple action like copying a file from one location to another will typically update these dates to the time of the copy. For a more reliable timeline, use the 'Show Timeline' feature, which is based on metadata inside the file itself.

## Classification System
The program classifies each file based on the indicators found. This is done to quickly prioritize which files require closer examination.

<red><b>YES (High Risk):</b></red> Assigned to files where strong evidence of alteration has been found. These files should always be thoroughly investigated. Indicators that trigger this flag are typically difficult to forge and point directly to a change in the file's content or structure.

<yellow><b>Indications Found (Medium Risk):</b></yellow> Assigned to files where one or more technical traces have been found that deviate from a standard, 'clean' PDF. These traces are not definitive proof of alteration in themselves, but they show that the file has a history or structure that warrants a closer look.

<green><b>NOT DETECTED (Low Risk):</b></green> Assigned to files where the program has not found any of the known indicators. This does not mean that the file is 100% unchanged, but that it does not exhibit the typical signs of alteration that the tool looks for.

## Explanation of Indicators
Below is a detailed explanation of each indicator that PDFRecon looks for.
 
<b>Has Revisions</b>
*<i>Changed:</i>* <red>YES</red>
• What it means: The PDF standard allows changes to be saved on top of an existing file (incremental saving). This leaves the original version of the document intact inside the file. PDFRecon has found and extracted one or more of these previous versions. This is unequivocal proof that the file has been changed after its original creation.

<b>TouchUp_TextEdit</b>
*<i>Changed:</i>* <red>YES</red>
• What it means: This is a specific metadata flag left by Adobe Acrobat when a user has manually edited text directly in the PDF document. It is very strong evidence of direct content alteration.

<b>Multiple Font Subsets</b>
*<i>Changed:</i>* <yellow>Indications Found</yellow>
• What it means: When text is added to a PDF, often only the characters actually used from a font are embedded (a 'subset'). If a file is edited with another program that does not have access to the exact same font, a new subset of the same base font may be created. Finding multiple subsets (e.g., Multiple Font Subsets: 'Arial': F1+ArialMT', 'F2+Arial-BoldMT' is a strong indication that text has been added or changed at different times or with different tools.

<b>Multiple Creators / Producers</b>
*<i>Changed:</i>* <yellow>Indikationer Fundet</yellow>
• What it means: PDF files contain metadata about which program created (/Creator) and generated (/Producer) the file. If multiple different names are found in these fields (e.g., Multiple Creators (Found 2): "Microsoft Word", "Adobe Acrobat Pro"), it indicates that the file has been processed by more than one program. This typically happens when a file is created in one program and then edited in another.

<b>xmpMM:History / DerivedFrom / DocumentAncestors</b>
*<i>Changed:</i>* <yellow>Indications Found</yellow>
• What it means: These are different types of XMP metadata that store information about the file's history. They can contain timestamps for when the file was saved, IDs from previous versions, and what software was used. The presence of these fields proves that the file has an editing history.

<b>Multiple DocumentID / Different InstanceID</b>
*<i>Changed:</i>* <yellow>Indications Found</yellow>
• What it means: Each PDF has a unique DocumentID that should ideally be the same for all versions. The InstanceID, however, changes every time the file is saved. If multiple different DocumentIDs are found (e.g., Trailer ID Changed: From [ID1...] to [ID2...]), or if there is an abnormally high number of InstanceIDs, it points to a complex editing history, potentially where parts from different documents have been combined.

<b>Multiple startxref</b>
*<i>Changed:</i>* <yellow>Indications Found</yellow>
• What it means: 'startxref' is a keyword that tells a PDF reader where to start reading the file's structure. A standard, unchanged file has only one. If there are more, it is a sign that incremental changes have been made (see 'Has Revisions').

<b>Objects with generation > 0</b>
*<i>Changed:</i>* <yellow>Indications Found</yellow>
• What it means: Each object in a PDF file has a version number (generation). In an original, unaltered file, this number is typically 0 for all objects. If objects are found with a higher generation number (e.g., '12 1 obj'), it is a sign that the object has been overwritten in a later, incremental save. This indicates that the file has been updated.

<b>More Layers Than Pages</b>
*<i>Changed:</i>* <yellow>Indications Found</yellow>
• What it means: The document's structure contains more layers (Optional Content Groups) than it has pages. Each layer is a container for content that can be shown or hidden. While technically possible, having more layers than pages is unusual. It might indicate a complex document, a file that has been heavily edited, or potentially that information is hidden in layers not associated with visible content. Files with this indicator should be examined more closely in a PDF reader that supports layer functionality.

<b>Linearized / Linearized + updated</b>
*<i>Changed:</i>* <yellow>Indications Found</yellow>
• What it means: A "linearized" PDF is optimized for fast web viewing. If such a file was later modified (updated), PDFRecon flags it. This may indicate that a supposedly final document was edited afterwards.

<b>Has PieceInfo</b>
*<i>Changed:</i>* <yellow>Indications Found</yellow>
• What it means: Some applications, particularly from Adobe, store extra technical traces (PieceInfo) about changes or versions. This can reveal that the file has been processed in specific tools like Illustrator.

<b>Has Redactions</b>
*<i>Changed:</i>* <yellow>Indications Found</yellow>
• What it means: The document contains technical fields for redaction (blackouts/removals). In some cases, hidden text may still be present. Redactions should always be assessed critically.

<b>Has Annotations</b>
*<i>Changed:</i>* <yellow>Indications Found</yellow>
• What it means: The document includes comments, notes, or highlights. They may have been added later and can contain information that is not visible in the main content.

<b>AcroForm NeedAppearances=true</b>
*<i>Changed:</i>* <yellow>Indications Found</yellow>
• What it means: Form fields may need their appearance regenerated when the document opens. Field text can change or be auto-filled, which may obscure the original content.

<b>Has Digital Signature</b>
*<i>Changed:</i>* <yellow>Indications Found</yellow>
• What it means: The document contains a digital signature. A valid signature confirms the file has not changed since signing. An invalid/broken signature can be a strong sign of later alteration.

<b>Date inconsistency (Info vs. XMP)</b>
*<i>Changed:</i>* <yellow>Indications Found</yellow>
• What it means: The creation/modification dates in the PDF Info dictionary do not match the dates in XMP metadata (e.g., Creation Date Mismatch: Info='20230101...', XMP='2023-01-02...'). Such discrepancies can indicate hidden or unauthorized changes.
"""

        # This dictionary holds all GUI text for easy language switching.
        return {
            "da": {
                "full_manual": MANUAL_DA,
                "choose_folder": "📁 Vælg mappe og scan",
                "show_timeline": "Vis Tidslinje",
                "status_initial": "Træk en mappe hertil eller brug knappen for at starte en analyse.",
                "col_id": "#", "col_name": "Navn", "col_changed": "Ændret", "col_path": "Sti", "col_md5": "MD5",
                "col_created": "Fil oprettet", "col_modified": "Fil sidst ændret", "col_exif": "EXIFTool", "col_indicators": "Tegn på ændring",
                "export_report": "💾 Eksporter rapport",
                "menu_file": "Fil", "menu_settings": "Indstillinger", "menu_exit": "Afslut",
                "menu_help": "Hjælp", "menu_manual": "Manual", "menu_about": "Om PDFRecon", "menu_license": "Vis Licens",
                "menu_log": "Vis logfil", "menu_language": "Sprog / Language",
                "preparing_analysis": "Forbereder analyse...", "analyzing_file": "🔍 Analyserer: {file}",
                "scan_progress_eta": "🔍 {file} | {fps:.1f} filer/s | ETA: {eta}",
                "scan_complete_summary": "✔ Færdig: {total} dokumenter | {changed} ændrede (JA) | {revs} revisioner | {inds} med indikationer | {clean} ikke påvist",
                "scan_complete_summary_with_errors": "✔ Færdig: {total} dok. | {changed} JA | {revs} rev. | {inds} ind. | {errors} fejl | {clean} rene",
                "no_exif_output_title": "Ingen EXIFTool-output", "no_exif_output_message": "Der er enten ingen EXIFTool-output for denne fil, eller også opstod der en fejl under kørsel.",
                "exif_popup_title": "EXIFTool Output", "exif_no_output": "Intet output", "exif_error": "Fejl. Læs exiftool i samme mappe", "exif_view_output": "Klik for at se output ➡",
                "indicators_popup_title": "Fundne Indikatorer", "indicators_view_output": "Klik for at se detaljer ➡", "no_indicators_message": "Der er ingen indikatorer for denne fil.",
                "license_error_title": "Fejl", "license_error_message": "Licensfilen 'license.txt' kunne ikke findes.\n\nSørg for, at filen hedder 'license.txt' og er inkluderet korrekt, når programmet pakkes.",
                "license_popup_title": "Licensinformation",
                "obj_gen_gt_zero": "Objekt med generation > 0",
                "log_not_found_title": "Logfil ikke fundet", "log_not_found_message": "Logfilen er endnu ikke oprettet. Den oprettes første gang programmet logger en handling.",
                "no_data_to_save_title": "Ingen data", "no_data_to_save_message": "Der er ingen data at gemme.",
                "excel_saved_title": "Handling fuldført", "excel_saved_message": "Rapporten er gemt.\n\nVil du åbne mappen, hvor filen ligger?",
                "excel_save_error_title": "Fejl ved lagring", "excel_save_error_message": "Filen kunne ikke gemmes. Den er muligvis i brug af et andet program.\n\nDetaljer: {e}",
                "excel_unexpected_error_title": "Uventet Fejl", "excel_unexpected_error_message": "En uventet fejl opstod under lagring.\n\nDetaljer: {e}",
                "open_folder_error_title": "Fejl ved åbning", "open_folder_error_message": "Kunne ikke automatisk åbne mappen.",
                "manual_title": "PDFRecon - Manual",
                "revision_of": "Revision af #{id}", "about_purpose_header": "Formål",
                "about_purpose_text": "PDFRecon identificerer potentielt manipulerede PDF-filer ved at:\n• Udtrække og analysere XMP-metadata, streams og revisioner\n• Detektere tegn på ændringer (f.eks. /TouchUp_TextEdit, /Prev)\n• Udtrække komplette, tidligere versioner af dokumentet\n• Generere en overskuelig rapport i Excel-format\n\n",
                "about_included_software_header": "Inkluderet Software", "about_included_software_text": "Dette værktøj benytter og inkluderer {tool} af Phil Harvey.\n{tool} er distribueret under Artistic/GPL-licens.\n\n",
                "about_project_website": "Projektets kildekode: ", 
                "about_website": "Officiel {tool} Hjemmeside: ", "about_source": "{tool} Kildekode: ", "about_developer_info": "\nUdvikler: Rasmus Riis\nE-mail: riisras@gmail.com\n",
                "about_version": version_string, "copy": "Kopiér", "close_button_text": "Luk", "excel_indicators_overview": "(Oversigt)",
                "exif_err_notfound": "(exiftool ikke fundet i programmets mappe)", "exif_err_prefix": "ExifTool Fejl:", "exif_err_run": "(fejl ved kørsel af exiftool: {e})",
                "drop_error_title": "Fejl", "drop_error_message": "Træk venligst en mappe, ikke en fil.",
                "timeline_no_data": "Der blev ikke fundet tidsstempeldata for denne fil.", "choose_folder_title": "Vælg mappe til analyse",
                "visual_diff": "Visuel sammenligning af revision", "diff_error_title": "Fejl ved sammenligning", "diff_error_msg": "Kunne ikke sammenligne filerne. En af filerne er muligvis korrupt eller tom.\n\nFejl: {e}",
                "diff_popup_title": "Visuel Sammenligning", "diff_original_label": "Seneste version", "diff_revision_label": "Tidligere version", "diff_differences_label": "Forskelle (markeret med rød)",
                "status_identical": "Visuelt Identisk (op til {pages} sider)", "diff_page_label": "Viser side {current} af {total}", "diff_prev_page": "Forrige Side", "diff_next_page": "Næste Side",
                "file_too_large": "Fil er for stor", "file_corrupt": "Korrupt fil", "file_encrypted": "Krypteret fil", "validation_error": "Valideringsfejl",
                "processing_error": "Processeringsfejl", "unknown_error": "Ukendt fejl",
                "Has XFA Form": "Har XFA Formular", "Has Digital Signature": "Har Digital Signatur", "Signature: Valid": "Signatur: Gyldig", "Signature: Invalid": "Signatur: Ugyldig", "More Layers Than Pages": "Flere Lag End Sider",
                "view_pdf": "Vis PDF", "pdf_viewer_title": "PDF Fremviser", "pdf_viewer_error_title": "Fremvisningsfejl",
                "pdf_viewer_error_message": "Kunne ikke åbne eller vise PDF-filen.\n\nFejl: {e}",
                "status_no": "NEJ",
                "filter_label": "🔎 Filter:",
                "settings_title": "Indstillinger", "settings_max_size": "Maks filstørrelse (MB):", "settings_timeout": "ExifTool Timeout (sek):",
                "settings_threads": "Maks. analysetråde:", "settings_diff_pages": "Sider for visuel sammenligning:", "settings_save": "Gem", "settings_cancel": "Annuller",
                "settings_saved_title": "Indstillinger Gemt", "settings_saved_msg": "Indstillingerne er blevet gemt.", "settings_invalid_input": "Ugyldigt input. Indtast venligst kun heltal."
            },
            "en": {
                "full_manual": MANUAL_EN,
                "choose_folder": "📁 Choose folder and scan", "show_timeline": "Show Timeline", "status_initial": "Drag a folder here or use the button to start an analysis.",
                "obj_gen_gt_zero": "Object with generation > 0",
                "col_id": "#", "col_name": "Name", "col_changed": "Changed", "col_path": "Path", "col_md5": "MD5",
                "col_created": "File Created", "col_modified": "File Modified", "col_exif": "EXIFTool", "col_indicators": "Signs of Alteration",
                "export_report": "💾 Export Report",
                "menu_file": "File", "menu_settings": "Settings", "menu_exit": "Exit",
                "menu_help": "Help", "menu_manual": "Manual", "menu_about": "About PDFRecon", "menu_license": "Show License",
                "menu_log": "Show Log File", "menu_language": "Language / Sprog",
                "preparing_analysis": "Preparing analysis...", "analyzing_file": "🔍 Analyzing: {file}",
                "scan_progress_eta": "🔍 {file} | {fps:.1f} files/s | ETA: {eta}",
                "scan_complete_summary": "✔ Finished: {total} documents | {changed} altered (YES) | {revs} revisions | {inds} with indications | {clean} not detected",
                "scan_complete_summary_with_errors": "✔ Done: {total} docs | {changed} YES | {revs} revs | {inds} ind. | {errors} errors | {clean} clean",
                "no_exif_output_title": "No EXIFTool Output", "no_exif_output_message": "There is either no EXIFTool output for this file, or an error occurred during execution.",
                "exif_popup_title": "EXIFTool Output", "exif_no_output": "No output", "exif_error": "Error. Missing Exiftool", "exif_view_output": "Click to view output ➡",
                "indicators_popup_title": "Indicators Found", "indicators_view_output": "Click to view details ➡", "no_indicators_message": "No indicators found for this file.",
                "license_error_title": "Error", "license_error_message": "The license file 'license.txt' could not be found.\n\nPlease ensure the file is named 'license.txt' and is included correctly when packaging the application.",
                "license_popup_title": "License Information",
                "log_not_found_title": "Log File Not Found", "log_not_found_message": "The log file has not been created yet. It is created the first time the program logs an action.",
                "no_data_to_save_title": "No Data", "no_data_to_save_message": "There is no data to save.",
                "excel_saved_title": "Action Completed", "excel_saved_message": "The report has been saved.\n\nDo you want to open the folder where the file is located?",
                "excel_save_error_title": "Save Error", "excel_save_error_message": "The file could not be saved. It might be in use by another program.\n\nDetails: {e}",
                "excel_unexpected_error_title": "Unexpected Error", "excel_unexpected_error_message": "An unexpected error occurred during saving.\n\nDetails: {e}",
                "open_folder_error_title": "Error Opening Folder", "open_folder_error_message": "Could not automatically open the folder.",
                "manual_title": "PDFRecon - Manual",
                "revision_of": "Revision of #{id}", "about_purpose_header": "Purpose",
                "about_purpose_text": "PDFRecon identifies potentially manipulated PDF files by:\n• Extracting and analyzing XMP metadata, streams, and revisions\n• Detecting signs of alteration (e.g., /TouchUp_TextEdit, /Prev)\n• Extracting complete, previous versions of the document\n• Generating a clear report in Excel format\n\n",
                "about_included_software_header": "Included Software", "about_included_software_text": "This tool utilizes and includes {tool} by Phil Harvey.\n{tool} is distributed under the Artistic/GPL license.\n\n",
                "about_website": "Official {tool} Website: ", "about_source": "Source Code: ", "about_developer_info": "\nDeveloper: Rasmus Riis\nE-mail: riisras@gmail.com\n",
                "about_project_website": "Project Sourcecode: ",
                "about_version": version_string, "copy": "Copy", "close_button_text": "Close", "excel_indicators_overview": "(Overview)",
                "exif_err_notfound": "(exiftool not found in program directory)", "exif_err_prefix": "ExifTool Error:", "exif_err_run": "(error running exiftool: {e})",
                "drop_error_title": "Error", "drop_error_message": "Please drag a folder, not a file.",
                "timeline_no_data": "No timestamp data was found for this file.", "choose_folder_title": "Select folder for analysis",
                "visual_diff": "Visually Compare Revision", "diff_error_title": "Comparison Error", "diff_error_msg": "Could not compare the files. One of the files might be corrupt or empty.\n\nError: {e}",
                "diff_popup_title": "Visual Comparison", "diff_original_label": "Latest version", "diff_revision_label": "Previous version", "diff_differences_label": "Differences (highlighted in red)",
                "status_identical": "Visually Identical (up to {pages} pages)", "diff_page_label": "Showing page {current} of {total}", "diff_prev_page": "Previous Page", "diff_next_page": "Next Page",
                "file_too_large": "File is too large", "file_corrupt": "Corrupt file", "file_encrypted": "Encrypted file", "validation_error": "Validation Error",
                "processing_error": "Processing Error", "unknown_error": "Unknown Error",
                "Has XFA Form": "Has XFA Form", "Has Digital Signature": "Has Digital Signature", "Signature: Valid": "Signature: Valid", "Signature: Invalid": "Signature: Invalid", "More Layers Than Pages": "More Layers Than Pages",
                "view_pdf": "View PDF", "pdf_viewer_title": "PDF Viewer", "pdf_viewer_error_title": "Viewer Error",
                "pdf_viewer_error_message": "Could not open or display the PDF file.\n\nError: {e}",
                "status_no": "NO",
                "filter_label": "🔎 Filter:",
                "settings_title": "Settings", "settings_max_size": "Max file size (MB):", "settings_timeout": "ExifTool Timeout (sec):",
                "settings_threads": "Max analysis threads:", "settings_diff_pages": "Pages for visual compare:", "settings_save": "Save", "settings_cancel": "Cancel",
                "settings_saved_title": "Settings Saved", "settings_saved_msg": "Your settings have been saved.", "settings_invalid_input": "Invalid input. Please enter only integers."
            }
        }

    def _load_or_create_config(self):
        """Loads configuration from config.ini or creates the file with default values."""
        parser = configparser.ConfigParser()
        # Set a default language in case the config file is missing or corrupt.
        self.default_language = "en"
        if not self.config_path.exists():
            logging.info("config.ini not found. Creating with default values.")
            parser['Settings'] = {
                'MaxFileSizeMB': '500',
                'ExifToolTimeout': '30',
                'MaxWorkerThreads': str(PDFReconConfig.MAX_WORKER_THREADS),
                'Language': self.default_language,
                'VisualDiffPageLimit': str(PDFReconConfig.VISUAL_DIFF_PAGE_LIMIT)
            }
            try:
                with open(self.config_path, 'w') as configfile:
                    configfile.write("# PDFRecon Configuration File\n")
                    parser.write(configfile)
            except IOError as e:
                logging.error(f"Could not write to config.ini: {e}")
                return
        
        try:
            parser.read(self.config_path)
            settings = parser['Settings']
            PDFReconConfig.MAX_FILE_SIZE = settings.getint('MaxFileSizeMB', 500) * 1024 * 1024
            PDFReconConfig.EXIFTOOL_TIMEOUT = settings.getint('ExifToolTimeout', 30)
            PDFReconConfig.MAX_WORKER_THREADS = settings.getint('MaxWorkerThreads', PDFReconConfig.MAX_WORKER_THREADS)
            PDFReconConfig.VISUAL_DIFF_PAGE_LIMIT = settings.getint('VisualDiffPageLimit', 5)
            # Load the language, fallback to the default 'en'
            self.default_language = settings.get('Language', 'en')
            logging.info(f"Configuration loaded from {self.config_path}")
        except Exception as e:
            logging.error(f"Could not read config.ini, using default values. Error: {e}")

    def _setup_logging(self):
        """ Sets up a robust logger that writes to a file. """
        self.log_file_path = self._resolve_path("pdfrecon.log", base_is_parent=True)
        
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        
        # Clear existing handlers to avoid duplicate logs
        if logger.hasHandlers():
            logger.handlers.clear()
            
        try:
            # Create a file handler to write logs to a file
            fh = logging.FileHandler(self.log_file_path, mode='a', encoding='utf-8')
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            fh.setFormatter(formatter)
            logger.addHandler(fh)
        except Exception as e:
            messagebox.showerror("Log Error", f"Could not create the log file.\n\nDetails: {e}")


    def _setup_styles(self):
        """Initializes and configures the styles for ttk widgets."""
        self.style = ttk.Style()
        # Use your theme as before (adjust if you had another one)
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        # Highlight on selection (keep as you had it)
        self.style.map('Treeview', background=[('selected', '#0078D7')])

        # Define the actual colors for tags
        self.style.configure("red_row", background="#FFD6D6")     # reddish background
        self.style.configure("yellow_row", background="#FFF4CC")  # yellow background

        # Map only these statuses now
        self.tree_tags = {
            "JA": "red_row",
            "YES": "red_row",
            "Sandsynligt": "yellow_row",
            "Possible": "yellow_row",
        }



    def _setup_menu(self):
        """Creates the main menu bar for the application."""
        self.menubar = tk.Menu(self.root)
        
        # --- File Menu ---
        self.file_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label=self._("menu_file"), menu=self.file_menu)
        self.file_menu.add_command(label=self._("menu_settings"), command=self.open_settings_popup)
        self.file_menu.add_separator()
        self.file_menu.add_command(label=self._("menu_exit"), command=self.root.quit)

        # --- Help Menu ---
        self.help_menu = tk.Menu(self.menubar, tearoff=0)
        self.lang_menu = tk.Menu(self.help_menu, tearoff=0) 

        self.menubar.add_cascade(label=self._("menu_help"), menu=self.help_menu)
        self.help_menu.add_command(label=self._("menu_manual"), command=self.show_manual)
        self.help_menu.add_command(label=self._("menu_about"), command=self.show_about)
        self.help_menu.add_separator()
        self.help_menu.add_cascade(label=self._("menu_language"), menu=self.lang_menu)
        self.lang_menu.add_radiobutton(label="Dansk", variable=self.language, value="da", command=self.switch_language)
        self.lang_menu.add_radiobutton(label="English", variable=self.language, value="en", command=self.switch_language)
        self.help_menu.add_separator()
        self.help_menu.add_command(label=self._("menu_license"), command=self.show_license)
        self.help_menu.add_command(label=self._("menu_log"), command=self.show_log_file)
        
        self.root.config(menu=self.menubar)

    def _update_summary_status(self):
        """Updates the status bar with a summary of the results from the full scan."""
        if not self.all_scan_data:
            self.status_var.set(self._("status_initial"))
            return

        # Build a temporary list of flags for all scanned files
        all_flags = []
        for data in self.all_scan_data:
            if data.get("status") == "error":
                error_type_key = data.get("error_type", "unknown_error")
                all_flags.append(self._(error_type_key))
            elif not data.get("is_revision"):
                flag = self.get_flag(data.get("indicator_keys", {}), False)
                all_flags.append(flag)

        # Define the set of error statuses for counting
        error_keys = ["file_too_large", "file_corrupt", "file_encrypted", "validation_error", "processing_error", "unknown_error"]
        error_statuses = {self._(key) for key in error_keys}
        
        # Count occurrences of each status type
        changed_count = all_flags.count("JA") + all_flags.count("YES")
        # Correctly count files with indications
        indications_found_count = all_flags.count("Sandsynligt") + all_flags.count("Possible")
                           
        error_count = sum(1 for flag in all_flags if flag in error_statuses)
        
        original_files_count = len([d for d in self.all_scan_data if not d.get('is_revision')])
        # Correctly calculate clean files
        not_flagged_count = original_files_count - changed_count - indications_found_count - error_count

        # Format the summary text based on whether errors were found
        if error_count > 0:
            summary_text = self._("scan_complete_summary_with_errors").format(
                total=original_files_count, changed=changed_count, revs=self.revision_counter,
                inds=indications_found_count, errors=error_count, clean=not_flagged_count
            )
        else:
            summary_text = self._("scan_complete_summary").format(
                total=original_files_count, changed=changed_count, revs=self.revision_counter,
                inds=indications_found_count, clean=not_flagged_count
            )
        self.status_var.set(summary_text)


    def switch_language(self):
        """Updates all text in the GUI to the selected language."""
        # --- Preserve Selection ---
        # Store the path of the currently selected item to re-select it after the update.
        path_of_selected = None
        if self.tree.selection():
            selected_item_id = self.tree.selection()[0]
            path_of_selected = self.tree.item(selected_item_id, "values")[3]

        # --- Update Menu and Button Text ---
        self.menubar.entryconfig(1, label=self._("menu_file"))
        self.file_menu.entryconfig(0, label=self._("menu_settings"))
        self.file_menu.entryconfig(2, label=self._("menu_exit"))
        self.menubar.entryconfig(2, label=self._("menu_help"))
        self.help_menu.entryconfig(0, label=self._("menu_manual"))
        self.help_menu.entryconfig(1, label=self._("menu_about"))
        self.help_menu.entryconfig(3, label=self._("menu_language"))
        self.help_menu.entryconfig(5, label=self._("menu_license"))
        self.help_menu.entryconfig(6, label=self._("menu_log"))
        self.scan_button.config(text=self._("choose_folder"))
        self.export_menubutton.config(text=self._("export_report"))
        self.filter_label.config(text=self._("filter_label"))
        
        # --- Update Treeview Column Headers ---
        for i, key in enumerate(self.columns_keys):
            self.tree.heading(self.columns[i], text=self._(key))

        # Re-apply the filter to update the table contents with the new language.
        self._apply_filter() 

        # --- Restore Selection and Details ---
        if path_of_selected:
            # Find the item ID that corresponds to the saved path
            new_item_to_select = next((item_id for item_id in self.tree.get_children("") if self.tree.item(item_id, "values")[3] == path_of_selected), None)
            if new_item_to_select:
                self.tree.selection_set(new_item_to_select)
                self.tree.focus(new_item_to_select)
                self.on_select_item(None) # Update the details view for the re-selected item
        else:
            # If nothing was selected, clear the details box
            self.detail_text.config(state="normal")
            self.detail_text.delete("1.0", tk.END)
            self.detail_text.config(state="disabled")

        # --- Update Status Bar ---
        is_scan_finished = self.scan_button['state'] == 'normal'
        if is_scan_finished and self.all_scan_data:
            self._update_summary_status()
        elif not self.all_scan_data:
            self.status_var.set(self._("status_initial"))

        # --- Save the selected language to the config file ---
        try:
            parser = configparser.ConfigParser()
            # Read existing config to preserve other settings
            parser.read(self.config_path)
            if 'Settings' not in parser:
                parser['Settings'] = {}
            parser['Settings']['Language'] = self.language.get()
            with open(self.config_path, 'w') as configfile:
                # Re-add the header comment
                configfile.write("# PDFRecon Configuration File\n")
                parser.write(configfile)
            logging.info(f"Language setting saved to {self.config_path}")
        except Exception as e:
            logging.error(f"Could not save language setting to config.ini: {e}")


    def _setup_main_frame(self):
        """Sets up the main user interface components within the root window."""
        # --- Main Container Frame ---
        frame = ttk.Frame(self.root, padding=10)
        frame.pack(fill="both", expand=True)

        # --- Top Controls Frame (Scan Button, Filter) ---
        top_controls_frame = ttk.Frame(frame)
        top_controls_frame.pack(pady=5, fill="x")

        self.scan_button = ttk.Button(top_controls_frame, text=self._("choose_folder"), width=25, command=self.choose_folder)
        self.scan_button.pack(side="left", padx=(0, 10))

        self.filter_label = ttk.Label(top_controls_frame, text=self._("filter_label"))
        self.filter_label.pack(side="left", padx=(5, 2))
        
        filter_entry = ttk.Entry(top_controls_frame, textvariable=self.filter_var)
        filter_entry.pack(side="left", fill="x", expand=True)
        self.filter_var.trace_add("write", self._apply_filter)

        # --- Status Bar ---
        self.status_var = tk.StringVar(value=self._("status_initial"))
        status_label = ttk.Label(frame, textvariable=self.status_var, foreground="darkgreen")
        status_label.pack(pady=(5, 10))

        # --- Treeview (Main Results Table) ---
        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill="both", expand=True)

        self.columns = ["ID", "Name", "Altered", "Path", "MD5", "File Created", "File Modified", "EXIFTool", "Signs of Alteration"]
        self.columns_keys = ["col_id", "col_name", "col_changed", "col_path", "col_md5", "col_created", "col_modified", "col_exif", "col_indicators"]
        self.tree = ttk.Treeview(tree_frame, columns=self.columns, show="headings", selectmode="browse")
        
        # Configure row colors
        self.tree.tag_configure("red_row", background='#FFDDDD')
        self.tree.tag_configure("yellow_row", background='#FFFFCC')
        self.tree.tag_configure("blue_row", background='#CCE5FF')
        self.tree.tag_configure("gray_row", background='#E0E0E0') # Light gray color
        
        # Set up treeview columns and headings
        for i, key in enumerate(self.columns_keys):
            self.tree.heading(self.columns[i], text=self._(key), command=lambda c=self.columns[i]: self._sort_column(c, False))
            self.tree.column(self.columns[i], anchor="w", width=120)
        
        self.tree.column("ID", width=40, anchor="center")
        self.tree.column("Name", width=150)

        # Add a scrollbar to the treeview
        tree_scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scrollbar.set)
        
        tree_scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        # Bind events
        self.tree.bind("<<TreeviewSelect>>", self.on_select_item)
        self.tree.bind("<Button-1>", self.on_tree_click)
        self.tree.bind("<Motion>", self._on_tree_motion)
        self.tree.bind("<Button-3>", self.show_context_menu)

        # --- Scrollable Details Box ---
        detail_frame = ttk.Frame(frame)
        detail_frame.pack(fill="both", expand=False, pady=(10, 5))

        detail_scrollbar = ttk.Scrollbar(detail_frame, orient="vertical")
        self.detail_text = tk.Text(detail_frame, height=10, wrap="word", font=("Segoe UI", 9),
                                   yscrollcommand=detail_scrollbar.set)
        detail_scrollbar.config(command=self.detail_text.yview)

        self.detail_text.pack(side="left", fill="both", expand=True)
        detail_scrollbar.pack(side="right", fill="y")

        # Configure tags for text formatting in the details box
        self.detail_text.tag_configure("bold", font=("Segoe UI", 9, "bold"))
        self.detail_text.tag_configure("link", foreground="blue", underline=True)
        self.detail_text.tag_bind("link", "<Enter>", lambda e: self.detail_text.config(cursor="hand2"))
        self.detail_text.tag_bind("link", "<Leave>", lambda e: self.detail_text.config(cursor=""))
        self.detail_text.tag_bind("link", "<Button-1>", self._open_path_from_detail)
        
        # --- Bottom Frame (Export Button and Progress Bar) ---
        bottom_frame = ttk.Frame(frame)
        bottom_frame.pack(fill="x", pady=(5,0))

        self.export_menubutton = ttk.Menubutton(bottom_frame, text=self._("export_report"), width=25)
        self.export_menubutton.pack(side="right", padx=5)
        self.export_menu = tk.Menu(self.export_menubutton, tearoff=0)
        self.export_menubutton["menu"] = self.export_menu
        self.export_menu.add_command(label="Excel (.xlsx)", command=lambda: self._prompt_and_export("xlsx"))
        self.export_menu.add_command(label="CSV (.csv)", command=lambda: self._prompt_and_export("csv"))
        self.export_menu.add_command(label="JSON (.json)", command=lambda: self._prompt_and_export("json"))
        self.export_menu.add_command(label="HTML (.html)", command=lambda: self._prompt_and_export("html"))
        self.export_menubutton.config(state="disabled")

        self.progressbar = ttk.Progressbar(bottom_frame, orient="horizontal", mode="determinate", style="blue.Horizontal.TProgressbar")
        self.progressbar.pack(side="left", fill="x", expand=True, padx=5)


    def _setup_drag_and_drop(self):
        """Enables drag and drop for the main window."""
        self.root.drop_target_register(DND_FILES)
        self.root.dnd_bind('<<Drop>>', self.handle_drop)

    def handle_drop(self, event):
        """Handles files that are dropped onto the window."""
        # The path can sometimes be enclosed in braces {}
        folder_path = event.data.strip('{}')
        if os.path.isdir(folder_path):
            self.start_scan_thread(Path(folder_path))
        else:
            messagebox.showwarning(self._("drop_error_title"), self._("drop_error_message"))

    def _on_tree_motion(self, event):
        """Changes the cursor to a hand when hovering over a clickable cell."""
        col_id = self.tree.identify_column(event.x)
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            self.tree.config(cursor="")
            return

        path_str = self.tree.item(row_id, "values")[3]
        
        # Check for EXIFTool column (index 8)
        if col_id == '#8':
            if path_str in self.exif_outputs and self.exif_outputs[path_str]:
                exif_output = self.exif_outputs[path_str]
                # Check if the output is an error message
                is_error = (exif_output == self._("exif_err_notfound") or
                            exif_output.startswith(self._("exif_err_prefix")) or
                            exif_output.startswith(self._("exif_err_run").split("{")[0]))
                if not is_error:
                    self.tree.config(cursor="hand2")
                    return
        
        # Check for Indicators column (index 9)
        if col_id == '#9':
            data_item = next((d for d in self.all_scan_data if str(d.get('path')) == path_str), None)
            if data_item and data_item.get("indicator_keys"):
                self.tree.config(cursor="hand2")
                return

        # Default cursor if not over a clickable cell
        self.tree.config(cursor="")

    def on_tree_click(self, event):
        """Handles clicks in the table to open popups."""
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell": return
        
        col_id = self.tree.identify_column(event.x)
        col_index = int(col_id.replace("#", "")) - 1
        row_id = self.tree.identify_row(event.y)
        if not row_id: return

        path_str = self.tree.item(row_id, "values")[3]

        if col_index == 7: # EXIFTool column
            if path_str in self.exif_outputs and self.exif_outputs[path_str]:
                self.show_exif_popup(self.exif_outputs[path_str])
            else:
                messagebox.showinfo(self._("no_exif_output_title"), self._("no_exif_output_message"), parent=self.root)
        
        elif col_index == 8: # Indicators column
            data_item = next((d for d in self.all_scan_data if str(d.get('path')) == path_str), None)
            if data_item and data_item.get("indicator_keys"):
                self.show_indicators_popup(data_item["indicator_keys"])
            else:
                messagebox.showinfo(self._("indicators_popup_title"), self._("no_indicators_message"), parent=self.root)

    def show_context_menu(self, event):
        """Displays a right-click context menu for the selected row."""
        item_id = self.tree.identify_row(event.y)
        if not item_id:
            return
        
        self.tree.selection_set(item_id)
        values = self.tree.item(item_id, "values")
        
        context_menu = tk.Menu(self.root, tearoff=0)

        # Add "View PDF" for all rows
        context_menu.add_command(label=self._("view_pdf"), command=lambda: self.show_pdf_viewer_popup(item_id))
        context_menu.add_separator()
        
        # Add common menu items
        context_menu.add_command(label="View EXIFTool Output", command=lambda: self.show_exif_popup_from_item(item_id))
        context_menu.add_command(label="View Timeline", command=self.show_timeline_popup)
        
        # Check if the selected item is a revision
        path_str = values[3] if values else None
        is_revision = False
        if path_str:
            scan_data_item = next((item for item in self.all_scan_data if str(item.get('path')) == path_str), None)
            if scan_data_item and scan_data_item.get('is_revision'):
                is_revision = True

        # Add revision-specific menu items
        if is_revision:
            context_menu.add_separator()
            context_menu.add_command(label=self._("visual_diff"), command=lambda: self.show_visual_diff_popup(item_id))

        context_menu.add_separator()
        context_menu.add_command(label="Open File Location", command=lambda: self.open_file_location(item_id))
        
        # Display the context menu at the cursor's position
        context_menu.tk_popup(event.x_root, event.y_root)

    def open_file_location(self, item_id):
        """Opens the folder containing the selected file in the system's file explorer."""
        values = self.tree.item(item_id, "values")
        if values:
            webbrowser.open(os.path.dirname(values[3]))

    def show_exif_popup_from_item(self, item_id):
        """Shows the EXIFTool popup for a given treeview item."""
        values = self.tree.item(item_id, "values")
        if values:
            self.show_exif_popup(self.exif_outputs.get(values[3]))
    def show_exif_popup(self, content):
        """Display a large, scrollable popup window with EXIFTool output."""
        if not content:
            messagebox.showinfo(self._("no_exif_output_title"),
                                self._("no_exif_output_message"),
                                parent=self.root)
            return

        # Close existing popup to avoid duplicates
        if getattr(self, "exif_popup", None) and self.exif_popup.winfo_exists():
            self.exif_popup.destroy()

        # Large, centered popup (~85% of screen)
        self.exif_popup = Toplevel(self.root)
        self.exif_popup.title(self._("exif_popup_title"))
        self.exif_popup.resizable(True, True)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = int(sw * 0.85)
        h = int(sh * 0.85)
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.exif_popup.geometry(f"{w}x{h}+{x}+{y}")
        self.exif_popup.transient(self.root)

        # Scrollbars + monospaced text
        frame = ttk.Frame(self.exif_popup, padding=8)
        frame.pack(fill="both", expand=True)

        vscroll = ttk.Scrollbar(frame, orient="vertical")
        vscroll.pack(side="right", fill="y")

        hscroll = ttk.Scrollbar(frame, orient="horizontal")
        hscroll.pack(side="bottom", fill="x")

        text = tk.Text(
            frame,
            wrap="none",
            yscrollcommand=vscroll.set,
            xscrollcommand=hscroll.set,
            font=("Consolas", 10)
        )
        text.pack(side="left", fill="both", expand=True)
        vscroll.config(command=text.yview)
        hscroll.config(command=text.xview)

        text.insert("1.0", content)
        self._make_text_copyable(text)
        text.mark_set("insert", "1.0")
        text.see("1.0")


    def _make_text_copyable(self, text_widget):
        """Makes a Text widget read-only but allows text selection and copying."""
        context_menu = tk.Menu(text_widget, tearoff=0)
        
        def copy_selection(event=None):
            """Copies the selected text to the clipboard."""
            try:
                selected_text = text_widget.get(tk.SEL_FIRST, tk.SEL_LAST)
                self.root.clipboard_clear()
                self.root.clipboard_append(selected_text)
            except tk.TclError:
                # This can happen if no text is selected
                pass
            return "break" # Prevents default event handling

        context_menu.add_command(label=self._("copy"), command=copy_selection)
        

        def show_context_menu(event):
            """Shows the context menu if text is selected."""
            if text_widget.tag_ranges(tk.SEL):
                context_menu.tk_popup(event.x_root, event.y_root)

        text_widget.config(state="normal") # Make it temporarily writable to bind
        text_widget.bind("<Key>", lambda e: "break") # Disable typing
        text_widget.bind("<Button-3>", show_context_menu) # Right-click
        text_widget.bind("<Control-c>", copy_selection) # Ctrl+C
        text_widget.bind("<Command-c>", copy_selection) # Command+C for macOS
        
    def _add_layer_indicators(self, raw: bytes, path: Path, indicators: dict):
        """
        Adds indicators for layers:
          - "Has Layers (count)" if OCGs are found.
          - "More Layers Than Pages" if layer count > page count.
        """
        try:
            layers_cnt = count_layers(raw)
        except Exception:
            layers_cnt = 0

        if layers_cnt <= 0:
            return

        indicators['HasLayers'] = {'count': layers_cnt}

        # Compare with page count (best-effort)
        page_count = 0
        try:
            with fitz.open(path) as _doc:
                page_count = _doc.page_count
        except Exception:
            pass

        if page_count and layers_cnt > page_count:
            indicators['MoreLayersThanPages'] = {'layers': layers_cnt, 'pages': page_count}


    def show_pdf_viewer_popup(self, item_id):
        """Displays a simple PDF viewer for the selected file."""
        self.root.config(cursor="watch")
        self.root.update_idletasks()

        try:
            path_str = self.tree.item(item_id, "values")[3]
            file_name = self.tree.item(item_id, "values")[1]
        except (IndexError, TypeError):
            self.root.config(cursor="")
            return

        try:
            # --- Popup Window Setup ---
            popup = Toplevel(self.root)
            popup.title(f"{self._('pdf_viewer_title')} - {file_name}")
            
            # --- PDF Loading ---
            popup.current_page = 0
            popup.doc = fitz.open(path_str)
            popup.total_pages = len(popup.doc)

            # --- Widget Layout ---
            main_frame = ttk.Frame(popup, padding=10)
            main_frame.pack(fill="both", expand=True)
            main_frame.rowconfigure(0, weight=1)
            main_frame.columnconfigure(0, weight=1)

            image_label = ttk.Label(main_frame)
            image_label.grid(row=0, column=0, pady=5, sticky="nsew")
            
            nav_frame = ttk.Frame(main_frame)
            nav_frame.grid(row=1, column=0, pady=(10,0))
            
            prev_button = ttk.Button(nav_frame, text=self._("diff_prev_page"))
            page_label = ttk.Label(nav_frame, text="", font=("Segoe UI", 9, "italic"))
            next_button = ttk.Button(nav_frame, text=self._("diff_next_page"))

            prev_button.pack(side="left", padx=10)
            page_label.pack(side="left", padx=10)
            next_button.pack(side="left", padx=10)
            
            def update_page(page_num):
                """Renders and displays a specific page of the PDF."""
                if not (0 <= page_num < popup.total_pages): return
                
                popup.current_page = page_num
                self.root.config(cursor="watch")
                self.root.update()

                # Render page to a pixmap, then to a PIL Image
                page = popup.doc.load_page(page_num)
                pix = page.get_pixmap(dpi=150)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                
                # Scale image to fit the window
                max_img_w, max_img_h = main_frame.winfo_width() * 0.95, main_frame.winfo_height() * 0.9
                img_w, img_h = img.size
                ratio = min(max_img_w / img_w, max_img_h / img_h) if img_w > 0 and img_h > 0 else 1
                scaled_size = (int(img_w * ratio), int(img_h * ratio))

                # Convert to Tkinter PhotoImage and display
                img_tk = ImageTk.PhotoImage(img.resize(scaled_size, Image.Resampling.LANCZOS))
                popup.img_tk = img_tk # Keep a reference to prevent garbage collection
                
                image_label.config(image=img_tk)
                page_label.config(text=self._("diff_page_label").format(current=page_num + 1, total=popup.total_pages))
                prev_button.config(state="normal" if page_num > 0 else "disabled")
                next_button.config(state="normal" if page_num < popup.total_pages - 1 else "disabled")
                self.root.config(cursor="")

            prev_button.config(command=lambda: update_page(popup.current_page - 1))
            next_button.config(command=lambda: update_page(popup.current_page + 1))
            
            def on_close():
                """Ensures the PDF document is closed properly."""
                if hasattr(popup, 'doc') and popup.doc:
                    popup.doc.close()
                popup.destroy()
            popup.protocol("WM_DELETE_WINDOW", on_close)

            popup.geometry("800x600")
            update_page(0) # Show the first page
            
            popup.transient(self.root)
            popup.grab_set()

        except Exception as e:
            logging.error(f"PDF viewer error: {e}")
            messagebox.showerror(self._("pdf_viewer_error_title"), self._("pdf_viewer_error_message").format(e=e), parent=self.root)
            if 'popup' in locals() and hasattr(popup, 'doc') and popup.doc:
                popup.doc.close()
        finally:
            self.root.config(cursor="")

    def show_visual_diff_popup(self, item_id):
        """Shows a side-by-side visual comparison of a revision and its original."""
        self.root.config(cursor="watch")
        self.root.update_idletasks()

        # Get paths for the revision and its corresponding original file
        rev_path_str = self.tree.item(item_id, "values")[3]
        original_path_str = next((str(d['original_path']) for d in self.all_scan_data if str(d['path']) == rev_path_str), None)

        if not original_path_str:
            messagebox.showerror(self._("diff_error_title"), "Original file for revision not found.", parent=self.root)
            self.root.config(cursor="")
            return

        try:
            # --- Popup Window Setup ---
            popup = Toplevel(self.root)
            popup.title(self._("diff_popup_title"))
            
            popup.current_page = 0
            popup.path_orig = original_path_str
            popup.path_rev = rev_path_str
            with fitz.open(popup.path_orig) as doc:
                popup.total_pages = doc.page_count

            # --- Widget Layout ---
            main_frame = ttk.Frame(popup, padding=10)
            main_frame.pack(fill="both", expand=True)

            image_frame = ttk.Frame(main_frame)
            image_frame.grid(row=1, column=0, columnspan=3, pady=5)
            
            label_orig = ttk.Label(image_frame)
            label_rev = ttk.Label(image_frame)
            label_diff = ttk.Label(image_frame)
            label_orig.grid(row=1, column=0, padx=5)
            label_rev.grid(row=1, column=1, padx=5)
            label_diff.grid(row=1, column=2, padx=5)

            ttk.Label(image_frame, text=self._("diff_original_label"), font=("Segoe UI", 10, "bold")).grid(row=0, column=0)
            ttk.Label(image_frame, text=self._("diff_revision_label"), font=("Segoe UI", 10, "bold")).grid(row=0, column=1)
            ttk.Label(image_frame, text=self._("diff_differences_label"), font=("Segoe UI", 10, "bold")).grid(row=0, column=2)

            nav_frame = ttk.Frame(main_frame)
            nav_frame.grid(row=2, column=0, columnspan=3, pady=(10,0))
            
            prev_button = ttk.Button(nav_frame, text=self._("diff_prev_page"))
            page_label = ttk.Label(nav_frame, text="", font=("Segoe UI", 9, "italic"))
            next_button = ttk.Button(nav_frame, text=self._("diff_next_page"))

            prev_button.pack(side="left", padx=10)
            page_label.pack(side="left", padx=10)
            next_button.pack(side="left", padx=10)
            
            def update_page(page_num):
                """Renders the original, revision, and difference for a specific page."""
                if not (0 <= page_num < popup.total_pages):
                    return
                
                popup.current_page = page_num
                self.root.config(cursor="watch")
                self.root.update()

                # Open both PDFs and load the same page
                with fitz.open(popup.path_orig) as doc_orig, fitz.open(popup.path_rev) as doc_rev:
                    page_orig = doc_orig.load_page(page_num)
                    page_rev = doc_rev.load_page(page_num)

                    pix_orig = page_orig.get_pixmap(dpi=150)
                    pix_rev = page_rev.get_pixmap(dpi=150)
                
                img_orig = Image.frombytes("RGB", [pix_orig.width, pix_orig.height], pix_orig.samples)
                img_rev = Image.frombytes("RGB", [pix_rev.width, pix_rev.height], pix_rev.samples)

                # --- Image Difference Calculation ---
                diff = ImageChops.difference(img_orig, img_rev)
                mask = diff.convert('L').point(lambda x: 255 if x > 20 else 0) # Threshold for noise
                final_diff = Image.composite(Image.new('RGB', img_orig.size, 'red'), ImageOps.grayscale(img_orig).convert('RGB'), mask)
                
                # --- Image Scaling ---
                screen_w, screen_h = popup.winfo_screenwidth(), popup.winfo_screenheight()
                max_img_w, max_img_h = (screen_w * 0.95) / 3, screen_h * 0.8 # Scale to fit 3 images across the screen
                orig_w, orig_h = img_orig.size
                ratio = min(max_img_w / orig_w, max_img_h / orig_h) if orig_w > 0 and orig_h > 0 else 1
                scaled_size = (int(orig_w * ratio), int(orig_h * ratio))

                # --- Display Images ---
                images_tk = [ImageTk.PhotoImage(img.resize(scaled_size, Image.Resampling.LANCZOS)) for img in [img_orig, img_rev, final_diff]]
                popup.images_tk = images_tk # Keep references
                
                label_orig.config(image=images_tk[0])
                label_rev.config(image=images_tk[1])
                label_diff.config(image=images_tk[2])

                # --- Update Navigation Controls ---
                page_label.config(text=self._("diff_page_label").format(current=page_num + 1, total=popup.total_pages))
                prev_button.config(state="normal" if page_num > 0 else "disabled")
                next_button.config(state="normal" if page_num < popup.total_pages - 1 else "disabled")
                self.root.config(cursor="")

            prev_button.config(command=lambda: update_page(popup.current_page - 1))
            next_button.config(command=lambda: update_page(popup.current_page + 1))

            update_page(0) # Show the first page
            
            popup.transient(self.root)
            popup.grab_set()

        except Exception as e:
            logging.error(f"Visual diff error: {e}")
            messagebox.showerror(self._("diff_error_title"), self._("diff_error_msg").format(e=e), parent=self.root)
            self.root.config(cursor="")

    def open_settings_popup(self):
        """Opens a window to edit application settings from config.ini."""
        settings_popup = Toplevel(self.root)
        settings_popup.title(self._("settings_title"))
        settings_popup.transient(self.root)
        settings_popup.geometry("400x200")
        settings_popup.resizable(False, False)

        main_frame = ttk.Frame(settings_popup, padding=15)
        main_frame.pack(expand=True, fill="both")

        # Create StringVars to hold the values from the entry boxes
        size_var = tk.StringVar(value=str(PDFReconConfig.MAX_FILE_SIZE // (1024*1024)))
        timeout_var = tk.StringVar(value=str(PDFReconConfig.EXIFTOOL_TIMEOUT))
        threads_var = tk.StringVar(value=str(PDFReconConfig.MAX_WORKER_THREADS))
        diff_pages_var = tk.StringVar(value=str(PDFReconConfig.VISUAL_DIFF_PAGE_LIMIT))

        # Create labels and entry fields
        fields = [
            (self._("settings_max_size"), size_var),
            (self._("settings_timeout"), timeout_var),
            (self._("settings_threads"), threads_var),
            (self._("settings_diff_pages"), diff_pages_var),
        ]

        for i, (label_text, var) in enumerate(fields):
            label = ttk.Label(main_frame, text=label_text)
            label.grid(row=i, column=0, sticky="w", pady=5)
            entry = ttk.Entry(main_frame, textvariable=var, width=10)
            entry.grid(row=i, column=1, sticky="e", pady=5)
        
        main_frame.columnconfigure(1, weight=1)

        def save_settings():
            """Validates, saves, and applies the new settings."""
            try:
                # Read and validate values
                new_size = int(size_var.get())
                new_timeout = int(timeout_var.get())
                new_threads = int(threads_var.get())
                new_diff_pages = int(diff_pages_var.get())

                # Update the running config
                PDFReconConfig.MAX_FILE_SIZE = new_size * 1024 * 1024
                PDFReconConfig.EXIFTOOL_TIMEOUT = new_timeout
                PDFReconConfig.MAX_WORKER_THREADS = new_threads
                PDFReconConfig.VISUAL_DIFF_PAGE_LIMIT = new_diff_pages

                # Write to config.ini
                parser = configparser.ConfigParser()
                parser.read(self.config_path)
                if 'Settings' not in parser:
                    parser['Settings'] = {}
                
                parser['Settings']['MaxFileSizeMB'] = str(new_size)
                parser['Settings']['ExifToolTimeout'] = str(new_timeout)
                parser['Settings']['MaxWorkerThreads'] = str(new_threads)
                parser['Settings']['VisualDiffPageLimit'] = str(new_diff_pages)

                with open(self.config_path, 'w') as configfile:
                    configfile.write("# PDFRecon Configuration File\n")
                    parser.write(configfile)

                logging.info("Settings updated and saved to config.ini.")
                messagebox.showinfo(self._("settings_saved_title"), self._("settings_saved_msg"), parent=settings_popup)
                settings_popup.destroy()

            except ValueError:
                messagebox.showerror("Error", self._("settings_invalid_input"), parent=settings_popup)
            except Exception as e:
                messagebox.showerror("Error", f"Could not save settings: {e}", parent=settings_popup)
                logging.error(f"Failed to save settings: {e}")

        # --- Buttons Frame ---
        buttons_frame = ttk.Frame(main_frame)
        buttons_frame.grid(row=len(fields), column=0, columnspan=2, pady=(15, 0))
        
        save_button = ttk.Button(buttons_frame, text=self._("settings_save"), command=save_settings)
        save_button.pack(side="left", padx=5)

        cancel_button = ttk.Button(buttons_frame, text=self._("settings_cancel"), command=settings_popup.destroy)
        cancel_button.pack(side="left", padx=5)

        settings_popup.grab_set()
        self.root.wait_window(settings_popup)


    def show_indicators_popup(self, indicators_dict):
        """Shows a pop-up window with a list of found indicators."""
        if not indicators_dict:
            messagebox.showinfo(self._("indicators_popup_title"), self._("no_indicators_message"), parent=self.root)
            return

        # Destroy any existing popup
        if hasattr(self, 'indicator_popup') and self.indicator_popup and self.indicator_popup.winfo_exists():
            self.indicator_popup.destroy()
        
        # --- Popup Window Setup ---
        self.indicator_popup = Toplevel(self.root)
        self.indicator_popup.title(self._("indicators_popup_title"))
        self.indicator_popup.geometry("600x400")
        self.indicator_popup.transient(self.root)

        # --- Text Widget with Scrollbar ---
        text_frame = ttk.Frame(self.indicator_popup, padding=10)
        text_frame.pack(fill="both", expand=True)
        
        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side="right", fill="y")
        
        text_widget = tk.Text(text_frame, wrap="word", yscrollcommand=scrollbar.set, font=("Segoe UI", 9))
        text_widget.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=text_widget.yview)
        
        # Format the content with translated keys and details
        content_lines = [self._format_indicator_details(key, details) for key, details in indicators_dict.items()]
        content = "• " + "\n• ".join(content_lines)

        text_widget.insert("1.0", content)
        
        # Make the text copyable but not editable
        self._make_text_copyable(text_widget)


    def _resolve_path(self, filename, base_is_parent=False):
        """
        Resolves the correct path for a resource file, whether running as a script
        or as a frozen executable (e.g., with PyInstaller).
        """
        if getattr(sys, 'frozen', False):
            # If the app is frozen, the base path is the folder containing the exe.
            base_path = Path(sys.executable).parent
            if not base_is_parent:
                # Data files (like exiftool) are in a temp folder _MEIPASS,
                # unless we want a file next to the exe (base_is_parent=True).
                return Path(getattr(sys, '_MEIPASS', base_path)) / filename
        else:
            # If running as a normal script, the base path is the script's folder.
            base_path = Path(__file__).resolve().parent
        return base_path / filename

    def show_license(self):
        """Displays the license information from 'license.txt' in a popup."""
        license_path = self._resolve_path("license.txt")
        try:
            with open(license_path, 'r', encoding='utf-8') as f: license_text = f.read()
        except FileNotFoundError:
            messagebox.showerror(self._("license_error_title"), self._("license_error_message"))
            return
        
        # --- Popup Window Setup ---
        license_popup = Toplevel(self.root)
        license_popup.title(self._("license_popup_title"))
        license_popup.geometry("600x500")
        license_popup.transient(self.root)

        # --- Text Widget with Scrollbar and Close Button ---
        text_frame = ttk.Frame(license_popup, padding=10)
        text_frame.pack(fill="both", expand=True)
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)
        
        scroll_frame = ttk.Frame(text_frame)
        scroll_frame.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(scroll_frame)
        scrollbar.pack(side="right", fill="y")
        text_widget = tk.Text(scroll_frame, wrap="word", yscrollcommand=scrollbar.set, font=("Courier New", 9), borderwidth=0, highlightthickness=0)
        text_widget.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=text_widget.yview)
        
        text_widget.insert("1.0", license_text)
        text_widget.config(state="disabled") # Make read-only
        
        close_button = ttk.Button(text_frame, text=self._("close_button_text"), command=license_popup.destroy)
        close_button.grid(row=1, column=0, pady=(10,0))

    def show_log_file(self):
        """Opens the application's log file in the default system viewer."""
        if self.log_file_path.exists():
            webbrowser.open(self.log_file_path.as_uri())
        else:
            messagebox.showinfo(self._("log_not_found_title"), self._("log_not_found_message"), parent=self.root)

    def _sort_column(self, col, reverse):
        """Sorts the treeview column when its header is clicked."""
        is_id_column = col == self.columns[0]
        # Define a key for sorting: convert to int for ID column, otherwise use string value
        def get_key(item):
            val = self.tree.set(item, col)
            return int(val) if is_id_column and val else val

        # Get data from tree, sort it, and re-insert it
        data_list = [(get_key(k), k) for k in self.tree.get_children("")]
        data_list.sort(reverse=reverse)
        for index, (val, k) in enumerate(data_list):
            self.tree.move(k, "", index)
        
        # Toggle the sort direction for the next click
        self.tree.heading(col, command=lambda: self._sort_column(col, not reverse))

    def choose_folder(self):
        """Opens a dialog for the user to select a folder to scan."""
        folder_path = filedialog.askdirectory(title=self._("choose_folder_title"))
        if folder_path:
            self.start_scan_thread(Path(folder_path))

    def start_scan_thread(self, folder_path):
        """Initializes and starts the background scanning process."""
        logging.info(f"Starting scan of folder: {folder_path}")
        
        # --- Reset Application State ---
        self.tree.delete(*self.tree.get_children())
        self.report_data.clear()
        self.all_scan_data.clear()
        self.exif_outputs.clear()
        self.timeline_data.clear()
        self.path_to_id.clear()
        self.revision_counter = 0
        self.scan_queue = queue.Queue()
        self.scan_start_time = time.time()
        self.filter_var.set("")
        
        # --- Update GUI for Scanning State ---
        self.scan_button.config(state="disabled")
        self.export_menubutton.config(state="disabled")
        self.status_var.set(self._("preparing_analysis"))
        self.progressbar.config(value=0)

        # --- Start Worker Thread ---
        # The scan runs in a separate thread to keep the GUI responsive.
        scan_thread = threading.Thread(target=self._scan_worker_parallel, args=(folder_path, self.scan_queue))
        scan_thread.daemon = True
        scan_thread.start()

        # Start polling the queue for updates from the worker thread.
        self._process_queue()

    def _find_pdf_files_generator(self, folder):
        """A generator that 'yields' PDF files as soon as they are found."""
        for base, _, files in os.walk(folder):
            for fn in files:
                if fn.lower().endswith(".pdf"):
                    yield Path(base) / fn

    def validate_pdf_file(self, filepath):
        """
        Validates a PDF file based on size, header, and encryption.
        Returns True if valid, otherwise raises an appropriate exception.
        """
        try:
            # Check file size
            if filepath.stat().st_size > PDFReconConfig.MAX_FILE_SIZE:
                raise PDFTooLargeError(f"File exceeds {PDFReconConfig.MAX_FILE_SIZE // (1024*1024)}MB size limit.")

            # Check PDF header
            with open(filepath, 'rb') as f:
                if f.read(5) != b'%PDF-':
                    raise PDFCorruptionError("Invalid PDF header. Not a PDF file.")
            
            # Check for encryption
            with fitz.open(filepath) as doc:
                if doc.is_encrypted:
                    # Try authenticating with an empty password
                    if not doc.authenticate(""):
                         raise PDFEncryptedError("File is encrypted and cannot be processed.")
            
            return True
        except PDFProcessingError:
            # Re-raise our custom exceptions
            raise
        except Exception as e:
            # Wrap other exceptions in our custom error type
            raise PDFCorruptionError(f"Could not validate file: {e}")

    def _process_large_file_streaming(self, filepath):
        """(Placeholder) Processes a large PDF file using streaming to save memory."""
        logging.info(f"Streaming processing is not yet implemented. Processing {filepath.name} normally.")
        pass
    def extract_additional_xmp_ids(self, txt: str) -> dict:
        """
        Harvest XMP IDs beyond basic xmpMM:{Original,Document,Instance}:
        - stRef:documentID / stRef:instanceID   (both attribute AND element forms)
        - xmpMM:DerivedFrom   (stRef:* and OriginalDocumentID inside)
        - xmpMM:Ingredients   (stRef:* inside)
        - xmpMM:History       (stRef:* and any InstanceID-like values)
        - photoshop:DocumentAncestors (Bag of GUIDs/uuids)
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

    def _process_single_file(self, fp):
        """
        Processes a single PDF file. This method is designed to run in a separate thread.
        Returns a list of dictionaries (one for the original, and one for each revision).
        """
        try:
            # First, validate the file (size, header, encryption)
            self.validate_pdf_file(fp)

            # --- Main Analysis ---
            raw = fp.read_bytes()
            doc = fitz.open(stream=raw, filetype="pdf")
            txt = self.extract_text(raw)
            indicators = self.detect_indicators(fp, txt, doc)
            md5_hash = md5_file(fp)
            exif = self.exiftool_output(fp, detailed=True)
            tool_changed, _, _, _ = self._detect_tool_change_from_exif_simple(exif)
            if tool_changed:
                indicators['ToolChange'] = {}
            original_timeline = self.generate_comprehensive_timeline(fp, txt, exif, is_revision=False)
            revisions = self.extract_revisions(raw, fp)

            doc.close()
            self._add_layer_indicators(raw, fp, indicators)

            # Add "Has Revisions" indicator if any were found
            if revisions:
                indicators['HasRevisions'] = {'count': len(revisions)}

            # --- Collect Results ---
            results = []
            original_row_data = {
                "path": fp, "indicator_keys": indicators, "md5": md5_hash, 
                "exif": exif, "is_revision": False, "timeline": original_timeline, "status": "success"
            }
            results.append(original_row_data)

            # --- Process Revisions ---
            for rev_path, basefile, rev_raw in revisions:
                rev_md5 = hashlib.md5(rev_raw).hexdigest()
                rev_exif = self.exiftool_output(rev_path, detailed=True)
                rev_txt = self.extract_text(rev_raw)
                revision_timeline = self.generate_comprehensive_timeline(rev_path, rev_txt, rev_exif, is_revision=True)

                # Skip revisions that ExifTool identifies as corrupt
                if "Warning" in rev_exif and "Invalid xref table" in rev_exif:
                    logging.info(f"Skipping revision {rev_path.name} due to 'Invalid xref table' warning.")
                    continue

                # Check if the revision is visually identical to the original
                is_identical = False
                try:
                    with fitz.open(fp) as doc_orig, fitz.open(rev_path) as doc_rev:
                        pages_to_compare = min(doc_orig.page_count, doc_rev.page_count, PDFReconConfig.VISUAL_DIFF_PAGE_LIMIT)
                        if pages_to_compare > 0:
                            is_identical = True
                            for i in range(pages_to_compare):
                                page_orig, page_rev = doc_orig.load_page(i), doc_rev.load_page(i)
                                if page_orig.rect != page_rev.rect: is_identical = False; break
                                pix_orig, pix_rev = page_orig.get_pixmap(dpi=96), page_rev.get_pixmap(dpi=96)
                                img_orig = Image.frombytes("RGB", [pix_orig.width, pix_orig.height], pix_orig.samples)
                                img_rev = Image.frombytes("RGB", [pix_rev.width, pix_rev.height], pix_rev.samples)
                                if ImageChops.difference(img_orig, img_rev).getbbox() is not None: is_identical = False; break
                except Exception as e:
                    logging.warning(f"Could not visually compare {rev_path.name}, keeping it. Error: {e}")
                
                revision_row_data = { 
                    "path": rev_path, "indicator_keys": {"Revision": {}}, "md5": rev_md5, "exif": rev_exif, 
                    "is_revision": True, "timeline": revision_timeline, "original_path": fp, 
                    "is_identical": is_identical, "status": "success"
                }
                results.append(revision_row_data)
            return results

        # --- Error Handling ---
        # Catch specific, known errors and return a structured error message.
        except PDFTooLargeError as e:
            logging.warning(f"Skipping large file {fp.name}: {e}")
            return [{"path": fp, "status": "error", "error_type": "file_too_large", "error_message": str(e)}]
        except PDFEncryptedError as e:
            logging.warning(f"Skipping encrypted file {fp.name}: {e}")
            return [{"path": fp, "status": "error", "error_type": "file_encrypted", "error_message": str(e)}]
        except PDFCorruptionError as e:
            logging.warning(f"Skipping corrupt file {fp.name}: {e}")
            return [{"path": fp, "status": "error", "error_type": "file_corrupt", "error_message": str(e)}]
        except Exception as e:
            logging.exception(f"Unexpected error processing file {fp.name}")
            return [{"path": fp, "status": "error", "error_type": "processing_error", "error_message": str(e)}]

    def _scan_worker_parallel(self, folder, q):
        """
        Finds PDF files and processes them in parallel using a ThreadPoolExecutor.
        Results are sent back to the main thread via a queue.
        """
        try:
            q.put(("scan_status", self._("preparing_analysis")))
            
            pdf_files = list(self._find_pdf_files_generator(folder))
            if not pdf_files:
                q.put(("finished", None))
                return

            # Set progress bar to determinate mode
            q.put(("progress_mode_determinate", len(pdf_files)))
            files_processed = 0

            # Use a thread pool to process files concurrently
            with ThreadPoolExecutor(max_workers=PDFReconConfig.MAX_WORKER_THREADS) as executor:
                future_to_path = {executor.submit(self._process_single_file, fp): fp for fp in pdf_files}
                for future in as_completed(future_to_path):
                    path = future_to_path[future]
                    files_processed += 1
                    try:
                        results = future.result()
                        for result_data in results:
                            q.put(("file_row", result_data))
                    except Exception as e:
                        logging.error(f"Unexpected error from thread pool for file {path.name}: {e}")
                        q.put(("file_row", {"path": path, "status": "error", "error_type": "unknown_error", "error_message": str(e)}))
                    
                    # Calculate and send progress update (FPS, ETA)
                    elapsed_time = time.time() - self.scan_start_time
                    fps = files_processed / elapsed_time if elapsed_time > 0 else 0
                    eta_seconds = (len(pdf_files) - files_processed) / fps if fps > 0 else 0
                    q.put(("detailed_progress", {"file": path.name, "fps": fps, "eta": time.strftime('%M:%S', time.gmtime(eta_seconds))}))

        except Exception as e:
            logging.error(f"Error in scan worker: {e}")
            q.put(("error", f"A critical error occurred: {e}"))
        finally:
            # Signal that the scan is finished
            q.put(("finished", None))


    def _process_queue(self):
        """
        Processes messages from the worker thread's queue to update the GUI.
        This function runs periodically via `root.after()`.
        """
        try:
            # Process all available messages in the queue
            while True:
                msg_type, data = self.scan_queue.get_nowait()
                
                if msg_type == "progress_mode_determinate":
                    self.progressbar.config(mode='determinate', maximum=data if data > 0 else 1, value=0)
                elif msg_type == "detailed_progress":
                    self.progressbar['value'] += 1
                    self.status_var.set(self._("scan_progress_eta").format(**data))
                elif msg_type == "scan_status": 
                    self.status_var.set(data)
                elif msg_type == "file_row":
                    # Store all scan data, including revisions and errors
                    self.all_scan_data.append(data)
                    # Store EXIF and timeline data in separate dicts for quick lookup
                    if not data.get("is_revision"):
                        self.exif_outputs[str(data["path"])] = data.get("exif")
                        self.timeline_data[str(data["path"])] = data.get("timeline")
                    else: # For revisions
                        self.exif_outputs[str(data["path"])] = data.get("exif")
                        self.timeline_data[str(data["path"])] = data.get("timeline")
                        self.revision_counter += 1

                elif msg_type == "error": 
                    logging.warning(data)
                    messagebox.showerror("Critical Error", data)
                elif msg_type == "finished":
                    self._finalize_scan()
                    return # Stop polling the queue
        except queue.Empty:
            # If the queue is empty, do nothing
            pass
        # Schedule the next check
        self.root.after(100, self._process_queue)

    def _finalize_scan(self):
        """Performs final actions after the scan is complete."""
        # --- Build path-to-ID map ---
        # This is done once from the complete dataset for efficiency.
        self.path_to_id.clear()
        temp_counter = 0
        for data in self.all_scan_data:
            if not data.get("is_revision"):
                temp_counter += 1
                self.path_to_id[str(data["path"])] = temp_counter

        # Apply the filter (which is initially empty) to show all results.
        self._apply_filter()
        
        # --- Update GUI to 'finished' state ---
        self.scan_button.config(state="normal")
        self.export_menubutton.config(state="normal")
        # Ensure the progress bar is full
        if self.progressbar['value'] < self.progressbar['maximum']:
             self.progressbar['value'] = self.progressbar['maximum']
        
        # Update the summary status bar
        self._update_summary_status()
        logging.info(f"Analysis complete. {self.status_var.get()}")

    def _apply_filter(self, *args):
        """Filters the displayed results based on the search term."""
        search_term = self.filter_var.get().lower()
        
        items_to_show = []
        if not search_term:
            # If no search term, show all data
            items_to_show = self.all_scan_data
        else:
            # Otherwise, filter the data
            for data in self.all_scan_data:
                path_str = str(data.get('path', ''))
                
                # Build a list of searchable fields for each item
                searchable_items = [
                    path_str,
                    data.get('md5', ''),
                ]
                
                if not data.get('is_revision'):
                    try:
                        stat = data['path'].stat()
                        searchable_items.append(datetime.fromtimestamp(stat.st_ctime).strftime("%d-%m-%Y %H:%M:%S"))
                        searchable_items.append(datetime.fromtimestamp(stat.st_mtime).strftime("%d-%m-%Y %H:%M:%S"))
                    except (FileNotFoundError, KeyError):
                        pass

                exif_output = self.exif_outputs.get(path_str, '')
                if exif_output:
                    searchable_items.append(exif_output)
                
                # Combine all searchable text and check for the search term
                full_searchable_text = " ".join(searchable_items).lower()

                if search_term in full_searchable_text:
                    items_to_show.append(data)
        
        # Repopulate the treeview with the filtered results
        self._populate_tree_from_data(items_to_show)

    def _populate_tree_from_data(self, data_list):
        """
        Repopulate the treeview from a (filtered) list of rows.

        Performance: two-pass build (O(n)) with minimal attribute lookups.
        Correctness: 'Revision of #N' uses the ORIGINAL's displayed ID within
        the *current view*. If the original is filtered out, we fall back to
        self.path_to_id (original-only index) so the text is still meaningful.
        """
        tree = self.tree
        _ = self._
        get_flag = self.get_flag
        tree_tags = self.tree_tags
        report_data = self.report_data

        # Clear visible table + export buffer
        tree.delete(*tree.get_children())
        report_data.clear()

        # -------- Pass 1: compute displayed IDs for ORIGINALS in the current view --------
        # Key: str(Path to original) -> displayed ID (as shown in the first column)
        parent_display_id = {}
        counter = 0
        for d in data_list:
            counter += 1
            if d.get("status") == "error":
                continue
            if not d.get("is_revision"):
                parent_display_id[str(d["path"])] = counter

        # -------- Pass 2: build rows and insert (fast path, minimal work per row) --------
        insert = tree.insert
        append = report_data.append
        counter = 0

        for d in data_list:
            counter += 1

            # --- Error rows ---
            if d.get("status") == "error":
                path = d["path"]
                error_type_key = d.get("error_type", "unknown_error")
                error_display_name = _(error_type_key)

                row_values = [
                    counter,                 # ID (GUI)
                    path.name,               # Name
                    error_display_name,      # Altered
                    str(path),               # Path
                    "N/A",                   # MD5
                    "",                      # File Created
                    "",                      # File Modified
                    _("exif_error"),         # EXIFTool
                    d.get("error_message", "Unknown error")  # Signs of Alteration
                ]
                append(row_values)
                insert("", "end", values=row_values, tags=("red_row",))
                continue

            # --- Normal rows (originals + revisions) ---
            path = d["path"]
            is_rev = d.get("is_revision", False)

            # EXIF column text (cheap checks only)
            exif_val = d.get("exif")
            if exif_val:
                is_exif_err = (
                    exif_val == _("exif_err_notfound")
                    or exif_val.startswith(_("exif_err_prefix"))
                    or exif_val.startswith(_("exif_err_run").split("{")[0])
                )
                exif_text = _("exif_error") if is_exif_err else _("exif_view_output")
            else:
                exif_text = _("exif_no_output")

            if is_rev:
                # Parent ID from current view if available; otherwise fall back
                # to your original-only map so we never show "None".
                parent_id = parent_display_id.get(str(d.get("original_path")))
                if parent_id is None:
                    parent_id = self.path_to_id.get(str(d.get("original_path")))

                if d.get("is_identical"):
                    flag = _("status_identical").format(pages=PDFReconConfig.VISUAL_DIFF_PAGE_LIMIT)
                else:
                    flag = get_flag({}, True, parent_id)
                created_time = ""
                modified_time = ""
                indicators_str = ""
                tag = "gray_row" if d.get("is_identical") else "blue_row"

            else:
                # ORIGINAL row: only stat() here, but catch failures fast
                try:
                    st = path.stat()
                    created_time = datetime.fromtimestamp(st.st_ctime).strftime("%d-%m-%Y %H:%M:%S")
                    modified_time = datetime.fromtimestamp(st.st_mtime).strftime("%d-%m-%Y %H:%M:%S")
                except Exception:
                    created_time = ""
                    modified_time = ""

                flag = get_flag(d.get("indicator_keys", {}), False)
                indicators_str = _("indicators_view_output") if d.get("indicator_keys") else _("status_no")
                tag = tree_tags.get(flag, "")

            row_values = [
                counter,                 # ID (GUI)
                path.name,               # Name
                flag,                    # Altered
                str(path),               # Path
                d.get("md5", ""),        # MD5
                created_time,            # File Created
                modified_time,           # File Modified
                exif_text,               # EXIFTool
                indicators_str           # Signs of Alteration
            ]

            append(row_values)
            insert("", "end", values=row_values, tags=(tag,))



    def on_select_item(self, event):
        """Updates the detail view when an item in the tree is selected."""
        selected_items = self.tree.selection()
        if not selected_items:
            # Clear the detail view if nothing is selected
            self.detail_text.config(state="normal")
            self.detail_text.delete("1.0", tk.END)
            self.detail_text.config(state="disabled")
            return
        
        values = self.tree.item(selected_items[0], "values")
        path_str = values[3]  # Path is at index 3
        
        # --- Populate Detail View ---
        self.detail_text.config(state="normal")
        self.detail_text.delete("1.0", tk.END)

        # Find the original scan data for the selected path
        original_data = next((d for d in self.all_scan_data if str(d.get('path')) == path_str), None)

        for i, val in enumerate(values):
            col_name = self.tree.heading(self.columns[i], "text")
            self.detail_text.insert(tk.END, f"{col_name}: ", ("bold",))
            
            if col_name == self._("col_path"):
                # Make the path a clickable link
                self.detail_text.insert(tk.END, val + "\n", ("link",))
            elif col_name == self._("col_indicators") and original_data and original_data.get("indicator_keys"):
                # Display the detailed, formatted list of indicators
                indicator_details = [self._format_indicator_details(key, details) for key, details in original_data["indicator_keys"].items()]
                full_indicators_str = "\n  • " + "\n  • ".join(indicator_details)
                self.detail_text.insert(tk.END, full_indicators_str + "\n")
            else:
                self.detail_text.insert(tk.END, val + "\n")
                
        self.detail_text.config(state="disabled")


    def _open_path_from_detail(self, event):
        """Opens the folder when a path link is clicked in the detail view."""
        index = self.detail_text.index(f"@{event.x},{event.y}")
        # Find which link tag was clicked
        tag_indices = self.detail_text.tag_ranges("link")
        for start, end in zip(tag_indices[0::2], tag_indices[1::2]):
            if self.detail_text.compare(start, "<=", index) and self.detail_text.compare(index, "<", end):
                path_str = self.detail_text.get(start, end).strip()
                try:
                    webbrowser.open(os.path.dirname(path_str))
                except Exception as e:
                    messagebox.showerror(self._("open_folder_error_title"), f"Could not open the folder: {e}")
                break

    def extract_revisions(self, raw, original_path):
        """
        Extracts previous versions (revisions) of a PDF from its raw byte content
        by looking for '%%EOF' markers.
        """
        revisions = []
        offsets = []
        pos = len(raw)
        # Find all '%%EOF' markers from the end of the file backwards
        while (pos := raw.rfind(b"%%EOF", 0, pos)) != -1: offsets.append(pos)
        
        # Filter out invalid or unlikely offsets
        valid_offsets = [o for o in sorted(offsets) if 1000 <= o <= len(raw) - 500]
        if valid_offsets:
            # Create a subdirectory for the extracted revisions
            altered_dir = original_path.parent / "Altered_files"
            altered_dir.mkdir(exist_ok=True)
            for i, offset in enumerate(valid_offsets, start=1):
                rev_bytes = raw[:offset + 5] # The revision is the content from the start to the EOF marker
                rev_filename = f"{original_path.stem}_rev{i}_@{offset}.pdf"
                rev_path = altered_dir / rev_filename
                try:
                    rev_path.write_bytes(rev_bytes)
                    revisions.append((rev_path, original_path.name, rev_bytes))
                except Exception as e: logging.error(f"Error extracting revision: {e}")
        return revisions

    def exiftool_output(self, path, detailed=False):
        """Runs ExifTool safely with a timeout and improved error handling."""
        exe_path = self._resolve_path("exiftool.exe", base_is_parent=True)
        if not exe_path.is_file(): return self._("exif_err_notfound")
        
        try:
            file_content = path.read_bytes()
            # Suppress console window on Windows
            startupinfo = None
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            # Build the command-line arguments for ExifTool
            command = [str(exe_path)]
            if detailed: command.extend(["-a", "-s", "-G1", "-struct"])
            else: command.extend(["-a"])
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
                if not process.stdout.strip(): return f"{self._('exif_err_prefix')}\n{error_message}"
                logging.warning(f"ExifTool stderr for {path.name}: {error_message}")

            # Decode the output, trying UTF-8 first, then latin-1 as a fallback
            try: raw_output = process.stdout.decode('utf-8').strip()
            except UnicodeDecodeError: raw_output = process.stdout.decode('latin-1', 'ignore').strip()

            # Remove empty lines from the output
            return "\n".join([line for line in raw_output.splitlines() if line.strip()])

        except subprocess.TimeoutExpired:
            logging.error(f"ExifTool timed out for file {path.name}")
            return self._("exif_err_prefix") + f"\nTimeout after {PDFReconConfig.EXIFTOOL_TIMEOUT} seconds."
        except Exception as e:
            logging.error(f"Error running exiftool for file {path}: {e}")
            return self._("exif_err_run").format(e=e)

    def _get_filesystem_times(self, filepath):
        """Helper function to get created/modified timestamps from the file system."""
        events = []
        try:
            stat = filepath.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime)
            events.append((mtime, f"File System: {self._('col_modified')}"))
            ctime = datetime.fromtimestamp(stat.st_ctime)
            events.append((ctime, f"File System: {self._('col_created')}"))
        except FileNotFoundError:
            pass
        return events
        
        
    def _detect_tool_change_from_exif(self, exiftool_output: str):
        """
        Returns a dict with:
          {
            'changed': bool,
            'create_tool': str, 'modify_tool': str,
            'create_engine': str, 'modify_engine': str,
            'modify_dt': datetime|None,
            'reason': 'producer'|'software'|'engine'|'mixed'
          }
        Sets changed=True if the tool or XMP engine has changed between the first create and the last modify.
        """
        lines = exiftool_output.splitlines()
        kv_re = re.compile(r'^\[(?P<group>[^\]]+)\]\s*(?P<tag>[\w\-/ ]+?)\s*:\s*(?P<value>.+)$')
        date_re = re.compile(
            r'^\[(?P<group>[^\]]+)\]\s*(?P<tag>[\w\-/ ]+?)\s*:\s*(?P<value>.*?)(?P<date>\d{4}:\d{2}:\d{2}\s\d{2}:\d{2}:\d{2}(?:[+\-]\d{2}:\d{2}|Z)?).*$'
        )

        # Collect relevant fields
        producer_pdf = producer_xmppdf = ""
        softwareagent = application = software = creatortool = ""
        create_engine = modify_engine = ""  # XMPToolkit at create/modify (heuristic)
        xmptoolkit = ""                    # general value

        def looks_like_software(s: str) -> bool:
            return bool(s and self.software_tokens.search(s))

        # First pass: collect key/value pairs
        for ln in lines:
            m = kv_re.match(ln)
            if not m:
                continue
            group = m.group("group").strip().lower()
            tag   = m.group("tag").strip().lower().replace(" ", "")
            val   = m.group("value").strip()

            if tag == "producer":
                if group == "pdf" and not producer_pdf:
                    producer_pdf = val
                elif group in ("xmp-pdf", "xmp_pdf") and not producer_xmppdf:
                    producer_xmppdf = val
                if not producer_pdf and producer_xmppdf:
                    producer_pdf = producer_xmppdf
                if not producer_xmppdf and producer_pdf:
                    producer_xmppdf = producer_pdf

            elif tag == "softwareagent" and not softwareagent:
                softwareagent = val
            elif tag == "application" and not application:
                application = val
            elif tag == "software" and not software:
                software = val
            elif tag == "creatortool" and not creatortool:
                if looks_like_software(val):
                    creatortool = val
            elif tag == "xmptoolkit" and not xmptoolkit:
                xmptoolkit = val

        # Select tool based on a priority order
        def choose_tool_for_create():
            return producer_pdf or producer_xmppdf or application or software or creatortool or ""
        def choose_tool_for_modify():
            return softwareagent or producer_pdf or producer_xmppdf or application or software or creatortool or ""

        # Find the first Create* and latest Modify*/MetadataDate timestamp
        create_dt = None
        modify_dt = None
        for ln in lines:
            m = date_re.match(ln)
            if not m:
                continue
            tag = m.group("tag").strip().lower().replace(" ", "")
            date_str = m.group("date")
            base = date_str.replace("Z", "+00:00").split('+')[0].split('-')[0]
            try:
                dt = datetime.strptime(base, "%Y:%m:%d %H:%M:%S")
            except ValueError:
                continue
            if tag in {"createdate", "creationdate"} and create_dt is None:
                create_dt = dt
            elif tag in {"modifydate", "metadatadate"}:
                if (modify_dt is None) or (dt > modify_dt):
                    modify_dt = dt

        create_tool = choose_tool_for_create()
        modify_tool = choose_tool_for_modify()

        # Heuristic: bind XMPToolkit as the engine for both create/modify if known.
        # If there's a ModifyDate, assume the same toolkit was active at the last change.
        if xmptoolkit:
            if create_dt:
                create_engine = xmptoolkit
            if modify_dt:
                modify_engine = xmptoolkit

        # Evaluate the change
        changed_tool = bool(create_tool and modify_tool and create_tool.strip() != modify_tool.strip())
        changed_engine = bool(create_engine and modify_engine and create_engine.strip() != modify_engine.strip())

        reason = None
        if changed_tool and changed_engine:
            reason = "mixed"
        elif changed_tool:
            reason = "producer" if (producer_pdf or producer_xmppdf) else "software"
        elif changed_engine:
            reason = "engine"
        else:
            reason = ""

        return {
            "changed": bool(changed_tool or changed_engine),
            "create_tool": create_tool, "modify_tool": modify_tool,
            "create_engine": create_engine, "modify_engine": modify_engine,
            "modify_dt": modify_dt,
            "reason": reason
        }

    def _parse_exiftool_timeline(self, exiftool_output):
        """
        Parses ExifTool output for timeline events with clear types (Created/Modified/Metadata),
        the correct 'Tool' (SoftwareAgent/Producer/Application/Software; CreatorTool only if software),
        and a separate 'XMP Engine' from XMPToolkit.
        """
        events = []
        lines = exiftool_output.splitlines()

        # --- Collect relevant fields ---
        kv_re = re.compile(r'^\[(?P<group>[^\]]+)\]\s*(?P<tag>[\w\-/ ]+?)\s*:\s*(?P<value>.+)$')
        producer_pdf = ""       # [PDF] Producer
        producer_xmppdf = ""    # [XMP-pdf] Producer
        softwareagent = ""      # XMP History SoftwareAgent or [XMP-*] SoftwareAgent
        application = ""        # Application
        software = ""           # Software
        creatortool = ""        # CreatorTool (only if it looks like software)
        xmptoolkit = ""         # XMP Engine (e.g., Adobe XMP Core ...)

        def looks_like_software(s: str) -> bool:
            return bool(s and self.software_tokens.search(s))

        for ln in lines:
            m = kv_re.match(ln)
            if not m:
                continue
            group = m.group("group").strip().lower()   # e.g., "pdf", "xmp-pdf", "xmp_pdf"
            tag   = m.group("tag").strip().lower().replace(" ", "")
            val   = m.group("value").strip()

            if tag == "producer":
                if group == "pdf" and not producer_pdf:
                    producer_pdf = val
                elif group in ("xmp-pdf", "xmp_pdf") and not producer_xmppdf:
                    producer_xmppdf = val
                if not producer_pdf and producer_xmppdf:
                    producer_pdf = producer_xmppdf
                if not producer_xmppdf and producer_pdf:
                    producer_xmppdf = producer_pdf

            elif tag == "softwareagent" and not softwareagent:
                softwareagent = val
            elif tag == "application" and not application:
                application = val
            elif tag == "software" and not software:
                software = val
            elif tag == "creatortool" and not creatortool:
                if looks_like_software(val):
                    creatortool = val
            elif tag == "xmptoolkit" and not xmptoolkit:
                xmptoolkit = val
            # 'creator' is intentionally ignored as it's often a person's name

        # Pre-select tools for display
        tool_for_create = producer_pdf or producer_xmppdf or application or software or creatortool or ""
        tool_for_modify = softwareagent or producer_pdf or producer_xmppdf or application or software or creatortool or ""

        # --- XMP History (Action/Agent/Changed) ---
        history_full_pattern = re.compile(r"\[XMP-xmpMM\]\s+History\s+:\s+(.*)")
        for line in lines:
            full_match = history_full_pattern.match(line)
            if full_match:
                history_str = full_match.group(1)
                event_blocks = re.findall(r'\{([^}]+)\}', history_str)
                for block in event_blocks:
                    details = {}
                    for pair in block.split(','):
                        if '=' in pair:
                            key, value = pair.split('=', 1)
                            details[key.strip()] = value.strip()
                    if 'When' in details:
                        try:
                            date_str = details['When']
                            dt_obj = datetime.strptime(date_str.replace("Z", "+00:00").split('+')[0].split('.')[0], "%Y:%m:%d %H:%M:%S")
                            action = details.get('Action', 'N/A')
                            agent  = details.get('SoftwareAgent', '')
                            changed = details.get('Changed', '')

                            desc = [f"Action: {action}"]
                            if agent:   desc.append(f"Agent: {agent}")
                            if changed: desc.append(f"Changed: {changed}")

                            events.append((dt_obj, f"XMP History   - {' | '.join(desc)}"))
                        except (ValueError, IndexError):
                            pass

        # --- Generic Date Lines ---
        date_re = re.compile(
            r'^\[(?P<group>[^\]]+)\]\s*(?P<tag>[\w\-/ ]+?)\s*:\s*(?P<value>.*?)(?P<date>\d{4}:\d{2}:\d{2}\s\d{2}:\d{2}:\d{2}(?:[+\-]\d{2}:\d{2}|Z)?).*$'
        )
        def _ts_label(tag: str) -> str:
            """Translates date tag names to more readable labels."""
            t = tag.replace(" ", "").lower()
            if self.language.get() == "da":
                return {"createdate": "Oprettet",
                        "creationdate": "Oprettet",
                        "modifydate": "Ændret",
                        "metadatadate": "Metadata"}.get(t, tag)
            else:
                return {"createdate": "Created",
                        "creationdate": "Created",
                        "modifydate": "Modified",
                        "metadatadate": "Metadata"}.get(t, tag)

        for line in lines:
            m = date_re.match(line)
            if not m:
                continue
            date_str = m.group("date")
            try:
                base = date_str.replace("Z", "+00:00").split('+')[0].split('-')[0]
                dt_obj = datetime.strptime(base, "%Y:%m:%d %H:%M:%S")
            except ValueError:
                continue

            group = m.group("group").strip()      # e.g., "PDF", "XMP-xmp"
            tag   = m.group("tag").strip()        # e.g., "CreateDate", "ModifyDate"
            tag_lc = tag.replace(" ", "").lower()

            label = _ts_label(tag)
            source = group if group else "ExifTool"

            # Assign the appropriate tool based on the date type
            if tag_lc in {"createdate", "creationdate"}:
                tool = tool_for_create
            elif tag_lc in {"modifydate", "metadatadate"}:
                tool = tool_for_modify
            else:
                tool = softwareagent or producer_pdf or producer_xmppdf or application or software or creatortool or ""

            tool_part = f" | Tool: {tool}" if tool else ""
            events.append((dt_obj, f"ExifTool ({source}) - {label}: {date_str}{tool_part}"))

        # --- Display XMP Engine separately (no date - add at first known time) ---
        if xmptoolkit:
            # find a suitable "anchor date": first Create or Modify if possible
            anchor_dt = None
            if events:
                anchor_dt = sorted(events, key=lambda x: x[0])[0][0]
            if not anchor_dt:
                anchor_dt = datetime.now()
            label_engine = "XMP Engine" if self.language.get() == "en" else "XMP-motor"
            events.append((anchor_dt, f"{label_engine}: {xmptoolkit}"))

        return events


    def _detect_tool_change_from_exif_simple(self, exiftool_output: str):
        """
        Returns (changed: bool, create_tool: str, modify_tool: str, modify_dt: datetime|None)
        changed=True if tool at creation != tool at last modification.
        """
        lines = exiftool_output.splitlines()

        # 1) Collect possible software/tool fields
        line_kv_re = re.compile(r'^\[(?P<group>[^\]]+)\]\s*(?P<tag>[\w\-/ ]+?)\s*:\s*(?P<value>.+)$')
        tool_fields = {}
        for ln in lines:
            m = line_kv_re.match(ln)
            if not m:
                continue
            group = m.group("group").strip()
            tag   = m.group("tag").strip()
            val   = m.group("value").strip()
            key_base = tag.replace(" ", "").lower()
            gkey     = group.lower().replace("-", "")
            if key_base in {"softwareagent", "software", "application"}:
                tool_fields[key_base] = val
            elif key_base == "producer":
                tool_fields["producer"] = val
                tool_fields[f"{gkey}_producer"] = val
            elif key_base == "creatortool":
                tool_fields["creatortool"] = val

        def looks_like_software(s: str) -> bool:
            return bool(s and self.software_tokens.search(s))

        def select_tool(tag_lc: str, group_lc: str) -> str:
            """Selects the most likely tool name from the collected fields."""
            if tool_fields.get("softwareagent"):  # XMP History / SoftwareAgent
                return tool_fields["softwareagent"]
            group_key = f"{group_lc.replace('-', '')}_producer"
            if group_key in tool_fields and tool_fields[group_key]:
                return tool_fields[group_key]
            if tool_fields.get("producer"):
                return tool_fields["producer"]
            if tool_fields.get("application"):
                return tool_fields["application"]
            if tool_fields.get("software"):
                return tool_fields["software"]
            ct = tool_fields.get("creatortool", "")
            return ct if looks_like_software(ct) else ""

        # 2) Find create and *latest* modify timestamps + groups (PDF/XMP-xmp)
        date_re = re.compile(
            r'^\[(?P<group>[^\]]+)\]\s*(?P<tag>[\w\-/ ]+?)\s*:\s*(?P<value>.*?)(?P<date>\d{4}:\d{2}:\d{2}\s\d{2}:\d{2}:\d{2}(?:[+\-]\d{2}:\d{2}|Z)?).*$'
        )

        create_tool, modify_tool = "", ""
        latest_modify_dt = None
        latest_modify_group = ""

        for ln in lines:
            m = date_re.match(ln)
            if not m:
                continue
            group = m.group("group").strip()
            tag   = m.group("tag").strip()
            date_str = m.group("date")
            base = date_str.replace("Z", "+00:00").split('+')[0].split('-')[0]
            try:
                dt_obj = datetime.strptime(base, "%Y:%m:%d %H:%M:%S")
            except ValueError:
                continue

            tag_lc = tag.replace(" ", "").lower()
            glc = group.lower()
            if tag_lc in {"createdate", "creationdate"} and not create_tool:
                create_tool = select_tool(tag_lc, glc)
            elif tag_lc in {"modifydate", "metadatadate"}:
                if latest_modify_dt is None or dt_obj > latest_modify_dt:
                    latest_modify_dt = dt_obj
                    latest_modify_group = glc

        if latest_modify_dt:
            modify_tool = select_tool("modifydate", latest_modify_group)

        # Determine if the tool changed
        changed = bool(create_tool and modify_tool and create_tool.strip() != modify_tool.strip())
        return changed, create_tool, modify_tool, latest_modify_dt

        
    def _format_timedelta(self, delta):
            """Formats a timedelta object into a readable string (e.g., (+1d 2h 3m 4.56s))."""
            if not delta or delta.total_seconds() < 0.001:
                return ""

            s = delta.total_seconds()
            days, remainder = divmod(s, 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, seconds = divmod(remainder, 60)
            
            parts = []
            if days > 0: parts.append(f"{int(days)}d")
            if hours > 0: parts.append(f"{int(hours)}h")
            if minutes > 0: parts.append(f"{int(minutes)}m")
            if seconds > 0 or not parts: parts.append(f"{seconds:.2f}s")

            return f"(+{ ' '.join(parts) })"
            
    def _parse_raw_content_timeline(self, file_content_string):
        """Helper function to parse timestamps directly from the file's raw content."""
        events = []
        
        # Look for PDF-style dates: /CreationDate (D:20230101120000...)
        pdf_date_pattern = re.compile(r"\/([A-Z][a-zA-Z0-9_]+)\s*\(\s*D:(\d{14})")
        for match in pdf_date_pattern.finditer(file_content_string):
            label, date_str = match.groups()
            try:
                dt_obj = datetime.strptime(date_str, "%Y%m%d%H%M%S")
                display_line = f"Raw File: /{label}: {dt_obj.strftime('%d-%m-%Y %H:%M:%S')}"
                events.append((dt_obj, display_line))
            except ValueError:
                continue

        # Look for XMP-style dates: <xmp:CreateDate>2023-01-01T12:00:00Z</xmp:CreateDate>
        xmp_date_pattern = re.compile(r"<([a-zA-Z0-9:]+)[^>]*?>\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.*?)\s*<\/([a-zA-Z0-9:]+)>")
        for match in xmp_date_pattern.finditer(file_content_string):
            label, date_str, closing_label = match.groups()
            if label != closing_label: continue # Ensure tags match
            try:
                # Clean the date string of timezones and milliseconds
                clean_date_str = date_str.split('Z')[0].split('+')[0].split('.')[0].strip()
                dt_obj = datetime.fromisoformat(clean_date_str)
                display_line = f"Raw File: <{label}>: {date_str}"
                events.append((dt_obj, display_line))
            except (ValueError, IndexError):
                continue
        return events

    def generate_comprehensive_timeline(self, filepath, raw_file_content, exiftool_output, is_revision=False):
        """Combines all sources into a timeline and inserts an event for tool changes."""
        all_events = []

        # 1) Get File System timestamps (only for original files, not revisions)
        if not is_revision:
            all_events.extend(self._get_filesystem_times(filepath))

        # 2) Get timestamps from ExifTool (this is the most reliable for revisions)
        all_events.extend(self._parse_exiftool_timeline(exiftool_output))

        # 3) Get timestamps from raw PDF/XMP content (ONLY for original files, not revisions)
        if not is_revision:
            all_events.extend(self._parse_raw_content_timeline(raw_file_content))

        # 4) Add a special event if a tool change was detected
        try:
            info = self._detect_tool_change_from_exif(exiftool_output)
            if info.get("changed"):
                # Use the modification date of the change if available, otherwise find the latest known date
                when = info.get("modify_dt")
                if not when and all_events:
                    when = max(all_events, key=lambda x: x[0])[0]
                if not when:
                    when = datetime.now()

                # Format the description of the tool change
                if self.language.get() == "da":
                    label = "Værktøj skiftet"
                    parts = []
                    if info.get("create_tool") or info.get("modify_tool"):
                        parts.append(f"{info.get('create_tool','?')} → {info.get('modify_tool','?')}")
                    if info.get("reason") == "engine" and (info.get('create_engine') or info.get('modify_engine')):
                        parts.append(f"(XMP-motor: {info.get('create_engine','?')} → {info.get('modify_engine','?')})")
                    line = f"{label}: " + " ".join(parts) if parts else label
                else:
                    label = "Tool changed"
                    parts = []
                    if info.get("create_tool") or info.get("modify_tool"):
                        parts.append(f"{info.get('create_tool','?')} → {info.get('modify_tool','?')}")
                    if info.get("reason") == "engine" and (info.get('create_engine') or info.get('modify_engine')):
                        parts.append(f"(XMP engine: {info.get('create_engine','?')} → {info.get('modify_engine','?')})")
                    line = f"{label}: " + " ".join(parts) if parts else label

                all_events.append((when, line))
        except Exception:
            pass

        # 5) Return all events, sorted chronologically
        return sorted(all_events, key=lambda x: x[0])

        
    def show_timeline_popup(self):
        """Displays a popup window with the detailed timeline for a selected file."""
        selected_item = self.tree.selection()
        if not selected_item: return
        path_str = self.tree.item(selected_item[0], "values")[3]
        
        events = self.timeline_data.get(path_str)
        if not events:
            messagebox.showinfo(self._("no_exif_output_title"), self._("timeline_no_data"), parent=self.root)
            return

        # --- Popup Window Setup ---
        popup = Toplevel(self.root)
        popup.title(f"Timeline for {os.path.basename(path_str)}")
        popup.geometry("950x700")
        popup.transient(self.root)

        # --- Text Widget with Scrollbars ---
        text_frame = ttk.Frame(popup, padding=10)
        text_frame.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side="right", fill="y")
        
        text_widget = tk.Text(text_frame, wrap="none", font=("Courier New", 10), yscrollcommand=scrollbar.set, borderwidth=0, highlightthickness=0)
        text_widget.pack(side="left", expand=True, fill="both")
        
        x_scrollbar = ttk.Scrollbar(text_frame, orient="horizontal", command=text_widget.xview)
        x_scrollbar.pack(side="bottom", fill="x")
        text_widget.config(xscrollcommand=x_scrollbar.set)
        
        scrollbar.config(command=text_widget.yview)
        
        # --- Configure Text Tags for Formatting ---
        text_widget.tag_configure("date_header", font=("Courier New", 11, "bold", "underline"), spacing1=10, spacing3=5)
        text_widget.tag_configure("time", font=("Courier New", 10, "bold"))
        text_widget.tag_configure("delta", foreground="#0078D7")
        
        text_widget.tag_configure("source_fs", foreground="#008000") # Green for filesystem
        text_widget.tag_configure("source_exif", foreground="#555555") # Gray for exiftool
        text_widget.tag_configure("source_raw", foreground="#800080") # Purple for raw content
        text_widget.tag_configure("source_xmp", foreground="#C00000") # Red for XMP history

        # --- Populate the Timeline View ---
        last_date = None
        last_dt_obj = None

        for dt_obj, description in events:
            # Insert a date header when the day changes
            if dt_obj.date() != last_date:
                if last_date is not None: text_widget.insert("end", "\n")
                text_widget.insert("end", f"--- {dt_obj.strftime('%d-%m-%Y')} ---\n", "date_header")
                last_date = dt_obj.date()

            # Calculate the time delta from the previous event
            delta_str = ""
            if last_dt_obj:
                delta = dt_obj - last_dt_obj
                delta_str = self._format_timedelta(delta)

            # Assign a color tag based on the event source
            source_tag = "source_exif"
            if description.startswith("File System"): source_tag = "source_fs"
            elif description.startswith("Raw File"): source_tag = "source_raw"
            elif description.startswith("XMP History"): source_tag = "source_xmp"
                
            # Insert the formatted line
            text_widget.insert("end", f"{dt_obj.strftime('%H:%M:%S')} ", "time")
            text_widget.insert("end", f"| {description:<80} ", source_tag)
            text_widget.insert("end", f"{delta_str}\n", "delta")
            
            last_dt_obj = dt_obj
        
        # Make the content copyable
        self._make_text_copyable(text_widget)
        
    @staticmethod
    def decompress_stream(b):
        """Attempts to decompress a PDF stream using common filters."""
        for fn in (zlib.decompress, lambda d: base64.a85decode(re.sub(rb"\s", b"", d), adobe=True), lambda d: binascii.unhexlify(re.sub(rb"\s|>", b"", d))):
            try: return fn(b).decode("latin1", "ignore")
            except Exception: pass
        return ""

    def extract_text(self, raw: bytes):
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
                    txt_segments.append(self.decompress_stream(body))
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

        return "\n".join(txt_segments)

    def analyze_fonts(self, filepath, doc):
            """
            Analyzes fonts to detect multiple subsets of the same base font.
            Returns a dictionary of conflicting fonts, e.g.,
            {'Calibri': {'ABC+Calibri', 'DEF+Calibri-Bold'}}
            """
            font_subsets = {}
            # Iterate through each page to get the fonts used
            for page_num in range(len(doc)):
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
            
            # Filter for only those fonts that actually have multiple subsets
            conflicting_fonts = {base: subsets for base, subsets in font_subsets.items() if len(subsets) > 1}
            if conflicting_fonts:
                logging.info(f"Multiple font subsets found in {filepath.name}: {conflicting_fonts}")

            return conflicting_fonts
    def detect_indicators(self, filepath, txt: str, doc):
        """
        Searches for indicators of alteration/manipulation.
        Returns a dictionary of indicator keys to their details.
        """
        indicators = {}

        # --- High-Confidence Indicators ---
        if re.search(r"touchup_textedit", txt, re.I):
            indicators['TouchUp_TextEdit'] = {}

        # --- Metadata Indicators ---
        creators = set(re.findall(r"/Creator\s*\((.*?)\)", txt, re.I))
        if len(creators) > 1:
            indicators['MultipleCreators'] = {'count': len(creators), 'values': list(creators)}
        
        producers = set(re.findall(r"/Producer\s*\((.*?)\)", txt, re.I))
        if len(producers) > 1:
            indicators['MultipleProducers'] = {'count': len(producers), 'values': list(producers)}

        if re.search(r'<xmpMM:History>', txt, re.I | re.S):
            indicators['XMPHistory'] = {}

        # --- Structural and Content Indicators ---
        try:
            conflicting_fonts = self.analyze_fonts(filepath, doc)
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
        if re.search(r"/Redact\b", txt, re.I): indicators['HasRedactions'] = {}
        if re.search(r"/Annots\b", txt, re.I): indicators['HasAnnotations'] = {}
        if re.search(r"/PieceInfo\b", txt, re.I): indicators['HasPieceInfo'] = {}
        if re.search(r"/AcroForm\b", txt, re.I):
            indicators['HasAcroForm'] = {}
            if re.search(r"/NeedAppearances\s+true\b", txt, re.I):
                indicators['AcroFormNeedAppearances'] = {}

        # Check for objects with generation > 0
        gen_gt_zero_matches = [m for m in re.finditer(r"\b(\d+)\s+(\d+)\s+obj\b", txt) if int(m.group(2)) > 0]
        if gen_gt_zero_matches:
            indicators['ObjGenGtZero'] = {'count': len(gen_gt_zero_matches)}

        # --- ID Comparison (families separated) ---
        def _norm_uuid(x):
            if x is None: return None
            if isinstance(x, (bytes, bytearray)): return x.hex().upper()
            s = str(x).strip().upper()
            return re.sub(r"^(URN:UUID:|UUID:|XMP\.IID:|XMP\.DID:)", "", s).strip("<>")

        # XMP ID family
        xmp_orig = _norm_uuid(re.search(r"xmpMM:OriginalDocumentID(?:>|=\")([^<\"]+)", txt, re.I).group(1) if re.search(r"xmpMM:OriginalDocumentID", txt, re.I) else None)
        xmp_doc = _norm_uuid(re.search(r"xmpMM:DocumentID(?:>|=\")([^<\"]+)", txt, re.I).group(1) if re.search(r"xmpMM:DocumentID", txt, re.I) else None)
        
        if xmp_orig and xmp_doc and xmp_doc != xmp_orig:
            indicators['XMPIDChange'] = {'from': xmp_orig, 'to': xmp_doc}

        # Trailer ID family
        trailer_match = re.search(r"/ID\s*\[\s*<\s*([0-9A-Fa-f]+)\s*>\s*<\s*([0-9A-Fa-f]+)\s*>\s*\]", txt)
        if trailer_match:
            trailer_orig, trailer_curr = _norm_uuid(trailer_match.group(1)), _norm_uuid(trailer_match.group(2))
            if trailer_orig and trailer_curr and trailer_curr != trailer_orig:
                indicators['TrailerIDChange'] = {'from': trailer_orig, 'to': trailer_curr}
        
        # --- Date Mismatch (Info vs. XMP) ---
        info_dates = dict(re.findall(r"/(ModDate|CreationDate)\s*\(\s*D:(\d{8,14})", txt))
        xmp_dates = {k: v for k, v in re.findall(r"<xmp:(ModifyDate|CreateDate)>([^<]+)</xmp:\1>", txt)}

        def _short(d: str) -> str: return re.sub(r"[-:TZ]", "", d)[:14]

        if "CreationDate" in info_dates and "CreateDate" in xmp_dates:
            if _short(info_dates["CreationDate"]) != _short(xmp_dates["CreateDate"]):
                indicators['CreateDateMismatch'] = {'info': info_dates["CreationDate"], 'xmp': xmp_dates["CreateDate"]}
        if "ModDate" in info_dates and "ModifyDate" in xmp_dates:
            if _short(info_dates["ModDate"]) != _short(xmp_dates["ModifyDate"]):
                indicators['ModifyDateMismatch'] = {'info': info_dates["ModDate"], 'xmp': xmp_dates["ModifyDate"]}
        
        return indicators
    

    def get_flag(self, indicators_dict, is_revision, parent_id=None):
        """
        Determines the file's status flag based on the found indicator keys.

        Rules:
          - Revisions always return "Revision of <id>".
          - High-risk indicators return YES/JA.
          - Any other findings return "Possible"/"Sandsynligt".
          - No findings return "NO".
        """
        if is_revision:
            return self._("revision_of").format(id=parent_id)

        keys_set = set(indicators_dict.keys())
        YES = "YES" if self.language.get() == "en" else "JA"
        NO = self._("status_no")

        # Adjust this set for your auto-YES indicators
        high_risk_indicators = {
            "HasRevisions",
            "TouchUp_TextEdit",
            "Signature: Invalid", # Note: This key is not yet generated by detect_indicators
        }

        if any(ind in high_risk_indicators for ind in keys_set):
            return YES

        # If there are any indications at all, but not auto-YES:
        if indicators_dict:
            return "Possible" if self.language.get() == "en" else "Sandsynligt"

        # No indications:
        return NO

    
    
    def show_about(self):
        """Displays the 'About' popup window."""
        about_popup = Toplevel(self.root)
        about_popup.title(self._("menu_about"))
        about_popup.geometry("520x480") # Adjusted height slightly
        about_popup.resizable(True, True)
        about_popup.transient(self.root)

        # --- Layout ---
        outer_frame = ttk.Frame(about_popup, padding=10)
        outer_frame.pack(fill="both", expand=True)
        outer_frame.rowconfigure(0, weight=1)
        outer_frame.columnconfigure(0, weight=1)

        text_frame = ttk.Frame(outer_frame)
        text_frame.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side="right", fill="y")
        
        about_text_widget = tk.Text(text_frame, wrap="word", yscrollcommand=scrollbar.set, borderwidth=0, highlightthickness=0, background=about_popup.cget("background"))
        about_text_widget.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=about_text_widget.yview)

        # --- Text Formatting Tags ---
        about_text_widget.tag_configure("bold", font=("Segoe UI", 9, "bold"))
        about_text_widget.tag_configure("link", foreground="blue", underline=True)
        about_text_widget.tag_configure("header", font=("Segoe UI", 9, "bold", "underline"))

        # --- Make links clickable ---
        def _open_link(event):
            index = about_text_widget.index(f"@{event.x},{event.y}")
            tag_indices = about_text_widget.tag_ranges("link")
            for start, end in zip(tag_indices[0::2], tag_indices[1::2]):
                if about_text_widget.compare(start, "<=", index) and about_text_widget.compare(index, "<", end):
                    url = about_text_widget.get(start, end).strip()
                    if not url.startswith("http"):
                        url = "https://" + url
                    webbrowser.open(url)
                    break

        about_text_widget.tag_bind("link", "<Enter>", lambda e: about_text_widget.config(cursor="hand2"))
        about_text_widget.tag_bind("link", "<Leave>", lambda e: about_text_widget.config(cursor=""))
        about_text_widget.tag_bind("link", "<Button-1>", _open_link)

        # --- Insert Content ---
        about_text_widget.insert("end", f"{self._('about_version')} ({datetime.now().strftime('%d-%m-%Y')})\n", "bold")
        about_text_widget.insert("end", self._("about_developer_info"))

        # Add project website
        about_text_widget.insert("end", self._("about_project_website"), "bold")
        about_text_widget.insert("end", "github.com/Rasmus-Riis/PDFRecon\n", "link")

        about_text_widget.insert("end", "\n------------------------------------\n\n")
        
        about_text_widget.insert("end", self._("about_purpose_header") + "\n", "header")
        about_text_widget.insert("end", self._("about_purpose_text"))
        
        about_text_widget.insert("end", self._("about_included_software_header") + "\n", "header")
        about_text_widget.insert("end", self._("about_included_software_text").format(tool="ExifTool"))
        
        about_text_widget.insert("end", self._("about_website").format(tool="ExifTool"), "bold")
        about_text_widget.insert("end", "exiftool.org\n", "link")
        
        about_text_widget.insert("end", self._("about_source").format(tool="ExifTool"), "bold")
        about_text_widget.insert("end", "github.com/exiftool/exiftool\n", "link")
        
        about_text_widget.config(state="disabled") # Make read-only
        
        # --- Close Button ---
        close_button = ttk.Button(outer_frame, text=self._("close_button_text"), command=about_popup.destroy)
        close_button.grid(row=1, column=0, pady=(10, 0))

    def show_manual(self):
        """Displays a pop-up window with the program manual."""
        manual_popup = Toplevel(self.root)
        manual_popup.title(self._("manual_title"))
        manual_popup.geometry("800x600")
        manual_popup.resizable(True, True)
        manual_popup.transient(self.root)

        # --- Layout ---
        outer_frame = ttk.Frame(manual_popup, padding=10)
        outer_frame.pack(fill="both", expand=True)
        outer_frame.rowconfigure(0, weight=1)
        outer_frame.columnconfigure(0, weight=1)

        text_frame = ttk.Frame(outer_frame)
        text_frame.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side="right", fill="y")
        
        manual_text_widget = tk.Text(text_frame, wrap="word", yscrollcommand=scrollbar.set, borderwidth=0, highlightthickness=0, background=manual_popup.cget("background"), font=("Segoe UI", 10))
        manual_text_widget.pack(side="left", fill="both", expand=True, padx=5)
        scrollbar.config(command=manual_text_widget.yview)

        # --- Text Formatting Tags ---
        manual_text_widget.tag_configure("h1", font=("Segoe UI", 16, "bold", "underline"), spacing3=10)
        manual_text_widget.tag_configure("h2", font=("Segoe UI", 12, "bold"), spacing1=10, spacing3=5)
        manual_text_widget.tag_configure("b", font=("Segoe UI", 10, "bold"))
        manual_text_widget.tag_configure("i", font=("Segoe UI", 10, "italic"))
        manual_text_widget.tag_configure("red", foreground="#C00000")
        manual_text_widget.tag_configure("yellow", foreground="#C07000")
        manual_text_widget.tag_configure("green", foreground="#008000")

        full_manual_text = self._("full_manual")
        
        # --- Simple Parser for Markdown-like Tags ---
        for line in full_manual_text.strip().split('\n'):
            line = line.strip()
            if line.startswith("# "):
                manual_text_widget.insert(tk.END, line[2:] + "\n", "h1")
            elif line.startswith("## "):
                manual_text_widget.insert(tk.END, line[3:] + "\n", "h2")
            else:
                # Process inline tags like <b> and <red>
                parts = re.split(r'(<.*?>)', line)
                active_tags = set()
                for part in parts:
                    if part.startswith("</"):
                        tag_name = part[2:-1]
                        if tag_name in active_tags:
                            active_tags.remove(tag_name)
                    elif part.startswith("<"):
                        tag_name = part[1:-1]
                        active_tags.add(tag_name)
                    elif part:
                        manual_text_widget.insert(tk.END, part, tuple(active_tags))
                manual_text_widget.insert(tk.END, "\n")

        manual_text_widget.config(state="disabled") # Make read-only

        # --- Close Button ---
        close_button = ttk.Button(outer_frame, text=self._("close_button_text"), command=manual_popup.destroy)
        close_button.grid(row=1, column=0, pady=(10, 0))

    def _prompt_and_export(self, file_format):
        """Prompts the user for a file path and calls the relevant export function."""
        if not self.report_data:
            messagebox.showwarning(self._("no_data_to_save_title"), self._("no_data_to_save_message"))
            return
        
        file_types = {
            "xlsx": [("Excel files", "*.xlsx")], "csv": [("CSV files", "*.csv")],
            "json": [("JSON files", "*.json")], "html": [("HTML files", "*.html")]
        }
        file_path = filedialog.asksaveasfilename(defaultextension=f".{file_format}", filetypes=file_types[file_format])
        if not file_path: return

        try:
            export_methods = {
                "xlsx": self._export_to_excel, "csv": self._export_to_csv,
                "json": self._export_to_json, "html": self._export_to_html
            }
            export_methods[file_format](file_path)
            
            # Ask to open the containing folder
            if messagebox.askyesno(self._("excel_saved_title"), self._("excel_saved_message")):
                webbrowser.open(os.path.dirname(file_path))

        except Exception as e:
            logging.error(f"Error exporting to {file_format.upper()}: {e}")
            messagebox.showerror(self._("excel_save_error_title"), self._("excel_save_error_message").format(e=e))

    def _export_to_excel(self, file_path):
        """Exports the displayed data to an Excel file."""
        logging.info(f"Exporting report to Excel file: {file_path}")
        wb = Workbook()
        ws = wb.active
        ws.title = "PDFRecon Results"
        
        # --- Create Headers ---
        headers = [self._(key) for key in self.columns_keys]
        headers[8] = f"{self._('col_indicators')} {self._('excel_indicators_overview')}"

        for col_num, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_num, value=header)
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color="DDDDDD", end_color="DDDDDD", fill_type="solid")
            cell.alignment = Alignment(wrap_text=True, horizontal="center", vertical="center")
        
        def _indicators_for_path(path_str: str) -> str:
            """Helper function to get a formatted string of indicators for a given path."""
            rec = next((d for d in self.all_scan_data if str(d.get('path')) == path_str), None)
            if not rec: return ""
            indicator_dict = rec.get('indicator_keys') or {}
            if not indicator_dict: return ""
            
            lines = [self._format_indicator_details(key, details) for key, details in indicator_dict.items()]
            return "• " + "\n• ".join(lines)

        # --- Write Data Rows ---
        for row_idx, row_data in enumerate(self.report_data, start=2):
            path = row_data[3]
            exif_text = self.exif_outputs.get(path, "")
            row_data_xlsx = row_data[:]
            row_data_xlsx[7] = exif_text # Replace placeholder with full EXIF text
            
            # Replace placeholder with full indicators list
            indicators_full = _indicators_for_path(path)
            if indicators_full:
                row_data_xlsx[8] = indicators_full

            for col_idx, value in enumerate(row_data_xlsx, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=str(value))
                cell.alignment = Alignment(wrap_text=True, vertical="top")
        
        # --- Final Touches ---
        ws.freeze_panes = "A2"
        for col in ws.columns:
            # Auto-adjust column width (with a max limit)
            max_len = max(len(str(cell.value)) if cell.value else 0 for cell in col)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 50)
        
        wb.save(file_path)
        logging.info(f"Excel report saved successfully to {file_path}")

    def _export_to_csv(self, file_path):
        """Exports the displayed data to a CSV file."""
        headers = [self._(key) for key in self.columns_keys]
        
        def _indicators_for_path(path_str: str) -> str:
            """Helper function to get a semicolon-separated string of indicators."""
            rec = next((d for d in self.all_scan_data if str(d.get('path')) == path_str), None)
            if not rec: return ""
            indicator_dict = rec.get('indicator_keys') or {}
            if not indicator_dict: return ""

            lines = [self._format_indicator_details(key, details) for key, details in indicator_dict.items()]
            return "; ".join(lines)

        # Prepare data with full EXIF output + full indicators
        data_for_export = []
        for row_data in self.report_data:
            new_row = row_data[:]
            path = new_row[3]
            exif_output = self.exif_outputs.get(path, "")
            new_row[7] = exif_output  # Replace "Click to view." with actual output
            indicators_full = _indicators_for_path(path)
            if indicators_full:
                new_row[8] = indicators_full
            data_for_export.append(new_row)

        # Use utf-8-sig for better Excel compatibility with special characters
        with open(file_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(data_for_export)

    def _export_to_json(self, file_path):
        """Exports a more detailed report of all scanned data to a JSON file."""
        full_export = []
        for item in self.all_scan_data:
            path_str = str(item['path'])
            item_copy = item.copy()
            item_copy['path'] = path_str # Convert Path object to string
            if 'original_path' in item_copy:
                item_copy['original_path'] = str(item_copy['original_path'])
            
            # Make indicator details serializable
            if 'indicator_keys' in item_copy:
                serializable_indicators = {}
                for key, details in item_copy['indicator_keys'].items():
                    if 'fonts' in details:
                        # Convert sets to lists
                        serializable_details = details.copy()
                        serializable_details['fonts'] = {k: list(v) for k, v in details['fonts'].items()}
                        serializable_indicators[key] = serializable_details
                    else:
                        serializable_indicators[key] = details
                item_copy['indicator_keys'] = serializable_indicators

            item_copy['exif_data'] = self.exif_outputs.get(path_str, "")
            full_export.append(item_copy)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            # Use default=str to handle non-serializable types like datetime
            json.dump(full_export, f, indent=4, default=str)

    def _export_to_html(self, file_path):
        """Exports a simple, color-coded HTML report."""
        html = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <title>PDFRecon Report</title>
            <style>
                body {{ font-family: sans-serif; }}
                table {{ border-collapse: collapse; width: 100%; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; word-break: break-all; }}
                th {{ background-color: #f2f2f2; }}
                .red-row {{ background-color: #FFDDDD; }}
                .yellow-row {{ background-color: #FFFFCC; }}
                .blue-row {{ background-color: #CCE5FF; }}
                .gray-row {{ background-color: #E0E0E0; }}
            </style>
        </head>
        <body>
            <h1>PDFRecon Report</h1>
            <p>Generated on {date}</p>
            <table>
                <thead><tr>{headers}</tr></thead>
                <tbody>{rows}</tbody>
            </table>
        </body>
        </html>
        """
        headers = "".join(f"<th>{self._(key)}</th>" for key in self.columns_keys)
        rows = ""
        tag_map = {"red_row": "red-row", "yellow_row": "yellow-row", "blue_row": "blue-row", "gray_row": "gray-row"}
        
        # --- Generate Table Rows ---
        for i, values in enumerate(self.report_data):
            tag_class = ""
            try:
                # Find the treeview item corresponding to this report row to get its color tag
                matching_id = next((item_id for item_id in self.tree.get_children() if self.tree.item(item_id, "values")[3] == values[3]), None)
                if matching_id:
                    tags = self.tree.item(matching_id, "tags")
                    if tags:
                        tag = tags[0]
                        tag_class = tag_map.get(tag, "")
            except (IndexError, StopIteration):
                 pass # No tag found
            
            rows += f'<tr class="{tag_class}">' + "".join(f"<td>{v}</td>" for v in values) + "</tr>"

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(html.format(
                date=datetime.now().strftime("%d-%m-%Y %H:%M:%S"),
                headers=headers,
                rows=rows
            ))

    def _format_indicator_details(self, key, details):
        """Generates a human-readable string for an indicator and its details."""
        if key == 'MultipleCreators':
            return f"Multiple Creators (Found {details['count']}): " + ", ".join(f'"{v}"' for v in details['values'])
        if key == 'MultipleProducers':
            return f"Multiple Producers (Found {details['count']}): " + ", ".join(f'"{v}"' for v in details['values'])
        if key == 'MultipleFontSubsets':
            font_details = []
            for base_font, subsets in details['fonts'].items():
                font_details.append(f"'{base_font}': {{{{{', '.join(subsets)}}}}}")
            return f"Multiple Font Subsets: " + "; ".join(font_details)
        if key == 'CreateDateMismatch':
            return f"Creation Date Mismatch: Info='{details['info']}', XMP='{details['xmp']}'"
        if key == 'ModifyDateMismatch':
            return f"Modify Date Mismatch: Info='{details['info']}', XMP='{details['xmp']}'"
        if key == 'TrailerIDChange':
            return f"Trailer ID Changed: From [{details['from']}] to [{details['to']}]"
        if key == 'XMPIDChange':
            return f"XMP DocumentID Changed: From [{details['from']}] to [{details['to']}]"
        if key == 'MultipleStartxref':
            return f"Multiple startxref (Found {details['count']})"
        if key == 'IncrementalUpdates':
            return f"Incremental updates (Found {details['count']} versions)"
        if key == 'ObjGenGtZero':
            return f"Objects with generation > 0 (Found {details['count']} objects)"
        if key == 'HasLayers':
            return f"Has Layers (Found {details['count']})"
        if key == 'MoreLayersThanPages':
            return f"More Layers ({details['layers']}) Than Pages ({details['pages']})"
        # Fallback for simple indicators with no details
        return key.replace("_", " ")


if __name__ == "__main__":
    # Ensure multiprocessing works correctly when the app is frozen (e.g., by PyInstaller).
    if sys.platform.startswith('win'):
        multiprocessing.freeze_support()
        
    # Initialize the main Tkinter window with DnD support
    root = TkinterDnD.Tk()
    app = PDFReconApp(root)
    # Start the application's main event loop
    root.mainloop()

