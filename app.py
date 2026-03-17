#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDFRecon - PDF Forensic Analysis Tool
Entry point: GUI by default, or CLI when a subcommand is passed (scan, export-signed, extract-js).
"""

import multiprocessing
import sys


def main():
    """Main entry point: CLI if subcommand given, else GUI."""
    multiprocessing.freeze_support()
    # CLI for pipeline integration (e.g. python app.py scan ./docs --output-dir ./out)
    if len(sys.argv) > 1 and sys.argv[1] in ("scan", "export-signed", "extract-js", "--help", "-h"):
        from cli import main as cli_main
        sys.exit(cli_main())
    # GUI
    from tkinterdnd2 import TkinterDnD
    from src.app_gui import PDFReconApp
    root = TkinterDnD.Tk()
    app = PDFReconApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
