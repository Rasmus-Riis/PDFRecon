"""
GUI Module

Handles all Tkinter GUI components and user interface logic.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .config import UI_COLORS, UI_FONTS, UI_DIMENSIONS


def center_window(root, window, width_scale=0.5, height_scale=0.5):
    """
    Center a window on the screen with optional width/height scaling.
    
    Args:
        root: Root window reference
        window: Window to center
        width_scale: Width scale factor (0-1)
        height_scale: Height scale factor (0-1)
    """
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    w = int(sw * width_scale)
    h = int(sh * height_scale)
    x = (sw - w) // 2
    y = (sh - h) // 2
    window.geometry(f"{w}x{h}+{x}+{y}")


def show_message(msg_type, title, message, parent=None):
    """
    Display a message dialog.
    
    Args:
        msg_type: "error", "warning", or "info"
        title: Dialog title
        message: Dialog message
        parent: Parent window
        
    Returns:
        Dialog result
    """
    message_funcs = {
        "error": messagebox.showerror,
        "warning": messagebox.showwarning,
        "info": messagebox.showinfo
    }
    msg_func = message_funcs.get(msg_type, messagebox.showinfo)
    return msg_func(title, message, parent=parent)


def setup_styles():
    """
    Initialize and configure ttk widget styles.
    
    Returns:
        ttk.Style: Configured style object
    """
    style = ttk.Style()
    try:
        style.theme_use('clam')
    except Exception:
        pass
    
    # Highlight on selection
    style.map('Treeview', background=[('selected', UI_COLORS['selection_blue'])])
    
    # Define colors for Treeview rows
    style.configure("red_row", background=UI_COLORS['red_row'])
    style.configure("yellow_row", background=UI_COLORS['yellow_row'])
    style.configure("blue_row", background=UI_COLORS['blue_row'])
    style.configure("gray_row", background=UI_COLORS['gray_row'])
    
    # Define custom style for progress bar
    style.configure("blue.Horizontal.TProgressbar", background=UI_COLORS['progress_blue'])
    
    return style


def create_main_frame(root):
    """
    Create and configure the main application frame.
    
    This is a skeleton - actual implementation would include:
    - Treeview setup with columns
    - Button and filter setup
    - Status bar
    - Export menu
    - Progress bar
    
    Args:
        root: Root window
        
    Returns:
        dict: Dictionary of created widgets
    """
    widgets = {}
    
    # Main container
    frame = ttk.Frame(root, padding=10)
    frame.pack(fill="both", expand=True)
    
    # Top controls
    top_frame = ttk.Frame(frame)
    top_frame.pack(pady=5, fill="x")
    
    scan_button = ttk.Button(top_frame, text="Choose Folder", 
                            width=UI_DIMENSIONS['button_width'])
    scan_button.pack(side="left", padx=(0, 10))
    
    widgets['scan_button'] = scan_button
    
    # Status bar
    status_var = tk.StringVar(value="Ready to scan PDFs")
    status_label = ttk.Label(frame, textvariable=status_var, 
                            foreground=UI_COLORS['text_green'], anchor="w")
    status_label.pack(pady=(5, 10), fill="x", expand=True)
    
    widgets['status_var'] = status_var
    
    # Progress bar
    progressbar = ttk.Progressbar(frame, orient="horizontal", mode="determinate",
                                 style="blue.Horizontal.TProgressbar")
    progressbar.pack(side="bottom", fill="x", padx=5, pady=5)
    
    widgets['progressbar'] = progressbar
    
    return widgets


def make_text_copyable(text_widget):
    """
    Make a Text widget read-only but allow text selection and copying.
    
    Args:
        text_widget: tk.Text widget to configure
    """
    context_menu = tk.Menu(text_widget, tearoff=0)
    
    def copy_selection(event=None):
        try:
            selected = text_widget.get(tk.SEL_FIRST, tk.SEL_LAST)
            text_widget.clipboard_clear()
            text_widget.clipboard_append(selected)
        except tk.TclError:
            pass
    
    context_menu.add_command(label="Copy", command=copy_selection)
    
    def show_context_menu(event):
        try:
            context_menu.tk_popup(event.x_root, event.y_root)
        except:
            pass
    
    text_widget.config(state="normal")
    text_widget.bind("<Key>", lambda e: "break")  # Disable typing
    text_widget.bind("<Button-3>", show_context_menu)  # Right-click
    text_widget.bind("<Control-c>", copy_selection)  # Ctrl+C
    text_widget.bind("<Command-c>", copy_selection)  # Command+C for macOS


# NOTE: The following would be moved from PDFReconApp and refactored:
# - _setup_main_frame()
# - _setup_menu()
# - _setup_styles()
# - _setup_detail_frame()
# - _setup_bottom_frame()
# - _show_note_popup()
# - show_inspector_popup()
# - show_context_menu()
# - switch_language()
# - All event handlers and UI update methods

# These are large methods that would be refactored to work with the module structure
# For now, they remain in PDFReconApp but should be extracted into this module
