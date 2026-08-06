# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules
import os
import sys

# Ensure src package is in the path during analysis
if os.path.abspath('.') not in sys.path:
    sys.path.insert(0, os.path.abspath('.'))

datas = [
    ('lang', 'lang'),
    ('assets', 'assets'),
    # Bundled decoder assets: the Adobe Glyph List (Tier 1) and the reference
    # font used for glyph shape comparison (Tier 2), plus its licence, which
    # must ship with it. Without these the decoder silently loses Tier 1 and
    # falls back to a reference font that cannot render Latin Extended-A.
    # Around 170 kB in total.
    #
    # The target MUST NOT be 'src/assets'. A data entry creates a real
    # directory of that name in the bundle, and a directory called 'src'
    # shadows the frozen 'src' package, so the app dies at startup with
    # "No module named 'src.popups'". Keep this in sync with
    # BUNDLED_ASSET_DIRNAME in src/cid_fonts.py.
    ('src/assets', 'pdfrecon_assets'),
    ('shared_ui', 'shared_ui'),
    ('license.txt', '.'),
    ('PDFRecon_Manual.html', '.'),
    ('icon.ico', '.'),
]
binaries = []
hiddenimports = [
    'fitz', 'pymupdf', 'requests', 'openpyxl', 'PIL', 'PIL.ImageChops', 'PIL.ImageOps', 'PIL.Image',
    # pikepdf is imported inside functions, so the analysis does not always
    # pick it up. It is required: TouchUp text extraction and the Tier 2
    # glyph renderer both depend on it, and without it the whole TouchUp
    # feature fails at runtime in the packaged build.
    'pikepdf',
]

# Collect all src submodules explicitly
try:
    src_submodules = collect_submodules('src')
    hiddenimports.extend(src_submodules)
    print(f"Found {len(src_submodules)} src submodules")
except Exception as e:
    print(f"Warning: Could not collect src submodules: {e}")
    # Fallback: manually list all src modules
    hiddenimports.extend([
        'src', 'src.app_gui', 'src.scanner', 'src.pdf_processor', 
        'src.advanced_forensics', 'src.exporter', 'src.gui', 'src.utils',
        'src.jpeg_forensics', 'src.logging_setup', 'src.config'
    ])

tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('tkinterdnd2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['app.py'],
    pathex=[os.path.abspath('.')],  # Add absolute path to current directory
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[os.path.abspath('.')],  # Look for hooks in current directory
    hooksconfig={},
    runtime_hooks=[],
    excludes=['numpy', 'pandas', 'matplotlib', 'scipy', 'torch', 'IPython', 'jnius', 'android', 'PIL._tkinter_finder', 'tkinter.test', 'unittest', 'pydoc'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PDFRecon',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
)
