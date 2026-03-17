# PDFRecon – Duplicate and Dead Code Review

## 1. Duplicate code

### 1.1 `extract_revisions` (three implementations)
- **`src/data_processing.py`** – `DataProcessingMixin.extract_revisions(self, raw, original_path)`  
  Used by the (currently dead) `_process_single_file` in actions and by scanner when `app_instance.extract_revisions` is used.
- **`src/scanner.py`** – `extract_revisions(raw, original_path)`  
  Used by `detect_indicators` when `app_instance` has no `extract_revisions` or when calling with `doc.write()`.
- **`src/scan_worker.py`** – `_extract_revisions(raw, original_path)`  
  Used by the real scan pipeline (`process_single_file_worker`).

**Recommendation:** Keep a single implementation (e.g. in `pdf_processor` or `scanner`) and call it from data_processing, scanner, and scan_worker.

---

### 1.2 `find_pdf_files_generator` (two implementations)
- **`src/scanner.py`** – `find_pdf_files_generator(folder_path)`  
  Not used by the app; scan uses the method below.
- **`src/actions.py`** – `_find_pdf_files_generator(self, folder)`  
  Same logic (walk dirs, yield `.pdf` paths). Used by `_scan_worker_parallel`.

**Recommendation:** Use one implementation (e.g. scanner’s) and have actions call it.

---

### 1.3 Text / stream extraction (two implementations)
- **`src/data_processing.py`** – `decompress_stream(b)`, `extract_text(raw)`  
  Used for main-thread extraction and Exif/timeline.
- **`src/scan_worker.py`** – `_decompress_stream(b)`, `_extract_text_for_scanning(raw)`  
  Same purpose for worker processes (no GUI deps).

**Recommendation:** Share core logic in a non-GUI module (e.g. `pdf_processor` or `utils`) and have both call it, or document that worker and GUI must stay in sync.

---

### 1.4 Indicator formatting (two implementations)
- **`src/data_processing.py`** – `_format_indicator_details(self, key, details)`  
  Full formatting for all indicator types; used by UI and export_logic.
- **`src/exporter.py`** – `format_indicator_details(key, details)`  
  Simpler version; used only by tests and not by the app’s export (export_logic uses `self._format_indicator_details`).

**Recommendation:** Either have exporter call into data_processing for real formatting or keep exporter’s version only for tests and document that.

---

### 1.5 Export logic (two layers)
- **`src/export_logic.py`** – `ExportMixin._export_to_excel/csv/json/html`  
  Actually used by the app; uses `self._format_indicator_details` and `clean_cell_value` from exporter.
- **`src/exporter.py`** – `export_to_excel`, `export_to_csv`, `export_to_json`, `export_to_html`  
  Standalone functions; **not called** by the app. Only `clean_cell_value` is imported (by export_logic).

**Recommendation:** Treat exporter as a helper (e.g. `clean_cell_value`) and optional/test API; document that the live export path is ExportMixin.

---

### 1.6 OCG layer label building (repeated pattern in popups)
- **`src/popups.py`** – In `show_inspector_popup` (lines ~371–384) and `show_pdf_viewer_popup` (lines ~658–671):  
  Same pattern: build `name_counts` from `doc_ocgs`/`popup_ocgs`, then `name_seen`, then label `f"{base_name} #{name_seen[base_name]}"` if `name_counts[base_name] > 1` else `base_name`.

**Recommendation:** Extract a small helper, e.g. `_ocg_display_label(info, name_counts, name_seen)` and use it in both popups.

---

### 1.7 Redundant assignment in `popups.py` (bug)
- **`src/popups.py`** in `update_page` (inspector), lines 551–553:
  - `scaled_size = (int(img.width * actual_ratio / zoom_factor), ...)`  
  - Next line: `scaled_size = (int(img.width * fit_ratio), int(img.height * fit_ratio))`  
  The first assignment is overwritten and has no effect; zoom is effectively ignored for size.

**Recommendation:** Remove the first `scaled_size` line or fix the logic so zoom is applied consistently.

---

