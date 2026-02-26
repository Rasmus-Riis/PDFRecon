import unittest
import fitz
import sys
import os

# Add the parent directory to sys.path to allow importing pdfrecon
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pdfrecon.pdf_processor import count_layers

class TestCountLayers(unittest.TestCase):
    def test_count_layers_basic(self):
        """Test counting layers in a PDF with explicit OCGs."""
        doc = fitz.open()

        # Add 5 layers
        for i in range(5):
            try:
                doc.add_ocg(f"Layer {i}")
            except AttributeError:
                # If add_ocg is not available, we can't create layers this way.
                # Assuming PyMuPDF is recent enough.
                self.skipTest("PyMuPDF version too old, add_ocg missing")
                return

        page = doc.new_page()
        page.draw_rect((0,0,100,100), color=(1,0,0)) # No layer

        pdf_bytes = doc.tobytes()
        doc.close()

        # Verify count
        count = count_layers(pdf_bytes)
        # Note: Depending on implementation, it might count 5.
        # But wait, the original implementation only counted used layers or referenced layers?
        # The new implementation uses doc.get_ocgs() which counts defined layers.
        # So it should be 5.

        # However, the original regex implementation searched for /OCGs [...] and /OC usage.
        # Since we added OCGs, they should be in /OCGs array.

        # Wait, if I change implementation to structural parsing, the behavior might change slightly
        # if layers are defined but not used?
        # But doc.get_ocgs() returns all defined OCGs.

        # Let's see what the original implementation would do.
        # It would find /OCGs [...] and count refs.

        self.assertEqual(count, 5, f"Expected 5 layers, got {count}")

    def test_count_layers_zero(self):
        """Test counting layers in a PDF with NO layers."""
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50,50), "Hello World")
        pdf_bytes = doc.tobytes()
        doc.close()

        count = count_layers(pdf_bytes)
        self.assertEqual(count, 0, f"Expected 0 layers, got {count}")

if __name__ == '__main__':
    unittest.main()
