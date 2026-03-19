import unittest
from src.advanced_forensics import detect_structural_scrubbing

class TestStructuralScrubbing(unittest.TestCase):
    def test_no_scrubbing(self):
        pdf_bytes = b"Just some normal text"
        indicators = {}
        detect_structural_scrubbing(pdf_bytes, indicators)
        self.assertNotIn('StructuralScrubbing', indicators)

    def test_null_scrubbing(self):
        pdf_bytes = b"Start" + b"\x00" * 250 + b"End"
        indicators = {}
        detect_structural_scrubbing(pdf_bytes, indicators)
        self.assertIn('StructuralScrubbing', indicators)
        self.assertEqual(indicators['StructuralScrubbing']['count'], 1)

    def test_space_scrubbing(self):
        pdf_bytes = b"Start" + b" " * 1500 + b"End"
        indicators = {}
        detect_structural_scrubbing(pdf_bytes, indicators)
        self.assertIn('StructuralScrubbing', indicators)
        self.assertEqual(indicators['StructuralScrubbing']['count'], 1)

    def test_both_scrubbing(self):
        pdf_bytes = b"Start" + b"\x00" * 250 + b"Middle" + b" " * 1500 + b"End"
        indicators = {}
        detect_structural_scrubbing(pdf_bytes, indicators)
        self.assertIn('StructuralScrubbing', indicators)
        self.assertEqual(indicators['StructuralScrubbing']['count'], 2)

if __name__ == '__main__':
    unittest.main()
