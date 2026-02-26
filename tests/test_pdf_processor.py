import unittest
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path
import sys
import os

# Add parent directory to path to import pdfrecon
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pdfrecon.pdf_processor import validate_pdf_file
from pdfrecon.config import PDFReconConfig, PDFProcessingError, PDFCorruptionError, PDFTooLargeError, PDFEncryptedError
import fitz

class TestValidatePdfFile(unittest.TestCase):

    @patch('pdfrecon.pdf_processor.fitz.open')
    def test_validate_pdf_file_success(self, mock_fitz_open):
        # Mock filepath
        mock_path = MagicMock(spec=Path)
        mock_path.stat.return_value.st_size = 1024  # Small file

        # Mock open context manager
        mock_file = mock_open(read_data=b"%PDF-1.4")
        mock_path.open = mock_file

        # Mock fitz document
        mock_doc = MagicMock()
        mock_doc.is_encrypted = False
        mock_fitz_open.return_value = mock_doc

        result = validate_pdf_file(mock_path)
        self.assertTrue(result)

        # Verify calls
        mock_path.stat.assert_called_once()
        mock_path.open.assert_called_once_with("rb")
        mock_fitz_open.assert_called_once_with(str(mock_path))
        mock_doc.close.assert_called_once()

    def test_validate_pdf_file_too_large(self):
        mock_path = MagicMock(spec=Path)
        # Size > PDFReconConfig.MAX_FILE_SIZE
        mock_path.stat.return_value.st_size = PDFReconConfig.MAX_FILE_SIZE + 1

        with self.assertRaises(PDFTooLargeError):
            validate_pdf_file(mock_path)

    def test_validate_pdf_file_invalid_header(self):
        mock_path = MagicMock(spec=Path)
        mock_path.stat.return_value.st_size = 1024

        # Header != %PDF
        mock_file = mock_open(read_data=b"NOTP")
        mock_path.open = mock_file

        with self.assertRaises(PDFCorruptionError):
            validate_pdf_file(mock_path)

    @patch('pdfrecon.pdf_processor.fitz.open')
    def test_validate_pdf_file_encrypted(self, mock_fitz_open):
        mock_path = MagicMock(spec=Path)
        mock_path.stat.return_value.st_size = 1024
        mock_file = mock_open(read_data=b"%PDF")
        mock_path.open = mock_file

        mock_doc = MagicMock()
        mock_doc.is_encrypted = True
        mock_fitz_open.return_value = mock_doc

        with self.assertRaises(PDFEncryptedError):
            validate_pdf_file(mock_path)

        mock_doc.close.assert_called_once()

    @patch('pdfrecon.pdf_processor.fitz.open')
    def test_validate_pdf_file_corrupt(self, mock_fitz_open):
        mock_path = MagicMock(spec=Path)
        mock_path.stat.return_value.st_size = 1024
        mock_file = mock_open(read_data=b"%PDF")
        mock_path.open = mock_file

        # fitz.open raises FileDataError
        mock_fitz_open.side_effect = fitz.FileDataError("Bad file")

        with self.assertRaises(PDFCorruptionError):
            validate_pdf_file(mock_path)

    def test_validate_pdf_file_unexpected_error(self):
        mock_path = MagicMock(spec=Path)
        mock_path.stat.side_effect = Exception("Disk error")

        with self.assertRaises(PDFProcessingError):
            validate_pdf_file(mock_path)

if __name__ == '__main__':
    unittest.main()
