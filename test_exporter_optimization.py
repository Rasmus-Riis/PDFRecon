import time
from openpyxl.styles import Alignment

def run_without_opt(rows, cols):
    start = time.time()
    for row in range(rows):
        for col in range(cols):
            alignment = Alignment(wrap_text=True, vertical="top")
    return time.time() - start

def run_with_opt(rows, cols):
    start = time.time()
    alignment = Alignment(wrap_text=True, vertical="top")
    for row in range(rows):
        for col in range(cols):
            a = alignment
    return time.time() - start

rows, cols = 1000, 10
print(f"Without opt: {run_without_opt(rows, cols):.4f}s")
print(f"With opt: {run_with_opt(rows, cols):.4f}s")