## 2. Dead code

### 2.1 Unreachable code after `return` in `show_manual`
- **`src/popups.py`** – In `show_manual`, after opening the manual in the browser or showing “Manual Not Found”, the function returns (lines 552–553).  
  The block that creates `manual_popup` (Toplevel, geometry, text widget, etc.) is **after** that return (lines 555–593) and is never executed.

**Recommendation:** Delete the unreachable block (lines 555–593) or move it into an alternate code path (e.g. “open in window” instead of browser) and call it before any return.

---

### 2.2 `_process_single_file` in actions (entire method unused)
- **`src/actions.py`** – `_process_single_file(self, fp)` (lines ~248–370) is **never called**.  
  The real scan uses `scan_worker.process_single_file_worker` and `_scan_worker_parallel` with the process pool.  
  This method also references `PDFTooLargeError`, `PDFEncryptedError`, `PDFCorruptionError` which are **not imported** in actions (only `PDFReconConfig` is imported from config), so if it were ever called it would raise `NameError`.

**Recommendation:** Remove `_process_single_file` from actions, or add the missing exception imports and a comment that it is legacy/unused. Prefer removal.

---

### 2.3 `_compile_software_regex` never called
- **`src/data_processing.py`** – `_compile_software_regex()` (lines 30–32) just returns `DataProcessingMixin.SOFTWARE_TOKENS`.  
  No references in the codebase.

**Recommendation:** Remove the method and use `SOFTWARE_TOKENS` directly where needed, or remove if truly unused.

---

### 2.4 Empty stub methods in UI layout
- **`src/ui_layout.py`** – `_setup_detail_frame(self, parent_frame)` and `_setup_bottom_frame(self, parent_frame)` (lines 317–320) only contain `pass`.  
  Not referenced anywhere.

**Recommendation:** Remove them or implement; otherwise they are dead stubs.

---

### 2.5 `_setup_drag_and_drop` no-op
- **`src/actions.py`** – `_setup_drag_and_drop` (lines 75–78): if not reader mode it does `pass` and does not set up drag-and-drop.  
  So drag-and-drop is never actually configured here.

**Recommendation:** Either implement DnD here or remove the method and any callers.

---

## 3. Bugs / missing definitions

### 3.1 `scanner.py` uses `fitz` without importing it
- **`src/scanner.py`** – In `extract_revisions`, line 98: `test_doc = fitz.open(stream=rev_bytes, filetype="pdf")`.  
  `fitz` is not imported in scanner (only config, pdf_processor, utils, advanced_forensics are).  
  When `extract_revisions` in scanner is used (e.g. from `detect_indicators` when not using app_instance’s extract_revisions), this will raise `NameError: name 'fitz' is not defined`.

**Recommendation:** Add `import fitz` (or the project’s `_import_with_fallback('fitz', 'fitz', 'PyMuPDF')`) at the top of `scanner.py`.

---

---

## 4. Summary table

| Category        | Location(s) | Description |
|----------------|-------------|-------------|
| Duplicate      | data_processing, scanner, scan_worker | `extract_revisions` x3 |
| Duplicate      | scanner, actions | `find_pdf_files_generator` x2 |
| Duplicate      | data_processing, scan_worker | decompress_stream + extract_text |
| Duplicate      | data_processing, exporter | `_format_indicator_details` vs `format_indicator_details` |
| Duplicate      | export_logic, exporter | Export-to-Excel/CSV/JSON/HTML (exporter versions unused) |
| Duplicate      | popups (inspector vs viewer) | OCG name_counts/name_seen/label loop |
| Bug            | popups | `scaled_size` assigned twice; first line useless |
| Dead           | popups | Code after `return` in `show_manual` |
| Dead           | actions | `_process_single_file` never called; missing exception imports |
| Dead           | data_processing | `_compile_software_regex` never called |
| Dead           | ui_layout | `_setup_detail_frame`, `_setup_bottom_frame` empty stubs |
| Dead           | actions | `_setup_drag_and_drop` no-op |
| Missing import | scanner | `fitz` used but not imported |
