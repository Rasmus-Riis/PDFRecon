import sys
import unittest
from unittest.mock import Mock, patch

# Mock all the missing modules
sys.modules['fitz'] = Mock()
sys.modules['tkinter'] = Mock()
sys.modules['tkinter.ttk'] = Mock()
sys.modules['tkinter.filedialog'] = Mock()
sys.modules['tkinter.messagebox'] = Mock()
sys.modules['tkinter.scrolledtext'] = Mock()
sys.modules['PIL'] = Mock()
sys.modules['PIL.Image'] = Mock()
sys.modules['PIL.ImageChops'] = Mock()
sys.modules['PIL.ImageTk'] = Mock()
sys.modules['openpyxl'] = Mock()
sys.modules['openpyxl.styles'] = Mock()
sys.modules['pikepdf'] = Mock()
sys.modules['pytest'] = Mock()

if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = loader.discover('tests')

    runner = unittest.TextTestRunner()

    # Just run it
    runner.run(suite)
