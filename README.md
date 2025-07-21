# PDFRecon - PDF Forensic Analysis Tool

PDFRecon is a graphical forensic tool designed to analyze PDF files for signs of manipulation, editing, and hidden content. It provides a user-friendly interface to quickly assess a large number of documents, identify suspicious files, and export findings for reporting.

Developed for forensic investigators, analysts, and anyone needing to verify the integrity of PDF documents.

## Features

* **Intuitive Graphical User Interface:** Easy-to-use interface built with Tkinter.
* **Drag & Drop:** Simply drag a folder onto the application window to start a scan.
* **Context Menu:** Right-click on any file in the results list for quick access to actions like viewing EXIF data, timelines, or opening the file's location.
* **Multi-Language Support:** Switch between Danish and English on the fly.
* **In-Depth Analysis:** Scans for a wide range of indicators, including:
    * **Revision History:** Automatically extracts and lists previous versions of a document saved within the file itself.
        * **How it works:** When a PDF is saved with "incremental updates," the original content is not overwritten. Instead, the changes are appended to the end of the file, and a new `%%EOF` (End-of-File) marker is added. The presence of multiple `%%EOF` markers is a definitive sign that the file has a history. PDFRecon scans for these markers and extracts each segment as a complete, standalone previous version of the document, allowing for a full reconstruction of the file's history.
    * **Editing Traces:** Detects specific metadata left by editing software, such as `TouchUp_TextEdit` from Adobe Acrobat.
    * **Font Analysis:** Identifies anomalies in font subsets, which can indicate text insertion or modification.
    * **Metadata Inconsistencies:** Finds conflicting `Creator` or `Producer` tool information.
* **ExifTool Integration:** Leverages the power of ExifTool to extract comprehensive metadata.
* **Visual Timeline:** Generates a detailed, human-readable timeline of all timestamped events found within a file's metadata.
* **Excel Export:** Export the complete analysis results to a formatted `.xlsx` file for documentation and reporting.
* **Color-Coded Results:** Uses a simple color system to help you prioritize your investigation:
    * **Red:** High risk. Strong evidence of manipulation found.
    * **Yellow:** Medium risk. Indications of editing or an unusual file history were found.
    * **Blue:** An extracted revision of another file.
    * **White:** No specific indicators of manipulation were detected.

## Installation

To run PDFRecon, you need Python 3.6 or newer and a few external libraries.

**1. Clone the repository:**
```bash
git clone [https://github.com/Rasmus-Riis/PDFRecon.git](https://github.com/Rasmus-Riis/PDFRecon.git)
cd PDFRecon
```

**2. Install required Python libraries:**
The project requires `PyMuPDF`, `openpyxl`, and `tkinterdnd2`. You can install them using pip:
```bash
pip install -r requirements.txt
```

**3. Download ExifTool:**
PDFRecon depends on the standalone Windows executable of **ExifTool**.

* Download `exiftool(-k).exe` from the [official ExifTool website](https://exiftool.org/).
* Rename the file to `exiftool.exe`.
* Place `exiftool.exe` in the same directory as the `PDFRecon.py` script.

## Usage

1.  **Run the script:**
    ```bash
    python PDFRecon.py
    ```
2.  **Start a Scan:**
    * **Drag and Drop:** Drag a folder from your file explorer and drop it anywhere on the PDFRecon window.
    * **Button:** Click the "📁 Vælg mappe og scan" / "📁 Choose folder and scan" button and select a folder.
3.  **Analyze Results:**
    * The main table will populate with all PDF files found. Use the color-coding to quickly identify files of interest.
    * Click on any row to see a summary of its data in the detail pane below the table.
    * Click on the "EXIFTool" column entry to view the full metadata output.
4.  **Use Context Menu:**
    * Right-click on any file in the list to open a context menu with shortcuts to:
        * View EXIFTool output
        * View the file's timeline
        * Open the file's location in your file explorer
5.  **Export Report:**
    * Click the "💾 Gem som Excel" / "💾 Save as Excel" button to save all the results in the table to an `.xlsx` file.

## License

This project is distributed under the MIT License. See the `LICENSE` file for more information.
