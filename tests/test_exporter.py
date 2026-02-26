import unittest
from pdfrecon.exporter import format_indicator_details

class TestFormatIndicatorDetails(unittest.TestCase):

    def test_empty_details(self):
        """Test with empty or None details."""
        self.assertEqual(format_indicator_details("MyIndicator", None), "MyIndicator")
        self.assertEqual(format_indicator_details("MyIndicator", {}), "MyIndicator")

    def test_count_indicator(self):
        """Test details with 'count' key."""
        details = {'count': 5}
        expected = "MyIndicator (5)"
        self.assertEqual(format_indicator_details("MyIndicator", details), expected)

    def test_text_indicator_short(self):
        """Test details with 'text' key (short text)."""
        details = {'text': "Short text"}
        expected = "MyIndicator: Short text..."
        self.assertEqual(format_indicator_details("MyIndicator", details), expected)

    def test_text_indicator_long(self):
        """Test details with 'text' key (long text, should be truncated)."""
        long_text = "A" * 60
        details = {'text': long_text}
        expected = f"MyIndicator: {long_text[:50]}..."
        self.assertEqual(format_indicator_details("MyIndicator", details), expected)

    def test_fonts_indicator(self):
        """Test details with 'fonts' key."""
        details = {'fonts': ['Arial', 'Times New Roman']}
        expected = "MyIndicator (2 fonts)"
        self.assertEqual(format_indicator_details("MyIndicator", details), expected)

        # Test empty fonts list
        details = {'fonts': []}
        expected = "MyIndicator (0 fonts)"
        self.assertEqual(format_indicator_details("MyIndicator", details), expected)

    def test_items_indicator(self):
        """Test details with 'items' key."""
        details = {'items': ['item1', 'item2', 'item3']}
        expected = "MyIndicator (3 items)"
        self.assertEqual(format_indicator_details("MyIndicator", details), expected)

        # Test empty items list
        details = {'items': []}
        expected = "MyIndicator (0 items)"
        self.assertEqual(format_indicator_details("MyIndicator", details), expected)

    def test_precedence(self):
        """Test precedence of keys in details dict."""
        # count vs text -> count wins
        details = {'count': 10, 'text': 'some text'}
        self.assertEqual(format_indicator_details("MyIndicator", details), "MyIndicator (10)")

        # text vs fonts -> text wins
        details = {'text': 'some text', 'fonts': ['f1']}
        self.assertEqual(format_indicator_details("MyIndicator", details), "MyIndicator: some text...")

        # fonts vs items -> fonts wins
        details = {'fonts': ['f1'], 'items': ['i1']}
        self.assertEqual(format_indicator_details("MyIndicator", details), "MyIndicator (1 fonts)")

    def test_items_not_list(self):
        """Test details with 'items' key but value is not a list."""
        details = {'items': 'not a list'}
        # Should fall through to return key because `isinstance(details['items'], list)` check fails
        self.assertEqual(format_indicator_details("MyIndicator", details), "MyIndicator")

    def test_non_dict_details(self):
        """Test with details not being a dict."""
        self.assertEqual(format_indicator_details("MyIndicator", "Not a dict"), "MyIndicator")
        self.assertEqual(format_indicator_details("MyIndicator", 123), "MyIndicator")

    def test_unknown_keys(self):
        """Test details dict with no recognized keys."""
        details = {'unknown': 'value'}
        self.assertEqual(format_indicator_details("MyIndicator", details), "MyIndicator")

if __name__ == '__main__':
    unittest.main()
