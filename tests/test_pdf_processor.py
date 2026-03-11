import unittest
from src.pdf_processor import count_layers

class TestCountLayers(unittest.TestCase):
    def test_no_layers(self):
        """Test count_layers with bytes containing no layer information."""
        pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        self.assertEqual(count_layers(pdf_bytes), 0)

    def test_ocgs_block(self):
        """Test count_layers with a simple /OCGs block."""
        # Represents /OCGs [ 10 0 R 11 0 R ]
        pdf_bytes = b"1 0 obj\n<< /OCGs [ 10 0 R 11 0 R ] >>\nendobj\n"
        self.assertEqual(count_layers(pdf_bytes), 2)

    def test_oc_refs(self):
        """Test count_layers with /OC references scattered in the content."""
        # Represents content with /OC 12 0 R and /OC 13 0 R
        pdf_bytes = b"stream\n/OC 12 0 R\n...\n/OC 13 0 R\nendstream\n"
        self.assertEqual(count_layers(pdf_bytes), 2)

    def test_mixed_layers(self):
        """Test count_layers with both /OCGs block and /OC references."""
        # /OCGs [ 10 0 R ] and /OC 12 0 R
        pdf_bytes = b"<< /OCGs [ 10 0 R ] >>\nstream\n/OC 12 0 R\nendstream\n"
        self.assertEqual(count_layers(pdf_bytes), 2)

    def test_duplicates(self):
        """Test count_layers with duplicate references."""
        # /OCGs [ 10 0 R 10 0 R ] and /OC 10 0 R
        pdf_bytes = b"<< /OCGs [ 10 0 R 10 0 R ] >>\nstream\n/OC 10 0 R\nendstream\n"
        self.assertEqual(count_layers(pdf_bytes), 1)

    def test_regex_robustness(self):
        """Test regex robustness with varying whitespace."""
        # /OCGs[10 0 R] (no space)
        # /OCGs  [  11  0  R  ] (extra spaces)
        # Note: OBJ_REF_RE expects (\d+)\s+(\d+)\s+R, so "11  0  R" matches because \s+ handles multiple spaces.
        # LAYER_OC_REF_RE also expects /OC\s+(\d+)\s+(\d+)\s+R.

        # Case 1: /OCGs tight spacing
        pdf_bytes_1 = b"<< /OCGs[10 0 R] >>"
        self.assertEqual(count_layers(pdf_bytes_1), 1)

        # Case 2: /OC with extra spaces
        pdf_bytes_2 = b"/OC  11  0  R"
        self.assertEqual(count_layers(pdf_bytes_2), 1)

        # Case 3: Combined
        pdf_bytes_3 = b"<< /OCGs[10 0 R] >>\n/OC  11  0  R"
        self.assertEqual(count_layers(pdf_bytes_3), 2)

if __name__ == "__main__":
    unittest.main()
