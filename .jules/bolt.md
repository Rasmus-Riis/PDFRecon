## 2024-05-19 - Fast-fail substring checks vs multiple regexes for indicator detection
**Learning:** In large string processing like PDF text extraction, case-insensitive regular expressions are extremely computationally expensive compared to native string methods. The `re.search(..., re.I)` approach takes orders of magnitude longer than `str.lower()` combined with the `in` operator.
**Action:** When scanning large texts for multiple case-insensitive patterns, cache the `.lower()` version of the string once. Use fast substring checks (`if "pattern" in text_lower`) as a prerequisite gate before evaluating more complex regexes. Apply this fast-fail pattern whenever porting or adding new indicator detection logic.

## 2025-02-17 - Optimize Regex Pre-checks and C-level comprehension

**Learning:** Large PDF text buffers are expensive to search with case-insensitive regex or complex capturing groups. Using `in` operator substring checks acts as a fast-fail mechanism that bypasses the regex engine entirely when patterns are absent. Further, replacing `re.finditer` with `re.findall` combined with list/set comprehensions leverages C-level implementations, yielding significant speedups for gathering elements like object definitions (`obj` and `R`).

**Action:** Whenever parsing large text buffers (like raw PDF text streams), identify static substrings that *must* exist for a complex regex to match. Use `if "substring" in txt:` as a guard clause before applying `re.search` or `re.findall`. Default to `re.findall` within comprehensions rather than iterating over `re.finditer` when building collections of matches.

## 2024-06-25 - Cache lowercased text for fast pre-checks
**Learning:** Running case-insensitive regex (`re.I`) on large blocks of text is computationally expensive.
**Action:** Always cache the lowercased version of a large string (`txt_lower = txt.lower()`) and use `in` operator substring pre-checks (O(n) speed) before executing complex case-insensitive regex searches. This drastically reduces the overhead when the search string is absent.

## 2025-02-23 - Fast PyMuPDF Image Deduplication
**Learning:** For deduplicating identical image content inside PDFs, calling `doc.extract_image(xref)` is an unnecessary bottleneck because it parses and decodes the image dictionary. Using `doc.xref_stream_raw(xref)` directly retrieves the raw compressed bytes, offering a 1.5x-4x speedup (depending on image complexity/size).
**Action:** When hashing streams or objects purely for equality checks (like deduplication or caching), prefer the `_raw` stream accessor (`xref_stream_raw`) instead of the parsed dictionary accessor (`extract_image`). Combined with `hashlib.md5(usedforsecurity=False)`, this gives optimal performance for large document processing without changing the logical outcome.

## 2024-05-18 - Optimized `sha256_file` and added `usedforsecurity=False`
**Learning:** `hashlib.md5(usedforsecurity=False)` provides a small performance optimization and avoids crashes on FIPS compliant machines. Also `sha256_file` was not using `buffering=0` with `bytearray` and `memoryview`, leading to excessive allocations, fixing it improved speed by 20%. The regex optimization `txt.lower()` cache was already implemented in earlier PR.
**Action:** Use `usedforsecurity=False` for all md5 hashes unless used for cryptography. Always use `bytearray` and `memoryview` when hashing files in chunks.

## 2025-03-15 - [Set literals vs List literals in performance-critical loops]
**Learning:** In Python, the `in` operator combined with a set literal (`{"A", "B"}`) is compiled into a `frozenset` at bytecode level (constant folding). This makes membership tests O(1) compared to O(n) for list literals (`["A", "B"]`). In hot paths parsing thousands of PDF operators, replacing list literals with set literals yields a 45-65% performance boost in those checks, reducing CPU overhead during PDF forensics scanning.
**Action:** Always favor set literals (`{...}`) over list literals (`[...]`) for static membership tests (using the `in` operator), particularly in loops and parsing logic.

## 2025-05-18 - Fast-fail substring checks for multiple regex operations
**Learning:** When using fast-fail substring guard checks (e.g., `if "guard" in txt_lower:`) to bypass multiple regular expression searches in the same code block, the guard substring must be chosen carefully to avoid unintentionally excluding valid targets. For example, using `if "document" in exif_lower and "id" in exif_lower:` to guard a block searching for `Document ID`, `Original Document ID`, and `Instance ID` will erroneously skip files containing only `Instance ID`.
**Action:** Be cautious when creating a single substring guard for a block that executes multiple distinct regex searches. A broader guard like `if "id" in exif_lower:` or applying individual substring checks for each distinct regex operation prevents regressions.

