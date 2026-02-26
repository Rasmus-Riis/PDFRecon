import unittest
from pdfrecon.exporter import clean_cell_value

class TestExporter(unittest.TestCase):

    def test_clean_cell_value_none(self):
        """Test clean_cell_value with None input."""
        self.assertEqual(clean_cell_value(None), "")

    def test_clean_cell_value_basic(self):
        """Test clean_cell_value with a basic string."""
        self.assertEqual(clean_cell_value("hello world"), "hello world")
        self.assertEqual(clean_cell_value(123), "123")

    def test_clean_cell_value_control_chars(self):
        """Test clean_cell_value removes control characters."""
        # \x01 is a control character that should be removed
        self.assertEqual(clean_cell_value("hello\x01world"), "helloworld")
        # \x08 is backspace, should be removed
        self.assertEqual(clean_cell_value("hello\x08world"), "helloworld")

    def test_clean_cell_value_allowed_control_chars(self):
        """Test clean_cell_value preserves allowed control characters."""
        # \t, \n, \r should be preserved
        self.assertEqual(clean_cell_value("hello\tworld"), "hello\tworld")
        self.assertEqual(clean_cell_value("hello\nworld"), "hello\nworld")
        self.assertEqual(clean_cell_value("hello\rworld"), "hello\rworld")

    def test_clean_cell_value_bom(self):
        """Test clean_cell_value removes BOM characters."""
        # UTF-8 BOM
        self.assertEqual(clean_cell_value("\ufeffhello"), "hello")
        # UTF-16 BE BOM (as string representation if it occurs)
        self.assertEqual(clean_cell_value("\ufffehello"), "hello")

    def test_clean_cell_value_mojibake(self):
        """Test clean_cell_value removes mojibake sequences."""
        self.assertEqual(clean_cell_value("þÿhello"), "hello")
        self.assertEqual(clean_cell_value("ÿþhello"), "hello")

    def test_clean_cell_value_null_byte(self):
        """Test clean_cell_value removes null bytes."""
        self.assertEqual(clean_cell_value("hello\x00world"), "helloworld")

    def test_clean_cell_value_mixed(self):
        """Test clean_cell_value with mixed issues."""
        # BOM + control char + mojibake + null byte
        dirty_string = "\ufeffþÿhello\x01world\x00"
        # The function removes control characters, BOM, mojibake, and null bytes.
        # Even if they appear together, the result should be clean.
        self.assertEqual(clean_cell_value(dirty_string), "helloworld")

if __name__ == '__main__':
    unittest.main()
