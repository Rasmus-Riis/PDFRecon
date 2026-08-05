import unittest
from unittest.mock import MagicMock, patch, mock_open
import sys
import hashlib
from pathlib import Path

# Add project root to path (at beginning to ensure we use local package)
sys.path.insert(0, ".")

# Dependencies that might be missing, or that would start a GUI, are mocked
# only for the duration of this module's own imports and then restored.
#
# Leaving the mocks in sys.modules replaces them for the whole pytest session,
# not just this file: every test module collected afterwards, and every lazy
# submodule import made later at runtime, resolves through the mock. That is
# not hypothetical - openpyxl imports openpyxl.packaging.extended lazily on
# the first Workbook.save(), so any later test that actually writes a
# spreadsheet fails with an unrelated-looking ImportError.
_MOCKED = [
    "customtkinter", "tkinter", "tkinter.filedialog", "tkinter.messagebox",
    "tkinter.ttk", "tkinterdnd2", "PIL", "PIL.Image", "PIL.ImageTk",
    "fitz", "openpyxl", "openpyxl.styles", "openpyxl.utils", "requests",
]
_ORIGINAL_MODULES = {name: sys.modules.get(name) for name in _MOCKED}
for _name in _MOCKED:
    sys.modules[_name] = MagicMock()

# Import modules
try:
    from src.app_gui import PDFReconApp
    from src.config import PDFReconConfig
except ImportError as e:
    print(f"ImportError: {e}")
    sys.exit(1)
except SystemExit:
    print("SystemExit caught during import. A dependency might be triggering exit.")
    sys.exit(1)
finally:
    for _name, _original in _ORIGINAL_MODULES.items():
        if _original is None:
            sys.modules.pop(_name, None)
        else:
            sys.modules[_name] = _original

class TestExifToolSecurity(unittest.TestCase):
    def setUp(self):
        # Create a mock app instance avoiding __init__
        self.app = PDFReconApp.__new__(PDFReconApp)
        # Mock _resolve_path
        self.app._resolve_path = MagicMock()
        # Mock translation method
        self.app._ = MagicMock(side_effect=lambda x: x)

        # Reset Config
        PDFReconConfig.EXIFTOOL_PATH = None
        PDFReconConfig.EXIFTOOL_HASH = None

    @patch("shutil.which")
    @patch("pathlib.Path.is_file", autospec=True)
    @patch("subprocess.run")
    def test_system_path_allowed(self, mock_run, mock_is_file, mock_which):
        """Test that ExifTool found in system path is allowed without hash."""
        # Setup: found in system path
        mock_which.return_value = "/usr/bin/exiftool"

        # Ensure Path("/usr/bin/exiftool").is_file() returns True
        def is_file_side_effect(self_obj):
            return str(self_obj) == "/usr/bin/exiftool"

        mock_is_file.side_effect = is_file_side_effect

        # Setup PDF path arg
        path_arg = MagicMock()
        path_arg.read_bytes.return_value = b"pdf_bytes"

        # Run
        # Note: We must mock open if it's called.
        # But system path shouldn't trigger open for hashing.
        with patch("builtins.open", new_callable=mock_open) as m_open:
            self.app.exiftool_output(path_arg)
            m_open.assert_not_called()

        # Verify: subprocess.run called
        mock_run.assert_called()

    @patch("shutil.which")
    @patch("pathlib.Path.is_file", autospec=True)
    def test_local_path_blocked_without_hash(self, mock_is_file, mock_which):
        """Test that ExifTool found locally is BLOCKED if no hash is configured."""
        mock_which.return_value = None # Not in system path

        local_path = Path("local/exiftool.exe")

        # _resolve_path returns local_path when looking for external file
        def resolve_side_effect(name, base_is_parent=False):
            if name == "exiftool.exe" and base_is_parent:
                return local_path
            return Path("nowhere")
        self.app._resolve_path.side_effect = resolve_side_effect

        # is_file returns True for local_path
        def is_file_side_effect(self_obj):
            return str(self_obj) == str(local_path)
        mock_is_file.side_effect = is_file_side_effect

        # Run
        path_arg = MagicMock()
        # Mock open to return bytes for hashing (it will be called)
        with patch("builtins.open", new_callable=mock_open, read_data=b"exe_content") as m_open:
            result = self.app.exiftool_output(path_arg)
            m_open.assert_called()

        # Verify blocked
        self.assertIn("Security Error", result)
        self.assertIn("untrusted location", result)

    @patch("shutil.which")
    @patch("pathlib.Path.is_file", autospec=True)
    @patch("subprocess.run")
    def test_local_path_allowed_with_hash(self, mock_run, mock_is_file, mock_which):
        """Test that ExifTool found locally is ALLOWED if hash matches."""
        mock_which.return_value = None
        local_path = Path("local/exiftool.exe")

        self.app._resolve_path.side_effect = lambda name, base_is_parent=False: local_path if base_is_parent else Path("nowhere")
        mock_is_file.side_effect = lambda self_obj: str(self_obj) == str(local_path)

        # Calculate expected hash
        sha = hashlib.sha256()
        sha.update(b"valid_bytes")
        expected_hash = sha.hexdigest()

        PDFReconConfig.EXIFTOOL_HASH = expected_hash

        path_arg = MagicMock()
        path_arg.read_bytes.return_value = b"pdf_bytes"

        with patch("builtins.open", new_callable=mock_open, read_data=b"valid_bytes"):
            self.app.exiftool_output(path_arg)

        mock_run.assert_called()

    @patch("shutil.which")
    @patch("pathlib.Path.is_file", autospec=True)
    def test_hash_mismatch_blocks(self, mock_is_file, mock_which):
        """Test that hash mismatch blocks execution."""
        mock_which.return_value = None
        local_path = Path("local/exiftool.exe")

        self.app._resolve_path.side_effect = lambda name, base_is_parent=False: local_path if base_is_parent else Path("nowhere")
        mock_is_file.side_effect = lambda self_obj: str(self_obj) == str(local_path)

        PDFReconConfig.EXIFTOOL_HASH = "correct_hash_value"

        path_arg = MagicMock()

        with patch("builtins.open", new_callable=mock_open, read_data=b"tampered_bytes"):
            result = self.app.exiftool_output(path_arg)

        self.assertIn("Error: ExifTool hash mismatch", result)

if __name__ == "__main__":
    unittest.main()
