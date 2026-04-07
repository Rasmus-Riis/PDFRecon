import tkinter as tk
from tkinter import ttk, Toplevel, messagebox
import customtkinter as ctk
import webbrowser
import logging
import re
import sys
import os
from pathlib import Path
from datetime import datetime

from .utils import _import_with_fallback
from .config import PDFReconConfig, UI_DIMENSIONS, UI_COLORS

PIL = _import_with_fallback('PIL', 'Image', 'Pillow')
from PIL import Image, ImageTk, ImageDraw, ImageChops, ImageOps, ImageFont

fitz = _import_with_fallback('fitz', 'fitz', 'PyMuPDF')
import typing
from typing import Any, Callable, Dict, Set

class PopupsMixin:
    if typing.TYPE_CHECKING:
        root: Any
        tree: Any
        file_annotations: Dict[str, str]
        dirty_notes: Set[str]
        case_is_dirty: bool
        is_reader_mode: bool
        file_menu: Any
        inspector_doc: Any
        all_scan_data: Dict[str, Any]
        current_pdf_page: int
        pdf_zoom: float
        inspector_title: Any
        advanced_text: Any
        hex_text: Any
        xmp_text: Any
        pdf_canvas: Any
        pdf_frame: Any
        info_frame: Any
        text_frame: Any
        hex_frame: Any
        xmp_frame: Any
        structure_frame: Any
        layer_frame: Any
        images_frame: Any
        timeline_frame: Any
        fonts_frame: Any
        inspector_popup: Any
        inspector_window: Any
        inspector_notebook: Any
        inspector_visual_diff_btn_frame: Any
        inspector_visual_diff_btn: Any
        inspector_touchup_btn_frame: Any
        inspector_touchup_btn: Any
        inspector_indicators_text: Any
        inspector_exif_text: Any
        inspector_timeline_text: Any
        inspector_pdf_update_job: Any
        columns: Any
        exif_outputs: Any
        _zoom_job: Any
        inspector_history_text: Any
        language: str
        timeline_data: Any
        _inspector_item_id: str
        
        _make_text_copyable: Callable[..., None]
        _jump_tree_down_5: Callable[..., None]
        _jump_tree_up_5: Callable[..., None]
        _format_indicator_details: Callable[..., str]
        _navigate_to_file: Callable[..., None]
        _resolve_case_path: Callable[..., str]
        _get_touchup_regions_for_page: Callable[..., Any]
        _format_timedelta: Callable[..., str]
        _extract_key_dates_from_timeline: Callable[..., Any]
        _apply_filter: Callable[[], None]
        on_select_item: Callable[[Any], None]
        _center_window: Callable[..., tuple]
        _: Callable[..., str]
        _safe_update_ui: Callable[[Callable], None]
        _schedule_worker: Callable[..., None]
        _schedule_main: Callable[..., None]
        
    def _show_note_popup(self):
        selected_items = self.tree.selection()
        if not selected_items:
            return
        
        item_id = selected_items[0]
        path_str = self.tree.item(item_id, "values")[4]
        file_name = self.tree.item(item_id, "values")[1]

        popup = Toplevel(self.root)
        popup.title(f"{self._('note_popup_title')}: {file_name}")

        w, h = self._center_window(popup, width_scale=0.3, height_scale=0.4)

        popup.transient(self.root)
        popup.grab_set()

        main_frame = ttk.Frame(popup, padding=10)
        main_frame.pack(fill="both", expand=True)
        
        note_text = tk.Text(main_frame, wrap="word", height=10)
        note_text.pack(fill="both", expand=True, pady=(0, 10))
        
        existing_note = self.file_annotations.get(path_str, "")
        if existing_note:
            note_text.insert("1.0", existing_note)

        def save_note():
            new_note = note_text.get("1.0", tk.END).strip()
            if new_note:
                self.file_annotations[path_str] = new_note
            elif path_str in self.file_annotations:
                del self.file_annotations[path_str]
            
            self.dirty_notes.add(path_str)
            self.case_is_dirty = True
            if self.is_reader_mode:
                self.file_menu.entryconfig(self._("menu_save_case_simple"), state="normal")
            
            self._apply_filter() 
            
            new_item_to_select = None
            for child_id in self.tree.get_children(""):
                if self.tree.item(child_id, "values")[4] == path_str:
                    new_item_to_select = child_id
                    break

            if new_item_to_select:
                self.tree.selection_set(new_item_to_select)
                self.tree.focus(new_item_to_select)
                self.on_select_item(None)

            popup.destroy()

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill="x")
        
        save_button = ttk.Button(button_frame, text=self._("settings_save"), command=save_note)
        save_button.pack(side="right", padx=5)
        
        cancel_button = ttk.Button(button_frame, text=self._("settings_cancel"), command=popup.destroy)
        cancel_button.pack(side="right")

    def show_inspector_popup(self, event=None):
        item_id = None
        if event: 
            if self.tree.identify_region(event.x, event.y) == "heading":
                return
            item_id = self.tree.identify_row(event.y)
        else: 
            selected_items = self.tree.selection()
            if selected_items:
                item_id = selected_items[0]

        if not item_id:
            return

        values = self.tree.item(item_id, "values")
        path_str = values[4] 
        file_name = values[1]
        resolved_path = self._resolve_case_path(path_str)
        file_data = self.all_scan_data.get(path_str)
        if not file_data:
            return

        if not self.inspector_window or not self.inspector_window.winfo_exists():
            self.inspector_window = Toplevel(self.root)
            self.inspector_window.title(self._("inspector_title"))
            
            self._center_window(self.inspector_window, width_scale=UI_DIMENSIONS['window_scale_width'], 
                              height_scale=UI_DIMENSIONS['window_scale_height'])

            notebook = ttk.Notebook(self.inspector_window)
            notebook.pack(pady=10, padx=10, fill="both", expand=True)
            self.inspector_notebook = notebook

            indicators_frame = ttk.Frame(notebook, padding="10")
            notebook.add(indicators_frame, text=self._("inspector_details_tab"))
            self.inspector_visual_diff_btn_frame = ttk.Frame(indicators_frame)
            self.inspector_visual_diff_btn = ctk.CTkButton(
                self.inspector_visual_diff_btn_frame,
                text=self._("visual_diff"),
                command=self._open_visual_diff_from_details,
                height=28,
                fg_color=UI_COLORS.get("accent_blue", "#1F6AA5"),
                text_color="white",
            )
            self.inspector_visual_diff_btn.pack(side="left", padx=(0, 8), pady=(0, 4))
            # Button for jumping to the PDF visual pane when TouchUp_TextEdit is present
            self.inspector_touchup_btn_frame = ttk.Frame(indicators_frame)
            self.inspector_touchup_btn = ctk.CTkButton(
                self.inspector_touchup_btn_frame,
                text=self._("enable_visual_pinpointing"),
                command=self._jump_to_touchup_visual_pane,
                height=26,
                fg_color=UI_COLORS.get("accent_green", "#2E7D32"),
                text_color="white",
            )
            self.inspector_touchup_btn.pack(side="left", padx=(0, 8), pady=(0, 4))
            self.inspector_indicators_text = tk.Text(indicators_frame, wrap="word", font=("Segoe UI", 9))
            self.inspector_indicators_text.pack(fill="both", expand=True)
            self.inspector_indicators_text.tag_configure("bold", font=("Segoe UI", 9, "bold"))
            self.inspector_indicators_text.tag_configure("related_link", foreground="#9999ff", underline=True)
            self.inspector_indicators_text.tag_configure("added", foreground="#22aa55", font=("Segoe UI", 9))
            self.inspector_indicators_text.tag_configure("removed", foreground="#cc4444", font=("Segoe UI", 9))
            self.inspector_indicators_text.tag_configure("diffhunk", foreground="#5599cc", font=("Segoe UI", 9, "italic"))
            self.inspector_indicators_text.tag_configure("not_found", foreground="#888888", font=("Segoe UI", 9, "italic"))
            self._make_text_copyable(self.inspector_indicators_text)

            exif_frame = ttk.Frame(notebook, padding="10")
            notebook.add(exif_frame, text=self._("col_exif"))
            exif_text_widget = tk.Text(exif_frame, wrap="word", font=("Consolas", 10))
            exif_vscroll = ttk.Scrollbar(exif_frame, orient="vertical", command=exif_text_widget.yview)
            exif_text_widget.config(yscrollcommand=exif_vscroll.set)
            exif_vscroll.pack(side="right", fill="y")
            exif_text_widget.pack(fill="both", expand=True)
            self.inspector_exif_text = exif_text_widget
            self._make_text_copyable(self.inspector_exif_text)

            timeline_frame = ttk.Frame(notebook, padding="10")
            notebook.add(timeline_frame, text=self._("inspector_timeline_tab"))
            timeline_text_widget = tk.Text(timeline_frame, wrap="word", font=("Courier New", 10))
            timeline_vscroll = ttk.Scrollbar(timeline_frame, orient="vertical", command=timeline_text_widget.yview)
            timeline_text_widget.config(yscrollcommand=timeline_vscroll.set)
            timeline_vscroll.pack(side="right", fill="y")
            timeline_text_widget.pack(fill="both", expand=True)
            self.inspector_timeline_text = timeline_text_widget
            self._make_text_copyable(self.inspector_timeline_text)

            # Configure tags for the combined history view (now in Details)
            self.inspector_indicators_text.tag_configure("header", font=("Segoe UI", 11, "bold"))
            self.inspector_indicators_text.tag_configure("version_header", font=("Segoe UI", 11, "bold"), foreground="#1F6AA5")
            self.inspector_indicators_text.tag_configure("label", font=("Segoe UI", 10, "bold"))
            self.inspector_indicators_text.tag_configure("value", font=("Segoe UI", 10))
            self.inspector_indicators_text.tag_configure("changed", font=("Segoe UI", 10, "bold"), foreground="#FF6600")
            self.inspector_indicators_text.tag_configure("unchanged", font=("Segoe UI", 10), foreground="#666666")
            self.inspector_indicators_text.tag_configure("separator", foreground="#444444")
            self.inspector_indicators_text.tag_configure("anomaly", foreground="red")
            self.inspector_indicators_text.tag_configure("indent", lmargin1=20, lmargin2=20)
            self.inspector_indicators_text.tag_configure("bullet", lmargin1=10, lmargin2=20)

            pdf_view_frame = ttk.Frame(notebook)
            notebook.add(pdf_view_frame, text=self._("inspector_pdf_viewer_tab"))
            self.inspector_pdf_frame = pdf_view_frame
            
            def on_inspector_close():
                if self.inspector_doc:
                    self.inspector_doc.close()
                    self.inspector_doc = None
                self.inspector_window.withdraw()

            def _inspector_nav_down(ev):
                self._jump_tree_down_5(ev)
                self.show_inspector_popup()
                return "break"

            def _inspector_nav_up(ev):
                self._jump_tree_up_5(ev)
                self.show_inspector_popup()
                return "break"

            self.inspector_window.bind("<Down>", _inspector_nav_down)
            self.inspector_window.bind("<Up>", _inspector_nav_up)
            
            self.inspector_window.protocol("WM_DELETE_WINDOW", on_inspector_close)

        self.inspector_window.title(f"{self._('inspector_title')}: {file_name}")

        self.inspector_indicators_text.config(state="normal")
        self.inspector_indicators_text.delete("1.0", tk.END)
        self._inspector_item_id = None
        self.inspector_visual_diff_btn_frame.pack_forget()
        self.inspector_touchup_btn_frame.pack_forget()

        # ── File metadata fields (all columns except indicators & note) ──
        indicator_col_name = self._("col_indicators")
        note_col_name = self._("col_note")
        for i, val in enumerate(values):
            col_name = self.tree.heading(self.columns[i], "text")
            if col_name in (indicator_col_name, note_col_name):
                continue  # handled separately below
            self.inspector_indicators_text.insert(tk.END, f"{col_name}: ", ("bold",))
            self.inspector_indicators_text.insert(tk.END, val + "\n")

        # ── Signs-of-alteration section ──
        if file_data and file_data.get("indicator_keys"):
            self.inspector_indicators_text.insert(tk.END, "\n")
            self.inspector_indicators_text.insert(
                tk.END,
                self._("signs_of_alteration_header") + ":\n",
                ("bold",)
            )
            self.inspector_indicators_text.insert(tk.END, "─" * 40 + "\n")

            for key, details in file_data["indicator_keys"].items():
                formatted = self._format_indicator_details(key, details)
                if not formatted:
                    continue
                # AssetRelationship belongs in the Historik & Relationer tab only
                if key == "AssetRelationship":
                    continue
                if key == "RelatedFiles":
                    continue  # Shown in History & Relations tab
                elif key == "ExtractedJavaScript":
                    scripts = details if isinstance(details, list) else details.get('scripts', [])
                    if scripts:
                        self.inspector_indicators_text.insert(
                            tk.END,
                            "\n• " + self._("js_indicator_label").format(count=len(scripts)) + "\n",
                            ("bold",)
                        )
                        for idx, s in enumerate(scripts, 1):
                            self.inspector_indicators_text.insert(
                                tk.END,
                                "  " + self._("js_script_label").format(num=idx, source=s.get('source', '?')) + "\n",
                                ("bold",)
                            )
                            self.inspector_indicators_text.insert(tk.END, (s.get('code') or '')[:8000])
                            if len(s.get('code') or '') > 8000:
                                self.inspector_indicators_text.insert(tk.END, "\n" + self._("diff_truncated"))
                            self.inspector_indicators_text.insert(tk.END, "\n")
                    else:
                        self.inspector_indicators_text.insert(tk.END, "\n• " + formatted + "\n")
                elif key == "TouchUp_TextEdit":
                    self._inspector_item_id = item_id
                    self.inspector_touchup_btn_frame.pack(fill="x", pady=(0, 4), before=self.inspector_indicators_text)
                    self.inspector_indicators_text.insert(tk.END, "\n• " + formatted + "\n")
                else:
                    # Each indicator on its own bullet line
                    for line in formatted.splitlines():
                        if line.strip():
                            indent = "  " if line.startswith(" ") else "• "
                            self.inspector_indicators_text.insert(tk.END, indent + line.lstrip() + "\n")

            # ── Revision diff section ──
            if file_data.get("revision_diff"):
                rd = file_data["revision_diff"]
                self._inspector_item_id = item_id
                self.inspector_visual_diff_btn_frame.pack(fill="x", pady=(0, 6), before=self.inspector_indicators_text)
                self.inspector_indicators_text.insert(tk.END, "\n" + "─" * 40 + "\n")
                self.inspector_indicators_text.insert(
                    tk.END,
                    self._("revision_comparison_title") + "\n",
                    ("bold",)
                )
                for line in (rd.get("unified_diff_lines") or [])[:150]:
                    # Style +/- diff lines
                    if line.startswith("+"):
                        self.inspector_indicators_text.insert(tk.END, line + "\n", ("added",))
                    elif line.startswith("-"):
                        self.inspector_indicators_text.insert(tk.END, line + "\n", ("removed",))
                    elif line.startswith("@@"):
                        self.inspector_indicators_text.insert(tk.END, line + "\n", ("diffhunk",))
                    else:
                        self.inspector_indicators_text.insert(tk.END, line + "\n")
                if len(rd.get("unified_diff_lines") or []) > 150:
                    self.inspector_indicators_text.insert(tk.END, self._("diff_truncated") + "\n")
                adds, dels = rd.get("additions", []), rd.get("deletions", [])
                if adds or dels:
                    self.inspector_indicators_text.insert(
                        tk.END,
                        "\n" + self._("diff_summary").format(adds=len(adds), dels=len(dels)) + "\n",
                        ("bold",)
                    )
            else:
                self.inspector_visual_diff_btn_frame.pack_forget()
        else:
            # No indicators — show the raw col value from the tree
            for i, val in enumerate(values):
                col_name = self.tree.heading(self.columns[i], "text")
                if col_name == indicator_col_name:
                    self.inspector_indicators_text.insert(tk.END, f"{col_name}: ", ("bold",))
                    self.inspector_indicators_text.insert(tk.END, val + "\n")

        # ── Note section ──
        note = self.file_annotations.get(path_str)
        if note:
            self.inspector_indicators_text.insert(tk.END, "\n" + "─"*40 + "\n")
            self.inspector_indicators_text.insert(tk.END, f"{self._('note_label')}\n", ("bold",))
            self.inspector_indicators_text.insert(tk.END, note)
        # ── History & Relations data (moved from separate tab) ──
        # 1. Asset Relationships (xmpMM)
        asset_rel = file_data.get("indicator_keys", {}).get("AssetRelationship")
        if asset_rel:
            self.inspector_indicators_text.insert(tk.END, "\n" + "═"*60 + "\n\n")
            self._populate_relationship_tab(asset_rel)
        
        # 1b. Related Files (derived_from / parent_of links)
        related_files = file_data.get("indicator_keys", {}).get("RelatedFiles")
        if related_files:
            self.inspector_indicators_text.insert(tk.END, "\n" + "═"*60 + "\n\n")
            self._insert_related_files_with_links(related_files)
        
        # 2. Version History (Physical Incremental Saves)
        self._populate_version_history(self.inspector_indicators_text, path_str, file_data)
        
        self.inspector_indicators_text.config(state="disabled")

        self.inspector_exif_text.config(state="normal")
        self.inspector_exif_text.delete("1.0", tk.END)
        self.inspector_exif_text.insert("1.0", self.exif_outputs.get(path_str, self._("no_exif_output_message")))
        self.inspector_exif_text.config(state="disabled")

        self.inspector_timeline_text.config(state="normal")
        self.inspector_timeline_text.delete("1.0", tk.END)
        self._populate_timeline_widget(self.inspector_timeline_text, path_str)
        self.inspector_timeline_text.config(state="disabled")

        if self.inspector_pdf_update_job:
            self.inspector_window.after_cancel(self.inspector_pdf_update_job)
            self.inspector_pdf_update_job = None

        for widget in self.inspector_pdf_frame.winfo_children():
            widget.destroy()
        
        if self.inspector_doc:
            self.inspector_doc.close()
        try:
            self.inspector_doc = fitz.open(resolved_path)
        except Exception:
            self.inspector_doc = None

        if self.inspector_doc:
            status_bar = ttk.Label(self.inspector_pdf_frame, text=f"File: {resolved_path}   |   Inspection Complete - Viewer Ready", relief="sunken", padding=(5, 2))
            status_bar.pack(side="bottom", fill="x")

            pdf_main_frame = ttk.Frame(self.inspector_pdf_frame, padding=10)
            pdf_main_frame.pack(side="top", fill="both", expand=True)
            
            pdf_main_frame.columnconfigure(0, weight=3)
            pdf_main_frame.columnconfigure(1, weight=1)
            pdf_main_frame.rowconfigure(1, weight=1) 
            
            touchup_info = file_data.get("indicator_keys", {}).get("TouchUp_TextEdit", {})
            has_touchup = bool(touchup_info)
            touchup_texts_by_page = {}
            
            if has_touchup:
                found_text = touchup_info.get("found_text", {})
                if isinstance(found_text, dict):
                    touchup_texts_by_page = found_text
                elif isinstance(found_text, list):
                    touchup_texts_by_page = {0: found_text}

            pdf_scroll_frame = ctk.CTkScrollableFrame(pdf_main_frame, fg_color="#1a1a1a") 
            pdf_scroll_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 10)) 
            
            pdf_image_label = ttk.Label(pdf_scroll_frame)
            pdf_image_label.pack(expand=True, fill="both")

            sidebar_frame = ttk.Frame(pdf_main_frame, padding=5)
            sidebar_frame.grid(row=1, column=1, sticky="nsew")
            
            nav_group = ttk.LabelFrame(sidebar_frame, text=self._("header_actions"), padding=10)
            nav_group.pack(fill="x", pady=(0, 10))
            
            page_label = ttk.Label(nav_group, text="", font=("Segoe UI", 10, "bold"))
            page_label.pack(pady=(0, 8))
            
            nav_btns = ttk.Frame(nav_group)
            nav_btns.pack(fill="x")
            _nav_fg = UI_COLORS.get("accent_blue", "#1F6AA5")
            prev_button = ctk.CTkButton(
                nav_btns, text=f"  ◀  {self._('diff_prev_page')}  ",
                height=32, fg_color=_nav_fg, text_color="white",
            )
            prev_button.pack(side="left", fill="x", expand=True, padx=(0, 4))
            next_button = ctk.CTkButton(
                nav_btns, text=f"  {self._('diff_next_page')}  ▶  ",
                height=32, fg_color=_nav_fg, text_color="white",
            )
            next_button.pack(side="left", fill="x", expand=True, padx=(4, 0))

            # If a TouchUp_TextEdit text diff is available, expose a "Show text diff" button here
            text_diff_available = file_data.get("indicator_keys", {}).get("TouchUp_TextEdit", {}).get("text_diff")
            if text_diff_available:
                show_diff_btn = ctk.CTkButton(
                    nav_group,
                    text="Show text diff",
                    height=26,
                    fg_color=UI_COLORS.get("accent_blue", "#1F6AA5"),
                    text_color="white",
                    command=lambda iid=item_id: self.show_text_diff_popup(iid),
                )
                show_diff_btn.pack(fill="x", pady=(8, 0))

            # If this row is a revision, expose a "Show diff" (visual) button in the PDF viewer pane
            if file_data.get("is_revision"):
                show_visual_btn = ctk.CTkButton(
                    nav_group,
                    text=self._("visual_diff"),
                    height=26,
                    fg_color=UI_COLORS.get("accent_green", "#2E7D32"),
                    text_color="white",
                    command=lambda iid=item_id: self.show_visual_diff_popup(iid),
                )
                show_visual_btn.pack(fill="x", pady=(6, 0))
            
            zoom_frame = ttk.Frame(nav_group)
            zoom_frame.pack(fill="x", pady=(10, 0))
            
            zoom_label_var = tk.StringVar(value="Zoom: 100%")
            ttk.Label(zoom_frame, textvariable=zoom_label_var, font=("Segoe UI", 9), width=10).pack(side="left", padx=(0, 5))
            
            zoom_var = tk.DoubleVar(value=1.0)
            def on_zoom_change(val):
                z = round(float(val), 2)
                zoom_label_var.set(f"Zoom: {int(z*100)}%")
                if hasattr(self, '_zoom_job') and self._zoom_job:
                    self.inspector_window.after_cancel(self._zoom_job)
                self._zoom_job = self.inspector_window.after(300, lambda: update_page(current_page_ref['page']))

            zoom_scale = ttk.Scale(zoom_frame, from_=0.5, to=3.0, variable=zoom_var, command=on_zoom_change)
            zoom_scale.pack(side="left", fill="x", expand=True)

