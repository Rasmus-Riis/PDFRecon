# PDFRecon - Advanced PDF Forensic Analysis Tool

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Python Version](https://img.shields.io/badge/python-3.6+-blue.svg)

**Uncover the hidden history of your PDF documents.** PDFRecon is a powerful and intuitive GUI tool built for forensic investigators, analysts, and anyone needing to verify a document's integrity. It rapidly scans large sets of PDF files, detecting signs of manipulation, extracting hidden revision histories, and presenting the findings in a clear, actionable format.

![PDFRecon Main Interface](https://raw.githubusercontent.com/Rasmus-Riis/PDFRecon/main/assets/PDFRecon_Screenshot.png)

---

## 🔑 Key Features

PDFRecon combines deep forensic analysis with a user-friendly interface to deliver results you can act on immediately.

### Deep Forensic Analysis

* **Revision History Extraction**: Automatically finds and extracts complete, historical versions of a document hidden within a single file. This provides a unique and powerful insight into a document's evolution over time.

* **Visual Revision Comparison** 🆕: Instantly compare any historical version with the latest one.
    * **Side-by-Side Viewing**: See both documents page by page.
    * **Red-Highlighted Differences**: A third panel highlights all visual changes in **red**, making any alteration—large or small—immediately obvious.

* **Intelligent Revision Filtering** 🔎: To reduce noise and focus your investigation, the application automatically filters and flags extracted revisions:
    * **Corrupt Revisions**: Revisions with serious structural errors (like an `Invalid xref table`) are hidden from the main view but are still saved in the `Altered_files` folder for manual inspection.
    * **Visually Identical Revisions**: Revisions saved without any visible changes (checked on up to the first 5 pages) are marked as **"Visually Identical"** and colored gray for easy deprioritization.

* **Editing Trace Analysis**: Detects specific metadata artifacts from editing software (e.g., `TouchUp_TextEdit` from Adobe Acrobat), analyzes font anomalies, and identifies conflicting creator/producer information in the file's metadata.

* **Detailed Timeline Generation**: Creates a readable, chronological timeline of all timestamped events found within a file’s metadata and structure, providing a clear picture of the file's lifecycle from creation to the latest modification.

* **Powered by ExifTool**: Leverages the full power of **ExifTool** to extract comprehensive metadata that other tools often miss.

### Intuitive UI & Reporting

* **Simple Drag & Drop Interface**: Just drag a folder onto the application window to start a complete analysis.

* **Color-Coded Results**: A simple color system helps you instantly prioritize your investigation:
    * 🔴 **Red**: **High Risk.** Strong evidence of manipulation was found.
    * 🟡 **Yellow**: **Medium Risk.** Indications of editing or an unusual file history were found.
    * 🔵 **Blue**: An extracted, earlier version of another file.
    * ⚪️ **Gray**: A revision that is visually identical to the latest version.
    * **White**: No specific indicators of manipulation were detected.

* **Multi-Language Support**: Switch the entire interface between **English** and **Danish** on the fly.

* **Multiple Export Formats**: Export the complete analysis to a formatted report, ready for documentation. Supported formats include `Excel (.xlsx)`, `CSV`, `JSON`, and `HTML`.

* **Save case**: After parsing the analysis can be saved into a case, so work can continue later without having to wait for the program to finish. 

* **Notes**: You can add notes to each file, making analysis easier on large volumes of PDF files

* **Export reader**: You can export the case to a portable reader that lack the possibility of parsing/adding new files

* **Verify file integrety**: The files will have their MD5 saved, so the program can easily check if the files have been altered during your examination
---

## 🚀 Installation & Setup

PDFRecon requires Python 3.6+ and a few external libraries.

For the 'Export Reader' function to be activated, the script needs to be compiled to .exe

### 1. Clone the Repository
git clone https://github.com/Rasmus-Riis/PDFRecon.git

cd PDFRecon
