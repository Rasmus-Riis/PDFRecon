#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDFRecon - PDF Forensic Analysis Tool
Entry point for the application.
"""

import multiprocessing

def main():
    """Main entry point for PDFRecon."""
    # Required for Windows when using multiprocessing in frozen app
    multiprocessing.freeze_support()
    
    # Import here to avoid issues with multiprocessing
    from tkinterdnd2 import TkinterDnD
    from pdfrecon.app_gui import PDFReconApp
    
    root = TkinterDnD.Tk()
    app = PDFReconApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
