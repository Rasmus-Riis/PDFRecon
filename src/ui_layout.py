import tkinter as tk
from tkinter import ttk, Menu
import customtkinter as ctk
import sys
from .config import UI_COLORS, UI_DIMENSIONS

class UILayoutMixin:
    def _setup_styles(self):
        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        self.style.map('Treeview', background=[('selected', UI_COLORS['selection_blue'])])
        self.style.configure("red_row", background=UI_COLORS['red_row'])
        self.style.configure("yellow_row", background=UI_COLORS['yellow_row'])
        self.style.configure("blue.Horizontal.TProgressbar", background=UI_COLORS['progress_blue'])

        self.tree_tags = {
            "JA": "red_row",
            "YES": "red_row",
            "Sandsynligt": "yellow_row",
            "Possible": "yellow_row",
        }
        
    def _update_title(self):
        title = self.base_title
        if self.current_case_filepath:
            from pathlib import Path
            title += f" - [{Path(self.current_case_filepath).name}]"
        
        if self.case_is_dirty:
            title += " *"
        
        self.root.title(title)    

    def _setup_menu(self):
        self.menubar = tk.Menu(self.root)
        
        self.file_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label=self._("menu_file"), menu=self.file_menu)
        self.file_menu.add_command(label=self._("menu_open_case"), command=self._open_case)
        self.file_menu.add_command(label=self._("menu_verify_integrity"), command=self._verify_integrity, state="disabled")
        self.file_menu.add_command(label=self._("menu_show_audit_log"), command=self.show_audit_log)
        
        save_cmd = self._save_current_case if self.is_reader_mode else self._save_case
        save_label = "menu_save_case_simple" if self.is_reader_mode else "menu_save_case"
        # Always keep "Save case" available; saving will warn if there's nothing to save.
        self.file_menu.add_command(label=self._(save_label), command=save_cmd, state="normal")
        
        if not self.is_reader_mode and getattr(sys, 'frozen', False):
            self.file_menu.add_command(label=self._("menu_export_reader"), command=self._export_reader, state="disabled")
        
        if not self.is_reader_mode:
            self.file_menu.add_separator()
            self.file_menu.add_command(label=self._("menu_settings"), command=self.open_settings_popup)

        self.file_menu.add_separator()
        self.file_menu.add_command(label=self._("menu_exit"), command=self.root.quit)

        self.help_menu = tk.Menu(self.menubar, tearoff=0)
        self.lang_menu = tk.Menu(self.help_menu, tearoff=0) 

        self.menubar.add_cascade(label=self._("menu_help"), menu=self.help_menu)
        self.help_menu.add_command(label=self._("menu_manual"), command=self.show_manual)
        self.help_menu.add_command(label=self._("menu_about"), command=self.show_about)
        self.help_menu.add_separator()
        self.help_menu.add_command(label=self._("menu_check_for_updates"), command=self._check_for_updates)
        self.help_menu.add_separator()
        self.help_menu.add_cascade(label=self._("menu_language"), menu=self.lang_menu)
        self.lang_menu.add_radiobutton(label="Dansk", variable=self.language, value="da", command=self.switch_language)
        self.lang_menu.add_radiobutton(label="English", variable=self.language, value="en", command=self.switch_language)
        self.help_menu.add_separator()
        self.help_menu.add_command(label=self._("menu_license"), command=self.show_license)
        self.help_menu.add_command(label=self._("menu_log"), command=self.show_log_file)
        
        self.root.config(menu=self.menubar)

    def switch_language(self):
        path_of_selected = None
        if self.tree.selection():
            selected_item_id = self.tree.selection()[0]
            try:
                path_of_selected = self.tree.item(selected_item_id, "values")[4]
            except IndexError:
                path_of_selected = None

        if self.menubar:
            self.menubar.destroy()
        self._setup_menu()

        scan_button_text = self._("choose_folder") if not self.is_reader_mode else self._("btn_load_case")
        self.scan_button.configure(text=scan_button_text)
        self.export_button.configure(text=self._("btn_export_report"))
        self.verify_button.configure(text=self._("btn_verify_integrity"))
        
        if hasattr(self, 'label_actions'): self.label_actions.configure(text=self._("header_actions"))
        if hasattr(self, 'label_tools'): self.label_tools.configure(text=self._("header_tools"))
        if hasattr(self, 'btn_log'): self.btn_log.configure(text=self._("btn_view_log"))
        if hasattr(self, 'btn_manual'): self.btn_manual.configure(text=self._("btn_forensic_manual"))
        
        if hasattr(self, 'label_filter'): self.label_filter.configure(text=self._("label_filter"))
        if hasattr(self, 'label_evidence'): self.label_evidence.configure(text=self._("header_evidence"))
        if hasattr(self, 'entry_search'): self.entry_search.configure(placeholder_text=self._("search_placeholder"))
        
        for i, key in enumerate(self.columns_keys):
            self.tree.heading(self.columns[i], text=self._(key))

        self._apply_filter() 

        if path_of_selected:
            new_item_to_select = next((item_id for item_id in self.tree.get_children("") if self.tree.item(item_id, "values")[4] == path_of_selected), None)
            if new_item_to_select:
                self.tree.selection_set(new_item_to_select)
                self.tree.focus(new_item_to_select)
                self.on_select_item(None)
        else:
            self.detail_text.delete("1.0", "end")

        is_scan_finished = self.scan_button.cget('state') == 'normal'
        if is_scan_finished and self.all_scan_data:
            self._update_summary_status()
        elif not self.all_scan_data:
            self.status_var.set(self._("status_initial"))

        if self.all_scan_data:
            if self.evidence_hashes:
                self.file_menu.entryconfig(1, state="normal") 
            
            if self.is_reader_mode:
                if self.case_is_dirty:
                    self.file_menu.entryconfig(2, state="normal") 
            else: 
                self.file_menu.entryconfig(2, state="normal") 
                if getattr(sys, 'frozen', False):
                    self.file_menu.entryconfig(3, state="normal") 

        self._save_config()

    def _setup_main_frame(self):
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        self._init_sidebar()
        self._init_table_area()
        self._init_statusbar()

    def _init_sidebar(self):
        sb = ctk.CTkFrame(self.root, width=220, corner_radius=0, fg_color=UI_COLORS['sidebar_bg'])
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_rowconfigure(9, weight=1)
        
        logo = ctk.CTkFrame(sb, fg_color="transparent")
        logo.grid(row=0, column=0, padx=20, pady=20, sticky="nw")
        ctk.CTkLabel(logo, text="PDF", font=ctk.CTkFont(size=24, weight="bold"), 
                    text_color=UI_COLORS['accent_blue']).pack(side="left")
        ctk.CTkLabel(logo, text="Recon", font=ctk.CTkFont(size=24, weight="bold"), 
                    text_color="white").pack(side="left")
        
        self.label_actions = ctk.CTkLabel(sb, text=self._("header_actions"), text_color="#777", 
                    font=ctk.CTkFont(size=11, weight="bold"))
        self.label_actions.grid(row=1, column=0, padx=20, pady=5, sticky="w")
        
        scan_button_text = self._("choose_folder") if not self.is_reader_mode else self._("btn_load_case")
        self.scan_button = ctk.CTkButton(sb, text=scan_button_text, command=self.choose_folder if not self.is_reader_mode else self._open_case,
                                        font=ctk.CTkFont(weight="bold"), 
                                        fg_color=UI_COLORS['accent_blue'], 
                                        hover_color=UI_COLORS['accent_blue_hover'])
        self.scan_button.grid(row=2, column=0, padx=20, pady=10, sticky="ew")
        
        if self.is_reader_mode:
            self.scan_button.configure(state="disabled")
        
        self.export_button = ctk.CTkButton(sb, text=self._("btn_export_report"), command=self._show_export_menu,
                                     font=ctk.CTkFont(weight="bold"), 
                                     fg_color=UI_COLORS['accent_green'], 
                                     hover_color=UI_COLORS['accent_green_hover'])
        self.export_button.grid(row=3, column=0, padx=20, pady=20, sticky="ew")
        
        self.label_tools = ctk.CTkLabel(sb, text=self._("header_tools"), text_color="#777", 
                    font=ctk.CTkFont(size=11, weight="bold"))
        self.label_tools.grid(row=4, column=0, padx=20, pady=(20,5), sticky="w")
        
        self.verify_button = ctk.CTkButton(sb, text=self._("btn_verify_integrity"), 
                                          command=self._verify_integrity,
                                          fg_color="#333", hover_color="#444")
        self.verify_button.grid(row=5, column=0, padx=20, pady=5, sticky="ew")
        
        self.btn_log = ctk.CTkButton(sb, text=self._("btn_view_log"), command=self.show_log_file,
                     fg_color="#333", hover_color="#444")
        self.btn_log.grid(row=6, column=0, padx=20, pady=5, sticky="ew")
        
        self.btn_manual = ctk.CTkButton(sb, text=self._("btn_forensic_manual"), command=self.show_manual,
                     fg_color="transparent", text_color="gray")
        self.btn_manual.grid(row=10, column=0, padx=20, pady=20, sticky="ew")

    def _show_export_menu(self):
        menu = Menu(self.root, tearoff=0)
        menu.add_command(label="Excel (.xlsx)", command=lambda: self._prompt_and_export("xlsx"))
        menu.add_command(label="CSV (.csv)", command=lambda: self._prompt_and_export("csv"))
        menu.add_command(label="JSON (.json)", command=lambda: self._prompt_and_export("json"))
        menu.add_command(label="HTML (.html)", command=lambda: self._prompt_and_export("html"))
        
        try:
            menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        finally:
            menu.grab_release()

    def _init_table_area(self):
        container = ctk.CTkFrame(self.root, fg_color="transparent")
        container.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        container.grid_rowconfigure(1, weight=3)
        container.grid_rowconfigure(3, weight=1)
        container.grid_columnconfigure(0, weight=1)
        
        search_frame = ctk.CTkFrame(container, fg_color="transparent")
        search_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.label_filter = ctk.CTkLabel(search_frame, text=self._("label_filter"), 
                    font=ctk.CTkFont(size=12, weight="bold"), 
                    text_color="gray")
        self.label_filter.pack(side="left", padx=(0, 10))
        
        self.entry_search = ctk.CTkEntry(search_frame, textvariable=self.filter_var,
                                        placeholder_text=self._("search_placeholder"),
                                        height=35)
        self.entry_search.pack(side="left", fill="x", expand=True)
        self.filter_var.trace_add("write", self._apply_filter)
        
        tree_frame = ctk.CTkFrame(container, fg_color=UI_COLORS['main_bg'])
        tree_frame.grid(row=1, column=0, sticky="nsew")
        
        self.columns = ["ID", "Name", "Altered", "Revisions", "Path", "MD5", "File Created", "File Modified", "EXIFTool", "Signs of Alteration", "Note"]
        self.columns_keys = ["col_id", "col_name", "col_changed", "col_revisions", "col_path", "col_md5", "col_created", "col_modified", "col_exif", "col_indicators", "col_note"]
        
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Dark.Treeview",
                       background=UI_COLORS['main_bg'],
                       foreground="white",
                       fieldbackground=UI_COLORS['main_bg'],
                       borderwidth=0,
                       rowheight=25)
        style.configure("Dark.Treeview.Heading",
                       background="#2b2b2b",
                       foreground="white",
                       borderwidth=1,
                       relief="raised",
                       font=("Segoe UI", 10, "bold"),
                       padding=(5, 10)) 
        style.map('Dark.Treeview.Heading',
                 background=[('active', '#3a3a3a')])
        style.map('Dark.Treeview', background=[('selected', UI_COLORS['selection_blue'])])
        
        self.tree = ttk.Treeview(tree_frame, columns=self.columns, show="headings", 
                                selectmode="browse", style="Dark.Treeview")
        
        self.tree.tag_configure("red_row", background=UI_COLORS['red_row'], foreground=UI_COLORS['red_fg'])
        self.tree.tag_configure("yellow_row", background=UI_COLORS['yellow_row'], foreground=UI_COLORS['yellow_fg'])
        self.tree.tag_configure("blue_row", background=UI_COLORS['blue_row'], foreground=UI_COLORS['blue_fg'])
        self.tree.tag_configure("purple_row", background=UI_COLORS['purple_row'], foreground=UI_COLORS['purple_fg'])
        self.tree.tag_configure("gray_row", background=UI_COLORS['gray_row'], foreground="white")
        
        col_widths = {
            "ID": UI_DIMENSIONS['col_id_width'],
            "Name": UI_DIMENSIONS['col_name_width'],
            "Altered": UI_DIMENSIONS['col_altered_width'],
            "Revisions": UI_DIMENSIONS['col_revisions_width'],
            "Note": UI_DIMENSIONS['col_note_width'],
        }
        
        for i, key in enumerate(self.columns_keys):
            self.tree.heading(self.columns[i], text=self._(key), 
                            command=lambda c=self.columns[i]: self._sort_column(c, False))
            width = col_widths.get(self.columns[i], 120)
            anchor = "center" if self.columns[i] in ["ID", "Revisions"] else "w"
            self.tree.column(self.columns[i], anchor=anchor, width=width)
        
        tree_scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scrollbar.set)
        
        tree_scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        
        self.tree.bind("<<TreeviewSelect>>", self.on_select_item)
        self.tree.bind("<Double-1>", self.show_inspector_popup)
        self.tree.bind("<Motion>", self._on_tree_motion)
        self.tree.bind("<Button-3>", self.show_context_menu)
        # Keyboard navigation: Up/Down move 1 row at a time (and update details)
        self.tree.bind("<Down>", self._jump_tree_down_5)
        self.tree.bind("<Up>", self._jump_tree_up_5)
        
        self.details_frame = ctk.CTkFrame(container, fg_color="#232323", corner_radius=5)
        self.details_frame.grid(row=3, column=0, sticky="nsew", pady=(5, 0))
        self.label_evidence = ctk.CTkLabel(self.details_frame, text=self._("header_evidence"), 
                    font=("Segoe UI", 11, "bold"), text_color="#777")
        self.label_evidence.pack(anchor="w", padx=10, pady=(5,0))
        
        self.detail_text = ctk.CTkTextbox(self.details_frame, fg_color="#1e1e1e", 
                                         text_color="#dcdcdc", font=("Consolas", 12))
        self.detail_text.pack(fill="both", expand=True, padx=5, pady=5)
        
        self.detail_text._textbox.tag_config("header", foreground=UI_COLORS['accent_blue'], 
                                            font=("Segoe UI", 12, "bold"))
        self.detail_text._textbox.tag_config("sep", foreground="#555555")
        self.detail_text._textbox.tag_config("alert", foreground="#ff5252")
        self.detail_text._textbox.tag_config("info", foreground="#888888")
        self.detail_text._textbox.tag_config("link", foreground=UI_COLORS['link_blue'], underline=True)
        self.detail_text._textbox.tag_bind("link", "<Enter>", lambda e: self.detail_text.configure(cursor="hand2"))
        self.detail_text._textbox.tag_bind("link", "<Leave>", lambda e: self.detail_text.configure(cursor=""))
        self.detail_text._textbox.tag_bind("link", "<Button-1>", self._open_path_from_detail)

    def _init_statusbar(self):
        initial_status = self._("status_initial_reader") if self.is_reader_mode else self._("status_initial")
        self.status_var = tk.StringVar(value=initial_status)
        
        self.statusbar = ctk.CTkLabel(self.root, textvariable=self.status_var, anchor="w", 
                                     fg_color="#1a1a1a", height=30, padx=20)
        self.statusbar.grid(row=1, column=0, columnspan=2, sticky="ew")
        
        self.progressbar = ctk.CTkProgressBar(self.root, height=10, corner_radius=0, 
                                             fg_color="#1a1a1a", progress_color=UI_COLORS['progress_blue'])
        self.progressbar.set(0)

    def _setup_detail_frame(self, parent_frame):
        pass

    def _setup_bottom_frame(self, parent_frame):
        pass

    def _jump_tree_down_5(self, event):
        """Move tree selection 1 row down (or to last row)."""
        children = list(self.tree.get_children(""))
        if not children:
            return "break"
        sel = self.tree.selection()
        if sel:
            current = sel[0]
            try:
                idx = children.index(current)
            except ValueError:
                idx = 0
        else:
            idx = -1
        new_idx = min(len(children) - 1, idx + 1)
        new_id = children[new_idx]
        self.tree.selection_set(new_id)
        self.tree.focus(new_id)
        self.tree.see(new_id)
        self.on_select_item(None)
        return "break"

    def _jump_tree_up_5(self, event):
        """Move tree selection 1 row up (or to first row)."""
        children = list(self.tree.get_children(""))
        if not children:
            return "break"
        sel = self.tree.selection()
        if sel:
            current = sel[0]
            try:
                idx = children.index(current)
            except ValueError:
                idx = 0
        else:
            idx = 0
        new_idx = max(0, idx - 1)
        new_id = children[new_idx]
        self.tree.selection_set(new_id)
        self.tree.focus(new_id)
        self.tree.see(new_id)
        self.on_select_item(None)
        return "break"