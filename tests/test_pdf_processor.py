import unittest
from unittest.mock import MagicMock, patch
from pdfrecon.pdf_processor import safe_extract_text

class TestSafeExtractText(unittest.TestCase):

    def test_safe_extract_text_timeout(self):
        """Test that safe_extract_text stops when timeout is exceeded."""

        # Create a mock document with 20 pages
        mock_doc = MagicMock()
        mock_doc.__len__.return_value = 20

        # Mock pages to return "Page N "
        def get_page(idx):
            mock_page = MagicMock()
            mock_page.get_text.return_value = f"Page {idx} "
            return mock_page

        mock_doc.__getitem__.side_effect = get_page

        # Mock time.time to simulate timeout
        with patch('pdfrecon.pdf_processor.time') as mock_time_module:
            # Side effect logic:
            # Call 1: start_time = time.time() -> 0
            # Call 2: Loop page 0. Check (0 % 10 == 0). time.time() -> 0. Diff=0. Continue.
            # Pages 1-9: Loop continues. No check (page % 10 != 0). No time.time() calls.
            # Call 3: Loop page 10. Check (10 % 10 == 0). time.time() -> 100. Diff=100 > 15. Break.
            # Subsequent calls (logging etc) -> 100
            def time_side_effect():
                calls = getattr(time_side_effect, 'calls', 0)
                time_side_effect.calls = calls + 1
                if calls < 2:
                    return 0.0
                return 100.0

            mock_time_module.time.side_effect = time_side_effect

            # Run extraction with timeout of 15 seconds
            result = safe_extract_text(doc=mock_doc, timeout_seconds=15)

            # Expected text: "Page 0 " to "Page 9 "
            expected_text = "".join([f"Page {i} " for i in range(10)])

            self.assertEqual(result, expected_text)

            # Verify that only pages 0-9 were accessed (10 calls)
            self.assertEqual(mock_doc.__getitem__.call_count, 10)

            # Verify arguments
            calls = mock_doc.__getitem__.call_args_list
            for i, call in enumerate(calls):
                self.assertEqual(call[0][0], i)

    def test_safe_extract_text_success(self):
        """Test that safe_extract_text completes successfully within timeout."""

        mock_doc = MagicMock()
        mock_doc.__len__.return_value = 5

        def get_page(idx):
            mock_page = MagicMock()
            mock_page.get_text.return_value = f"Page {idx} "
            return mock_page

        mock_doc.__getitem__.side_effect = get_page

        with patch('pdfrecon.pdf_processor.time') as mock_time_module:
            # Time stays constant, so no timeout
            mock_time_module.time.return_value = 0.0

            result = safe_extract_text(doc=mock_doc, timeout_seconds=15)

            expected_text = "".join([f"Page {i} " for i in range(5)])
            self.assertEqual(result, expected_text)
            self.assertEqual(mock_doc.__getitem__.call_count, 5)

if __name__ == '__main__':
    unittest.main()
