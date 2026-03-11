<<<<<<< HEAD
## 2024-05-19 - Fast-fail substring checks vs multiple regexes for indicator detection
**Learning:** In large string processing like PDF text extraction, case-insensitive regular expressions are extremely computationally expensive compared to native string methods. The `re.search(..., re.I)` approach takes orders of magnitude longer than `str.lower()` combined with the `in` operator.
**Action:** When scanning large texts for multiple case-insensitive patterns, cache the `.lower()` version of the string once. Use fast substring checks (`if "pattern" in text_lower`) as a prerequisite gate before evaluating more complex regexes. Apply this fast-fail pattern whenever porting or adding new indicator detection logic.

## 2025-02-17 - Optimize Regex Pre-checks and C-level comprehension

**Learning:** Large PDF text buffers are expensive to search with case-insensitive regex or complex capturing groups. Using `in` operator substring checks acts as a fast-fail mechanism that bypasses the regex engine entirely when patterns are absent. Further, replacing `re.finditer` with `re.findall` combined with list/set comprehensions leverages C-level implementations, yielding significant speedups for gathering elements like object definitions (`obj` and `R`).

**Action:** Whenever parsing large text buffers (like raw PDF text streams), identify static substrings that *must* exist for a complex regex to match. Use `if "substring" in txt:` as a guard clause before applying `re.search` or `re.findall`. Default to `re.findall` within comprehensions rather than iterating over `re.finditer` when building collections of matches.
=======

## 2024-06-25 - Cache lowercased text for fast pre-checks
**Learning:** Running case-insensitive regex (`re.I`) on large blocks of text is computationally expensive.
**Action:** Always cache the lowercased version of a large string (`txt_lower = txt.lower()`) and use `in` operator substring pre-checks (O(n) speed) before executing complex case-insensitive regex searches. This drastically reduces the overhead when the search string is absent.
>>>>>>> c72abd91ce8fd83a0aad99a1c9d12f5138bc7c18
