
try:
    from pdfrecon.app_gui import PDFReconApp
    print("Import successful")
except ImportError as e:
    print(f"Import failed: {e}")
except Exception as e:
    print(f"Error: {e}")
