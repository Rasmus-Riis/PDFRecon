"""
PDFRecon - Main Application Entry Point

Modular Architecture:
- pdfrecon.config: Configuration, constants, exceptions
- pdfrecon.utils: Utility functions
- pdfrecon.logging_setup: Logging configuration
- pdfrecon.pdf_processor: PDF operations with hang prevention
- pdfrecon.scanner: PDF analysis and scanning (Phase 5a ✓)
- pdfrecon.exporter: Report generation and export (Phase 5b ✓)
- pdfrecon.app_gui: Main GUI application class
- pdfrecon/__init__.py: Package initialization
"""

import sys
from pathlib import Path

# Add parent directory to path to allow imports
sys.path.insert(0, str(Path(__file__).parent))

from pdfrecon import __version__
from pdfrecon.config import APP_VERSION, PDFReconConfig
from pdfrecon.logging_setup import setup_logging
from pdfrecon.utils import _import_with_fallback

# Import customtkinter for modern UI
import customtkinter as ctk

# Import TkinterDnD for drag-and-drop support
TkinterDnD = _import_with_fallback('tkinterdnd2', 'TkinterDnD', 'tkinterdnd2')
from tkinterdnd2 import TkinterDnD


def main():
    """Main entry point for PDFRecon application."""
    
    print(f"PDFRecon v{APP_VERSION}")
    print("=" * 50)
    
    # Setup logging
    log_file = Path.home() / "PDFRecon" / "pdfrecon.log"
    log_file.parent.mkdir(exist_ok=True)
    setup_logging(log_file)
    
    print(f"Log file: {log_file}")
    
    # Import the main application class from the modular structure
    from pdfrecon.app_gui import PDFReconApp
    
    # Create root window using customtkinter
    root = ctk.CTk()
    
    # Initialize application
    app = PDFReconApp(root)
    
    # Start main event loop
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nApplication terminated by user")
        sys.exit(0)
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