#            pinpoint_var = tk.BooleanVar(value=True)
#            pinpoint_cb = ttk.Checkbutton(nav_group, text=self._("enable_visual_pinpointing"), 
#                                          variable=pinpoint_var, command=lambda: update_page(current_page_ref['page']))
#            pinpoint_cb.pack(pady=(10, 0), anchor="w")

            if has_touchup:
                touchup_text_frame = ttk.LabelFrame(sidebar_frame, text=self._("extracted_altered_text"), padding=5)
                touchup_text_frame.pack(fill="x", pady=(0, 10))
                
                touchup_text_widget = tk.Text(touchup_text_frame, wrap="word", height=6, 
                                              font=("Segoe UI", 9), bg="#ffffff", fg="#333333",
                                              relief="sunken", padx=4, pady=4)
                touchup_text_widget.pack(fill="x")
                touchup_text_widget.tag_configure("header", font=("Segoe UI", 9, "bold"), foreground="#cc0000")
                touchup_text_widget.tag_configure("hint", font=("Segoe UI", 8, "italic"), foreground="#666666")
                touchup_text_widget.tag_configure("number", font=("Consolas", 9, "bold"), foreground="#0066cc")
                touchup_text_widget.config(state="disabled")
            else:
                touchup_text_widget = None

            legend_frame = ttk.LabelFrame(sidebar_frame, text=self._("legend_title"), padding=12)
            legend_frame.pack(fill="x", pady=(0, 15))
            
            indicator_vars = {
                "ela": tk.BooleanVar(value=True),
                "jpeg": tk.BooleanVar(value=True),
                "colorspace": tk.BooleanVar(value=True),
                "touchup": tk.BooleanVar(value=True),
                "font": tk.BooleanVar(value=True),
                "duplicate": tk.BooleanVar(value=True),
                "nonembedded_font": tk.BooleanVar(value=True),
                "structural_scrubbing": tk.BooleanVar(value=True)
            }
            
            def select_all_none(state):
                for var in indicator_vars.values():
                    var.set(state)
                update_page(current_page_ref['page'])

            toggle_frame = ttk.Frame(legend_frame)
            toggle_frame.pack(fill="x", pady=(0, 10))
            
            ctk.CTkButton(toggle_frame, text=self._("select_all"), height=24, width=80,
                          command=lambda: select_all_none(True)).pack(side="left", padx=2)
            ctk.CTkButton(toggle_frame, text=self._("select_none"), height=24, width=80,
                          command=lambda: select_all_none(False)).pack(side="left", padx=2)
            
            def add_legend_item(color, label_key, var_key):
                f = ttk.Frame(legend_frame)
                f.pack(fill="x", pady=4)
                
                cb = ttk.Checkbutton(f, variable=indicator_vars[var_key], 
                                     command=lambda: update_page(current_page_ref['page']))
                cb.pack(side="left", padx=(0, 5))
                
                canvas = tk.Canvas(f, width=18, height=18, bg=color, highlightthickness=1, highlightbackground="#666")
                canvas.pack(side="left", padx=(0, 10))
                ttk.Label(f, text=self._(label_key), font=("Segoe UI", 9)).pack(side="left")

            add_legend_item("red", "legend_ela", "ela")
            add_legend_item("orange", "legend_jpeg", "jpeg")
            add_legend_item("cyan", "legend_colorspace", "colorspace")
            add_legend_item("#8000FF", "legend_touchup", "touchup") 
            add_legend_item("orange", "legend_font", "font")
            add_legend_item("yellow", "legend_duplicate", "duplicate")
            add_legend_item("#32CD32", "legend_nonembedded_font", "nonembedded_font") 
            add_legend_item("#FF00FF", "legend_structural_scrubbing", "structural_scrubbing") 

            current_page_ref = {'page': 0}
            total_pages = len(self.inspector_doc)
            layer_vars = {}
            doc_ocgs = self.inspector_doc.get_ocgs() if self.inspector_doc.is_pdf else {}
            _orig_pdf_bytes = self.inspector_doc.tobytes()

            if doc_ocgs:
                layer_frame = ttk.LabelFrame(sidebar_frame, text=self._("doc_layers_label"), padding=5)
                layer_frame.pack(fill="x", pady=(0, 10))
                
                scrollable_layers = ctk.CTkScrollableFrame(layer_frame, height=100, fg_color="transparent")
                scrollable_layers.pack(fill="x", expand=True)

                def _apply_ocg_state():
                    on_xrefs  = [x for x, v in layer_vars.items() if v.get()]
                    off_xrefs = [x for x, v in layer_vars.items() if not v.get()]
                    all_ocg_xrefs = list(doc_ocgs.keys())
                    order_str = " ".join(f"{x} 0 R" for x in all_ocg_xrefs)
                    on_str    = "[" + " ".join(f"{x} 0 R" for x in on_xrefs)  + "]"
                    off_str   = "[" + " ".join(f"{x} 0 R" for x in off_xrefs) + "]"
                    ocg_str   = " ".join(f"{x} 0 R" for x in all_ocg_xrefs)
                    new_ocprops = f"<</D<</Order[{order_str}]/ON{on_str}/OFF{off_str}/RBGroups[]>>/OCGs[{ocg_str}]>>"
                    
                    tmp_doc = fitz.open(stream=_orig_pdf_bytes, filetype="pdf")
                    tmp_doc.xref_set_key(tmp_doc.pdf_catalog(), "OCProperties", new_ocprops)
                    mod_bytes = tmp_doc.tobytes()
                    tmp_doc.close()
                    if self.inspector_doc: self.inspector_doc.close()
                    self.inspector_doc = fitz.open(stream=mod_bytes, filetype="pdf")

                name_counts = {}
                for xref, info in doc_ocgs.items():
                    base_name = info.get('name', f'OCG {xref}')
                    name_counts[base_name] = name_counts.get(base_name, 0) + 1
                name_seen = {}
                for xref, info in doc_ocgs.items():
                    base_name = info.get('name', f'OCG {xref}')
                    name_seen[base_name] = name_seen.get(base_name, 0) + 1
                    label = f"{base_name} #{name_seen[base_name]}" if name_counts[base_name] > 1 else base_name
                    var = tk.BooleanVar(value=info.get('on', True))
                    layer_vars[xref] = var
                    
                    def _toggle(v=var): 
                        _apply_ocg_state()
                        update_page(current_page_ref['page'])
                        
                    cb = ttk.Checkbutton(scrollable_layers, text=label, variable=var, command=_toggle)
                    cb.pack(anchor="w")
                
                ttk.Label(layer_frame, text=self._("layer_info_tooltip"), font=("Segoe UI", 7, "italic"), 
                          foreground="gray", wraplength=200).pack(anchor="w", pady=(4, 0))

            def update_page(page_num):
                if not self.inspector_doc or not (0 <= page_num < total_pages):
                    return
                current_page_ref['page'] = page_num
                
                try:
                    if not self.inspector_window.winfo_exists() or not pdf_main_frame.winfo_exists():
                        return
                except tk.TclError:
                    return

                page = self.inspector_doc.load_page(page_num)
                
                if has_touchup and touchup_text_widget:
                    page_texts = touchup_texts_by_page.get(page_num + 1, [])
                    
                    touchup_text_widget.config(state="normal")
                    touchup_text_widget.delete("1.0", tk.END)
                    
                    if page_texts:
                        touchup_text_widget.insert("1.0", self._("extracted_text_header").format(page=page_num + 1), "header")
                        touchup_text_widget.insert(tk.END, self._("extracted_text_note"), "hint")
                        for idx, text in enumerate(page_texts, 1):
                            touchup_text_widget.insert(tk.END, f"[{idx}] ", "number")
                            touchup_text_widget.insert(tk.END, f"{text}\n")
                    else:
                        touchup_text_widget.insert("1.0", self._("extracted_text_none").format(page=page_num + 1))
                    
                    touchup_text_widget.config(state="disabled")
                
                try:
                    zoom_factor = float(zoom_var.get())
                except Exception:
                    zoom_factor = 1.0
                
                dpi = int(150 * zoom_factor)
                pix = page.get_pixmap(dpi=dpi)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                
