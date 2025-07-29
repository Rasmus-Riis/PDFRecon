import tkinter as tk
from tkinter import ttk, filedialog, messagebox, Toplevel
import hashlib
import os
import re
import subprocess
import zlib
from pathlib import Path
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
import threading
import queue
import webbrowser
import sys
import logging
import tempfile
try:
    import fitz  # PyMuPDF
except ImportError:
    # Denne besked vil blive vist, hvis PyMuPDF ikke er installeret.
    messagebox.showerror("Manglende Bibliotek", "PyMuPDF er ikke installeret.\n\nKør venligst 'pip install PyMuPDF' i din terminal for at bruge dette program.")
    sys.exit(1)
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:
    messagebox.showerror("Manglende Bibliotek", "tkinterdnd2 er ikke installeret.\n\nKør venligst 'pip install tkinterdnd2' i din terminal for at bruge dette program.")
    sys.exit(1)


class PDFReconApp:
    def __init__(self, root):
        # --- Applikationskonfiguration ---
        self.app_version = "11.5.3"
        
        self.root = root
        self.root.title(f"PDFRecon v{self.app_version}")
        self.root.geometry("1200x700")

        # OPDATERET: Tilføjet kode til at indlæse et brugerdefineret ikon
        try:
            # Forsøger at indlæse 'icon.ico' fra samme mappe som scriptet.
            # Sørg for at din ikon-fil hedder 'icon.ico'.
            icon_path = self._resolve_path('icon.ico')
            if icon_path.exists():
                self.root.iconbitmap(icon_path)
            else:
                logging.warning("icon.ico blev ikke fundet. Bruger standard-ikon.")
        except tk.TclError:
            logging.warning("Kunne ikke indlæse icon.ico. Bruger standard-ikon.")
        except Exception as e:
            logging.error(f"Uventet fejl ved indlæsning af ikon: {e}")


        # --- Applikationens data ---
        self.report_data = [] # Bruges til visning og Excel-eksport
        self.scan_data = [] # Gemmer de rå, uprocesserede resultater til sprogskifte
        self.exif_outputs = {}
        self.timeline_data = {}
        self.row_counter = 0
        self.path_to_id = {}

        self.revision_counter = 0
        self.scan_queue = queue.Queue()
        self.tree_sort_column = None
        self.tree_sort_reverse = False
        self.exif_popup = None

        # --- Sprogopsætning ---
        self.language = tk.StringVar(value="da")
        
        # --- Opsætning af GUI ---
        self._setup_logging()
        self.translations = self.get_translations() # Skal kaldes efter logging er sat op
        self._setup_styles()
        self._setup_menu()
        self._setup_main_frame()
        self._setup_drag_and_drop()
        
        logging.info(f"PDFRecon v{self.app_version} startet.")

    def _(self, key):
        """Returnerer den oversatte tekst for en given nøgle."""
        return self.translations[self.language.get()][key]

    def get_translations(self):
        """Indeholder alle oversættelser for programmet."""
        version_string = f"PDFRecon v{self.app_version} (Optimized)"
        return {
            "da": {
                "choose_folder": "📁 Vælg mappe og scan",
                "show_timeline": "Vis Tidslinje",
                "status_initial": "Træk en mappe hertil eller brug knappen for at starte en analyse.",
                "col_id": "#",
                "col_name": "Navn",
                "col_changed": "Status",
                "col_path": "Sti",
                "col_md5": "MD5",
                "col_created": "Fil oprettet",
                "col_modified": "Fil sidst ændret",
                "col_exif": "EXIFTool",
                "col_indicators": "Tegn på ændring",
                "save_excel": "💾 Gem som Excel",
                "menu_help": "Hjælp",
                "menu_manual": "Manual",
                "menu_about": "Om PDFRecon",
                "menu_license": "Vis Licens",
                "menu_log": "Vis logfil",
                "menu_language": "Sprog / Language",
                "preparing_analysis": "Forbereder analyse...",
                "analyzing_file": "🔍 Analyserer: {file}",
                "scan_complete_summary": "✔ Færdig: {total} dokumenter | {changed} ændrede (JA) | {revs} revisioner | {inds} med indikationer | {clean} ikke påvist",
                "no_exif_output_title": "Ingen EXIFTool-output",
                "no_exif_output_message": "Der er enten ingen EXIFTool-output for denne fil, eller også opstod der en fejl under kørsel.",
                "exif_popup_title": "EXIFTool Output",
                "exif_no_output": "Intet output",
                "exif_error": "Fejl",
                "exif_view_output": "Klik for at se output ➡",
                "license_error_title": "Fejl",
                "license_error_message": "Licensfilen 'license.txt' kunne ikke findes.\n\nSørg for, at filen hedder 'license.txt' og er inkluderet korrekt, når programmet pakkes.",
                "license_popup_title": "Licensinformation",
                "log_not_found_title": "Logfil ikke fundet",
                "log_not_found_message": "Logfilen er endnu ikke oprettet. Den oprettes første gang programmet logger en handling.",
                "no_data_to_save_title": "Ingen data",
                "no_data_to_save_message": "Der er ingen data at gemme.",
                "excel_saved_title": "Handling fuldført",
                "excel_saved_message": "Excel-rapporten er gemt.\n\nVil du åbne mappen, hvor filen ligger?",
                "excel_save_error_title": "Fejl ved lagring",
                "excel_save_error_message": "Filen kunne ikke gemmes. Den er muligvis i brug af et andet program.\n\nDetaljer: {e}",
                "excel_unexpected_error_title": "Uventet Fejl",
                "excel_unexpected_error_message": "En uventet fejl opstod under lagring.\n\nDetaljer: {e}",
                "open_folder_error_title": "Fejl ved åbning",
                "open_folder_error_message": "Kunne ikke automatisk åbne mappen.",
                "manual_title": "PDFRecon - Manual",
                "manual_intro_header": "Introduktion",
                "manual_intro_text": "PDFRecon er et værktøj designet til at assistere i efterforskningen af PDF-filer. Programmet analyserer filer for en række tekniske indikatorer, der kan afsløre manipulation, redigering eller skjult indhold. Resultaterne præsenteres i en overskuelig tabel, der kan eksporteres til Excel for videre dokumentation.\n\n",
                "manual_disclaimer_header": "Vigtig bemærkning om tidsstempler",
                "manual_disclaimer_text": "Kolonnerne 'Fil oprettet' og 'Fil sidst ændret' viser tidsstempler fra computerens filsystem. Vær opmærksom på, at disse tidsstempler kan være upålidelige. En simpel handling som at kopiere en fil fra én placering til en anden vil typisk opdatere disse datoer til tidspunktet for kopieringen. For en mere pålidelig tidslinje, brug funktionen 'Vis Tidslinje', som er baseret på metadata inde i selve filen.\n\n",
                "manual_class_header": "Klassificeringssystem",
                "manual_class_text": "Programmet klassificerer hver fil baseret på de fundne indikatorer. Dette gøres for hurtigt at kunne prioritere, hvilke filer der kræver nærmere undersøgelse.\n\n",
                "manual_high_risk_header": "JA (Høj Risiko): ",
                "manual_high_risk_text": "Tildeles filer, hvor der er fundet stærke beviser for manipulation. Disse filer bør altid undersøges grundigt. Indikatorer, der udløser dette flag, er typisk svære at forfalske og peger direkte på en ændring i filens indhold eller struktur.\n\n",
                "manual_med_risk_header": "Indikationer Fundet (Mellem Risiko): ",
                "manual_med_risk_text": "Tildeles filer, hvor der er fundet en eller flere tekniske spor, der afviger fra en standard, 'ren' PDF. Disse spor er ikke i sig selv et endegyldigt bevis på manipulation, men de viser, at filen har en historik eller struktur, der berettiger et nærmere kig.\n\n",
                "manual_low_risk_header": "IKKE PÅVIST (Lav Risiko): ",
                "manual_low_risk_text": "Tildeles filer, hvor programmet ikke har fundet nogen af de kendte indikatorer. Dette betyder ikke, at filen med 100% sikkerhed er uændret, men at den ikke udviser de typiske tegn på manipulation, som værktøjet leder efter.\n\n",
                "manual_indicators_header": "Forklaring af Indikatorer",
                "manual_indicators_text": "Nedenfor er en detaljeret forklaring af hver indikator, som PDFRecon leder efter.\n\n",
                "manual_has_rev_header": "Has Revisions",
                "manual_has_rev_class": "JA",
                "manual_has_rev_desc": "• Hvad det betyder: PDF-standarden tillader, at man gemmer ændringer oven i en eksisterende fil (inkrementel lagring). Dette efterlader den oprindelige version af dokumentet intakt inde i filen. PDFRecon har fundet og udtrukket en eller flere af disse tidligere versioner. Dette er et utvetydigt bevis på, at filen er blevet ændret efter sin oprindelige oprettelse.\n\n",
                "manual_touchup_header": "TouchUp_TextEdit",
                "manual_touchup_class": "JA",
                "manual_touchup_desc": "• Hvad det betyder: Dette er et specifikt metadata-flag, som Adobe Acrobat efterlader, når en bruger manuelt har redigeret tekst direkte i PDF-dokumentet. Det er et meget stærkt bevis på direkte manipulation af indholdet.\n\n",
                "manual_fonts_header": "Multiple Font Subsets",
                "manual_fonts_class": "Indikationer Fundet",
                "manual_fonts_desc": "• Hvad det betyder: Når tekst tilføjes til en PDF, indlejres ofte kun de tegn fra en skrifttype, der rent faktisk bruges (et 'subset'). Hvis en fil redigeres med et andet program, der ikke har adgang til præcis samme skrifttype, kan der opstå et nyt subset af den samme grundlæggende skrifttype. At finde flere subsets (f.eks. 'ABCDE+Calibri' og 'FGHIJ+Calibri') er en stærk indikation på, at tekst er blevet tilføjet eller ændret på forskellige tidspunkter eller med forskellige værktøjer.\n\n",
                "manual_tools_header": "Multiple Creators / Producers",
                "manual_tools_class": "Indikationer Fundet",
                "manual_tools_desc": "• Hvad det betyder: PDF-filer indeholder metadata om, hvilket program der har oprettet (/Creator) og genereret (/Producer) filen. Hvis der findes flere forskellige navne i disse felter (f.eks. både 'Microsoft Word' og 'Adobe Acrobat'), indikerer det, at filen er blevet behandlet af mere end ét program. Dette sker typisk, når en fil oprettes i ét program og derefter redigeres i et andet.\n\n",
                "manual_history_header": "xmpMM:History / DerivedFrom / DocumentAncestors",
                "manual_history_class": "Indikationer Fundet",
                "manual_history_desc": "• Hvad det betyder: Dette er forskellige typer af XMP-metadata, som gemmer information om filens historik. De kan indeholde tidsstempler for, hvornår filen er gemt, ID'er fra tidligere versioner, og hvilket software der er brugt. Fund af disse felter beviser, at filen har en redigeringshistorik.\n\n",
                "manual_id_header": "Multiple DocumentID / Different InstanceID",
                "manual_id_class": "Indikationer Fundet",
                "manual_id_desc": "• Hvad det betyder: Hver PDF har et unikt DocumentID, der ideelt set er det samme for alle versioner. InstanceID ændres derimod for hver gang, filen gemmes. Hvis der findes flere forskellige DocumentID'er, eller hvis der er et unormalt højt antal InstanceID'er, peger det på en kompleks redigeringshistorik, potentielt hvor dele fra forskellige dokumenter er blevet kombineret.\n\n",
                "manual_xref_header": "Multiple startxref",
                "manual_xref_class": "Indikationer Fundet",
                "manual_xref_desc": "• Hvad det betyder: 'startxref' er et nøgleord, der fortæller en PDF-læser, hvor den skal begynde at læse filens struktur. En standard, uændret fil har kun ét. Hvis der er flere, er det et tegn på, at der er foretaget inkrementelle ændringer (se 'Has Revisions').\n\n",
                "revision_of": "Revision af #{id}",
                "about_purpose_header": "Formål",
                "about_purpose_text": "PDFRecon identificerer potentielt manipulerede PDF-filer ved at:\n• Udtrække og analysere XMP-metadata, streams og revisioner\n• Detektere tegn på ændringer (f.eks. /TouchUp_TextEdit, /Prev)\n• Udtrække komplette, tidligere versioner af dokumentet\n• Generere en overskuelig rapport i Excel-format\n\n",
                "about_included_software_header": "Inkluderet Software",
                "about_included_software_text": "Dette værktøj benytter og inkluderer {tool} af Phil Harvey.\n{tool} er distribueret under Artistic/GPL-licens.\n\n",
                "about_website": "Officiel {tool} Hjemmeside: ",
                "about_source": "{tool} Kildekode: ",
                "about_developer_info": "\nUdvikler: Rasmus Riis\nE-mail: riisras@gmail.com\n",
                "about_version": version_string,
                "copy": "Kopiér",
                "close_button_text": "Luk",
                "excel_indicators_overview": "(Oversigt)",
                "exif_err_notfound": "(exiftool ikke fundet i programmets mappe)",
                "exif_err_prefix": "ExifTool Fejl:",
                "exif_err_run": "(fejl ved kørsel af exiftool: {e})",
                "drop_error_title": "Fejl",
                "drop_error_message": "Træk venligst en mappe, ikke en fil.",
                "timeline_no_data": "Der blev ikke fundet tidsstempeldata for denne fil.",
                "choose_folder_title": "Vælg mappe til analyse",
            },
            "en": {
                "choose_folder": "📁 Choose folder and scan",
                "show_timeline": "Show Timeline",
                "status_initial": "Drag a folder here or use the button to start an analysis.",
                "col_id": "#",
                "col_name": "Name",
                "col_changed": "Status",
                "col_path": "Path",
                "col_md5": "MD5",
                "col_created": "File Created",
                "col_modified": "File Modified",
                "col_exif": "EXIFTool",
                "col_indicators": "Signs of Alteration",
                "save_excel": "💾 Save as Excel",
                "menu_help": "Help",
                "menu_manual": "Manual",
                "menu_about": "About PDFRecon",
                "menu_license": "Show License",
                "menu_log": "Show Log File",
                "menu_language": "Language / Sprog",
                "preparing_analysis": "Preparing analysis...",
                "analyzing_file": "🔍 Analyzing: {file}",
                "scan_complete_summary": "✔ Finished: {total} documents | {changed} altered (YES) | {revs} revisions | {inds} with indications | {clean} not detected",
                "no_exif_output_title": "No EXIFTool Output",
                "no_exif_output_message": "There is either no EXIFTool output for this file, or an error occurred during execution.",
                "exif_popup_title": "EXIFTool Output",
                "exif_no_output": "No output",
                "exif_error": "Error",
                "exif_view_output": "Click to view output ➡",
                "license_error_title": "Error",
                "license_error_message": "The license file 'license.txt' could not be found.\n\nPlease ensure the file is named 'license.txt' and is included correctly when packaging the application.",
                "license_popup_title": "License Information",
                "log_not_found_title": "Log File Not Found",
                "log_not_found_message": "The log file has not been created yet. It is created the first time the program logs an action.",
                "no_data_to_save_title": "No Data",
                "no_data_to_save_message": "There is no data to save.",
                "excel_saved_title": "Action Completed",
                "excel_saved_message": "The Excel report has been saved.\n\nDo you want to open the folder where the file is located?",
                "excel_save_error_title": "Save Error",
                "excel_save_error_message": "The file could not be saved. It might be in use by another program.\n\nDetails: {e}",
                "excel_unexpected_error_title": "Unexpected Error",
                "excel_unexpected_error_message": "An unexpected error occurred during saving.\n\nDetails: {e}",
                "open_folder_error_title": "Error Opening Folder",
                "open_folder_error_message": "Could not automatically open the folder.",
                "manual_title": "PDFRecon - Manual",
                "manual_intro_header": "Introduction",
                "manual_intro_text": "PDFRecon is a tool designed to assist in the investigation of PDF files. The program analyzes files for a range of technical indicators that can reveal manipulation, editing, or hidden content. The results are presented in a clear table that can be exported to Excel for further documentation.\n\n",
                "manual_disclaimer_header": "Important Note on Timestamps",
                "manual_disclaimer_text": "The 'File Created' and 'File Modified' columns show timestamps from the computer's file system. Be aware that these timestamps can be unreliable. A simple action like copying a file from one location to another will typically update these dates to the time of the copy. For a more reliable timeline, use the 'Show Timeline' feature, which is based on metadata inside the file itself.\n\n",
                "manual_class_header": "Classification System",
                "manual_class_text": "The program classifies each file based on the indicators found. This is done to quickly prioritize which files require closer examination.\n\n",
                "manual_high_risk_header": "YES (High Risk): ",
                "manual_high_risk_text": "Assigned to files where strong evidence of manipulation has been found. These files should always be thoroughly investigated. Indicators that trigger this flag are typically difficult to forge and point directly to a change in the file's content or structure.\n\n",
                "manual_med_risk_header": "Indications Found (Medium Risk): ",
                "manual_med_risk_text": "Assigned to files where one or more technical traces have been found that deviate from a standard, 'clean' PDF. These traces are not definitive proof of manipulation in themselves, but they show that the file has a history or structure that warrants a closer look.\n\n",
                "manual_low_risk_header": "NOT DETECTED (Low Risk): ",
                "manual_low_risk_text": "Assigned to files where the program has not found any of the known indicators. This does not mean that the file is 100% unchanged, but that it does not exhibit the typical signs of manipulation that the tool looks for.\n\n",
                "manual_indicators_header": "Explanation of Indicators",
                "manual_indicators_text": "Below is a detailed explanation of each indicator that PDFRecon looks for.\n\n",
                "manual_has_rev_header": "Has Revisions",
                "manual_has_rev_class": "YES",
                "manual_has_rev_desc": "• What it means: The PDF standard allows changes to be saved on top of an existing file (incremental saving). This leaves the original version of the document intact inside the file. PDFRecon has found and extracted one or more of these previous versions. This is unequivocal proof that the file has been changed after its original creation.\n\n",
                "manual_touchup_header": "TouchUp_TextEdit",
                "manual_touchup_class": "YES",
                "manual_touchup_desc": "• What it means: This is a specific metadata flag left by Adobe Acrobat when a user has manually edited text directly in the PDF document. It is very strong evidence of direct content manipulation.\n\n",
                "manual_fonts_header": "Multiple Font Subsets",
                "manual_fonts_class": "Indications Found",
                "manual_fonts_desc": "• What it means: When text is added to a PDF, often only the characters actually used from a font are embedded (a 'subset'). If a file is edited with another program that does not have access to the exact same font, a new subset of the same base font may be created. Finding multiple subsets (e.g., 'ABCDE+Calibri' and 'FGHIJ+Calibri') is a strong indication that text has been added or changed at different times or with different tools.\n\n",
                "manual_tools_header": "Multiple Creators / Producers",
                "manual_tools_class": "Indications Found",
                "manual_tools_desc": "• What it means: PDF files contain metadata about which program created (/Creator) and generated (/Producer) the file. If multiple different names are found in these fields (e.g., both 'Microsoft Word' and 'Adobe Acrobat'), it indicates that the file has been processed by more than one program. This typically happens when a file is created in one program and then edited in another.\n\n",
                "manual_history_header": "xmpMM:History / DerivedFrom / DocumentAncestors",
                "manual_history_class": "Indications Found",
                "manual_history_desc": "• What it means: These are different types of XMP metadata that store information about the file's history. They can contain timestamps for when the file was saved, IDs from previous versions, and what software was used. The presence of these fields proves that the file has an editing history.\n\n",
                "manual_id_header": "Multiple DocumentID / Different InstanceID",
                "manual_id_class": "Indications Found",
                "manual_id_desc": "• What it means: Each PDF has a unique DocumentID that should ideally be the same for all versions. The InstanceID, however, changes every time the file is saved. If multiple different DocumentIDs are found, or if there is an abnormally high number of InstanceIDs, it points to a complex editing history, potentially where parts from different documents have been combined.\n\n",
                "manual_xref_header": "Multiple startxref",
                "manual_xref_class": "Indications Found",
                "manual_xref_desc": "• What it means: 'startxref' is a keyword that tells a PDF reader where to start reading the file's structure. A standard, unchanged file has only one. If there are more, it is a sign that incremental changes have been made (see 'Has Revisions').\n\n",
                "revision_of": "Revision of #{id}",
                "about_purpose_header": "Purpose",
                "about_purpose_text": "PDFRecon identifies potentially manipulated PDF files by:\n• Extracting and analyzing XMP metadata, streams, and revisions\n• Detecting signs of alteration (e.g., /TouchUp_TextEdit, /Prev)\n• Extracting complete, previous versions of the document\n• Generating a clear report in Excel format\n\n",
                "about_included_software_header": "Included Software",
                "about_included_software_text": "This tool utilizes and includes {tool} by Phil Harvey.\n{tool} is distributed under the Artistic/GPL license.\n\n",
                "about_website": "Official {tool} Website: ",
                "about_source": "Source Code: ",
                "about_developer_info": "\nDeveloper: Rasmus Riis\nE-mail: riisras@gmail.com\n",
                "about_version": version_string,
                "copy": "Copy",
                "close_button_text": "Close",
                "excel_indicators_overview": "(Overview)",
                "exif_err_notfound": "(exiftool not found in program directory)",
                "exif_err_prefix": "ExifTool Error:",
                "exif_err_run": "(error running exiftool: {e})",
                "drop_error_title": "Error",
                "drop_error_message": "Please drag a folder, not a file.",
                "timeline_no_data": "No timestamp data was found for this file.",
                "choose_folder_title": "Select folder for analysis",
            }
        }

    def _setup_logging(self):
        """ Sætter en robust logger op, der skriver til en fil. """
        self.log_file_path = Path(sys.argv[0]).resolve().parent / "pdfrecon.log"
        
        # Konfigurer root loggeren direkte for at undgå konflikter
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        
        # Fjern eventuelle eksisterende handlers for at undgå duplikat-logging
        if logger.hasHandlers():
            logger.handlers.clear()
            
        # Opret og tilføj en ny file handler
        try:
            fh = logging.FileHandler(self.log_file_path, mode='a', encoding='utf-8')
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            fh.setFormatter(formatter)
            logger.addHandler(fh)
        except Exception as e:
            # Hvis logging fejler, prøv at vise en fejlmeddelelse som en sidste udvej.
            messagebox.showerror("Log Fejl", f"Kunne ikke oprette logfilen.\n\nDetaljer: {e}")


    def _setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.map('Treeview', background=[('selected', '#0078D7')])
        self.tree_tags = {
            "JA": "red_row",
            "Indikationer Fundet": "yellow_row",
            "YES": "red_row",
            "Indications Found": "yellow_row"
        }
        # OPDATERET: Tilføjet stil for blå progress bar
        self.style.configure("blue.Horizontal.TProgressbar",
                             troughcolor='#EAEAEA',
                             background='#0078D7') # En standard blå farve

    def _setup_menu(self):
        self.menubar = tk.Menu(self.root)
        
        self.help_menu = tk.Menu(self.menubar, tearoff=0)
        self.lang_menu = tk.Menu(self.help_menu, tearoff=0) # OPDATERET: Sprogmenu er nu en undermenu til Hjælp

        self.menubar.add_cascade(label=self._("menu_help"), menu=self.help_menu)
        self.help_menu.add_command(label=self._("menu_manual"), command=self.show_manual)
        self.help_menu.add_command(label=self._("menu_about"), command=self.show_about)
        self.help_menu.add_separator()
        self.help_menu.add_cascade(label=self._("menu_language"), menu=self.lang_menu) # OPDATERET: Tilføjet sprogmenu her
        self.lang_menu.add_radiobutton(label="Dansk", variable=self.language, value="da", command=self.switch_language)
        self.lang_menu.add_radiobutton(label="English", variable=self.language, value="en", command=self.switch_language)
        self.help_menu.add_separator()
        self.help_menu.add_command(label=self._("menu_license"), command=self.show_license)
        self.help_menu.add_command(label=self._("menu_log"), command=self.show_log_file)
        
        self.root.config(menu=self.menubar)

    def _update_summary_status(self):
        """Opdaterer statuslinjen med en oversigt over resultaterne."""
        if not self.report_data:
            self.status_var.set(self._("status_initial"))
            return

        total_docs = self.progressbar['maximum']
        changed_count = sum(1 for row in self.report_data if row[2] in ["JA", "YES"])
        indications_found_count = sum(1 for row in self.report_data if row[2] in ["Indikationer Fundet", "Indications Found"])
        
        # For at få et præcist 'clean' antal, skal vi tælle de faktiske originale filer
        original_files_count = len({str(data['path']) for data in self.scan_data if not data['is_revision']})
        not_flagged_count = original_files_count - changed_count - indications_found_count

        summary_text = self._("scan_complete_summary").format(
            total=original_files_count,
            changed=changed_count,
            revs=self.revision_counter,
            inds=indications_found_count,
            clean=not_flagged_count
        )
        self.status_var.set(summary_text)


    def switch_language(self):
        """Opdaterer al tekst i GUI'en til det valgte sprog."""
        # Gem stien til den valgte række, hvis der er en
        path_of_selected = None
        if self.tree.selection():
            selected_item_id = self.tree.selection()[0]
            path_of_selected = self.tree.item(selected_item_id, "values")[3]

        # Opdater statisk tekst
        self.menubar.entryconfig(1, label=self._("menu_help"))
        self.help_menu.entryconfig(0, label=self._("menu_manual"))
        self.help_menu.entryconfig(1, label=self._("menu_about"))
        self.help_menu.entryconfig(3, label=self._("menu_language"))
        self.help_menu.entryconfig(5, label=self._("menu_license"))
        self.help_menu.entryconfig(6, label=self._("menu_log"))
        self.scan_button.config(text=self._("choose_folder"))
        self.timeline_button.config(text=self._("show_timeline"))
        self.export_button.config(text=self._("save_excel"))
        for i, key in enumerate(self.columns_keys):
            self.tree.heading(self.columns[i], text=self._(key))

        # GENTOLK OG GENINDSÆT ALLE RÆKKER I TABELLEN
        self.tree.delete(*self.tree.get_children(""))
        
        self.report_data.clear()
        self.row_counter = 0
        self.path_to_id.clear()
        self.revision_counter = 0
        
        for data in self.scan_data:
            self._add_row_to_table(data)
        
        # Gen-vælg den række, der var valgt før, og opdater detaljeruden
        if path_of_selected:
            new_item_to_select = None
            for item_id in self.tree.get_children(""):
                if self.tree.item(item_id, "values")[3] == path_of_selected:
                    new_item_to_select = item_id
                    break
            if new_item_to_select:
                self.tree.selection_set(new_item_to_select)
                self.tree.focus(new_item_to_select)
                self.on_select_item(None) # Kald manuelt for at opdatere detaljeruden
        else:
            # Hvis intet var valgt, ryd detaljeruden
            self.detail_text.config(state="normal")
            self.detail_text.delete("1.0", tk.END)
            self.detail_text.config(state="disabled")

        # Opdater statuslinjen, hvis en scanning er afsluttet
        is_scan_finished = self.scan_button['state'] == 'normal'
        if is_scan_finished and self.scan_data:
            self._update_summary_status()
        elif not self.scan_data:
            self.status_var.set(self._("status_initial"))


    def _setup_main_frame(self):
        frame = ttk.Frame(self.root, padding=10)
        frame.pack(fill="both", expand=True)

        button_frame = ttk.Frame(frame)
        button_frame.pack(pady=5, fill="x")

        self.scan_button = ttk.Button(button_frame, text=self._("choose_folder"), width=25, command=self.choose_folder)
        self.scan_button.pack(side="left", padx=5)
        
        self.timeline_button = ttk.Button(button_frame, text=self._("show_timeline"), width=20, command=self.show_timeline_popup, state="disabled")
        self.timeline_button.pack(side="left", padx=5)
        

        self.scanning_indicator_label = ttk.Label(button_frame, text="", foreground="blue", font=("Segoe UI", 9))
        self.scanning_indicator_label.pack(side="left", padx=15, pady=5)

        self.status_var = tk.StringVar(value=self._("status_initial"))
        status_label = ttk.Label(frame, textvariable=self.status_var, foreground="darkgreen")
        status_label.pack(pady=(5, 10))

        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill="both", expand=True)

        self.columns = ["ID", "Name", "Altered", "Path", "MD5", "File Created", "File Modified", "EXIFTool", "Signs of Alteration"]
        self.columns_keys = ["col_id", "col_name", "col_changed", "col_path", "col_md5", "col_created", "col_modified", "col_exif", "col_indicators"]
        self.tree = ttk.Treeview(tree_frame, columns=self.columns, show="headings", selectmode="browse")
        
        self.tree.tag_configure("red_row", background='#FFDDDD')
        self.tree.tag_configure("yellow_row", background='#FFFFCC')
        self.tree.tag_configure("blue_row", background='#E0E8F0') # Lyseblå for revisioner
        
        for i, key in enumerate(self.columns_keys):
            self.tree.heading(self.columns[i], text=self._(key), command=lambda c=self.columns[i]: self._sort_column(c, False))
            self.tree.column(self.columns[i], anchor="w", width=120)
        
        self.tree.column("ID", width=40, anchor="center")
        self.tree.column("Name", width=150)

        tree_scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scrollbar.set)
        
        tree_scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_select_item)
        self.tree.bind("<Button-1>", self.on_tree_click)
        self.tree.bind("<Motion>", self._on_tree_motion)
        # OPDATERET: Tilføjet binding for højrekliks-menu
        self.tree.bind("<Button-3>", self.show_context_menu)

        # ÆNDRET: height er sat til 10 for at gøre feltet én linje højere
        self.detail_text = tk.Text(frame, height=10, wrap="word", font=("Segoe UI", 9))
        self.detail_text.pack(fill="both", expand=False, pady=(10, 5))
        self.detail_text.tag_configure("bold", font=("Segoe UI", 9, "bold"))
        self.detail_text.tag_configure("link", foreground="blue", underline=True)
        self.detail_text.tag_bind("link", "<Enter>", lambda e: self.detail_text.config(cursor="hand2"))
        self.detail_text.tag_bind("link", "<Leave>", lambda e: self.detail_text.config(cursor=""))
        self.detail_text.tag_bind("link", "<Button-1>", self._open_path_from_detail)
        
        bottom_frame = ttk.Frame(frame)
        bottom_frame.pack(fill="x", pady=(5,0))

        self.export_button = ttk.Button(bottom_frame, text=self._("save_excel"), width=25, command=self.export_to_excel)
        self.export_button.pack(side="right", padx=5)

        # OPDATERET: Anvender den nye blå stil på progress bar
        self.progressbar = ttk.Progressbar(bottom_frame, orient="horizontal", mode="determinate", style="blue.Horizontal.TProgressbar")
        self.progressbar.pack(side="left", fill="x", expand=True, padx=5)

    def _setup_drag_and_drop(self):
        """Aktiverer drag and drop for hovedvinduet."""
        self.root.drop_target_register(DND_FILES)
        self.root.dnd_bind('<<Drop>>', self.handle_drop)

    def handle_drop(self, event):
        """Håndterer filer, der bliver sluppet på vinduet."""
        # Fjerner eventuelle '{' og '}' fra stien, som kan opstå på Windows
        folder_path = event.data.strip('{}')
        if os.path.isdir(folder_path):
            self.start_scan_thread(Path(folder_path))
        else:
            messagebox.showwarning(self._("drop_error_title"), self._("drop_error_message"))

    def _on_tree_motion(self, event):
        """Ændrer cursor til en hånd, når den holdes over en klikbar celle."""
        col_id = self.tree.identify_column(event.x)
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            self.tree.config(cursor="")
            return

        # Kolonne #8 er EXIFTool
        if col_id == '#8':
            path_str = self.tree.item(row_id, "values")[3]
            if path_str in self.exif_outputs and self.exif_outputs[path_str]:
                 # Tjek om outputtet er en fejlmeddelelse
                exif_output = self.exif_outputs[path_str]
                is_error = (exif_output == self._("exif_err_notfound") or
                            exif_output.startswith(self._("exif_err_prefix")) or
                            exif_output.startswith(self._("exif_err_run").split("{")[0]))
                if not is_error:
                    self.tree.config(cursor="hand2")
                    return
        
        self.tree.config(cursor="")

    def on_tree_click(self, event):
        """Håndterer klik i tabellen for at åbne popups."""
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell": return
        
        col_id = self.tree.identify_column(event.x)
        col_index = int(col_id.replace("#", "")) - 1
        row_id = self.tree.identify_row(event.y)
        if not row_id: return

        path_str = self.tree.item(row_id, "values")[3]

        # Klik på EXIFTool-kolonnen (index 7)
        if col_index == 7:
            if path_str in self.exif_outputs and self.exif_outputs[path_str]:
                self.show_exif_popup(self.exif_outputs[path_str])
            else:
                messagebox.showinfo(self._("no_exif_output_title"), self._("no_exif_output_message"), parent=self.root)
        
    def show_context_menu(self, event):
        """Viser en højrekliks-menu for den valgte række."""
        item_id = self.tree.identify_row(event.y)
        if not item_id:
            return
        
        self.tree.selection_set(item_id)
        
        context_menu = tk.Menu(self.root, tearoff=0)
        context_menu.add_command(label="Vis EXIFTool-output", command=lambda: self.show_exif_popup_from_item(item_id))
        context_menu.add_command(label="Vis Tidslinje", command=self.show_timeline_popup)
        context_menu.add_command(label="Åbn filens placering", command=lambda: self.open_file_location(item_id))
        
        context_menu.tk_popup(event.x_root, event.y_root)

    def open_file_location(self, item_id):
        values = self.tree.item(item_id, "values")
        if values:
            webbrowser.open(os.path.dirname(values[3]))

    def show_exif_popup_from_item(self, item_id):
        values = self.tree.item(item_id, "values")
        if values:
            self.show_exif_popup(self.exif_outputs.get(values[3]))

    def _make_text_copyable(self, text_widget):
        """Gør en Text widget skrivebeskyttet, men tillader tekstvalg og kopiering."""
        
        context_menu = tk.Menu(text_widget, tearoff=0)
        
        def copy_selection(event=None):
            try:
                selected_text = text_widget.get(tk.SEL_FIRST, tk.SEL_LAST)
                self.root.clipboard_clear()
                self.root.clipboard_append(selected_text)
            except tk.TclError:
                pass
            return "break"

        context_menu.add_command(label=self._("copy"), command=copy_selection)

        def show_context_menu(event):
            if text_widget.tag_ranges(tk.SEL):
                context_menu.tk_popup(event.x_root, event.y_root)

        text_widget.config(state="normal")
        text_widget.bind("<Key>", lambda e: "break")
        text_widget.bind("<Button-3>", show_context_menu)
        text_widget.bind("<Control-c>", copy_selection)
        text_widget.bind("<Command-c>", copy_selection)

    def show_exif_popup(self, content):
        if not content:
            messagebox.showinfo(self._("no_exif_output_title"), self._("no_exif_output_message"), parent=self.root)
            return
        if hasattr(self, 'exif_popup') and self.exif_popup and self.exif_popup.winfo_exists():
            self.exif_popup.destroy()
        self.exif_popup = Toplevel(self.root)
        self.exif_popup.title(self._("exif_popup_title"))
        self.exif_popup.geometry("600x400")
        self.exif_popup.transient(self.root)
        text_frame = ttk.Frame(self.exif_popup, padding=5)
        text_frame.pack(fill="both", expand=True)
        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side="right", fill="y")
        text_widget = tk.Text(text_frame, wrap="word", yscrollcommand=scrollbar.set)
        text_widget.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=text_widget.yview)
        text_widget.insert("1.0", content)
        self._make_text_copyable(text_widget)

    def _resolve_path(self, filename):
        if getattr(sys, 'frozen', False):
            base_path = Path(sys._MEIPASS)
        else:
            base_path = Path(__file__).resolve().parent
        return base_path / filename

    def show_license(self):
        license_path = self._resolve_path("license.txt")
        try:
            with open(license_path, 'r', encoding='utf-8') as f: license_text = f.read()
        except FileNotFoundError:
            messagebox.showerror(self._("license_error_title"), self._("license_error_message"))
            return
        license_popup = Toplevel(self.root)
        license_popup.title(self._("license_popup_title"))
        license_popup.geometry("600x500")
        license_popup.transient(self.root)
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
        text_widget.config(state="disabled")
        close_button = ttk.Button(text_frame, text=self._("close_button_text"), command=license_popup.destroy)
        close_button.grid(row=1, column=0, pady=(10,0))

    def show_log_file(self):
        if self.log_file_path.exists():
            webbrowser.open(self.log_file_path.as_uri())
        else:
            messagebox.showinfo(self._("log_not_found_title"), self._("log_not_found_message"), parent=self.root)

    def _sort_column(self, col, reverse):
        # Konverter til int hvis det er ID-kolonnen
        is_id_column = col == self.columns[0]
        def get_key(item):
            val = self.tree.set(item, col)
            return int(val) if is_id_column and val else val

        data_list = [(get_key(k), k) for k in self.tree.get_children("")]
        data_list.sort(reverse=reverse)
        for index, (val, k) in enumerate(data_list):
            self.tree.move(k, "", index)
        self.tree.heading(col, command=lambda: self._sort_column(col, not reverse))

    def choose_folder(self):
        folder_path = filedialog.askdirectory(title=self._("choose_folder_title"))
        if folder_path:
            self.start_scan_thread(Path(folder_path))

    def start_scan_thread(self, folder_path):
        logging.info(f"Starter scanning af mappe: {folder_path}")
        self.tree.delete(*self.tree.get_children())
        self.report_data.clear()
        self.scan_data.clear() # Nulstil de rå resultater
        self.exif_outputs.clear()
        self.timeline_data.clear()
        self.row_counter = 0
        self.path_to_id.clear()

        self.revision_counter = 0
        self.scan_queue = queue.Queue()
        
        self.scan_button.config(state="disabled")
        self.export_button.config(state="disabled")
        self.timeline_button.config(state="disabled")

        self.status_var.set(self._("preparing_analysis"))
        self.progressbar.config(value=0) # Nulstil progressbar

        scan_thread = threading.Thread(target=self._scan_worker, args=(folder_path, self.scan_queue))
        scan_thread.daemon = True
        scan_thread.start()

        self._process_queue()

    def _find_pdf_files_generator(self, folder):
        """En generator, der 'yield'er PDF-filer, så snart de findes."""
        for base, _, files in os.walk(folder):
            for fn in files:
                if fn.lower().endswith(".pdf"):
                    yield Path(base) / fn

    def _scan_worker(self, folder, q):
        # Skift til ubestemt progress bar, da vi ikke kender totalen endnu
        q.put(("progress_mode_indeterminate", None))
        
        count = 0
        original_file_count = 0
        # Brug en generator til at få filer én ad gangen
        for fp in self._find_pdf_files_generator(folder):
            original_file_count += 1
            try:
                logging.info(f"Behandler fil [{original_file_count}]: {fp}")
                q.put(("scan_status", self._("analyzing_file").format(file=fp.name)))
                raw = fp.read_bytes()
                
                doc = fitz.open(stream=raw, filetype="pdf")
                txt = self.extract_text(raw)
                indicator_keys = self.detect_indicators(txt, doc)
                md5_hash = hashlib.md5(raw).hexdigest()
                exif = self.exiftool_output(fp, detailed=True)
                timeline = self.generate_comprehensive_timeline(fp, txt, exif)
                revisions = self.extract_revisions(raw, fp)
                doc.close()
                
                final_indicator_keys = indicator_keys[:]
                if revisions:
                    final_indicator_keys.append("Has Revisions")
                    logging.info(f"Fil '{fp.name}': Fandt {len(revisions)} revision(er).")
                
                original_row_data = {
                    "path": fp, 
                    "indicator_keys": final_indicator_keys,
                    "md5": md5_hash,  
                    "exif": exif, 
                    "is_revision": False, 
                    "timeline": timeline
                }
                q.put(("file_row", original_row_data))
                
                for rev_path, basefile, rev_raw in revisions:
                    rev_md5 = hashlib.md5(rev_raw).hexdigest()
                    rev_exif = self.exiftool_output(rev_path, detailed=True)
                    rev_timeline = timeline 

                    revision_row_data = {
                        "path": rev_path, 
                        "indicator_keys": ["Revision"], 
                        "md5": rev_md5,  
                        "exif": rev_exif, 
                        "is_revision": True, 
                        "timeline": rev_timeline, 
                        "original_path": fp
                    }
                    q.put(("file_row", revision_row_data))

            except Exception as e:
                logging.exception(f"Uventet fejl ved behandling af fil {fp.name}")
                q.put(("error", f"Kunne ikke læse {fp.name}: {e}"))
                
        # Når løkken er færdig, kender vi det endelige antal
        q.put(("progress_mode_determinate", original_file_count))
        q.put(("finished", None))

    def _process_queue(self):
        try:
            while True:
                msg_type, data = self.scan_queue.get_nowait()
                
                if msg_type == "progress_mode_indeterminate":
                    self.progressbar.config(mode='indeterminate')
                    self.progressbar.start(10) # Start animationen
                elif msg_type == "progress_mode_determinate":
                    self.progressbar.stop() # Stop animationen
                    # Sørg for at maximum er mindst 1 for at undgå fejl
                    max_val = data if data > 0 else 1
                    self.progressbar.config(mode='determinate', maximum=max_val, value=max_val)
                elif msg_type == "scan_status": 
                    self.scanning_indicator_label.config(text=data)
                elif msg_type == "file_row":
                    self.scan_data.append(data) # Gem de rå resultater
                    self._add_row_to_table(data) # Tilføj den nye række til tabellen
                elif msg_type == "error": 
                    logging.warning(data)
                elif msg_type == "finished":
                    self._finalize_scan()
                    return
        except queue.Empty:
            pass
        self.root.after(100, self._process_queue)

    def _add_row_to_table(self, data):
        path = data["path"]
        
        self.row_counter += 1
        
        if data["is_revision"]:
            self.revision_counter += 1
            created_time = ""
            modified_time = ""
            parent_id = self.path_to_id.get(str(data["original_path"]))
            flag = self.get_flag([], True, parent_id)
            indicators_str = ""
        else:
            self.path_to_id[str(path)] = self.row_counter
            stat = path.stat()
            created_time = datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S")
            modified_time = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            flag = self.get_flag(data["indicator_keys"], False)
            indicators_str = "; ".join(data["indicator_keys"])

        self.exif_outputs[str(path)] = data["exif"]
        self.timeline_data[str(path)] = data["timeline"]

        exif_text = self._("exif_no_output")
        if data["exif"]:
            is_error = (data["exif"] == self._("exif_err_notfound") or 
                        data["exif"].startswith(self._("exif_err_prefix")) or 
                        data["exif"].startswith(self._("exif_err_run").split("{")[0]))
            if is_error:
                exif_text = self._("exif_error")
            else:
                exif_text = self._("exif_view_output")

        row_values = [self.row_counter, path.name, flag, str(path), data["md5"], created_time, modified_time, exif_text, indicators_str]
        
        tag = ""
        if data["is_revision"]:
            tag = "blue_row"
        else:
            tag_map = {
                "JA": "red_row",
                "Indikationer Fundet": "yellow_row",
                "YES": "red_row",
                "Indications Found": "yellow_row"
            }
            tag = tag_map.get(flag, "")
        
        self.report_data.append(row_values)
        self.tree.insert("", "end", values=row_values, tags=(tag,))


    def _finalize_scan(self):
        self.scan_button.config(state="normal")
        self.export_button.config(state="normal")
        self.scanning_indicator_label.config(text="")
        
        self._update_summary_status()
        logging.info(f"Analyse fuldført. {self.status_var.get()}")

    def on_select_item(self, event):
        selected_items = self.tree.selection()
        
        if len(selected_items) == 1:
            item_path = self.tree.item(selected_items[0], "values")[3]
            if self.timeline_data.get(item_path):
                self.timeline_button.config(state="normal")
            else:
                self.timeline_button.config(state="disabled")
        else:
            self.timeline_button.config(state="disabled")


        if not selected_items:
            # Hvis intet er valgt, ryd detaljeruden
            self.detail_text.config(state="normal")
            self.detail_text.delete("1.0", tk.END)
            self.detail_text.config(state="disabled")
            return
        
        values = self.tree.item(selected_items[0], "values")
        self.detail_text.config(state="normal")
        self.detail_text.delete("1.0", tk.END)
        for i, val in enumerate(values):
            col_name = self.tree.heading(self.columns[i], "text")
            self.detail_text.insert(tk.END, f"{col_name}: ", ("bold",))
            if col_name == self._("col_path"): self.detail_text.insert(tk.END, val + "\n", ("link",))
            elif col_name == self._("col_indicators"):
                self.detail_text.insert(tk.END, val + "\n")
            else: self.detail_text.insert(tk.END, val + "\n")
        self.detail_text.config(state="disabled")

    def _open_path_from_detail(self, event):
        index = self.detail_text.index(f"@{event.x},{event.y}")
        tag_indices = self.detail_text.tag_ranges("link")
        for start, end in zip(tag_indices[0::2], tag_indices[1::2]):
            if self.detail_text.compare(start, "<=", index) and self.detail_text.compare(index, "<", end):
                path_str = self.detail_text.get(start, end).strip()
                try: webbrowser.open(os.path.dirname(path_str))
                except Exception as e: messagebox.showerror(self._("open_folder_error_title"), f"Kunne ikke åbne mappen: {e}")
                break

    def extract_revisions(self, raw, original_path):
        revisions = []
        offsets = []
        pos = len(raw)
        while (pos := raw.rfind(b"%%EOF", 0, pos)) != -1: offsets.append(pos)
        valid_offsets = [o for o in sorted(offsets) if 1000 <= o <= len(raw) - 500]
        if valid_offsets:
            altered_dir = original_path.parent / "Altered_files"
            altered_dir.mkdir(exist_ok=True)
            for i, offset in enumerate(valid_offsets, start=1):
                rev_bytes = raw[:offset + 5]
                rev_filename = f"{original_path.stem}_rev{i}_@{offset}.pdf"
                rev_path = altered_dir / rev_filename
                try:
                    rev_path.write_bytes(rev_bytes)
                    revisions.append((rev_path, original_path.name, rev_bytes))
                except Exception as e: logging.error(f"Fejl ved udtræk af revision: {e}")
        return revisions

    def exiftool_output(self, path, detailed=False):
        exe_path = self._resolve_path("exiftool.exe")
        if not exe_path.is_file():
            return self._("exif_err_notfound")
        try:
            startupinfo = None
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            command = [str(exe_path)]
            if detailed:
                command.extend(["-a", "-s", "-G1", "-struct"])
            else:
                command.extend(["-a"])
            
            command.append(str(path))

            process = subprocess.run(command, capture_output=True, check=False, startupinfo=startupinfo)
            
            if process.returncode != 0 or process.stderr:
                error_message = process.stderr.decode('latin-1', 'ignore').strip()
                return f"{self._('exif_err_prefix')}\n{error_message}"
            
            try:
                raw_output = process.stdout.decode('utf-8').strip()
            except UnicodeDecodeError:
                raw_output = process.stdout.decode('latin-1', 'ignore').strip()

            lines = [line for line in raw_output.splitlines() if line.strip()]
            return "\n".join(lines)

        except Exception as e:
            logging.error(f"Fejl ved kørsel af exiftool for fil {path}: {e}")
            return self._("exif_err_run").format(e=e)

    def _get_filesystem_times(self, filepath):
        """Hjælpefunktion til at hente tidsstempler fra filsystemet."""
        events = []
        try:
            stat = filepath.stat()
            # st_mtime: Sidst ændret
            mtime = datetime.fromtimestamp(stat.st_mtime)
            events.append((mtime, f"File System: {self._('col_modified')}"))
            # st_ctime: Oprettet (eller sidst ændret metadata på Unix)
            ctime = datetime.fromtimestamp(stat.st_ctime)
            events.append((ctime, f"File System: {self._('col_created')}"))
        except FileNotFoundError:
            pass
        return events

    def _parse_exiftool_timeline(self, exiftool_output):
        """Hjælpefunktion til at parse tidsstempler fra ExifTool output."""
        events = []
        lines = exiftool_output.splitlines()
        processed_lines = set()

        # NY PARSING: Håndterer den komplekse, én-linjes XMP History-output
        history_full_pattern = re.compile(r"\[XMP-xmpMM\]\s+History\s+:\s+(.*)")
        for i, line in enumerate(lines):
            full_match = history_full_pattern.match(line)
            if full_match:
                history_str = full_match.group(1)
                # Find hver enkelt hændelse i { ... }
                event_blocks = re.findall(r'\{([^}]+)\}', history_str)
                for block in event_blocks:
                    details = {}
                    # Split hver hændelse op i key=value par
                    pairs = block.split(',')
                    for pair in pairs:
                        if '=' in pair:
                            key, value = pair.split('=', 1)
                            details[key.strip()] = value.strip()
                    
                    if 'When' in details:
                        try:
                            date_str = details['When']
                            # Rens dato-strengen for tidszone og millisekunder
                            dt_obj = datetime.strptime(date_str.split('+')[0].split('.')[0], "%Y:%m:%d %H:%M:%S")
                            
                            action = details.get('Action', 'N/A')
                            agent = details.get('SoftwareAgent', '')
                            changed = details.get('Changed', '')
                            
                            # Byg en pænere beskrivelse
                            desc_parts = [f"Action: {action}"]
                            if agent: desc_parts.append(f"Agent: {agent}")
                            if changed: desc_parts.append(f"Changed: {changed}")
                            
                            display_line = f"XMP History   - {' | '.join(desc_parts)}"
                            events.append((dt_obj, display_line))
                        except (ValueError, IndexError):
                            continue # Ignorer ugyldige datoformater i historikken
                processed_lines.add(i) # Marker linjen som behandlet

        # Eksisterende parsing af datoer (nu med forbedret label)
        generic_date_pattern = re.compile(r"(\d{4}:\d{2}:\d{2}\s\d{2}:\d{2}:\d{2})")
        for i, line in enumerate(lines):
            if i in processed_lines: continue
            match = generic_date_pattern.search(line)
            if match:
                try:
                    dt_obj = datetime.strptime(match.group(1), "%Y:%m:%d %H:%M:%S")
                    # Gør linjen mere læselig ved at fjerne unødvendig info
                    clean_line = line.split(':', 1)[-1].strip()
                    source_match = re.search(r"\[(.*?)\]", line)
                    source = source_match.group(1) if source_match else "ExifTool"
                    display_line = f"ExifTool ({source:<10}) - {clean_line}"
                    events.append((dt_obj, display_line))
                except ValueError:
                    continue
        return events
    def _format_timedelta(self, delta):
            """Formaterer et timedelta-objekt til en læsbar streng."""
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
        """Hjælpefunktion til at parse tidsstempler direkte fra filens indhold."""
        events = []
        
        pdf_date_pattern = re.compile(r"\/([A-Z][a-zA-Z0-9_]+)\s*\(\s*D:(\d{14})")
        for match in pdf_date_pattern.finditer(file_content_string):
            label, date_str = match.groups()
            try:
                dt_obj = datetime.strptime(date_str, "%Y%m%d%H%M%S")
                display_line = f"Raw File: /{label}: {dt_obj.strftime('%Y-%m-%d %H:%M:%S')}"
                events.append((dt_obj, display_line))
            except ValueError:
                continue

        xmp_date_pattern = re.compile(r"<([a-zA-Z0-9:]+)[^>]*?>\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.*?)\s*<\/([a-zA-Z0-9:]+)>")
        for match in xmp_date_pattern.finditer(file_content_string):
            label, date_str, closing_label = match.groups()
            if label != closing_label: continue
            try:
                clean_date_str = date_str.split('Z')[0].split('+')[0].split('-')[0].strip()
                dt_obj = datetime.fromisoformat(clean_date_str)
                display_line = f"Raw File: <{label}>: {date_str}"
                events.append((dt_obj, display_line))
            except (ValueError, IndexError):
                continue
        return events
    
    def _deduplicate_timeline(self, events):
        """Fjerner hændelser med identiske tidsstempler."""
        unique_events = []
        seen_timestamps = set()
        # Sorter for at sikre at den første (mest specifikke) hændelse bevares
        for dt_obj, description in sorted(events, key=lambda x: (x[0], len(x[1]))):
            if dt_obj not in seen_timestamps:
                unique_events.append((dt_obj, description))
                seen_timestamps.add(dt_obj)
        return unique_events

    def generate_comprehensive_timeline(self, filepath, raw_file_content, exiftool_output):
        """Skaber en komplet tidslinje ved at kombinere alle kilder."""
        all_events = []
        all_events.extend(self._get_filesystem_times(filepath))
        all_events.extend(self._parse_exiftool_timeline(exiftool_output))
        all_events.extend(self._parse_raw_content_timeline(raw_file_content))
        
        # Denne linje, der fjerner dubletter, kan slettes eller forblive udkommenteret.
        # unique_events = self._deduplicate_timeline(all_events)
        
        # KORREKTION: Vi sorterer og returnerer den oprindelige 'all_events' liste,
        # som indeholder alle hændelser, inklusiv dubletter.
        return sorted(all_events, key=lambda x: x[0])
        
    def show_timeline_popup(self):
        selected_item = self.tree.selection()
        if not selected_item: return
        path_str = self.tree.item(selected_item[0], "values")[3]
        
        events = self.timeline_data.get(path_str)
        if not events:
            messagebox.showinfo(self._("no_exif_output_title"), self._("timeline_no_data"), parent=self.root)
            return

        popup = Toplevel(self.root)
        popup.title(f"Timeline for {os.path.basename(path_str)}")
        popup.geometry("950x700") # Justeret størrelse
        popup.transient(self.root)

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
        
        # Definer tags til formatering
        text_widget.tag_configure("date_header", font=("Courier New", 11, "bold", "underline"), spacing1=10, spacing3=5)
        text_widget.tag_configure("time", font=("Courier New", 10, "bold"))
        text_widget.tag_configure("delta", foreground="#0078D7") # Blå farve
        
        # Farver for kilder
        text_widget.tag_configure("source_fs", foreground="#008000") # Grøn
        text_widget.tag_configure("source_exif", foreground="#555555") # Mørkegrå
        text_widget.tag_configure("source_raw", foreground="#800080") # Lilla
        text_widget.tag_configure("source_xmp", foreground="#C00000") # Rød

        last_date = None
        last_dt_obj = None

        for dt_obj, description in events:
            # Indsæt dato-overskrift ved ny dato
            if dt_obj.date() != last_date:
                if last_date is not None: text_widget.insert("end", "\n")
                text_widget.insert("end", f"--- {dt_obj.strftime('%Y-%m-%d')} ---\n", "date_header")
                last_date = dt_obj.date()

            # Beregn og formater tidsforskel
            delta_str = ""
            if last_dt_obj:
                delta = dt_obj - last_dt_obj
                delta_str = self._format_timedelta(delta)

            # Bestem kilde og tag for farve
            source_tag = "source_exif" # Default
            if description.startswith("File System"): source_tag = "source_fs"
            elif description.startswith("Raw File"): source_tag = "source_raw"
            elif description.startswith("XMP History"): source_tag = "source_xmp"
                
            # Indsæt tidspunkt
            text_widget.insert("end", f"{dt_obj.strftime('%H:%M:%S')} ", "time")
            # Indsæt beskrivelse med kilde-farve
            text_widget.insert("end", f"| {description:<80} ", source_tag)
            # Indsæt tidsforskel
            text_widget.insert("end", f"{delta_str}\n", "delta")
            
            last_dt_obj = dt_obj
        
        self._make_text_copyable(text_widget)
    @staticmethod
    def decompress_stream(b):
        for fn in (zlib.decompress, lambda d: __import__("base64").a85decode(re.sub(rb"\s", b"", d), adobe=True), lambda d: __import__("binascii").unhexlify(re.sub(rb"\s|>", b"", d))):
            try: return fn(b).decode("latin1", "ignore")
            except Exception: pass
        return ""

    def extract_text(self, raw):
        txt_segments = [raw.decode("latin1", "ignore")]
        for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S):
            txt_segments.append(self.decompress_stream(m.group(1)))
        m = re.search(rb"<\?xpacket begin=.*?\?>(.*?)<\?xpacket end=[^>]*\?>", raw, re.S)
        if m:
            try: txt_segments.append(m.group(1).decode("utf-8", "ignore"))
            except Exception: pass
        return "\n".join(txt_segments)
    
    @staticmethod
    def analyze_fonts(doc):
        """Analyserer skrifttyper og returnerer True, hvis der findes flere subsets for den samme skrifttype."""
        font_subsets = {}
        for pno in range(len(doc)):
            fonts = doc.get_page_fonts(pno)
            for font in fonts:
                font_name = font[3]
                if '+' in font_name:
                    _, base_font = font_name.split('+', 1)
                    font_subsets.setdefault(base_font, set()).add(font_name)
        
        for base_font, subsets in font_subsets.items():
            if len(subsets) > 1:
                return True
        return False

    def detect_indicators(self, txt, doc):
        """Søger efter indikatorer og returnerer en liste med de fundne indikatork-nøgler."""
        indicators = []

        if re.search(r"touchup_textedit", txt, re.I):
            indicators.append("TouchUp_TextEdit")
        
        if txt.lower().count("startxref") > 1:
            indicators.append("Multiple startxref")

        creators = set(re.findall(r"\/Creator\s*\((.*?)\)", txt, re.I))
        if len(creators) > 1:
            indicators.append(f"Multiple Creators (x{len(creators)})")
        
        producers = set(re.findall(r"\/Producer\s*\((.*?)\)", txt, re.I))
        if len(producers) > 1:
            indicators.append(f"Multiple Producers (x{len(producers)})")

        if re.search(r'<xmpMM:History>', txt, re.I | re.S):
            indicators.append("xmpMM:History")
            
        if self.analyze_fonts(doc):
            indicators.append("Multiple Font Subsets")

        # ID-INDSAMLING
        all_instance_ids = []
        all_doc_ids = []
        
        try:
            trailer = doc.xref_get_trailer()
            trailer_id = trailer.get("ID")
            if isinstance(trailer_id, list) and len(trailer_id) == 2:
                all_doc_ids.append(trailer_id[0].hex().upper())
                all_instance_ids.append(trailer_id[1].hex().upper())
        except Exception:
            pass

        xmp_instance_ids = re.findall(r'xmpMM:InstanceID(?:>|=")([^<"]+)', txt, re.I)
        all_instance_ids.extend(xmp_instance_ids)
        
        xmp_doc_ids = re.findall(r'xmpMM:DocumentID(?:>|=")([^<"]+)', txt, re.I)
        all_doc_ids.extend(xmp_doc_ids)

        xmp_orig_doc_ids = re.findall(r'xmpMM:OriginalDocumentID(?:>|=")([^<"]+)', txt, re.I)
        all_doc_ids.extend(xmp_orig_doc_ids)

        history_block_match = re.search(r'<xmpMM:History>\s*<rdf:Seq>(.*?)</rdf:Seq>\s*</xmpMM:History>', txt, re.S | re.I)
        if history_block_match:
            history_events = re.findall(r'(?:stEvt:instanceID|instanceID)="([^"]+)"', history_block_match.group(1), re.I)
            all_instance_ids.extend(history_events)

        unique_instance_ids = set(filter(None, all_instance_ids))
        if len(unique_instance_ids) > 1:
            indicators.append(f"Multiple InstanceID (x{len(unique_instance_ids)})")

        unique_doc_ids = set(filter(None, all_doc_ids))
        if len(unique_doc_ids) > 1:
            indicators.append(f"Multiple DocumentID (x{len(unique_doc_ids)})")

        return indicators

    def get_flag(self, indicator_keys, is_revision, parent_id=None):
        """Bestemmer filens statusflag baseret på fundne indikatornøgler."""
        if is_revision:
            return self._("revision_of").format(id=parent_id)
        
        keys_set = set(indicator_keys)
        if "Has Revisions" in keys_set:  
            return "YES" if self.language.get() == "en" else "JA"
        
        high_risk = {"TouchUp_TextEdit"}
        if any(item in high_risk for item in keys_set):
            return "YES" if self.language.get() == "en" else "JA"
        
        if indicator_keys:  
            return "Indications Found" if self.language.get() == "en" else "Indikationer Fundet"
        
        return "NOT DETECTED" if self.language.get() == "en" else "IKKE PÅVIST"
    
    def show_about(self):
        about_popup = Toplevel(self.root)
        about_popup.title(self._("menu_about"))
        about_popup.geometry("520x440")
        about_popup.resizable(True, True)
        about_popup.transient(self.root)
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
        about_text_widget.tag_configure("bold", font=("Segoe UI", 9, "bold"))
        about_text_widget.tag_configure("link", foreground="blue", underline=True)
        about_text_widget.tag_configure("header", font=("Segoe UI", 9, "bold", "underline"))
        about_text_widget.insert("end", f"{self._('about_version')} ({datetime.now().strftime('%d-%m-%Y')})\n", "bold")
        about_text_widget.insert("end", self._("about_developer_info"))
        about_text_widget.insert("end", "\n------------------------------------\n\n")
        about_text_widget.insert("end", self._("about_purpose_header") + "\n", "header")
        about_text_widget.insert("end", self._("about_purpose_text"))
        about_text_widget.insert("end", self._("about_included_software_header") + "\n", "header")
        about_text_widget.insert("end", self._("about_included_software_text").format(tool="ExifTool"))
        about_text_widget.insert("end", self._("about_website").format(tool="ExifTool"), "bold")
        about_text_widget.insert("end", "https://exiftool.org\n", "link")
        about_text_widget.insert("end", self._("about_source").format(tool="ExifTool"), "bold")
        about_text_widget.insert("end", "https://github.com/exiftool/exiftool\n", "link")
        about_text_widget.config(state="disabled")
        close_button = ttk.Button(outer_frame, text=self._("close_button_text"), command=about_popup.destroy)
        close_button.grid(row=1, column=0, pady=(10, 0))

    def show_manual(self):
        """Viser et pop-up vindue med programmets manual."""
        manual_popup = Toplevel(self.root)
        manual_popup.title(self._("manual_title"))
        manual_popup.geometry("800x600")
        manual_popup.resizable(True, True)
        manual_popup.transient(self.root)

        outer_frame = ttk.Frame(manual_popup, padding=10)
        outer_frame.pack(fill="both", expand=True)
        outer_frame.rowconfigure(0, weight=1)
        outer_frame.columnconfigure(0, weight=1)

        text_frame = ttk.Frame(outer_frame)
        text_frame.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side="right", fill="y")
        
        manual_text = tk.Text(text_frame, wrap="word", yscrollcommand=scrollbar.set, borderwidth=0, highlightthickness=0, background=manual_popup.cget("background"), font=("Segoe UI", 10))
        manual_text.pack(side="left", fill="both", expand=True, padx=5)
        scrollbar.config(command=manual_text.yview)

        # Definer tags til formatering
        manual_text.tag_configure("h1", font=("Segoe UI", 16, "bold", "underline"), spacing3=10)
        manual_text.tag_configure("h2", font=("Segoe UI", 12, "bold"), spacing1=10, spacing3=5)
        manual_text.tag_configure("bold", font=("Segoe UI", 10, "bold"))
        manual_text.tag_configure("italic", font=("Segoe UI", 10, "italic"))
        manual_text.tag_configure("code", font=("Courier New", 9), background="#f0f0f0")
        manual_text.tag_configure("red", foreground="#C00000")
        manual_text.tag_configure("yellow", foreground="#C07000")
        manual_text.tag_configure("green", foreground="#008000")

        # Indsæt manualens indhold
        manual_text.insert(tk.END, self._("manual_title") + "\n", "h1")
        
        manual_text.insert(tk.END, self._("manual_intro_header") + "\n", "h2")
        manual_text.insert(tk.END, self._("manual_intro_text"))

        manual_text.insert(tk.END, self._("manual_disclaimer_header") + "\n", "h2")
        manual_text.insert(tk.END, self._("manual_disclaimer_text"))

        manual_text.insert(tk.END, self._("manual_class_header") + "\n", "h2")
        manual_text.insert(tk.END, self._("manual_class_text"))
        
        manual_text.insert(tk.END, self._("manual_high_risk_header"), ("bold", "red"))
        manual_text.insert(tk.END, self._("manual_high_risk_text"))

        manual_text.insert(tk.END, self._("manual_med_risk_header"), ("bold", "yellow"))
        manual_text.insert(tk.END, self._("manual_med_risk_text"))

        manual_text.insert(tk.END, self._("manual_low_risk_header"), ("bold", "green"))
        manual_text.insert(tk.END, self._("manual_low_risk_text"))

        manual_text.insert(tk.END, self._("manual_indicators_header") + "\n", "h2")
        manual_text.insert(tk.END, self._("manual_indicators_text"))

        manual_text.insert(tk.END, self._("manual_has_rev_header") + "\n", ("bold",))
        manual_text.insert(tk.END, "• " + self._("col_changed") + ": ", "italic")
        manual_text.insert(tk.END, self._("manual_has_rev_class") + "\n", "red")
        manual_text.insert(tk.END, self._("manual_has_rev_desc"))

        manual_text.insert(tk.END, self._("manual_touchup_header") + "\n", ("bold",))
        manual_text.insert(tk.END, "• " + self._("col_changed") + ": ", "italic")
        manual_text.insert(tk.END, self._("manual_touchup_class") + "\n", "red")
        manual_text.insert(tk.END, self._("manual_touchup_desc"))

        manual_text.insert(tk.END, self._("manual_fonts_header") + "\n", ("bold",))
        manual_text.insert(tk.END, "• " + self._("col_changed") + ": ", "italic")
        manual_text.insert(tk.END, self._("manual_fonts_class") + "\n", "yellow")
        manual_text.insert(tk.END, self._("manual_fonts_desc"))

        manual_text.insert(tk.END, self._("manual_tools_header") + "\n", ("bold",))
        manual_text.insert(tk.END, "• " + self._("col_changed") + ": ", "italic")
        manual_text.insert(tk.END, self._("manual_tools_class") + "\n", "yellow")
        manual_text.insert(tk.END, self._("manual_tools_desc"))
        
        manual_text.insert(tk.END, self._("manual_history_header") + "\n", ("bold",))
        manual_text.insert(tk.END, "• " + self._("col_changed") + ": ", "italic")
        manual_text.insert(tk.END, self._("manual_history_class") + "\n", "yellow")
        manual_text.insert(tk.END, self._("manual_history_desc"))

        manual_text.insert(tk.END, self._("manual_id_header") + "\n", ("bold",))
        manual_text.insert(tk.END, "• " + self._("col_changed") + ": ", "italic")
        manual_text.insert(tk.END, self._("manual_id_class") + "\n", "yellow")
        manual_text.insert(tk.END, self._("manual_id_desc"))
        
        manual_text.insert(tk.END, self._("manual_xref_header") + "\n", ("bold",))
        manual_text.insert(tk.END, "• " + self._("col_changed") + ": ", "italic")
        manual_text.insert(tk.END, self._("manual_xref_class") + "\n", "yellow")
        manual_text.insert(tk.END, self._("manual_xref_desc"))
        
        manual_text.config(state="disabled")

        close_button = ttk.Button(outer_frame, text=self._("close_button_text"), command=manual_popup.destroy)
        close_button.grid(row=1, column=0, pady=(10, 0))

    def export_to_excel(self):
        if not self.report_data:
            messagebox.showwarning(self._("no_data_to_save_title"), self._("no_data_to_save_message"))
            return
        file_path = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel files", "*.xlsx")])
        if not file_path:
            return
        
        logging.info(f"Eksporterer rapport til Excel-fil: {file_path}")
        wb = Workbook()
        ws = wb.active
        ws.title = "PDFRecon Results"
        
        # Ændrer den 9. kolonneoverskrift for klarhed i Excel
        headers = [self._(key) for key in self.columns_keys]
        headers[8] = f"{self._('col_indicators')} {self._('excel_indicators_overview')}"

        for col_num, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_num, value=header)
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color="DDDDDD", end_color="DDDDDD", fill_type="solid")
            cell.alignment = Alignment(wrap_text=True, horizontal="center", vertical="center")
        
        for row_idx, row_data in enumerate(self.report_data, start=2):
            path = row_data[3]
            exif_text = self.exif_outputs.get(path, "")
            row_data_xlsx = row_data[:]
            row_data_xlsx[7] = exif_text
            
            for col_idx, value in enumerate(row_data_xlsx, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=str(value)) # Sikrer at alt er streng
                cell.alignment = Alignment(wrap_text=True, vertical="top")
        
        ws.freeze_panes = "A2"
        for col in ws.columns:
            max_len = max(len(str(cell.value)) if cell.value else 0 for cell in col)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 50)
        
        try:
            wb.save(file_path)
            logging.info(f"Excel-rapport gemt succesfuldt til {file_path}")
        except IOError as e:
            logging.error(f"IOError ved lagring af Excel-fil til {file_path}: {e}")
            messagebox.showerror(self._("excel_save_error_title"), self._("excel_save_error_message").format(e=e))
            return
        except Exception as e:
            logging.exception(f"Uventet fejl ved lagring af Excel-fil til {file_path}")
            messagebox.showerror(self._("excel_unexpected_error_title"), self._("excel_unexpected_error_message").format(e=e))
            return

        if messagebox.askyesno(self._("excel_saved_title"), self._("excel_saved_message")):
            try:
                if sys.platform == "win32":
                    os.startfile(os.path.dirname(file_path))
                elif sys.platform == "darwin":
                    subprocess.call(["open", os.path.dirname(file_path)])
                else:
                    subprocess.call(["xdg-open", os.path.dirname(file_path)])
            except Exception as e:
                logging.error(f"Kunne ikke åbne mappen {os.path.dirname(file_path)}: {e}")
                messagebox.showwarning(self._("open_folder_error_title"), self._("open_folder_error_message"))


if __name__ == "__main__":
    # VIGTIGT: Brug TkinterDnD.Tk() i stedet for tk.Tk()
    root = TkinterDnD.Tk()
    app = PDFReconApp(root)
    root.mainloop()