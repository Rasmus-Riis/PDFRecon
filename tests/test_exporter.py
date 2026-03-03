import unittest
from pdfrecon.exporter import format_indicator_details, clean_cell_value

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
        expected = "MyIndicator (Short text)"
        self.assertEqual(format_indicator_details("MyIndicator", details), expected)

    def test_text_indicator_long(self):
        """Test details with 'text' key (long text, should be truncated)."""
        long_text = "A" * 60
        details = {'text': long_text}
        expected = f"MyIndicator ({long_text[:50]}...)"
        self.assertEqual(format_indicator_details("MyIndicator", details), expected)

    def test_fonts_indicator(self):
        """Test details with 'fonts' key."""
        details = {'fonts': ['Arial', 'Times New Roman']}
        expected = "MyIndicator (2 fonts)"
        self.assertEqual(format_indicator_details("MyIndicator", details), expected)

    def test_items_indicator(self):
        """Test details with 'items' key."""
        details = {'items': ['item1', 'item2', 'item3']}
        expected = "MyIndicator (3 items)"
        self.assertEqual(format_indicator_details("MyIndicator", details), expected)

    def test_empty_items_list(self):
        details = {'items': []}
        expected = "MyIndicator (0 items)"
        self.assertEqual(format_indicator_details("MyIndicator", details), expected)

    def test_precedence(self):
        """Test precedence of keys in details dict."""
        # count vs text -> count wins
        details = {'count': 10, 'text': 'some text'}
        expected = "MyIndicator (10)"
        self.assertEqual(format_indicator_details("MyIndicator", details), expected)

    def test_text_vs_fonts(self):
        """Test text vs fonts -> text wins"""
        details = {'text': 'some text', 'fonts': ['f1']}
        expected = "MyIndicator (some text)"
        self.assertEqual(format_indicator_details("MyIndicator", details), expected)

    def test_items_not_list(self):
        """Test items key but value is not a list."""
        details = {'items': 'not a list'}
        # Should fall through to return key because !isinstance(details['items'], list)
        self.assertEqual(format_indicator_details("MyIndicator", details), "MyIndicator")

    def test_non_dict_details(self):
        """Test with details not being a dict."""
        self.assertEqual(format_indicator_details("MyIndicator", "Not a dict"), "MyIndicator")
        self.assertEqual(format_indicator_details("MyIndicator", 123), "MyIndicator")

    def test_unknown_keys(self):
        """Test details dict with no recognized keys."""
        details = {'unknown': 'value'}
        self.assertEqual(format_indicator_details("MyIndicator", details), "MyIndicator")

class TestExporter(unittest.TestCase):
    def test_clean_cell_value_none(self):
        """Test clean_cell_value with None input."""
        self.assertEqual(clean_cell_value(None), "")

    def test_clean_cell_value_basic(self):
        """Test clean_cell_value with a basic string."""
        self.assertEqual(clean_cell_value("hello world"), "hello world")
        self.assertEqual(clean_cell_value("123"), "123")

    def test_clean_cell_value_control_chars(self):
        """test_clean_cell_value removes control characters."""
        # \x01 is a control character that should be removed
        self.assertEqual(clean_cell_value("hello\x01world"), "helloworld")
        # \x08 is backspace, should be removed
        self.assertEqual(clean_cell_value("hello\x08world"), "helloworld")

    def test_clean_cell_value_allowed_control_chars(self):
        """test_clean_cell_value preserves allowed control characters."""
        # \t, \n, \r should be preserved
        self.assertEqual(clean_cell_value("hello\tworld"), "hello\tworld")
        self.assertEqual(clean_cell_value("hello\nworld"), "hello\nworld")
        self.assertEqual(clean_cell_value("hello\rworld"), "hello\rworld")

    def test_clean_cell_value_bom(self):
        """test_clean_cell_value removes BOM characters."""
        # UTF-8 BOM
        self.assertEqual(clean_cell_value("\xef\xbb\xbfhello"), "hello")
        # UTF-16 BE BOM (as string representation if it occurs)
        self.assertEqual(clean_cell_value("\ufeffhello"), "hello")

    def test_clean_cell_value_mojibake(self):
        """test_clean_cell_value removes mojibake sequences."""
        self.assertEqual(clean_cell_value("Pjhello"), "hello")

    def test_clean_cell_value_null_byte(self):
        """test_clean_cell_value removes null bytes."""
        self.assertEqual(clean_cell_value("hello\0world"), "helloworld")

    def test_clean_cell_value_mixed(self):
        """test_clean_cell_value with mixed issues."""
        # BOM + control char + mojibake + null byte
        dirty_string = "\ufeffPjhello\x01world\0"
        # The function removes control characters, BOM, mojibake, and null bytes.
        # Even if they appear together, the result should be clean.
        self.assertEqual(clean_cell_value(dirty_string), "helloworld")

if __name__ == '__main__':
    unittest.main()