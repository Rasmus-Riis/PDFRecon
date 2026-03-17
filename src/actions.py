import os
import sys
import shutil
import logging
import queue
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, Toplevel, ttk
import webbrowser
import json
import pickle
import requests
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from datetime import datetime

from .config import PDFReconConfig, PDFTooLargeError, PDFEncryptedError, PDFCorruptionError
from .utils import CaseEncoder, case_decoder
from .scan_worker import process_single_file_worker, build_scan_config, _worker_init
from .chain_of_custody import (
    get_custody_log_path,
    log_ingestion,
    log_verify,
    read_and_verify_custody_log,
    format_custody_log_display,
)

class ActionsMixin:
    def _update_summary_status(self):
        if not self.all_scan_data:
            self.status_var.set(self._("status_initial"))
            return

        all_flags = []
        for data in self.all_scan_data.values():
            if data.get("status") == "error":
                error_type_key = data.get("error_type", "unknown_error")
                all_flags.append(self._(error_type_key))
            elif not data.get("is_revision"):
                flag = self.get_flag(data.get("indicator_keys", {}), False)
                all_flags.append(flag)

        error_keys = ["file_too_large", "file_corrupt", "file_encrypted", "validation_error", "processing_error", "unknown_error"]
        error_statuses = {self._(key) for key in error_keys}
        
        changed_count = all_flags.count("JA") + all_flags.count("YES")
        indications_found_count = all_flags.count("Sandsynligt") + all_flags.count("Possible")
        total_altered = changed_count + indications_found_count
                           
        error_count = sum(1 for flag in all_flags if flag in error_statuses)
        
        original_files_count = len([d for d in self.all_scan_data.values() if not d.get('is_revision')])
        not_flagged_count = original_files_count - changed_count - indications_found_count - error_count

        if error_count > 0:
            summary_text = self._("scan_complete_summary_with_errors").format(
                total=original_files_count, total_altered=total_altered,
                changed_count=changed_count, revs=self.revision_counter,
                indications_found_count=indications_found_count, errors=error_count, clean=not_flagged_count
            )
        else:
            summary_text = self._("scan_complete_summary").format(
                total=original_files_count, total_altered=total_altered,
                changed_count=changed_count, revs=self.revision_counter,
                indications_found_count=indications_found_count, clean=not_flagged_count
            )
        self.status_var.set(summary_text)

    def _perform_copy(self, source, dest_path):
        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(source, Path):
                shutil.copy2(source, dest_path)
                logging.info(f"Copied file from {source.name} to: {dest_path}")
            elif isinstance(source, bytes):
                dest_path.write_bytes(source)
                logging.info(f"Copied revision bytes to: {dest_path}")
        except Exception as e:
            logging.error(f"Error copying to {dest_path}: {e}")

    def _setup_drag_and_drop(self):
        if self.is_reader_mode:
            return
        pass

    def _save_current_case(self):
        if not self.current_case_filepath or not self.case_is_dirty:
            return
        
        try:
            self._write_case_to_file(self.current_case_filepath)
            self.case_is_dirty = False
            self.dirty_notes.clear()
            logging.info(f"Annotations saved to case file: {self.current_case_filepath}")
            self._apply_filter()
        except Exception as e:
            logging.error(f"Failed to save case file '{self.current_case_filepath}': {e}")
            messagebox.showerror(self._("case_save_error_title"), self._("case_save_error_msg").format(e=e))

    def handle_drop(self, event):
        folder_path = event.data.strip('{}')
        if os.path.isdir(folder_path):
            self.start_scan_thread(Path(folder_path))
        else:
            messagebox.showwarning(self._("drop_error_title"), self._("drop_error_message"))

    def _on_tree_motion(self, event):
        col_id = self.tree.identify_column(event.x)
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            self.tree.config(cursor="")
            return

        path_str = self.tree.item(row_id, "values")[4]
        
        if col_id == '#9':
            if path_str in self.exif_outputs and self.exif_outputs[path_str]:
                exif_output = self.exif_outputs[path_str]
                is_error = (exif_output == self._("exif_err_notfound") or
                            exif_output.startswith(self._("exif_err_prefix")) or
                            exif_output.startswith(self._("exif_err_run").split("{")[0]))
                if not is_error:
                    self.tree.config(cursor="hand2")
                    return
        
        if col_id == '#10':
            data_item = self.all_scan_data.get(path_str)
            if data_item and data_item.get("indicator_keys"):
                self.tree.config(cursor="hand2")
                return

        self.tree.config(cursor="")

    def show_context_menu(self, event):
        item_id = self.tree.identify_row(event.y)
        if not item_id:
            return
        
        self.tree.selection_set(item_id)
        values = self.tree.item(item_id, "values")
        path_str = values[4] if values else None
        file_data = self.all_scan_data.get(path_str)

        context_menu = tk.Menu(self.root, tearoff=0)
        
        context_menu.add_command(label="Inspector...", command=self.show_inspector_popup)
        context_menu.add_command(label=self._("menu_add_note"), command=self._show_note_popup)
        context_menu.add_separator()
        
        text_diff_available = file_data and file_data.get("indicator_keys", {}).get("TouchUp_TextEdit", {}).get("text_diff")
        if text_diff_available:
            context_menu.add_command(label="View Text Diff", command=lambda: self.show_text_diff_popup(item_id))
        
        is_revision = file_data and file_data.get('is_revision')
        if is_revision:
            context_menu.add_command(label=self._("visual_diff"), command=lambda: self.show_visual_diff_popup(item_id))

        related_files = file_data and file_data.get("indicator_keys", {}).get("RelatedFiles", {}).get("files", [])
        if related_files:
            related_menu = tk.Menu(context_menu, tearoff=0)
            for rel_file in related_files:
                rel_name = rel_file.get("name", "Unknown")
                rel_path = rel_file.get("path", "")
                rel_type = rel_file.get("type", "related")
                prefix = "← " if rel_type == "derived_from" else "→ " if rel_type == "parent_of" else "↔ "
                related_menu.add_command(
                    label=f"{prefix}{rel_name}",
                    command=lambda p=rel_path: self._navigate_to_file(p)
                )
            context_menu.add_cascade(label=f"🔗 Related Files ({len(related_files)})", menu=related_menu)
            
        context_menu.add_separator()
        context_menu.add_command(label="Open File Location", command=lambda: self.open_file_location(item_id))
        
        context_menu.tk_popup(event.x_root, event.y_root)  

    def _navigate_to_file(self, path_str):
        for item_id in self.tree.get_children():
            values = self.tree.item(item_id, "values")
            if len(values) > 4 and values[4] == path_str:
                self.tree.selection_set(item_id)
                self.tree.see(item_id)
                self.tree.focus(item_id)
                self.on_select_item(None)
                return
        messagebox.showinfo(self._("not_found_title"), self._("related_file_not_found"))

    def open_file_location(self, item_id):
        values = self.tree.item(item_id, "values")
        if values:
            path_str = values[4]
            resolved_path = self._resolve_case_path(path_str)
            if resolved_path and resolved_path.exists():
                webbrowser.open(os.path.dirname(resolved_path))
            else:
                messagebox.showwarning(self._("file_not_found_title"), self._("file_at_path_not_found").format(path=resolved_path))       

    def _make_text_copyable(self, text_widget):
        context_menu = tk.Menu(text_widget, tearoff=0)
        
        def copy_selection(event=None):
            try:
                selected_text = text_widget.get(tk.SEL_FIRST, tk.SEL_LAST)
                self.root.clipboard_clear()
                self.root.clipboard_append(selected_text)
            except tk.TclError:
                pass
            return "break"

        context_menu.add_command(label=self._("copy"), command=copy_selection)
        
        def show_context_menu(event):
            if text_widget.tag_ranges(tk.SEL):
                context_menu.tk_popup(event.x_root, event.y_root)

        text_widget.config(state="normal") 
        text_widget.bind("<Key>", lambda e: "break") 
        text_widget.bind("<Button-3>", show_context_menu) 
        text_widget.bind("<Control-c>", copy_selection) 
        text_widget.bind("<Command-c>", copy_selection) 

    def choose_folder(self):
        folder_path = filedialog.askdirectory(title=self._("choose_folder_title"))
        if folder_path:
            self.start_scan_thread(Path(folder_path))

    def start_scan_thread(self, folder_path):
        logging.info(f"Starting scan of folder: {folder_path}")
        
        self._reset_state()
        self.last_scan_folder = folder_path
        self.case_root_path = folder_path 
        
        self.scan_button.configure(state="disabled")
        if not self.is_reader_mode and getattr(sys, 'frozen', False):
            self.file_menu.entryconfig(self._("menu_export_reader"), state="disabled")

        self.status_var.set(self._("preparing_analysis"))
        self.progressbar.set(0)
        self.progressbar.grid(row=2, column=0, columnspan=2, sticky="ew")

        self.copy_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='CopyWorker')

        scan_thread = threading.Thread(target=self._scan_worker_parallel, args=(folder_path, self.scan_queue))
        scan_thread.daemon = True
        scan_thread.start()

        self._process_queue()

    def _process_single_file(self, fp):
        try:
            file_size = fp.stat().st_size
            if file_size > PDFReconConfig.MAX_FILE_SIZE:
                raise PDFTooLargeError(f"File size {file_size / (1024**2):.1f}MB exceeds limit")
            
            raw = fp.read_bytes()
            doc = self._safe_pdf_open(fp, raw_bytes=raw)
            txt = self.extract_text(raw)
            
            exif = self.exiftool_output(fp, detailed=True)
            parsed_exif = self._parse_exif_data(exif)
            
            document_ids = self._extract_all_document_ids(txt, exif)
            
            from .scanner import detect_indicators as scanner_detect_indicators
            indicator_keys = scanner_detect_indicators(fp, txt, doc, exif_output=exif, app_instance=self)
            
            self._add_layer_indicators(raw, fp, indicator_keys)
            
            import hashlib
            md5_hash = hashlib.md5(raw, usedforsecurity=False).hexdigest()
            
            original_timeline = self.generate_comprehensive_timeline(fp, txt, exif, parsed_exif_data=parsed_exif)
            revisions = self.extract_revisions(raw, fp)
            doc.close()
            
            final_indicator_keys = indicator_keys.copy()
            if revisions:
                final_indicator_keys['HasRevisions'] = {'count': len(revisions)}
            
            results = []
            original_row_data = {
                "path": fp,
                "indicator_keys": final_indicator_keys,
                "md5": md5_hash,
                "exif": exif,
                "is_revision": False,
                "timeline": original_timeline,
                "status": "success",
                "document_ids": document_ids
            }
            results.append(original_row_data)
            
            for rev_path, basefile, rev_raw in revisions:
                try:
                    rev_md5 = hashlib.md5(rev_raw, usedforsecurity=False).hexdigest()
                    rev_exif = self.exiftool_output(rev_path, detailed=True)
                    rev_parsed_exif = self._parse_exif_data(rev_exif)
                    
                    if PDFReconConfig.EXPORT_INVALID_XREF and "Warning" in rev_exif and "Invalid xref table" in rev_exif:
                        logging.info(f"Submitting invalid XREF revision for {rev_path.name} to be copied and SKIPPING from results.")
                        invalid_xref_dir = self.last_scan_folder / "Invalid XREF"
                        invalid_xref_dir.mkdir(exist_ok=True)
                        dest_path = invalid_xref_dir / rev_path.name
                        if self.copy_executor:
                            self.copy_executor.submit(self._perform_copy, rev_raw, dest_path)
                        continue 

                    rev_txt = self.extract_text(rev_raw)
                    revision_timeline = self.generate_comprehensive_timeline(rev_path, rev_txt, rev_exif, parsed_exif_data=rev_parsed_exif)
                    
                    is_identical = False
                    try:
                        import fitz
                        from PIL import Image, ImageChops
                        with fitz.open(fp) as doc_orig, fitz.open(rev_path) as doc_rev:
                            pages_to_compare = min(doc_orig.page_count, doc_rev.page_count, PDFReconConfig.VISUAL_DIFF_PAGE_LIMIT)
                            if pages_to_compare > 0:
                                is_identical = True
                                for i in range(pages_to_compare):
                                    page_orig, page_rev = doc_orig.load_page(i), doc_rev.load_page(i)
                                    if page_orig.rect != page_rev.rect: 
                                        is_identical = False
                                        break
                                    pix_orig, pix_rev = page_orig.get_pixmap(dpi=96), page_rev.get_pixmap(dpi=96)
                                    img_orig = Image.frombytes("RGB", [pix_orig.width, pix_orig.height], pix_orig.samples)
                                    img_rev = Image.frombytes("RGB", [pix_rev.width, pix_rev.height], pix_rev.samples)
                                    if img_orig.size != img_rev.size:
                                        is_identical = False
                                        break
                                    if ImageChops.difference(img_orig, img_rev).getbbox() is not None: 
                                        is_identical = False
                                        break
                    except Exception as ve:
                        logging.warning(f"Could not visually compare revision {rev_path.name} to {fp.name}: {ve}")
                        is_identical = False
                    
                    if is_identical:
                        logging.info(f"Revision {rev_path.name} is visually identical to its parent {fp.name}")
                    
                    indicator_keys = {"Revision": {}}
                    if is_identical:
                        indicator_keys["VisuallyIdentical"] = {}
                    
                    revision_row_data = {
                        "path": rev_path,
                        "indicator_keys": indicator_keys,
                        "md5": rev_md5,
                        "exif": rev_exif,
                        "is_revision": True,
                        "timeline": revision_timeline,
                        "original_path": fp,
                        "is_identical": is_identical,
                        "status": "success"
                    }
                    results.append(revision_row_data)
                except Exception as e:
                    logging.warning(f"Error processing revision {rev_path.name}: {e}")
            
            return results
            
        except PDFTooLargeError as e:
            logging.warning(f"Skipping large file {fp.name}: {e}")
            return [{"path": fp, "status": "error", "error_type": "file_too_large", "error_message": str(e)}]
        except PDFEncryptedError as e:
            logging.warning(f"Skipping encrypted file {fp.name}: {e}")
            return [{"path": fp, "status": "error", "error_type": "file_encrypted", "error_message": str(e)}]
        except PDFCorruptionError as e:
            logging.warning(f"Skipping corrupt file {fp.name}: {e}")
            return [{"path": fp, "status": "error", "error_type": "file_corrupt", "error_message": str(e)}]
        except Exception as e:
            logging.exception(f"Unexpected error processing file {fp.name}")
            return [{"path": fp, "status": "error", "error_type": "processing_error", "error_message": str(e)}]

    def _scan_worker_parallel(self, folder, q):
        try:
            q.put(("scan_status", self._("preparing_analysis")))

            pdf_files = list(self._find_pdf_files_generator(folder))
            if not pdf_files:
                q.put(("finished", None))
                return

            q.put(("progress_mode_determinate", len(pdf_files)))
            files_processed = 0

            cfg = build_scan_config()
            fp_strings = [str(fp) for fp in pdf_files]

            with ProcessPoolExecutor(
                max_workers=PDFReconConfig.MAX_WORKER_THREADS,
                initializer=_worker_init,
                initargs=(cfg,),
            ) as executor:
                future_to_path = {
                    executor.submit(process_single_file_worker, fp_s, cfg): Path(fp_s)
                    for fp_s in fp_strings
                }

                for future in as_completed(future_to_path):
                    path = future_to_path[future]
                    files_processed += 1

                    try:
                        results = future.result()
                        for result_data in results:
                            if "path" in result_data and isinstance(result_data["path"], str):
                                result_data["path"] = Path(result_data["path"])
                            if "original_path" in result_data and isinstance(result_data["original_path"], str):
                                result_data["original_path"] = Path(result_data["original_path"])
                            q.put(("file_row", result_data))
                    except Exception as e:
                        logging.error(f"Unexpected error from process pool for file {path.name}: {e}")
                        q.put(("file_row", {"path": path, "status": "error", "error_type": "unknown_error", "error_message": str(e)}))

                    elapsed_time = time.time() - self.scan_start_time
                    fps = files_processed / elapsed_time if elapsed_time > 0 else 0
                    eta_seconds = (len(pdf_files) - files_processed) / fps if fps > 0 else 0
                    q.put(("detailed_progress", {"file": path.name, "fps": fps, "eta": time.strftime('%M:%S', time.gmtime(eta_seconds))}))

        except Exception as e:
            logging.error(f"Error in scan worker: {e}")
            q.put(("error", f"A critical error occurred: {e}"))
        finally:
            q.put(("finished", None))

    def _reset_state(self):
        self.tree.delete(*self.tree.get_children())
        self.report_data.clear()
        self.all_scan_data.clear()
        self.exif_outputs.clear()
        self.timeline_data.clear()
        self.path_to_id.clear()
        self.evidence_hashes.clear()
        self.revision_counter = 0
        import queue
        self.scan_queue = queue.Queue()
        self.scan_start_time = time.time()
        self.filter_var.set("")
        self.last_scan_folder = None
        self.current_case_filepath = None
        self.case_is_dirty = False
        self.dirty_notes.clear()
        self.detail_text.delete("1.0", "end")

    def _open_case(self, filepath=None):
        if not filepath:
            if self.all_scan_data:
                if not messagebox.askokcancel(self._("case_open_warning_title"), self._("case_open_warning_msg")):
                    return
            
            filepath = filedialog.askopenfilename(
                title="Open PDFRecon Case",
                filetypes=[("PDFRecon Case Files", "*.prc"), ("All files", "*.*")]
            )
        
        if not filepath:
            return

        try:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    case_data = json.load(f, object_hook=case_decoder)
            except (UnicodeDecodeError, json.JSONDecodeError):
                if not messagebox.askyesno(
                    self._("case_legacy_warning_title"),
                    self._("case_legacy_warning_msg"),
                    icon='warning'
                ):
                    return

                with open(filepath, 'rb') as f:
                    case_data = pickle.load(f)
                logging.warning(f"Loaded legacy pickle case file: {filepath}")

            self._reset_state()
            self.current_case_filepath = filepath 
            self.case_is_dirty = False
            self._update_title() 
            self.case_root_path = Path(filepath).parent 
            
            loaded_data = case_data.get('all_scan_data', [])
            if isinstance(loaded_data, list):
                self.all_scan_data = {str(item.get('path')): item for item in loaded_data}
            else:
                self.all_scan_data = loaded_data

            self.file_annotations = case_data.get('file_annotations', {})
            self.exif_outputs = case_data.get('exif_outputs', {})
            self.dirty_notes.clear()
            self.timeline_data = case_data.get('timeline_data', {})
            self.path_to_id = case_data.get('path_to_id', {})
            self.evidence_hashes = case_data.get('evidence_hashes', {})
            self.revision_counter = case_data.get('revision_counter', 0)
            self.last_scan_folder = case_data.get('scan_folder', None)
            
            self._apply_filter()
            self._update_summary_status()
            self.export_button.configure(state="normal")
            
            if self.evidence_hashes:
                self.file_menu.entryconfig(self._("menu_verify_integrity"), state="normal")

            if not self.is_reader_mode:
                self.file_menu.entryconfig(self._("menu_save_case"), state="normal")
                if getattr(sys, 'frozen', False):
                    self.file_menu.entryconfig(self._("menu_export_reader"), state="normal")

            logging.info(f"Successfully loaded case file: {filepath}")

        except Exception as e:
            logging.error(f"Failed to open case file '{filepath}': {e}")
            messagebox.showerror(self._("case_open_error_title"), self._("case_open_error_msg").format(e=e))

    def _verify_integrity(self):
        if not self.evidence_hashes:
            messagebox.showinfo(self._("verify_title"), self._("verify_no_hashes"))
            return

        self.status_var.set(self._("verify_running"))
        self.root.update_idletasks()

        mismatched_files = []
        missing_files = []
        
        total_files = len(self.evidence_hashes)
        verified_count = 0

        for path_str, original_hash in self.evidence_hashes.items():
            full_path = self._resolve_case_path(path_str)
            if not full_path or not full_path.exists():
                missing_files.append(str(path_str))
                continue
            
            current_hash = self._hash_file(full_path)
            if current_hash != original_hash:
                mismatched_files.append(str(path_str))
            
            verified_count += 1
            # Chain of custody: record verify result
            try:
                custody_log = get_custody_log_path(
                    Path(self.case_root_path) if self.case_root_path else Path("."),
                    getattr(self, "current_case_filepath", None),
                )
                log_verify(
                    custody_log,
                    path_str,
                    original_hash,
                    current_hash or "",
                    current_hash == original_hash if current_hash else False,
                    case_path=self.current_case_filepath,
                )
            except Exception as e:
                logging.debug("Custody log verify: %s", e)

        self._update_summary_status()

        if not mismatched_files and not missing_files:
            logging.info(f"Integrity check result: Success. All {verified_count}/{total_files} files are valid.")
            messagebox.showinfo(self._("verify_fail_title"), self._("verify_success"))
        else:
            log_summary = (f"Integrity check result: FAILURE. "
                           f"Verified: {verified_count}/{total_files}, "
                           f"Mismatched: {len(mismatched_files)}, "
                           f"Missing: {len(missing_files)}")
            logging.warning(log_summary)

            report_lines = []
            report_popup = Toplevel(self.root)
            report_popup.title(self._("verify_fail_title"))
            
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            w = max(700, int(sw * 0.5))
            h = max(450, int(sh * 0.6))
            x, y = (sw - w) // 2, (sh - h) // 2
            report_popup.geometry(f"{w}x{h}+{x}+{y}")
            
            text_frame = ttk.Frame(report_popup, padding=10)
            text_frame.pack(fill="both", expand=True)
            text_widget = tk.Text(text_frame, wrap="word", font=("Courier New", 9))
            text_widget.pack(fill="both", expand=True)

            def add_line(text):
                report_lines.append(text)
                text_widget.insert(tk.END, text + "\n")

            add_line(f"{self._('verify_report_header')}")
            add_line("-----------------------------")
            add_line(f"{self._('verify_report_verified')}: {verified_count}/{total_files}")
            add_line(f"{self._('verify_report_mismatched')}: {len(mismatched_files)}")
            add_line(f"{self._('verify_report_missing')}: {len(missing_files)}\n")

            if mismatched_files:
                add_line(f"{self._('verify_report_modified_header')}")
                logging.warning("Mismatched files:")
                for f in mismatched_files:
                    add_line(f"- {f}")
                    logging.warning(f"- {f}")
                add_line("")
            
            if missing_files:
                add_line(f"{self._('verify_report_missing_header')}")
                logging.warning("Missing files:")
                for f in missing_files:
                    add_line(f"- {f}")
                    logging.warning(f"- {f}")

            text_widget.config(state="disabled")
            messagebox.showwarning(self._("verify_fail_title"), self._("verify_fail_msg"), parent=report_popup)

    def show_log_file(self):
        if self.log_file_path.exists():
            webbrowser.open(self.log_file_path.as_uri())
        else:
            messagebox.showinfo(self._("log_not_found_title"), self._("log_not_found_message"), parent=self.root)

    def show_audit_log(self):
        """Show the chain-of-custody audit log in a window with tamper verification."""
        root = Path(self.case_root_path) if self.case_root_path else Path(self.last_scan_folder or ".")
        case_path = None
        if getattr(self, "current_case_filepath", None):
            case_path = Path(self.current_case_filepath) if isinstance(self.current_case_filepath, str) else self.current_case_filepath
        log_path = get_custody_log_path(root, case_path)
        entries, valid, bad_line, message = read_and_verify_custody_log(log_path)
        popup = tk.Toplevel(self.root)
        popup.title("Audit log (chain of custody)")
        popup.geometry("720x520")
        popup.transient(self.root)
        main = ttk.Frame(popup, padding=10)
        main.pack(fill="both", expand=True)
        # Integrity status
        status_frame = ttk.LabelFrame(main, text="Integrity", padding=8)
        status_frame.pack(fill="x", pady=(0, 8))
        if valid:
            status_label = ttk.Label(status_frame, text="Integrity verified. Hash chain intact.", foreground="green")
        else:
            status_label = ttk.Label(status_frame, text=message or "Tampering detected.", foreground="red")
        status_label.pack(anchor="w")
        ttk.Label(status_frame, text=f"Log file: {log_path}", font=("Segoe UI", 8), foreground="gray").pack(anchor="w")
        # Log content
        text_frame = ttk.Frame(main)
        text_frame.pack(fill="both", expand=True)
        log_text = tk.Text(text_frame, wrap="word", font=("Consolas", 9))
        scroll = ttk.Scrollbar(text_frame, orient="vertical", command=log_text.yview)
        log_text.config(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        log_text.pack(side="left", fill="both", expand=True)
        if entries:
            log_text.insert("1.0", format_custody_log_display(entries))
        else:
            log_text.insert("1.0", message + "\n\nNo entries to display.")
        log_text.config(state="disabled")
        ttk.Button(main, text="Close", command=popup.destroy).pack(pady=(8, 0))

    def _sort_column(self, col, reverse):
        is_id_column = col == self.columns[0]
        def get_key(item):
            val = self.tree.set(item, col)
            return int(val) if is_id_column and val else val

        data_list = [(get_key(k), k) for k in self.tree.get_children("")]
        data_list.sort(reverse=reverse)
        for index, (val, k) in enumerate(data_list):
            self.tree.move(k, "", index)
        
        self.tree.heading(col, command=lambda: self._sort_column(col, not reverse))

    def _save_case(self):
        if not self.all_scan_data:
            messagebox.showwarning(self._("case_nothing_to_save_title"), self._("case_nothing_to_save_msg"))
            return
            
        filepath = filedialog.asksaveasfilename(
            title="Save PDFRecon Case As",
            defaultextension=".prc",
            filetypes=[("PDFRecon Case Files", "*.prc"), ("All files", "*.*")]
        )
        if not filepath:
            return
        
        try:
            self._write_case_to_file(filepath)
            logging.info(f"Successfully saved case to: {filepath}")

            self.current_case_filepath = filepath
            self.case_is_dirty = False
            self.dirty_notes.clear()
            self._apply_filter()

        except Exception as e:
            logging.error(f"Failed to save case file '{filepath}': {e}")
            messagebox.showerror(self._("case_save_error_title"), self._("case_save_error_msg").format(e=e))

    def _find_pdf_files_generator(self, folder):
        for base, _, files in os.walk(folder):
            for fn in files:
                if fn.lower().endswith(".pdf"):
                    yield Path(base) / fn

    def _check_for_updates(self):
        threading.Thread(target=self._perform_update_check, daemon=True).start()

    def _perform_update_check(self):
        GITHUB_REPO = "Rasmus-Riis/PDFRecon"
        
        api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        
        try:
            response = requests.get(api_url, timeout=10)
            response.raise_for_status() 
            
            latest_release = response.json()
            latest_version_str = latest_release.get("tag_name", "").lstrip('v')
            
            if not latest_version_str:
                self.root.after(0, lambda: messagebox.showwarning(self._("update_error_title"), self._("update_parse_error_msg")))
                return

            current_version_tuple = tuple(map(int, self.app_version.split('.')))
            latest_version_tuple = tuple(map(int, latest_version_str.split('.')))

            if latest_version_tuple > current_version_tuple:
                release_url = latest_release.get("html_url")
                message = self._("update_available_msg").format(
                    new_version=latest_version_str,
                    current_version=self.app_version
                )
                if messagebox.askyesno(self._("update_available_title"), message):
                    webbrowser.open(release_url)
            else:
                self.root.after(0, lambda: messagebox.showinfo(self._("update_no_new_title"), self._("update_no_new_msg")))

        except requests.exceptions.RequestException as e:
            logging.error(f"Update check failed: {e}")
            self.root.after(0, lambda: messagebox.showerror(self._("update_error_title"), self._("update_net_error_msg")))

    def _process_queue(self):
        try:
            import queue
            while True:
                msg_type, data = self.scan_queue.get_nowait()
                
                if msg_type == "progress_mode_determinate":
                    self._progress_max = data if data > 0 else 1
                    self._progress_current = 0
                    self.progressbar.set(0)
                elif msg_type == "detailed_progress":
                    self._progress_current += 1
                    self.progressbar.set(self._progress_current / self._progress_max if self._progress_max > 0 else 0)
                    self.status_var.set(self._("scan_progress_eta").format(**data))
                elif msg_type == "scan_status": 
                    self.status_var.set(data)
                elif msg_type == "file_row":
                    path_key = str(data["path"])
                    if path_key in self.all_scan_data:
                        logging.warning(f"Duplicate path key detected: {path_key}")
                    self.all_scan_data[path_key] = data
                    if not data.get("is_revision"):
                        self.exif_outputs[path_key] = data.get("exif")
                        self.timeline_data[path_key] = data.get("timeline")
                    else: 
                        self.exif_outputs[path_key] = data.get("exif")
                        self.timeline_data[path_key] = data.get("timeline")
                        self.revision_counter += 1

                elif msg_type == "error": 
                    logging.warning(data)
                    messagebox.showerror("Critical Error", data)
                elif msg_type == "finished":
                    self._finalize_scan()
                    return 
        except queue.Empty:
            pass
        except Exception:
            pass
        self.root.after(100, self._process_queue)

    def _finalize_scan(self):
        self._apply_filter()
        
        self.scan_button.configure(state="normal")

        self.evidence_hashes = self._calculate_hashes(self.all_scan_data.values())
        if self.evidence_hashes:
             self.file_menu.entryconfig(self._("menu_verify_integrity"), state="normal")
        # Chain of custody: log ingestion for each hashed file
        try:
            root = Path(self.last_scan_folder) if self.last_scan_folder else Path(".")
            custody_log = get_custody_log_path(root, getattr(self, "current_case_filepath", None))
            for path_str, file_hash in self.evidence_hashes.items():
                resolved = self._resolve_case_path(path_str)
                if resolved and resolved.exists():
                    log_ingestion(custody_log, resolved, file_hash, case_path=self.current_case_filepath)
        except Exception as e:
            logging.debug("Custody log write at scan complete: %s", e)

        if not self.is_reader_mode:
            self.file_menu.entryconfig(self._("menu_save_case"), state="normal")
            if getattr(sys, 'frozen', False):
                 self.file_menu.entryconfig(self._("menu_export_reader"), state="normal")
        
        self.progressbar.set(1.0)
        self.root.after(500, lambda: self.progressbar.grid_forget())
        
        self._finalize_copy_operations()

    def _apply_filter(self, *args):
        search_term = self.filter_var.get().lower()
        
        items_to_show = []
        scan_data_iterable = self.all_scan_data.values()

        if not search_term:
            items_to_show = list(scan_data_iterable)
        else:
            for data in scan_data_iterable:
                searchable_items = []

                path_str = str(data.get('path', ''))
                searchable_items.append(path_str)
                searchable_items.append(data.get('md5', ''))

                if not data.get('is_revision'):
                    try:
                        resolved_path = self._resolve_case_path(data['path'])
                        if resolved_path and resolved_path.exists():
                            stat = resolved_path.stat()
                            searchable_items.append(datetime.fromtimestamp(stat.st_ctime).strftime("%d-%m-%Y %H:%M:%S"))
                            searchable_items.append(datetime.fromtimestamp(stat.st_mtime).strftime("%d-%m-%Y %H:%M:%S"))
                    except (FileNotFoundError, KeyError, AttributeError):
                        pass 

                is_rev = data.get("is_revision", False)
                if data.get("status") == "error":
                    error_type_key = data.get("error_type", "unknown_error")
                    searchable_items.append(self._(error_type_key))
                elif is_rev:
                    if data.get("is_identical"):
                         searchable_items.append(self._("status_identical"))
                    searchable_items.append(self._("revision_of").split("{")[0])
                else: 
                    flag = self.get_flag(data.get("indicator_keys", {}), False)
                    searchable_items.append(flag)

                exif_output = self.exif_outputs.get(path_str, '')
                if exif_output:
                    searchable_items.append(exif_output)

                note = self.file_annotations.get(path_str, '')
                if note:
                    searchable_items.append(note)

                indicator_dict = data.get('indicator_keys', {})
                if indicator_dict:
                    details_list = []
                    for k, v in indicator_dict.items():
                        fmt_detail = self._format_indicator_details(k, v)
                        if fmt_detail:
                            details_list.append(fmt_detail)
                    searchable_items.extend(details_list)
                elif not is_rev:
                    searchable_items.append(self._("status_no"))
                
                full_searchable_text = " ".join(searchable_items).lower()
                if search_term in full_searchable_text:
                    items_to_show.append(data)
        
        self._populate_tree_from_data(items_to_show)  

    def _populate_tree_from_data(self, data_list):
        self.tree.delete(*self.tree.get_children())
        self.report_data.clear()

        parent_display_ids = {}
        parent_counter = 0
        for d in self.all_scan_data.values(): 
            if not d.get("is_revision") and d.get("status") != "error":
                parent_counter += 1
                parent_display_ids[str(d["path"])] = parent_counter

        for i, d in enumerate(data_list):
            path_obj = Path(d["path"])
            path_str = str(d["path"])
            is_rev = d.get("is_revision", False)
            indicator_keys = d.get("indicator_keys", {})

            note_indicator = ""
            if path_str in self.dirty_notes:
                note_indicator = "📝*"
            elif path_str in self.file_annotations:
                note_indicator = "📝"

            exif_display = "✔" if d.get("exif") else ""

            if is_rev:
                parent_display_id = parent_display_ids.get(str(d.get("original_path")))
                display_id = parent_display_id if parent_display_id else i + 1
                flag = self._("status_identical").format(pages=PDFReconConfig.VISUAL_DIFF_PAGE_LIMIT) if d.get("is_identical") else self.get_flag({}, True, parent_display_id)
                tag = "gray_row" if d.get("is_identical") else "blue_row"
                revisions_display, created_time, modified_time, indicators_display = "", "", "", ""
            else: 
                display_id = parent_display_ids.get(path_str, i + 1)
                flag = self.get_flag(indicator_keys, False)
                tag = self.tree_tags.get(flag, "")
                if "RelatedFiles" in indicator_keys:
                    tag = "purple_row"
                revisions_count = indicator_keys.get("HasRevisions", {}).get("count", 0)
                revisions_display = str(revisions_count) if revisions_count > 0 else ""
                indicators_display = "✔" if indicator_keys else ""
                try:
                    full_path = self._resolve_case_path(path_obj)
                    st = full_path.stat()
                    created_time = datetime.fromtimestamp(st.st_ctime).strftime("%d-%m-%Y %H:%M:%S")
                    modified_time = datetime.fromtimestamp(st.st_mtime).strftime("%d-%m-%Y %H:%M:%S")
                except Exception:
                    created_time, modified_time = "", ""

            row_values = [
                display_id, path_obj.name, flag, revisions_display, path_str,
                d.get("md5", ""), created_time, modified_time,
                exif_display, indicators_display, note_indicator
            ]
            
            self.tree.insert("", "end", values=row_values, tags=(tag,))
            self.report_data.append(row_values)

    def on_select_item(self, event):
        selected_items = self.tree.selection()
        if not selected_items:
            self.detail_text.delete("1.0", "end")
            return
        
        item_id = selected_items[0]
        values = self.tree.item(item_id, "values")
        path_str = values[4]
        
        self.detail_text.delete("1.0", "end")
        
        original_data = self.all_scan_data.get(path_str)

        for i, val in enumerate(values):
            col_name = self.tree.heading(self.columns[i], "text")
            self.detail_text.insert("end", f"{col_name}: ", ("bold",))
            
            if col_name == self._("col_path"):
                self.detail_text.insert("end", val + "\n", ("link",))
            elif col_name == self._("col_indicators") and original_data and original_data.get("indicator_keys"):
                indicator_details = []
                for k, v in original_data["indicator_keys"].items():
                    fmt = self._format_indicator_details(k, v)
                    if fmt:
                        indicator_details.append(fmt)
                
                if indicator_details:
                    full_indicators_str = "\n  • " + "\n  • ".join(indicator_details)
                    self.detail_text.insert("end", full_indicators_str + "\n")
            else:
                self.detail_text.insert("end", val + "\n")
                
        note = self.file_annotations.get(path_str)
        if note:
            self.detail_text.insert("end", "\n" + "-"*40 + "\n")
            self.detail_text.insert("end", f"{self._('note_label')}\n", ("bold",))
            self.detail_text.insert("end", note)

        if self.inspector_window and self.inspector_window.winfo_viewable():
            self.show_inspector_popup()            

    def _open_path_from_detail(self, event):
        index = self.detail_text.index(f"@{event.x},{event.y}")
        tag_indices = self.detail_text.tag_ranges("link")
        for start, end in zip(tag_indices[0::2], tag_indices[1::2]):
            if self.detail_text.compare(start, "<=", index) and self.detail_text.compare(index, "<", end):
                path_str = self.detail_text.get(start, end).strip()
                try:
                    webbrowser.open(os.path.dirname(path_str))
                except Exception as e:
                    messagebox.showerror(self._("open_folder_error_title"), self._("could_not_open_folder").format(e=e))
                break

    def _finalize_copy_operations(self):
        if self.copy_executor:
            self.copy_executor.shutdown(wait=True)
            self.copy_executor = None
            logging.info("All background copy operations have finished.")
            self.root.after(0, self._update_summary_status)