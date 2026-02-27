## 2024-05-23 - Duplicate Code in `_scan_worker_parallel`

**Learning:** I discovered that the `_scan_worker_parallel` method is defined twice in `pdfrecon/app_gui.py`. The second definition overrides the first one. This is a clear case of accidental code duplication, likely from a merge or refactoring error.

**Action:** When working on a large file like `pdfrecon/app_gui.py`, always check for duplicate method definitions. I will remove the first (and seemingly less complete/older) definition of `_scan_worker_parallel` to clean up the code and prevent confusion. The second definition seems to be the one intended to be used as it includes timeout handling.
