"""
PyInstaller hook for pdfrecon package
"""
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Collect all submodules
hiddenimports = collect_submodules('pdfrecon')

# Collect any data files in the package
datas = collect_data_files('pdfrecon', excludes=['*.pyc', '__pycache__'])
