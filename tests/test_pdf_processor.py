import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
from pdfrecon.pdf_processor import safe_pdf_open
from pdfrecon.config import PDFCorruptionError

class TestSafePdfOpen(unittest.TestCase):

    @patch('pdfrecon.pdf_processor.fitz.open')
    def test_safe_pdf_open_filepath(self, mock_fitz_open):
        """Test safe_pdf_open with a file path."""
        # Setup mock
        mock_doc = MagicMock()
        mock_fitz_open.return_value = mock_doc

        filepath = Path("test.pdf")

        # Execute
        result = safe_pdf_open(filepath)

        # Verify
        mock_fitz_open.assert_called_once_with(str(filepath))
        self.assertEqual(result, mock_doc)

    @patch('pdfrecon.pdf_processor.fitz.open')
    def test_safe_pdf_open_raw_bytes(self, mock_fitz_open):
        """Test safe_pdf_open with raw bytes."""
        # Setup mock
        mock_doc = MagicMock()
        mock_fitz_open.return_value = mock_doc

        filepath = Path("test.pdf")
        raw_bytes = b"%PDF-1.4..."

        # Execute
        result = safe_pdf_open(filepath, raw_bytes=raw_bytes)

        # Verify
        mock_fitz_open.assert_called_once_with(stream=raw_bytes, filetype="pdf")
        self.assertEqual(result, mock_doc)

    @patch('pdfrecon.pdf_processor.fitz.open')
    def test_safe_pdf_open_exception(self, mock_fitz_open):
        """Test safe_pdf_open raises PDFCorruptionError on exception."""
        # Setup mock to raise exception
        mock_fitz_open.side_effect = RuntimeError("Mock error")

        filepath = Path("test.pdf")

        # Execute and Verify
        with self.assertRaises(PDFCorruptionError) as cm:
            safe_pdf_open(filepath)

        self.assertIn("Cannot open PDF: Mock error", str(cm.exception))

if __name__ == '__main__':
    unittest.main()