#                if pinpoint_var.get():
                indicator_keys = file_data.get("indicator_keys", {})
                zoom = dpi / 72.0
                draw = ImageDraw.Draw(img)
                
                if "ErrorLevelAnalysis" in indicator_keys and indicator_vars["ela"].get():
                    for finding in indicator_keys["ErrorLevelAnalysis"].get("findings", []):
                        if finding.get("page") == page_num + 1:
                            xref = finding.get("xref")
                            if xref:
                                try:
                                    for img_info in page.get_image_info(xrefs=True):
                                        if img_info["xref"] == xref:
                                            r = img_info["bbox"]
                                            r_scaled = [r[0]*zoom, r[1]*zoom, r[2]*zoom, r[3]*zoom]
                                            draw.rectangle(r_scaled, outline="red", width=5)
                                except Exception: pass
                
                if "JPEG_Analysis" in indicator_keys and indicator_vars["jpeg"].get():
                    for finding in indicator_keys["JPEG_Analysis"].get("findings", []):
                        if finding.get("page") == page_num + 1:
                            xref = finding.get("xref")
                            if xref:
                                try:
                                    for img_info in page.get_image_info(xrefs=True):
                                        if img_info["xref"] == xref:
                                            r = img_info["bbox"]
                                            r_scaled = [r[0]*zoom, r[1]*zoom, r[2]*zoom, r[3]*zoom]
                                            draw.rectangle(r_scaled, outline="orange", width=5)
                                except Exception: pass
                
                if "PageInconsistency" in indicator_keys and indicator_vars["ela"].get():
                    for p_info in indicator_keys["PageInconsistency"].get("pages", []):
                        if p_info.get("page") == page_num + 1:
                            border = 10
                            draw.rectangle([border, border, img.width-border, img.height-border], 
                                           outline="red", width=border)
                                      
                if "ColorSpaceAnomaly" in indicator_keys and indicator_vars["colorspace"].get():
                    for f_info in indicator_keys["ColorSpaceAnomaly"].get("findings", []):
                        if f_info.get("page") == page_num + 1:
                            border = 10
                            draw.rectangle([border, border, img.width-border, img.height-border], 
                                           outline="cyan", width=border)
                                      
                if "TouchUp_TextEdit" in indicator_keys and indicator_vars["touchup"].get():
                    found_text = indicator_keys["TouchUp_TextEdit"].get("found_text", {})
                    page_texts = []
                    if isinstance(found_text, dict):
                        page_texts = found_text.get(page_num + 1, [])
                    elif isinstance(found_text, list):
                        page_texts = found_text 
                        
                    for text_segment in page_texts:
                        try:
                            parts = [p.strip() for p in text_segment.split("│")]
                            for part in parts:
                                if not part or len(part) < 2:
                                    continue
                                rects = page.search_for(part)
                                for r in rects:
                                    r_scaled = [r[0]*zoom, r[1]*zoom, r[2]*zoom, r[3]*zoom]
                                    draw.rectangle(r_scaled, outline="#8000FF", width=5)
                        except Exception:
                            pass
                            
                if "MultipleFontSubsets" in indicator_keys and indicator_vars["font"].get():
                    conflicting_fonts = indicator_keys["MultipleFontSubsets"].get("fonts", {})
                    all_conflicting_subsets = []
                    for subsets in conflicting_fonts.values():
                        all_conflicting_subsets.extend(list(subsets))
                        
                    try:
                        text_dict = page.get_text("dict")
                        for block in text_dict.get("blocks", []):
                            for line in block.get("lines", []):
                                for span in line.get("spans", []):
                                    if span.get("font") in all_conflicting_subsets:
                                        r = span["bbox"]
                                        r_scaled = [r[0]*zoom, r[1]*zoom, r[2]*zoom, r[3]*zoom]
                                        draw.rectangle(r_scaled, outline="orange", width=5)
                    except Exception:
                        pass
                        
                if "DuplicateImagesWithDifferentXrefs" in indicator_keys and indicator_vars["duplicate"].get():
                    xrefs = indicator_keys["DuplicateImagesWithDifferentXrefs"].get("xrefs", [])
                    for xref in xrefs:
                        try:
                            for img_info in page.get_image_info(xrefs=True):
                                if img_info["xref"] == xref:
                                    r = img_info["bbox"]
                                    r_scaled = [r[0]*zoom, r[1]*zoom, r[2]*zoom, r[3]*zoom]
                                    draw.rectangle(r_scaled, outline="yellow", width=5)
                        except Exception:
                            pass

                if "NonEmbeddedFont" in indicator_keys and indicator_vars["nonembedded_font"].get():
                    non_embedded = indicator_keys["NonEmbeddedFont"].get("fonts", [])
                    try:
                        text_dict = page.get_text("dict")
                        for block in text_dict.get("blocks", []):
                            for line in block.get("lines", []):
                                for span in line.get("spans", []):
                                    if span.get("font") in non_embedded:
                                        r = span["bbox"]
                                        r_scaled = [r[0]*zoom, r[1]*zoom, r[2]*zoom, r[3]*zoom]
                                        draw.rectangle(r_scaled, outline="#32CD32", width=5) 
                    except Exception:
                        pass

                if "StructuralScrubbing" in indicator_keys and indicator_vars["structural_scrubbing"].get():
                    banner_h = max(20, int(25 * zoom))
                    draw.rectangle([0, 0, img.width, banner_h], fill="#FF00FF") 
            
                if pdf_main_frame.winfo_width() <= 1 or pdf_main_frame.winfo_height() <= 1:
                    self.inspector_pdf_update_job = self.inspector_window.after(50, lambda: update_page(page_num))
                    return
                
                max_w = pdf_main_frame.winfo_width() * 0.95
                max_h = pdf_main_frame.winfo_height() * 0.95
                
                base_pix = page.get_pixmap(dpi=150)
                fit_ratio = min(max_w / base_pix.width, max_h / base_pix.height) if base_pix.width > 0 else 1
                scaled_size = (int(img.width * fit_ratio), int(img.height * fit_ratio))

                img_tk = ImageTk.PhotoImage(img.resize(scaled_size, Image.Resampling.LANCZOS))
                pdf_image_label.img_tk = img_tk
                
                pdf_image_label.config(image=img_tk)
                page_label.config(text=self._("diff_page_label").format(current=page_num + 1, total=total_pages))
                prev_button.configure(state="normal" if page_num > 0 else "disabled")
                next_button.configure(state="normal" if page_num < total_pages - 1 else "disabled")

            prev_button.configure(command=lambda: update_page(current_page_ref['page'] - 1))
            next_button.configure(command=lambda: update_page(current_page_ref['page'] + 1))
            
            self.inspector_pdf_update_job = self.inspector_window.after(100, lambda: update_page(0))
        else:
            ttk.Label(self.inspector_pdf_frame, text=self._("could_not_display_pdf")).pack(pady=20)

        self.inspector_window.deiconify()
        self.inspector_window.lift()

    def _insert_related_files_with_links(self, details):
        files = details.get('files', [])
        # Filter out placeholder IDs (e.g. 'ID: xmp.did:...', 'xmp.did:...')
        def _is_placeholder(name_val):
            s = str(name_val).strip()
            return not s or s == 'xmp.did:...' or s.startswith('ID: ') and s.endswith('...')
        filtered = [f for f in files if f.get('name') and not _is_placeholder(f['name'])]
        if not filtered:
            return
        
        self.inspector_indicators_text.insert(
            tk.END,
            "• " + self._("related_files_label") + f" ({len(filtered)}):",
            ("bold",)
        )
        
        for f in filtered:
            rel_type = f.get('type', 'related')
            name = f.get('name', 'Unknown')
            path = f.get('path', '')
            found_in_case = bool(path)
            
            if rel_type == 'derived_from':
                prefix = f"\n      ← {self._('relationship_derived_from')}: "
            elif rel_type == 'parent_of':
                prefix = f"\n      → {self._('relationship_parent_of')}: "
            else:
                prefix = f"\n      ↔ {self._('relationship_related_to')}: "
            
            self.inspector_indicators_text.insert(tk.END, prefix)
            
            if found_in_case:
                tag_name = f"link_{hash(path)}"
                self.inspector_indicators_text.tag_configure(tag_name, foreground="#9999ff", underline=True)
                self.inspector_indicators_text.insert(tk.END, name, (tag_name,))
                self.inspector_indicators_text.tag_bind(tag_name, "<Button-1>", 
                    lambda e, p=path: self._navigate_to_file(p))
                self.inspector_indicators_text.tag_bind(tag_name, "<Enter>", 
                    lambda e: self.inspector_indicators_text.config(cursor="hand2"))
                self.inspector_indicators_text.tag_bind(tag_name, "<Leave>", 
                    lambda e: self.inspector_indicators_text.config(cursor=""))
            else:
                # Not in case — show greyed out with not-found label
                self.inspector_indicators_text.insert(
                    tk.END, f"{name}  [{self._('not_found_label')}]",
                    ("not_found",)
                )
        self.inspector_indicators_text.insert(tk.END, "\n")

    def _insert_related_files_in_history(self, details):
        """Insert related files (derived_from / parent_of) into the History & Relations tab."""
        files = details.get('files', [])
        # Filter out placeholder IDs (e.g. 'ID: xmp.did:...', 'xmp.did:...')
        def _is_placeholder(name_val):
            s = str(name_val).strip()
            return not s or s == 'xmp.did:...' or s.startswith('ID: ') and s.endswith('...')
        filtered = [f for f in files if f.get('name') and not _is_placeholder(f['name'])]
        if not filtered:
            return
        
        tw = self.inspector_history_text
        tw.insert(tk.END, self._("related_files_label") + f" ({len(filtered)})\n", ("bold",))
        
        for f in filtered:
            rel_type = f.get('type', 'related')
            name = f.get('name', 'Unknown')
            path = f.get('path', '')
            found_in_case = bool(path)
            
            if rel_type == 'derived_from':
                prefix = f"  ← {self._('relationship_derived_from')}: "
            elif rel_type == 'parent_of':
                prefix = f"  → {self._('relationship_parent_of')}: "
            else:
                prefix = f"  ↔ {self._('relationship_related_to')}: "
            
            tw.insert(tk.END, prefix)
            
            if found_in_case:
                tag_name = f"hist_link_{hash(path)}"
                tw.tag_configure(tag_name, foreground="#9999ff", underline=True)
                tw.insert(tk.END, name, (tag_name,))
                tw.tag_bind(tag_name, "<Button-1>", 
                    lambda e, p=path: self._navigate_to_file(p))
                tw.tag_bind(tag_name, "<Enter>", 
                    lambda e: tw.config(cursor="hand2"))
                tw.tag_bind(tag_name, "<Leave>", 
                    lambda e: tw.config(cursor=""))
            else:
                tw.insert(
                    tk.END, f"{name}  [{self._('not_found_label')}]",
                    ("not_found",)
                )
            tw.insert(tk.END, "\n")

    def show_text_diff_popup(self, item_id):
        path_str = self.tree.item(item_id, "values")[4]
        file_data = self.all_scan_data.get(path_str)
        
        if not file_data:
            messagebox.showinfo(self._("error_title"), self._("data_not_found"), parent=self.root)
            return

        text_diff_data = file_data.get("indicator_keys", {}).get("TouchUp_TextEdit", {}).get("text_diff")
        if not text_diff_data:
            messagebox.showinfo(self._("no_diff_title"), self._("no_diff_data"), parent=self.root)
            return

        popup = Toplevel(self.root)
        popup.title(f"Text Comparison for {file_data['path'].name}")
        
        self._center_window(popup, width_scale=0.7, height_scale=0.75)
        
        popup.transient(self.root)

        frame = ttk.Frame(popup, padding=10)
        frame.pack(fill="both", expand=True)
        
        text_widget = tk.Text(frame, wrap="word", font=("Courier New", 10))
        v_scroll = ttk.Scrollbar(frame, orient="vertical", command=text_widget.yview)
        text_widget.config(yscrollcommand=v_scroll.set)
        v_scroll.pack(side="right", fill="y")
        text_widget.pack(side="left", fill="both", expand=True)

        text_widget.tag_configure("addition", foreground="green")
        text_widget.tag_configure("deletion", foreground="red")

        for line in text_diff_data:
            if line.startswith('+ '):
                text_widget.insert(tk.END, line, "addition")
            elif line.startswith('- '):
                text_widget.insert(tk.END, line, "deletion")
            else:
                text_widget.insert(tk.END, line)
        
        self._make_text_copyable(text_widget)

    def _populate_relationship_tab(self, data):
        """Populate the History tab with structured relationship info."""
        txt = self.inspector_indicators_text
        has_data = False
        
        # 1. Derivation (Source)
        derivation = data.get('derivation')
        if derivation:
            doc_id = derivation.get('documentID') or derivation.get('instanceID')
            if doc_id:
                txt.insert(tk.END, self._("relationship_derivation") + "\n", ("header",))
                for k, v in derivation.items():
                    if v:
                        txt.insert(tk.END, f"  • {k}: ", ("bold",))
                        txt.insert(tk.END, f"{v}\n")
                txt.insert(tk.END, "\n")
                has_data = True
        
        # 2. Ingredients
        ingredients = data.get('ingredients', [])
        
        if ingredients:
            txt.insert(tk.END, f"{self._('relationship_ingredients')} ({len(ingredients)}):\n", ("header",))
            for ing in ingredients:
                name = ing.get('filePath') or str(ing.get('documentID') or ing.get('instanceID') or '?')
                txt.insert(tk.END, f"  • {name}\n", ("bold",))
                for k, v in ing.items():
                    if k == 'filePath': continue
                    if v:
                        txt.insert(tk.END, f"    - {k}: {v}\n", ("indent",))
            txt.insert(tk.END, "\n")
            has_data = True
        
        # 3. Pantry
        pantry = data.get('pantry', {})
        
        if pantry:
            txt.insert(tk.END, f"{self._('relationship_pantry')} ({len(pantry)}):\n", ("header",))
            for pid, pdata in pantry.items():
                txt.insert(tk.END, f"  • {pid}\n", ("bold",))
                for k in ['documentID', 'instanceID', 'originalDocumentID']:
                    val = pdata.get('ids', {}).get(k)
                    if val:
                        txt.insert(tk.END, f"    - {k}: {val}\n", ("indent",))
            txt.insert(tk.END, "\n")
            has_data = True
        
        # 4. Anomalies
        anomalies = data.get('anomalies', [])
        if anomalies:
            txt.insert(tk.END, self._("relationship_anomalies") + ":\n", ("header", "anomaly"))
            for anomaly in anomalies:
                txt.insert(tk.END, f"  [!] {anomaly}\n", ("anomaly", "bullet"))
            has_data = True

        if not has_data:
            txt.insert(tk.END, f"{self._('no_relationship_data')}\n", ("unchanged",))

    def _insert_related_files_with_links(self, details):
        """Insert related files into the text widget, making them clickable if found in current results."""
        files = details.get('files', [])
        # Filter placeholders and empty names
        def _is_placeholder_name(name_val):
            s = str(name_val).strip()
            return not s or s == 'xmp.did:...' or (s.startswith('ID: ') and s.endswith('...'))
        filtered_files = [f for f in files if f.get('name') and not _is_placeholder_name(f['name'])]
        count = len(filtered_files)
        
        if count == 0:
            return

        self.inspector_indicators_text.insert(tk.END, f"{self._('related_files_label')} ({count}):\n")
        
        for f in filtered_files:
            rel_type = f.get('type', 'related')
            name = f.get('name', 'Unknown')
            doc_id = f.get('id')
            
            # Label
            if rel_type == 'derived_from':
                label = f"  \u2190 {self._('relationship_derived_from')}: "
            elif rel_type == 'parent_of':
                label = f"  \u2192 {self._('relationship_parent_of') if hasattr(self, '_') and self._('relationship_parent_of') != 'relationship_parent_of' else 'Parent of'}: "
            else:
                label = f"  \u2194 {self._('relationship_related_to') if hasattr(self, '_') and self._('relationship_related_to') != 'relationship_related_to' else 'Related to'}: "
            
            self.inspector_indicators_text.insert(tk.END, label)
            
            # Check if we can find this file in our results
            found_path = None
            if doc_id:
                for p, d in self.all_scan_data.items():
                    if doc_id in d.get('document_ids', {}).get('own_ids', set()):
                        found_path = p
                        break
            
            if found_path:
                # Make it a link
                tag = f"link_{found_path.replace(':', '_').replace('/', '_').replace('\\', '_')}"
                self.inspector_indicators_text.insert(tk.END, name, (tag, "link"))
                self.inspector_indicators_text.tag_bind(tag, "<Button-1>", lambda e, p=found_path: self._on_related_file_click(p))
                self.inspector_indicators_text.tag_bind(tag, "<Enter>", lambda e: self.inspector_indicators_text.config(cursor="hand2"))
                self.inspector_indicators_text.tag_bind(tag, "<Leave>", lambda e: self.inspector_indicators_text.config(cursor=""))
            else:
                # Just text
                self.inspector_indicators_text.insert(tk.END, name)
            
            self.inspector_indicators_text.insert(tk.END, "\n")

    def _on_related_file_click(self, path):
        # Find if the file is in the tree
        found = False
        for item in self.tree.get_children():
            if self.tree.item(item, "values")[2] == str(path): # Index 2 is usually the path hidden or shown
                self.tree.selection_set(item)
                self.tree.see(item)
                found = True
                break
        
        if not found:
            # Maybe it's not in the visible tree but in all_scan_data?
            # Re-select by matching path in all items
            for item in self.tree.get_children(''):
                if str(Path(self.tree.item(item, 'tags')[0] if self.tree.item(item, 'tags') else "")) == str(path):
                     self.tree.selection_set(item)
                     self.tree.see(item)
                     found = True
                     break
        
        if not found:
            messagebox.showinfo(self._("not_found_title"), self._("related_file_not_found"), parent=self.inspector_window)
        
    def _open_visual_diff_from_details(self):
        """Open the Visual Diff popup for the row currently shown in the Inspector Details pane."""
        item_id = getattr(self, "_inspector_item_id", None)
        if not item_id:
            sel = self.tree.selection()
            if sel:
                item_id = sel[0]
        if item_id:
            self.show_visual_diff_popup(item_id)
        else:
            messagebox.showinfo(self._("info_title"), self._("data_not_found"), parent=self.root)

    def _jump_to_touchup_visual_pane(self):
        """Switch the Inspector to the PDF viewer tab for visual TouchUp inspection."""
        notebook = getattr(self, "inspector_notebook", None)
        if notebook and getattr(self, "inspector_pdf_frame", None):
            try:
                notebook.select(self.inspector_pdf_frame)
            except Exception:
                pass

    def show_visual_diff_popup(self, item_id):
        self.root.config(cursor="watch")
        self.root.update_idletasks()

        rev_path_str = self.tree.item(item_id, "values")[4]
        rev_data = self.all_scan_data.get(rev_path_str)
        original_path_str = rev_data.get('original_path') if rev_data else None

        if not original_path_str:
            messagebox.showerror(self._("diff_error_title"), self._("orig_file_not_found"), parent=self.root)
            self.root.config(cursor="")
            return

        resolved_rev_path = self._resolve_case_path(rev_path_str)
        resolved_orig_path = self._resolve_case_path(original_path_str)

        try:
            popup = Toplevel(self.root)
            popup.title(self._("diff_popup_title"))
            # Auto-fit window width close to monitor width so all three PDFs can be seen side by side
            try:
                screen_w = popup.winfo_screenwidth()
                screen_h = popup.winfo_screenheight()
                win_w = int(screen_w * 0.95)
                win_h = int(screen_h * 0.7)
                popup.geometry(f"{win_w}x{win_h}")
            except Exception:
                pass

            popup.current_page = 0
            popup.path_orig = resolved_orig_path
            popup.path_rev = resolved_rev_path
            with fitz.open(popup.path_orig) as doc:
                popup.total_pages = doc.page_count

            main_frame = ttk.Frame(popup, padding=10)
            main_frame.pack(fill="both", expand=True)

            # Scrollable canvas that contains the three preview images so zoom never hides controls.
            # Canvas can scroll both horizontally and vertically; window size can be smaller than content.
            canvas = tk.Canvas(main_frame, highlightthickness=0)
            canvas.grid(row=1, column=0, columnspan=3, sticky="nsew")
            main_frame.rowconfigure(1, weight=1)
            main_frame.columnconfigure(0, weight=1)
            img_scroll_y = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
            img_scroll_y.grid(row=1, column=3, sticky="ns", padx=(4, 0))
            img_scroll_x = ttk.Scrollbar(main_frame, orient="horizontal", command=canvas.xview)
            img_scroll_x.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(4, 0))
            canvas.configure(yscrollcommand=img_scroll_y.set, xscrollcommand=img_scroll_x.set)

            image_frame = ttk.Frame(canvas)
            canvas.create_window((0, 0), window=image_frame, anchor="nw")
            
            label_orig = ttk.Label(image_frame)
            label_rev = ttk.Label(image_frame)
            label_diff = ttk.Label(image_frame)
            label_orig.grid(row=1, column=0, padx=5)
            label_rev.grid(row=1, column=1, padx=5)
            label_diff.grid(row=1, column=2, padx=5)

            ttk.Label(image_frame, text=self._("diff_original_label"), font=("Segoe UI", 10, "bold")).grid(row=0, column=0)
            ttk.Label(image_frame, text=self._("diff_revision_label"), font=("Segoe UI", 10, "bold")).grid(row=0, column=1)
            ttk.Label(image_frame, text=self._("diff_differences_label"), font=("Segoe UI", 10, "bold")).grid(row=0, column=2)

            nav_frame = ttk.Frame(main_frame)
            nav_frame.grid(row=3, column=0, columnspan=3, pady=(10,0))
            
            prev_button = ttk.Button(nav_frame, text=self._("diff_prev_page"))
            page_label = ttk.Label(nav_frame, text="", font=("Segoe UI", 9, "italic"))
            next_button = ttk.Button(nav_frame, text=self._("diff_next_page"))

            prev_button.pack(side="left", padx=10)
            page_label.pack(side="left", padx=10)
            next_button.pack(side="left", padx=10)

            # Zoom slider for visual diff (same style as inspector viewer)
            zoom_frame = ttk.Frame(nav_frame)
            zoom_frame.pack(side="right", fill="x", expand=True, padx=(20, 0))
            zoom_label_var = tk.StringVar(value="Zoom: 100%")
            ttk.Label(zoom_frame, textvariable=zoom_label_var, font=("Segoe UI", 9), width=11).pack(side="left", padx=(0, 5))
            zoom_var = tk.DoubleVar(value=1.0)
            zoom_job = {"id": None}
            def on_zoom_change(val):
                z = round(float(val), 2)
                zoom_label_var.set(f"Zoom: {int(z*100)}%")
                # Re-render current page with new zoom factor (debounced)
                if zoom_job["id"] is not None:
                    try:
                        popup.after_cancel(zoom_job["id"])
                    except Exception:
                        pass
                zoom_job["id"] = popup.after(150, lambda: update_page(popup.current_page))
            zoom_scale = ttk.Scale(zoom_frame, from_=0.5, to=3.0, variable=zoom_var, command=on_zoom_change)
            zoom_scale.pack(side="left", fill="x", expand=True)
            
            # Refit images when the canvas size changes (e.g. window resize)
            resize_job = {"id": None}
            def _on_canvas_configure(event):
                if resize_job["id"] is not None:
                    try:
                        canvas.after_cancel(resize_job["id"])
                    except Exception:
                        pass
                resize_job["id"] = canvas.after(150, lambda: update_page(popup.current_page))
            canvas.bind("<Configure>", _on_canvas_configure)

            # Mouse wheel scrolling when scrollbars are present
            def _on_mousewheel(event):
                if not canvas.winfo_exists():
                    return
                try:
                    if event.state & 0x0001:  # Shift held -> horizontal scroll
                        canvas.xview_scroll(-1 * (event.delta // 120), "units")
                    else:
                        canvas.yview_scroll(-1 * (event.delta // 120), "units")
                except tk.TclError:
                    pass
                return "break"
            canvas.bind("<MouseWheel>", _on_mousewheel)
            popup.bind("<MouseWheel>", _on_mousewheel)

            def update_page(page_num):
                if not (0 <= page_num < popup.total_pages):
                    return
                
                popup.current_page = page_num
                self.root.config(cursor="watch")
                self.root.update()

                with fitz.open(popup.path_orig) as doc_orig, fitz.open(popup.path_rev) as doc_rev:
                    if page_num >= doc_rev.page_count:
                        page_orig = doc_orig.load_page(page_num)
                        # Auto-fit initial zoom so all three images roughly span the monitor width
                        if not hasattr(popup, "_auto_zoom_done"):
                            screen_w = popup.winfo_screenwidth()
                            page_width_pts = page_orig.rect.width or 1.0
                            base_width = (page_width_pts / 72.0) * 150.0  # width at 150 dpi
                            target_per_image = (screen_w * 0.9) / 3.0
                            factor = target_per_image / base_width if base_width > 0 else 1.0
                            factor = max(0.5, min(3.0, factor))
                            zoom_var.set(factor)
                            popup._auto_zoom_done = True

                        try:
                            zoom_factor = float(zoom_var.get())
                        except Exception:
                            zoom_factor = 1.0
                        zoom_factor = max(0.5, min(3.0, zoom_factor))
                        dpi = int(150 * zoom_factor)

                        pix_orig = page_orig.get_pixmap(dpi=dpi)
                        img_orig = Image.frombytes("RGB", [pix_orig.width, pix_orig.height], pix_orig.samples)
                        img_rev = Image.new('RGB', img_orig.size, (200, 200, 200)) 
                        final_diff = Image.new('RGB', img_orig.size, (100, 100, 100)) 
                    else:
                        page_orig = doc_orig.load_page(page_num)
                        page_rev = doc_rev.load_page(page_num)

                        if not hasattr(popup, "_auto_zoom_done"):
                            screen_w = popup.winfo_screenwidth()
                            page_width_pts = page_orig.rect.width or 1.0
                            base_width = (page_width_pts / 72.0) * 150.0
                            target_per_image = (screen_w * 0.9) / 3.0
                            factor = target_per_image / base_width if base_width > 0 else 1.0
                            factor = max(0.5, min(3.0, factor))
                            zoom_var.set(factor)
                            popup._auto_zoom_done = True

                        try:
                            zoom_factor = float(zoom_var.get())
                        except Exception:
                            zoom_factor = 1.0
                        zoom_factor = max(0.5, min(3.0, zoom_factor))
                        dpi = int(150 * zoom_factor)

                        pix_orig = page_orig.get_pixmap(dpi=dpi)
                        pix_rev = page_rev.get_pixmap(dpi=dpi)

                        img_orig = Image.frombytes("RGB", [pix_orig.width, pix_orig.height], pix_orig.samples)
                        img_rev = Image.frombytes("RGB", [pix_rev.width, pix_rev.height], pix_rev.samples)

                        if img_orig.size != img_rev.size:
                            img_rev = img_rev.resize(img_orig.size, Image.Resampling.LANCZOS)

                        diff = ImageChops.difference(img_orig, img_rev)
                        mask = diff.convert('L').point(lambda x: 255 if x > 20 else 0)
                        final_diff = Image.composite(Image.new('RGB', img_orig.size, 'red'), ImageOps.grayscale(img_orig).convert('RGB'), mask)
                
                # Do NOT shrink images to fit the frame; let the scrollable canvas handle overflow.
                images_tk = [ImageTk.PhotoImage(img) for img in [img_orig, img_rev, final_diff]]
                popup.images_tk = images_tk
                
                label_orig.config(image=images_tk[0])
                label_rev.config(image=images_tk[1])
                label_diff.config(image=images_tk[2])
                # Update scrollregion so larger zooms are reachable via scroll, not by pushing controls off-screen
                image_frame.update_idletasks()
                bbox = canvas.bbox("all")
                if bbox:
                    canvas.configure(scrollregion=bbox)

                page_label.config(text=self._("diff_page_label").format(current=page_num + 1, total=popup.total_pages))
                prev_button.configure(state="normal" if page_num > 0 else "disabled")
                next_button.configure(state="normal" if page_num < popup.total_pages - 1 else "disabled")
                self.root.config(cursor="")

            prev_button.configure(command=lambda: update_page(popup.current_page - 1))
            next_button.configure(command=lambda: update_page(popup.current_page + 1))

            update_page(0)
            
            popup.transient(self.root)
            popup.grab_set()

        except Exception as e:
            logging.error(f"Visual diff error: {e}")
            messagebox.showerror(self._("diff_error_title"), self._("diff_error_msg").format(e=e), parent=self.root)
            self.root.config(cursor="")

    def open_settings_popup(self):
        settings_popup = Toplevel(self.root)
        settings_popup.title(self._("settings_title"))
        settings_popup.transient(self.root)
        settings_popup.geometry("400x200")
        settings_popup.resizable(False, False)

        main_frame = ttk.Frame(settings_popup, padding=15)
        main_frame.pack(expand=True, fill="both")

        size_var = tk.StringVar(value=str(PDFReconConfig.MAX_FILE_SIZE // (1024*1024)))
        timeout_var = tk.StringVar(value=str(PDFReconConfig.EXIFTOOL_TIMEOUT))
        threads_var = tk.StringVar(value=str(PDFReconConfig.MAX_WORKER_THREADS))
        diff_pages_var = tk.StringVar(value=str(PDFReconConfig.VISUAL_DIFF_PAGE_LIMIT))
        export_xref_var = tk.BooleanVar(value=PDFReconConfig.EXPORT_INVALID_XREF)

        fields = [
            (self._("settings_max_size"), size_var),
            (self._("settings_timeout"), timeout_var),
            (self._("settings_threads"), threads_var),
            (self._("settings_diff_pages"), diff_pages_var),
        ]

        for i, (label_text, var) in enumerate(fields):
            label = ttk.Label(main_frame, text=label_text)
            label.grid(row=i, column=0, sticky="w", pady=5)
            entry = ttk.Entry(main_frame, textvariable=var, width=10)
            entry.grid(row=i, column=1, sticky="e", pady=5)
        
        main_frame.columnconfigure(1, weight=1)
        xref_check = ttk.Checkbutton(main_frame, text=self._("settings_export_invalid_xref"), variable=export_xref_var)
        xref_check.grid(row=len(fields), column=0, columnspan=2, sticky="w", pady=5)

        def save_settings():
            try:
                new_size = int(size_var.get())
                new_timeout = int(timeout_var.get())
                new_threads = int(threads_var.get())
                new_diff_pages = int(diff_pages_var.get())
                new_export_xref = export_xref_var.get()

                PDFReconConfig.MAX_FILE_SIZE = new_size * 1024 * 1024
                PDFReconConfig.EXIFTOOL_TIMEOUT = new_timeout
                PDFReconConfig.MAX_WORKER_THREADS = new_threads
                PDFReconConfig.VISUAL_DIFF_PAGE_LIMIT = new_diff_pages
                PDFReconConfig.EXPORT_INVALID_XREF = new_export_xref

                if getattr(self, '_config_writable', True):
                    try:
                        import configparser
                        parser = configparser.ConfigParser()
                        parser.read(self.config_path)
                        if 'Settings' not in parser:
                            parser['Settings'] = {}
                        
                        parser['Settings']['MaxFileSizeMB'] = str(new_size)
                        parser['Settings']['ExifToolTimeout'] = str(new_timeout)
                        parser['Settings']['MaxWorkerThreads'] = str(new_threads)
                        parser['Settings']['VisualDiffPageLimit'] = str(new_diff_pages)
                        parser['Settings']['ExportInvalidXREF'] = str(new_export_xref)

                        with open(self.config_path, 'w') as configfile:
                            configfile.write("# PDFRecon Configuration File\n")
                            parser.write(configfile)
                    except Exception:
                        pass 

                messagebox.showinfo(self._("settings_saved_title"), self._("settings_saved_msg"), parent=settings_popup)
                settings_popup.destroy()

            except ValueError:
                messagebox.showerror(self._("error_title"), self._("settings_invalid_input"), parent=settings_popup)

        buttons_frame = ttk.Frame(main_frame)
        buttons_frame.grid(row=len(fields) + 1, column=0, columnspan=2, pady=(15, 0))
        
        save_button = ttk.Button(buttons_frame, text=self._("settings_save"), command=save_settings)
        save_button.pack(side="left", padx=5)

        cancel_button = ttk.Button(buttons_frame, text=self._("settings_cancel"), command=settings_popup.destroy)
        cancel_button.pack(side="left", padx=5)

        settings_popup.grab_set()
        self.root.wait_window(settings_popup)

    def show_license(self):
        possible_paths = []
        if getattr(sys, 'frozen', False):
            meipass = getattr(sys, '_MEIPASS', '')
            if meipass:
                possible_paths.append(Path(meipass) / "license.txt")
            possible_paths.append(Path(sys.executable).parent / "license.txt")
        else:
            possible_paths.append(Path(__file__).resolve().parent.parent / "license.txt")
        
        license_path = None
        for p in possible_paths:
            if p.exists():
                license_path = p
                break
        
        if not license_path:
            messagebox.showerror(self._("license_error_title"), self._("license_error_message"))
            return
            
        try:
            with open(license_path, 'r', encoding='utf-8') as f: license_text = f.read()
        except FileNotFoundError:
            messagebox.showerror(self._("license_error_title"), self._("license_error_message"))
            return
        
        license_popup = Toplevel(self.root)
        license_popup.title(self._("license_popup_title"))
        license_popup.geometry("600x500")
        license_popup.transient(self.root)

        text_frame = ttk.Frame(license_popup, padding=10)
        text_frame.pack(fill="both", expand=True)
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)
        
        scroll_frame = ttk.Frame(text_frame)
        scroll_frame.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(scroll_frame)
        scrollbar.pack(side="right", fill="y")
        text_widget = tk.Text(scroll_frame, wrap="word", yscrollcommand=scrollbar.set, font=("Courier New", 9), borderwidth=0, highlightthickness=0)
        text_widget.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=text_widget.yview)
        
        text_widget.insert("1.0", license_text)
        text_widget.config(state="disabled") 
        
        close_button = ttk.Button(text_frame, text=self._("close_button_text"), command=license_popup.destroy)
        close_button.grid(row=1, column=0, pady=(10,0))

    def show_about(self):
        about_popup = Toplevel(self.root)
        about_popup.title(self._("menu_about"))
        about_popup.geometry("520x480") 
        about_popup.resizable(True, True)
        about_popup.transient(self.root)

        outer_frame = ttk.Frame(about_popup, padding=10)
        outer_frame.pack(fill="both", expand=True)
        outer_frame.rowconfigure(0, weight=1)
        outer_frame.columnconfigure(0, weight=1)

        text_frame = ttk.Frame(outer_frame)
        text_frame.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side="right", fill="y")
        
        about_text_widget = tk.Text(text_frame, wrap="word", yscrollcommand=scrollbar.set, borderwidth=0, highlightthickness=0, background=about_popup.cget("background"))
        about_text_widget.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=about_text_widget.yview)

        about_text_widget.tag_configure("bold", font=("Segoe UI", 9, "bold"))
        about_text_widget.tag_configure("link", foreground="blue", underline=True)
        about_text_widget.tag_configure("header", font=("Segoe UI", 9, "bold", "underline"))

        def _open_link(event):
            index = about_text_widget.index(f"@{event.x},{event.y}")
            tag_indices = about_text_widget.tag_ranges("link")
            for start, end in zip(tag_indices[0::2], tag_indices[1::2]):
                if about_text_widget.compare(start, "<=", index) and about_text_widget.compare(index, "<", end):
                    url = about_text_widget.get(start, end).strip()
                    if not url.startswith("http"):
                        url = "https://" + url
                    webbrowser.open(url)
                    break

        about_text_widget.tag_bind("link", "<Enter>", lambda e: about_text_widget.config(cursor="hand2"))
        about_text_widget.tag_bind("link", "<Leave>", lambda e: about_text_widget.config(cursor=""))
        about_text_widget.tag_bind("link", "<Button-1>", _open_link)

        about_text_widget.insert("end", f"{self._('about_version')} ({datetime.now().strftime('%d-%m-%Y')})\n", "bold")
        about_text_widget.insert("end", self._("about_developer_info"))

        about_text_widget.insert("end", self._("about_project_website"), "bold")
        about_text_widget.insert("end", "github.com/Rasmus-Riis/PDFRecon\n", "link")

        about_text_widget.insert("end", "\n------------------------------------\n\n")
        
        about_text_widget.insert("end", self._("about_purpose_header") + "\n", "header")
        about_text_widget.insert("end", self._("about_purpose_text"))
        
        about_text_widget.insert("end", self._("about_included_software_header") + "\n", "header")
        about_text_widget.insert("end", self._("about_included_software_text").format(tool="ExifTool"))
        
        about_text_widget.insert("end", self._("about_website").format(tool="ExifTool"), "bold")
        about_text_widget.insert("end", "exiftool.org\n", "link")
        
        about_text_widget.insert("end", self._("about_source").format(tool="ExifTool"), "bold")
        about_text_widget.insert("end", "github.com/exiftool/exiftool\n", "link")
        
        about_text_widget.config(state="disabled") 
        
        close_button = ttk.Button(outer_frame, text=self._("close_button_text"), command=about_popup.destroy)
        close_button.grid(row=1, column=0, pady=(10, 0))

    def show_manual(self):
        lang = "da" if self.language.get() == "da" else "en"
        manual_paths_to_try = []
        
        if getattr(sys, 'frozen', False):
            meipass = getattr(sys, '_MEIPASS', '')
            if meipass:
                manual_paths_to_try.append(os.path.join(meipass, 'PDFRecon_Manual.html'))
                manual_paths_to_try.append(os.path.join(meipass, 'PDFRecon_Help.html'))
            exe_dir = os.path.dirname(sys.executable)
            manual_paths_to_try.append(os.path.join(exe_dir, 'PDFRecon_Manual.html'))
            manual_paths_to_try.append(os.path.join(exe_dir, 'PDFRecon_Help.html'))
        else:
            script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            manual_paths_to_try.append(os.path.join(script_dir, 'PDFRecon_Manual.html'))
            manual_paths_to_try.append(os.path.join(script_dir, 'PDFRecon_Help.html'))
        
        manual_paths_to_try.append(os.path.join(os.getcwd(), 'PDFRecon_Manual.html'))
        manual_paths_to_try.append(os.path.join(os.getcwd(), 'PDFRecon_Help.html'))
        
        for html_path in manual_paths_to_try:
            if os.path.exists(html_path):
                try:
                    file_url = Path(html_path).as_uri() + f'?lang={lang}'
                    webbrowser.open(file_url)
                    return
                except Exception as e:
                    logging.error(f"Failed to open manual: {e}")
                    continue
        
        searched_paths = "\n".join(manual_paths_to_try[:5]) 
        messagebox.showwarning(
            "Manual Not Found",
            f"Could not find the forensic manual.\n\nSearched locations:\n{searched_paths}"
        )
        return

    def show_pdf_viewer_popup(self, item_id):
        self.root.config(cursor="watch")
        self.root.update_idletasks()

        try:
            path_str = self.tree.item(item_id, "values")[4]
            file_name = self.tree.item(item_id, "values")[1]
            resolved_path = self._resolve_case_path(path_str)
        except (IndexError, TypeError):
            self.root.config(cursor="")
            return

        file_data = self.all_scan_data.get(path_str)
        has_touchup = False
        touchup_texts_by_page = {}
        has_ela = False
        ela_xrefs_by_page = {}
        
        if file_data:
            indicator_keys = file_data.get("indicator_keys", {})
            
            touchup_info = indicator_keys.get("TouchUp_TextEdit", {})
            if touchup_info:
                has_touchup = True
                found_text = touchup_info.get("found_text", {})
                if isinstance(found_text, dict):
                    touchup_texts_by_page = found_text
                elif isinstance(found_text, list):
                    touchup_texts_by_page = {0: found_text}

            ela_info = indicator_keys.get("ErrorLevelAnalysis", {})
            jpeg_info = indicator_keys.get("JPEG_Analysis", {})
            if ela_info or jpeg_info:
                has_ela = True
                findings = ela_info.get("findings", []) + jpeg_info.get("findings", [])
                for f in findings:
                    page_num = f.get("page", 1) - 1 
                    xref = f.get("xref")
                    if xref:
                        ela_xrefs_by_page.setdefault(page_num, []).append(xref)

        try:
            popup = Toplevel(self.root)
            popup.title(f"{self._('pdf_viewer_title')} - {file_name}")
            
            popup.current_page = 0
            popup.doc = fitz.open(resolved_path)
            popup.total_pages = len(popup.doc)
            popup.has_touchup = has_touchup
            popup.touchup_texts_by_page = touchup_texts_by_page
            popup.touchup_regions_cache = {}  
            popup.has_ela = has_ela
            popup.ela_xrefs_by_page = ela_xrefs_by_page
            
            main_frame = ttk.Frame(popup, padding=10)
            main_frame.pack(fill="both", expand=True)
            main_frame.rowconfigure(0, weight=1)
            main_frame.columnconfigure(0, weight=1)

            info_frame = ttk.Frame(main_frame)
            info_frame.grid(row=0, column=0, sticky="ew")
            if has_touchup or has_ela:
                messages = []
                if has_touchup:
                    messages.append("🔴 TouchUp_TextEdit detected (highlighted in red)")
                if has_ela:
                    messages.append("🟠 Image Anomalies detected (highlighted in orange)")
                info_label = ttk.Label(info_frame, text=" | ".join(messages), 
                                       foreground="red" if has_touchup else "orange", font=("Segoe UI", 9, "italic"))
                info_label.pack(pady=5)

            image_label = ttk.Label(main_frame)
            image_label.grid(row=1, column=0, pady=5, sticky="nsew")
            main_frame.rowconfigure(1, weight=1)
            
            nav_frame = ttk.Frame(main_frame)
            nav_frame.grid(row=2, column=0, pady=(10,0))
            
            prev_button = ttk.Button(nav_frame, text=self._("diff_prev_page"))
            page_label = ttk.Label(nav_frame, text="", font=("Segoe UI", 9, "italic"))
            next_button = ttk.Button(nav_frame, text=self._("diff_next_page"))

            prev_button.pack(side="left", padx=10)
            page_label.pack(side="left", padx=10)
            next_button.pack(side="left", padx=10)

            popup_ocgs = popup.doc.get_ocgs()  
            _popup_all_xrefs = list(popup_ocgs.keys())
            popup_layer_vars = {}  
            _popup_orig_bytes = popup.doc.tobytes()

            def _apply_popup_ocg_state():
                on_xrefs  = [x for x, v in popup_layer_vars.items() if v.get()]
                off_xrefs = [x for x, v in popup_layer_vars.items() if not v.get()]
                order_str = " ".join(f"{x} 0 R" for x in _popup_all_xrefs)
                on_str    = "[" + " ".join(f"{x} 0 R" for x in on_xrefs)  + "]"
                off_str   = "[" + " ".join(f"{x} 0 R" for x in off_xrefs) + "]"
                ocg_str   = " ".join(f"{x} 0 R" for x in _popup_all_xrefs)
                new_ocprops = (
                    f"<</D<</Order[{order_str}]"
                    f"/ON{on_str}/OFF{off_str}/RBGroups[]>>"
                    f"/OCGs[{ocg_str}]>>"
                )
                tmp_doc = fitz.open(stream=_popup_orig_bytes, filetype="pdf")
                tmp_doc.xref_set_key(tmp_doc.pdf_catalog(), "OCProperties", new_ocprops)
                mod_bytes = tmp_doc.tobytes()
                tmp_doc.close()
                if popup.doc:
                    popup.doc.close()
                popup.doc = fitz.open(stream=mod_bytes, filetype="pdf")

            if popup_ocgs:
                popup_layer_frame = ttk.LabelFrame(main_frame, text=self._("doc_layers_label"), padding=5)
                popup_layer_frame.grid(row=3, column=0, pady=(8, 0), sticky="ew")
                name_counts = {}
                for xref, info in popup_ocgs.items():
                    base_name = info.get('name', f'OCG {xref}')
                    name_counts[base_name] = name_counts.get(base_name, 0) + 1
                name_seen = {}
                for xref, info in popup_ocgs.items():
                    base_name = info.get('name', f'OCG {xref}')
                    name_seen[base_name] = name_seen.get(base_name, 0) + 1
                    if name_counts[base_name] > 1:
                        label = f"{base_name} #{name_seen[base_name]}"
                    else:
                        label = base_name
                    var = tk.BooleanVar(value=info.get('on', True))
                    popup_layer_vars[xref] = var
                    def _make_popup_toggle():
                        def _toggle():
                            _apply_popup_ocg_state()
                            update_page(popup.current_page)
                        return _toggle
                    cb = ttk.Checkbutton(popup_layer_frame, text=label, variable=var, command=_make_popup_toggle())
                    cb.pack(anchor="w")
                ttk.Label(
                    popup_layer_frame,
                    text=self._("layer_info_tooltip"),
                    font=("Segoe UI", 8, "italic"),
                    foreground="gray",
                    wraplength=340,
                ).pack(anchor="w", pady=(4, 0))

            def update_page(page_num):
                if not (0 <= page_num < popup.total_pages): return
                
                popup.current_page = page_num
                self.root.config(cursor="watch")
                self.root.update()

                page = popup.doc.load_page(page_num)
                
                highlight_rects = []
                if popup.has_touchup:
                    if page_num not in popup.touchup_regions_cache:
                        page_texts = popup.touchup_texts_by_page.get(page_num + 1, [])
                        if 0 in popup.touchup_texts_by_page:
                            page_texts = page_texts + popup.touchup_texts_by_page.get(0, [])
                        
                        popup.touchup_regions_cache[page_num] = self._get_touchup_regions_for_page(
                            popup.doc, page_num, page_texts
                        )
                    highlight_rects = popup.touchup_regions_cache[page_num]
                
                ela_rects = []
                if popup.has_ela:
                    xrefs = popup.ela_xrefs_by_page.get(page_num, [])
                    for xref in xrefs:
                        try:
                            rects = page.get_image_rects(xref)
                            ela_rects.extend(rects)
                        except Exception:
                            pass
                
                if highlight_rects or ela_rects:
                    shape = page.new_shape()
                    if highlight_rects:
                        for rect in highlight_rects:
                            shape.draw_rect(rect)
                            shape.finish(color=(1, 0, 0), fill=None, width=2)  
                            
                            shape.draw_rect(rect)
                            shape.finish(color=None, fill=(1, 0, 0), fill_opacity=0.3)  
                    
                    if ela_rects:
                        for rect in ela_rects:
                            shape.draw_rect(rect)
                            shape.finish(color=(1, 0.5, 0), fill=None, width=2)  
                            
                            shape.draw_rect(rect)
                            shape.finish(color=None, fill=(1, 0.5, 0), fill_opacity=0.3)  
                    
                    shape.commit()
                
                pix = page.get_pixmap(dpi=150)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                
                max_img_w, max_img_h = main_frame.winfo_width() * 0.95, main_frame.winfo_height() * 0.85
                img_w, img_h = img.size
                ratio = min(max_img_w / img_w, max_img_h / img_h) if img_w > 0 and img_h > 0 else 1
                scaled_size = (int(img_w * ratio), int(img_h * ratio))

                img_tk = ImageTk.PhotoImage(img.resize(scaled_size, Image.Resampling.LANCZOS))
                popup.img_tk = img_tk 
                
                image_label.config(image=img_tk)
                page_label.config(text=self._("diff_page_label").format(current=page_num + 1, total=popup.total_pages))
                prev_button.configure(state="normal" if page_num > 0 else "disabled")
                next_button.configure(state="normal" if page_num < popup.total_pages - 1 else "disabled")
                self.root.config(cursor="")

            prev_button.configure(command=lambda: update_page(popup.current_page - 1))
            next_button.configure(command=lambda: update_page(popup.current_page + 1))
            
            def on_close():
                if hasattr(popup, 'doc') and popup.doc:
                    popup.doc.close()
                popup.destroy()
            popup.protocol("WM_DELETE_WINDOW", on_close)

            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            w, h = int(sw * 0.7), int(sh * 0.85)
            x, y = (sw - w) // 2, (sh - h) // 2
            popup.geometry(f"{w}x{h}+{x}+{y}")

            update_page(0)
            
            popup.transient(self.root)
            popup.grab_set()

        except Exception as e:
            logging.error(f"PDF viewer error: {e}")
            messagebox.showerror(self._("pdf_viewer_error_title"), self._("pdf_viewer_error_message").format(e=e), parent=self.root)
            if 'popup' in locals() and hasattr(popup, 'doc') and popup.doc:
                popup.doc.close()
        finally:
            self.root.config(cursor="")

    def _populate_timeline_widget(self, text_widget, path_str):
        timeline_data = self.timeline_data.get(path_str)
        
        if not timeline_data or (not timeline_data.get("aware") and not timeline_data.get("naive")):
            text_widget.insert("1.0", self._("timeline_no_data"))
            return

        text_widget.tag_configure("date_header", font=("Courier New", 11, "bold", "underline"), spacing1=10, spacing3=5)
        text_widget.tag_configure("time", font=("Courier New", 10, "bold"))
        text_widget.tag_configure("delta", foreground="#0078D7")
        text_widget.tag_configure("section_header", font=("Courier New", 12, "bold"), spacing1=15, spacing3=10, justify='center')
        text_widget.tag_configure("source_fs", foreground="#008000")
        text_widget.tag_configure("source_exif", foreground="#555555")
        text_widget.tag_configure("source_raw", foreground="#800080")
        text_widget.tag_configure("source_xmp", foreground="#C00000")

        aware_events = timeline_data.get("aware", [])
        naive_events = timeline_data.get("naive", [])
        
        if aware_events:
            header_text = ("\n--- Tider med tidszoneinformation ---\n" if self.language.get() == "da" 
                           else "\n--- Times with timezone information ---\n")
            text_widget.insert("end", header_text, "section_header")

            last_date = None
            last_dt_obj = None
            for dt_obj, description in aware_events:
                try:
                    local_dt = dt_obj.astimezone()
                except OSError:
                    local_dt = dt_obj
                if local_dt.date() != last_date:
                    if last_date is not None: text_widget.insert("end", "\n")
                    text_widget.insert("end", f"--- {local_dt.strftime('%d-%m-%Y')} ---\n", "date_header")
                    last_date = local_dt.date()
                delta_str = ""
                if last_dt_obj:
                    delta = local_dt - last_dt_obj
                    delta_str = self._format_timedelta(delta)
                source_tag = "source_exif"
                if description.startswith("File System"): source_tag = "source_fs"
                time_str = local_dt.strftime('%H:%M:%S %z')
                text_widget.insert("end", f"{time_str:<15}", "time")
                text_widget.insert("end", f" | {description:<60}", source_tag)
                text_widget.insert("end", f" | {delta_str}\n", "delta")
                last_dt_obj = local_dt

        if naive_events:
            header_text = ("\n--- Tider uden tidszoneinformation ---\n" if self.language.get() == "da" 
                           else "\n--- Times without timezone information ---\n")
            text_widget.insert("end", header_text, "section_header")
            
            last_date = None
            last_dt_obj = None 
            for dt_obj, description in naive_events:
                if dt_obj.date() != last_date:
                    if last_date is not None: text_widget.insert("end", "\n")
                    text_widget.insert("end", f"--- {dt_obj.strftime('%d-%m-%Y')} ---\n", "date_header")
                    last_date = dt_obj.date()
                delta_str = ""
                if last_dt_obj:
                    delta = dt_obj - last_dt_obj
                    delta_str = self._format_timedelta(delta)
                source_tag = "source_exif"
                if description.startswith("File System"): source_tag = "source_fs"
                elif description.startswith("Raw File"): source_tag = "source_raw"
                elif description.startswith("XMP History"): source_tag = "source_xmp"
                time_str = dt_obj.strftime('%H:%M:%S')
                text_widget.insert("end", f"{time_str:<15}", "time")
                text_widget.insert("end", f" | {description:<60}", source_tag)
                text_widget.insert("end", f" | {delta_str}\n", "delta")
                last_dt_obj = dt_obj

    def _populate_version_history(self, text_widget, path_str, file_data):
        text_widget.tag_configure("header", font=("Courier New", 12, "bold"), spacing1=10, spacing3=5)
        text_widget.tag_configure("version_header", font=("Courier New", 11, "bold"), foreground="#1F6AA5")
        text_widget.tag_configure("label", font=("Courier New", 10, "bold"))
        text_widget.tag_configure("value", font=("Courier New", 10))
        text_widget.tag_configure("changed", font=("Courier New", 10, "bold"), foreground="#FF6600")
        text_widget.tag_configure("unchanged", font=("Courier New", 10), foreground="#666666")
        text_widget.tag_configure("separator", foreground="#444444")

        if not file_data:
            text_widget.insert("end", self._("no_data_available"))
            return

        indicators = file_data.get("indicator_keys", {})
        has_revisions = indicators.get("HasRevisions", {}).get("count", 0)
        incremental_count = indicators.get("IncrementalUpdates", {}).get("count", 0)
        startxref_count = indicators.get("MultipleStartxref", {}).get("count", 0)
        is_revision = file_data.get("is_revision", False)

        if is_revision:
            text_widget.insert("end", self._("revision_select_parent") + "\n")
            return

        if not has_revisions and not incremental_count and startxref_count <= 1:
            text_widget.insert("end", self._("no_incremental_updates") + "\n\n", "header")
            text_widget.insert("end", self._("no_incremental_desc") + "\n\n")
            text_widget.insert("end", self._("no_incremental_note"))
            return

        if not has_revisions and (incremental_count or startxref_count > 1):
            detected_versions = incremental_count if incremental_count else startxref_count
            text_widget.insert("end", f"{self._('incremental_detected').format(count=detected_versions)}\n\n", "header")
            text_widget.insert("end", f"⚠ {self._('warning_title').upper()}: ", "label")
            text_widget.insert("end", f"{self._('incremental_important')}\n\n", "value")
            text_widget.insert("end", f"{self._('incremental_no_extract')}\n\n", "changed")
            text_widget.insert("end", f"{self._('incremental_final_times')}\n\n", "label")
            
            current_timeline = self.timeline_data.get(path_str, {})
            current_dates = self._extract_key_dates_from_timeline(current_timeline)
            
            text_widget.insert("end", "─" * 50 + "\n", "separator")
            for label_key, key in [("label_created", "created"), ("label_modified", "modified"), ("label_metadata", "metadata")]:
                value = current_dates.get(key, "N/A")
                text_widget.insert("end", f"  {self._(label_key):12}: ", "label")
                text_widget.insert("end", f"{value}\n", "value" if value != "N/A" else "unchanged")
            
            tool = current_dates.get("tool", "")
            if tool:
                text_widget.insert("end", f"  {self._('label_tool'):12}: ", "label")
                text_widget.insert("end", f"{tool}\n", "value")
            return

        versions = []
        
        current_timeline = self.timeline_data.get(path_str, {})
        current_dates = self._extract_key_dates_from_timeline(current_timeline)
        versions.append({
            "name": self._("final_version"),
            "path": path_str,
            "dates": current_dates,
            "is_current": True
        })

        for rev_path_str, rev_data in self.all_scan_data.items():
            if rev_data.get("is_revision") and str(rev_data.get("original_path")) == path_str:
                rev_timeline = self.timeline_data.get(rev_path_str, {})
                rev_dates = self._extract_key_dates_from_timeline(rev_timeline)
                try:
                    rev_name = Path(rev_path_str).stem
                    if "_rev" in rev_name:
                        rev_num = rev_name.split("_rev")[1].split("_")[0]
                        offset = rev_name.split("@")[1] if "@" in rev_name else "?"
                        version_label = f"Version {rev_num} (@{offset})"
                    else:
                        version_label = Path(rev_path_str).name
                except Exception:
                    version_label = Path(rev_path_str).name
                
                versions.append({
                    "name": version_label,
                    "path": rev_path_str,
                    "dates": rev_dates,
                    "is_current": False
                })

        def sort_key(v):
            if v["is_current"]:
                return (999, "")
            name = v["name"]
            if "Version " in name:
                try:
                    num = int(name.split("Version ")[1].split(" ")[0])
                    return (num, name)
                except Exception:
                    pass
            return (0, name)
        
        versions.sort(key=sort_key)

        text_widget.insert("end", self._("version_history_header").format(count=len(versions)) + "\n\n", "header")
        
        text_widget.insert("end", self._("important_label"), "label")
        text_widget.insert("end", self._("incremental_normal_feature") + "\n", "value")
        text_widget.insert("end", self._("incremental_signing") + "\n")
        text_widget.insert("end", self._("incremental_forms") + "\n")
        text_widget.insert("end", self._("incremental_comments") + "\n")
        text_widget.insert("end", self._("incremental_acrobat_save") + "\n\n")
        text_widget.insert("end", self._("compare_timestamps_desc") + "\n\n", "value")

        prev_dates = None

        for v in versions:
            dates = v["dates"]
            
            if v["is_current"]:
                text_widget.insert("end", f"▶ {v['name']} ({self._('current_file')})\n", "version_header")
            else:
                text_widget.insert("end", f"  {v['name']}\n", "version_header")
            
            text_widget.insert("end", "  " + "─" * 50 + "\n", "separator")

            date_fields = [
                ("label_created", "created"),
                ("label_modified", "modified"),
                ("label_metadata", "metadata"),
            ]

            for label_key, key in date_fields:
                value = dates.get(key, "N/A")
                text_widget.insert("end", f"  {self._(label_key):12}: ", "label")
                
                if prev_dates and prev_dates.get(key) and value != prev_dates.get(key):
                    text_widget.insert("end", f"{value}", "changed")
                    text_widget.insert("end", self._("label_changed_from").format(old=prev_dates.get(key)) + "\n", "changed")
                else:
                    text_widget.insert("end", f"{value}\n", "value" if value != "N/A" else "unchanged")

            tool = dates.get("tool", "")
            if tool:
                text_widget.insert("end", f"  {self._('label_tool'):12}: ", "label")
                if prev_dates and prev_dates.get("tool") and tool != prev_dates.get("tool"):
                    text_widget.insert("end", f"{tool}", "changed")
                    text_widget.insert("end", self._("label_changed") + "\n", "changed")
                else:
                    text_widget.insert("end", f"{tool}\n", "value")

            text_widget.insert("end", "\n")
            prev_dates = dates

        text_widget.insert("end", "═" * 54 + "\n", "separator")
        text_widget.insert("end", "\n" + self._("version_history_tip_label"), "label")
        text_widget.insert("end", self._("version_history_tip_changed") + "\n", "value")
        text_widget.insert("end", self._("version_history_tip_folder") + "\n", "value")