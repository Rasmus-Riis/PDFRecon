## 2024-05-19 - String concatenation in loops
**Learning:** `safe_extract_text` uses string concatenation (`txt += page_text`) in a loop. In Python, string concatenation in a loop can lead to O(n^2) time complexity because strings are immutable and a new string must be allocated and copied each iteration. Using a list to collect strings and joining them at the end (`"".join(text_chunks)`) is much more efficient (O(n)).
**Action:** Replace `txt += page_text` with list accumulation and `"".join()` in `safe_extract_text` and any similar instances handling large texts.
