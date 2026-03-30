import time
import sys
import os
from unittest.mock import MagicMock

sys.modules['fitz'] = MagicMock()
sys.modules['PIL'] = MagicMock()
sys.modules['exiftool'] = MagicMock()

from src.scan_worker import _extract_all_document_ids as worker_extract
from src.data_processing import DataProcessingMixin

# Test string without matches
txt_miss = "A" * 10_000_000 + " " * 100
exif_miss = "A" * 1000

# Test string with matches
txt_hit = "A" * 10_000_000 + 'xmpMM:DocumentID="uuid:1234"' + " " * 100
exif_hit = "Document ID : uuid:1234\n" + "A" * 1000

print("Testing without matches:")
start = time.time()
worker_extract(txt_miss, exif_miss)
t1 = time.time() - start
print(f"Time (no match): {t1:.4f}s")

print("Testing with matches:")
start = time.time()
worker_extract(txt_hit, exif_hit)
t2 = time.time() - start
print(f"Time (with match): {t2:.4f}s")
