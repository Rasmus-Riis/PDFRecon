import unittest
from unittest.mock import MagicMock, patch
import time
from pdfrecon.pdf_processor import safe_extract_text

class TestSafeExtractText(unittest.TestCase):

    def test_max_size_limit(self):
        # Create a byte string slightly larger than max_size_mb (50MB by default)
        # Using 1MB max_size for test to save memory/time
        max_size_mb = 1
        raw_bytes = b"0" * ((max_size_mb * 1024 * 1024) + 1)

        with patch('pdfrecon.pdf_processor.logging.warning') as mock_log:
            result = safe_extract_text(raw_bytes=raw_bytes, max_size_mb=max_size_mb)
            self.assertEqual(result, "")
            mock_log.assert_called_with(f"PDF too large for text extraction: {len(raw_bytes) / (1024*1024):.1f}MB")

    def test_suspicious_patterns_objstm(self):
        raw_bytes = b"start /ObjStm end"
        with patch('pdfrecon.pdf_processor.logging.warning') as mock_log:
            result = safe_extract_text(raw_bytes=raw_bytes)
            self.assertEqual(result, "")
            mock_log.assert_called_with("PDF contains suspicious patterns (streams or object streams), skipping full extraction")

    def test_suspicious_patterns_streams(self):
        raw_bytes = b"stream" * 101
        with patch('pdfrecon.pdf_processor.logging.warning') as mock_log:
            result = safe_extract_text(raw_bytes=raw_bytes)
            self.assertEqual(result, "")
            mock_log.assert_called_with("PDF contains suspicious patterns (streams or object streams), skipping full extraction")

    @patch('pdfrecon.pdf_processor.fitz.open')
    @patch('pdfrecon.pdf_processor.time.time')
    def test_timeout_limit(self, mock_time, mock_fitz_open):
        # Setup mock doc with 20 pages
        mock_doc = MagicMock()
        mock_doc.__len__.return_value = 20
        mock_page = MagicMock()
        mock_page.get_text.return_value = "text"
        mock_doc.__getitem__.return_value = mock_page
        mock_fitz_open.return_value = mock_doc

        # Configure time.time to simulate timeout
        # First call is start_time
        # Loop checks every 10 pages (at index 0, 10, 20...)
        # We want it to pass at 0, fail at 10.

        # side_effect: start_time, check_0 (pass), check_10 (fail)
        # check_0: time - start < timeout
        # check_10: time - start > timeout

        timeout = 5
        start_t = 100.0

        # Sequence of time.time() calls:
        # 1. start_time assignment
        # 2. inside loop: check if page_num % 10 == 0
        #    Wait, the code calls time.time() ONLY if page_num % 10 == 0

        # Iteration 0:
        #   check condition: page_num (0) % 10 == 0 -> True. call time.time()
        # Iteration 1..9:
        #   check condition: page_num % 10 != 0 -> False. No time.time() call.
        # Iteration 10:
        #   check condition: page_num (10) % 10 == 0 -> True. call time.time()

        # So we need mock_time to return:
        # 1. start_time (100.0)
        # 2. check at page 0 (101.0) -> 101-100 = 1 < 5 (OK)
        # 3. check at page 10 (110.0) -> 110-100 = 10 > 5 (Timeout!)
        # 4. logging.warning calls time.time() again for the message!

        mock_time.side_effect = [start_t, start_t + 1, start_t + 10, start_t + 10]

        with patch('pdfrecon.pdf_processor.logging.warning') as mock_log:
            result = safe_extract_text(raw_bytes=b"dummy", timeout_seconds=timeout)

            # Should process pages 0 to 9. Page 10 check fails, so break loop.
            # Total pages processed: 10.
            # Text length: 10 * 4 ("text") = 40?
            # Wait, page 10 check happens BEFORE processing page 10.
            # So pages 0..9 are processed. Page 10 is NOT processed.

            self.assertEqual(mock_doc.__getitem__.call_count, 10)
            self.assertEqual(result, "text" * 10)
            mock_log.assert_called_with(f"Text extraction timeout after 10.0s, stopping at page 10/20")

    @patch('pdfrecon.pdf_processor.fitz.open')
    def test_page_limit(self, mock_fitz_open):
        mock_doc = MagicMock()
        mock_doc.__len__.return_value = 1500
        mock_page = MagicMock()
        mock_page.get_text.return_value = "a"
        mock_doc.__getitem__.return_value = mock_page
        mock_fitz_open.return_value = mock_doc

        result = safe_extract_text(raw_bytes=b"dummy")

        # Should stop at 1000
        self.assertEqual(len(result), 1000)
        self.assertEqual(mock_doc.__getitem__.call_count, 1000)

    @patch('pdfrecon.pdf_processor.fitz.open')
    def test_text_accumulation_limit(self, mock_fitz_open):
        mock_doc = MagicMock()
        mock_doc.__len__.return_value = 100
        mock_page = MagicMock()
        # Return 1MB text per page
        mock_page.get_text.return_value = "a" * (1024 * 1024)
        mock_doc.__getitem__.return_value = mock_page
        mock_fitz_open.return_value = mock_doc

        # Limit is 50MB.
        # 1MB per page.
        # Should process 50 pages?
        # Check: if len(txt) > 50MB: break
        # Page 0: len=1MB. Check > 50MB? No.
        # ...
        # Page 50: len=51MB. Check > 50MB? Yes. Break.
        # So it processes 51 pages.

        with patch('pdfrecon.pdf_processor.logging.warning') as mock_log:
            result = safe_extract_text(raw_bytes=b"dummy")

            self.assertEqual(mock_doc.__getitem__.call_count, 51)
            self.assertTrue(len(result) >= 50 * 1024 * 1024)
            mock_log.assert_called_with("Text extraction exceeded 50MB limit, stopping at page 50/100")

    @patch('pdfrecon.pdf_processor.fitz.open')
    def test_happy_path(self, mock_fitz_open):
        mock_doc = MagicMock()
        mock_doc.__len__.return_value = 5
        mock_page = MagicMock()
        mock_page.get_text.return_value = "page"
        mock_doc.__getitem__.return_value = mock_page
        mock_fitz_open.return_value = mock_doc

        result = safe_extract_text(raw_bytes=b"dummy")
        self.assertEqual(result, "page" * 5)

    @patch('pdfrecon.pdf_processor.fitz.open')
    def test_extraction_error(self, mock_fitz_open):
        mock_doc = MagicMock()
        mock_doc.__len__.return_value = 3

        mock_page = MagicMock()
        mock_page.get_text.return_value = "ok"

        # Page 0: ok
        # Page 1: raise Exception
        # Page 2: ok

        def get_page(idx):
            if idx == 1:
                raise ValueError("Page error")
            return mock_page

        mock_doc.__getitem__.side_effect = get_page
        mock_fitz_open.return_value = mock_doc

        with patch('pdfrecon.pdf_processor.logging.warning') as mock_log:
            result = safe_extract_text(raw_bytes=b"dummy")

            # Should have text from page 0 and 2.
            self.assertEqual(result, "okok")
            mock_log.assert_called_with("Error extracting page 1: Page error")

if __name__ == '__main__':
    unittest.main()
