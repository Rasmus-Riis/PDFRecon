## 2026-06-30 - O(1) set membership over O(N) list traversal in scanner.py
**Learning:** Python lists in `in` loops exhibit O(N^2) complexity, leading to severe slowdowns when analyzing large xref sections or numerous objects. In high-frequency parsing tasks where order is not required for duplication checks, sets offer immediate O(1) lookups that dramatically improve scaling. Also, be careful to remove ad-hoc profiling artifacts before finishing.
**Action:** Always prefer `set()` membership testing over `list()` for `in` checks where duplication is being evaluated.
