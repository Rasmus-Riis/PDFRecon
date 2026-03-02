
## 2024-05-18 - Optimized `sha256_file` and added `usedforsecurity=False`
**Learning:** `hashlib.md5(usedforsecurity=False)` provides a small performance optimization and avoids crashes on FIPS compliant machines. Also `sha256_file` was not using `buffering=0` with `bytearray` and `memoryview`, leading to excessive allocations, fixing it improved speed by 20%. The regex optimization `txt.lower()` cache was already implemented in earlier PR.
**Action:** Use `usedforsecurity=False` for all md5 hashes unless used for cryptography. Always use `bytearray` and `memoryview` when hashing files in chunks.
