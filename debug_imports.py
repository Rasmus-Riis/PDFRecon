import sys
import os
from pathlib import Path

# Add root to sys.path
root = Path(__file__).parent.parent
sys.path.append(str(root))

print(f"Checking imports from {root}...")
try:
    from src.scanner import PDFScanner
    print("SUCCESS: PDFScanner imported.")
except Exception as e:
    import traceback
    traceback.print_exc()
