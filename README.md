# PDFRecon v12 - Advanced PDF Forensic Analysis Tool

PDFRecon is a powerful and intuitive GUI tool designed for the forensic analysis of PDF documents. It enables investigators to rapidly scan a large number of files for signs of manipulation, editing, and hidden history.

Developed for forensic investigators, analysts, and anyone who needs to verify the integrity and history of a PDF document.

---

## 🔑 Key Features

PDFRecon combines deep forensic analysis with a user-friendly interface to deliver clear, actionable results.

### Deep Forensic Analysis
* **Revision History Extraction**: Automatically finds and extracts complete, historical versions of a document that are hidden within a single file, providing a unique insight into the document's evolution.
* **Visual Revision Comparison** 🆕: Instantly compare a document's previous version with the latest in a side-by-side view with page navigation. A third panel highlights all visual changes in **red**, making any alteration—large or small—immediately obvious.
* **Intelligent Revision Filtering** 🔎: To reduce noise and focus the investigation, the application automatically filters the results:
  * **Corrupt Revisions**: Revisions with serious structural errors (`Invalid xref table`) are hidden from the main view but are still saved in the `Altered_files` folder for manual inspection.
  * **Visually Identical Revisions**: Revisions saved without any visible changes (checked on up to the first 5 pages) are kept in the list but marked as **"Visually Identical"** and colored **gray** for easy identification.
* **Editing Trace Analysis**: Detects specific metadata artifacts from editing software (e.g., `TouchUp_TextEdit` from Adobe Acrobat), font anomalies, and conflicting software information in the file's metadata.
* **Detailed Timeline Generation**: Creates a readable, chronological timeline of all timestamped events found within a file’s metadata, providing a clear picture of the file's lifecycle.
* **Powered by ExifTool**: Leverages the power of **ExifTool** to extract comprehensive and in-depth metadata that other tools often miss.

### Intuitive UI & Reporting
* **Simple Drag & Drop**: Drag a folder directly onto the application window to start an analysis.
* **Color-Coded Results**: A simple color system helps you prioritize your investigation:
  * 🔴 **Red**: High risk. Strong evidence of manipulation found.
  * 🟡 **Yellow**: Medium risk. Indications of editing or an unusual file history were found.
  * 🔵 **Blue**: An extracted, earlier version of another file.
  * ⚪ **Gray**: A revision that is visually identical to the latest version.
  * **White**: No specific indicators of manipulation were detected.
* **Multi-Language Interface**: Switch between English and Danish on the fly.
* **Excel Export**: Export the complete analysis to a formatted `.xlsx` file, ready for documentation and reporting.

---

## Installation

PDFRecon requires Python 3.6+ and a few external libraries.

### 1. Clone the repository
```bash
git clone https://github.com/Rasmus-Riis/PDFRecon.git
cd PDFRecon
```

### 2. Install required Python libraries
The project requires **PyMuPDF**, **openpyxl**, **tkinterdnd2**, and **Pillow**.  
You can install them using the `requirements.txt` file:
```bash
pip install -r requirements.txt
```

### 3. Download ExifTool (Important!)
PDFRecon depends on the stand-alone Windows executable of ExifTool. This ensures you do not need a separate `lib` folder.

1. Download the **Windows Stand-Alone Executable** from the [official ExifTool website](https://exiftool.org/).
2. The downloaded file is typically named `exiftool(-k).exe`. Rename it to **exiftool.exe**.
3. Place the renamed `exiftool.exe` in the same directory as the `PDFRecon.py` script and also place `exiftool_files` folder in the same directory as the exe file.

---

## Usage

**Run the script:**
```bash
python PDFRecon.py
```

**Start a Scan** by either dragging a folder onto the window or by using the **"Choose folder"** button.

**Analyze Results:** Use the color codes to quickly identify files of interest. Right-click on any file for more actions.

**Compare Revisions:** Right-click on a blue or gray row (a revision) and select **"Visually Compare Revision"** to see the changes.  
Use the **"Next/Previous Page"** buttons to navigate.

---

## License

This project is distributed under the **MIT License**.  
See the [LICENSE](LICENSE) file for more information.
