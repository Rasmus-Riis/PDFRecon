
## 2024-06-25 - Cache lowercased text for fast pre-checks
**Learning:** Running case-insensitive regex (`re.I`) on large blocks of text is computationally expensive.
**Action:** Always cache the lowercased version of a large string (`txt_lower = txt.lower()`) and use `in` operator substring pre-checks (O(n) speed) before executing complex case-insensitive regex searches. This drastically reduces the overhead when the search string is absent.
