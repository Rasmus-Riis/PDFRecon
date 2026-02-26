import unittest
from unittest.mock import MagicMock
import sys
import os

# Add project root to path so we can import pdfrecon
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from pdfrecon.advanced_forensics import detect_hidden_text_patterns

class TestHiddenTextPatterns(unittest.TestCase):

    def test_invisible_text_mode(self):
        """Test detection of text rendering mode 3 (invisible)."""
        txt = "Some content /F1 10 Tf 3 Tr (Hidden) Tj"
        doc = MagicMock()
        indicators = {}
        detect_hidden_text_patterns(txt, doc, indicators)
        self.assertIn('InvisibleTextMode', indicators)
        self.assertEqual(indicators['InvisibleTextMode']['status'], 'Text rendering mode 3 (invisible) detected')

    def test_excessive_white_color(self):
        """Test detection of excessive white color usage."""
        # Create a string with > 20 occurrences of "1 1 1 RG" or "1 1 1 rg"
        txt = "1 1 1 RG " * 21
        doc = MagicMock()
        indicators = {}
        detect_hidden_text_patterns(txt, doc, indicators)
        self.assertIn('ExcessiveWhiteColor', indicators)
        self.assertEqual(indicators['ExcessiveWhiteColor']['count'], 21)

    def test_text_outside_mediabox(self):
        """Test detection of text outside the MediaBox."""
        txt = "Clean content"
        doc = MagicMock()
        # Mocking page iteration
        page = MagicMock()
        doc.__getitem__.return_value = page
        doc.__len__.return_value = 1

        # Mediabox: (0, 0, 595, 842) - Standard A4
        page.mediabox = (0, 0, 595, 842)

        # Text block far outside: e.g., x=800 (595+100=695 is the limit)
        # Bbox format: (x0, y0, x1, y1)
        outside_bbox = (800, 100, 850, 120)

        blocks = {
            "blocks": [
                {
                    "lines": [
                        {"bbox": outside_bbox}
                    ]
                }
            ]
        }
        page.get_text.return_value = blocks

        indicators = {}
        detect_hidden_text_patterns(txt, doc, indicators)
        self.assertIn('TextOutsideMediaBox', indicators)
        self.assertEqual(indicators['TextOutsideMediaBox']['page'], 1)

    def test_no_patterns(self):
        """Test with clean input containing no suspicious patterns."""
        txt = "Normal content with 0 Tr"
        doc = MagicMock()
        doc.__len__.return_value = 1
        page = MagicMock()
        doc.__getitem__.return_value = page
        page.mediabox = (0, 0, 595, 842)

        # Normal bbox inside page
        normal_bbox = (100, 100, 200, 120)
        blocks = {
            "blocks": [
                {
                    "lines": [
                        {"bbox": normal_bbox}
                    ]
                }
            ]
        }
        page.get_text.return_value = blocks

        indicators = {}
        detect_hidden_text_patterns(txt, doc, indicators)
        self.assertEqual(len(indicators), 0)

if __name__ == '__main__':
    unittest.main()
