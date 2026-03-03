"""
PyInstaller hook for src package
"""
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Collect all submodules
hiddenimports = collect_submodules('src')

# Collect any data files in the package
datas = collect_data_files('src', excludes=['*.pyc', '__pycache__'])