## 2024-03-24 - Fast-Fail Substring Pre-Checks for Regex
**Learning:** For performance optimization on large byte arrays and text blocks (e.g., raw PDF data in `src/advanced_forensics.py`), using literal substring pre-checks (like `b'\x00' * 200 in pdf_bytes` or `"@" in txt`) as a fast-path filter before invoking `re.findall` significantly reduces execution time (50x-200x speedups) by bypassing the regex engine overhead when the pattern is absent.
**Action:** Always implement literal substring guards for expensive regular expressions applied to large strings or byte sequences when the literal is a required component of the pattern.
## 2025-05-19 - Optimize `re.finditer` with single capture group to `re.findall`
**Learning:** Using `re.finditer` and explicitly iterating through match objects (`m.group(1)`) is significantly slower than using `re.findall` when extracting single capture groups from regular expressions, especially within large string buffers like PDF metadata. `re.findall` leverages C-level implementations, directly returning a list of strings instead of generating intermediate `Match` objects, offering up to ~40% speedups.
**Action:** Replace `for m in re.finditer(pattern, string): v = m.group(1)` with `for match in re.findall(pattern, string): v = match`. Do the same when multiple capture groups are present and both are extracted.

## 2025-05-19 - Pre-mapping UI tree items to prevent O(N^2) exports
**Learning:** The `_export_to_html` method contained an O(N^2) bottleneck where it iterated through `tree.get_children()` inside a report data loop to find matching tags.
**Action:** When performing data exports that need to correlate with UI elements, pre-map the UI tree items to a dictionary (e.g. by file path) before entering the export loop to achieve O(1) lookups and significantly reduce export time.
## 2024-05-18 - Optimize stream whitespace removal
**Learning:** In the PDF stream decompression hot path, using `re.sub(rb"\s", b"", d)` for removing whitespace from large byte arrays is notably slow due to Python regex engine overhead. Native byte methods like `b"".join(d.split())` perform the same operation significantly faster (up to ~8x faster in micro-benchmarks).
**Action:** When cleaning whitespace from large raw byte streams before decoding, prefer native split/join over regular expressions.

## 2024-04-26 - Native String Ops Over re.sub
**Learning:** Using `re.sub` for simple string prefix stripping and character filtering introduces significant overhead in hot parsing paths (like UUID cleaning and date normalization). Native string operations (`startswith`/slicing, `.replace()`, and `filter`) are up to 3x-4x faster than their regex equivalents. Furthermore, chained `if` checks are safer than regex for handling stacked prefixes.
**Action:** Always prefer native string slicing, `.startswith`, or chained `.replace()` over `re.sub` when stripping fixed prefixes or a small set of known characters.
## 2024-05-19 - Fast-fail optimization for case-insensitive regex matching
**Learning:** Adding fast-fail substring guards before case-insensitive (`re.I`) regular expressions is risky and error-prone. If the string contains uppercase characters, it will fail the `in` check unless `.lower()` is used. But using `.lower()` on a multi-megabyte string or byte array allocates $O(N)$ additional memory, potentially leading to Out-Of-Memory (OOM) crashes in a production environment dealing with large files. Guard checks checking for permutations (e.g. `b"TouchUp" in raw or b"touchup" in raw`) still fail to catch mixed case edge cases like `b"ToUcHup"`. Therefore, only case-sensitive exact regex matching (`re.S` without `re.I`) should be optimized with fast-fail `in` substring guards.
**Action:** When performing `re.search` optimization with `in` guards on large inputs, ensure the regex doesn't have the `re.I` flag, unless you can guarantee the text will never contain mixed-case letters, or you are okay with a minor O(N) memory spike in case of using `.lower()`.

## 2025-05-19 - Optimize literal keyword counting
**Learning:** Using `len(re.findall(r"\bkeyword\b", text))` to count occurrences of a literal string is very slow compared to the native Python method `text.count("keyword")`. For a large PDF text extraction loop, checking "endobj" occurrences can be extremely fast (approx. 37x speedup for this operation) by relying on `string.count`, which avoids regex compilation and engine overhead entirely, assuming the keyword does not need complex word boundary matching. Note that in PDFs `endobj` almost universally appears as an isolated token so `\b` is unnecessary.
**Action:** Always prefer `string.count("word")` over `len(re.findall(r"\bword\b", string))` when checking for the number of occurrences of a unique, known literal keyword, especially inside loops over large text buffers.
