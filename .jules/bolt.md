
## 2025-02-23 - Fast PyMuPDF Image Deduplication
**Learning:** For deduplicating identical image content inside PDFs, calling `doc.extract_image(xref)` is an unnecessary bottleneck because it parses and decodes the image dictionary. Using `doc.xref_stream_raw(xref)` directly retrieves the raw compressed bytes, offering a 1.5x-4x speedup (depending on image complexity/size).
**Action:** When hashing streams or objects purely for equality checks (like deduplication or caching), prefer the `_raw` stream accessor (`xref_stream_raw`) instead of the parsed dictionary accessor (`extract_image`). Combined with `hashlib.md5(usedforsecurity=False)`, this gives optimal performance for large document processing without changing the logical outcome.
