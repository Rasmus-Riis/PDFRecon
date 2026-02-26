import unittest
import sys
import os

# Add the parent directory to sys.path to allow importing pdfrecon
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from pdfrecon.advanced_forensics import detect_polyglot_file

class TestDetectPolyglotFile(unittest.TestCase):

    def test_no_pdf_header(self):
        # Case: No %PDF header
        pdf_bytes = b'Some random data without the header'
        indicators = {}
        detect_polyglot_file(pdf_bytes, indicators)
        self.assertIn('PolyglotFile', indicators)
        self.assertEqual(indicators['PolyglotFile']['status'], 'CRITICAL: No PDF header found')

    def test_valid_header_at_start(self):
        # Case: Header at offset 0
        pdf_bytes = b'%PDF-1.4\n...'
        indicators = {}
        detect_polyglot_file(pdf_bytes, indicators)
        self.assertNotIn('PolyglotFile', indicators)

    def test_suspicious_header_offset(self):
        # Case: Header at offset >= 512
        prefix = b'a' * 512
        pdf_bytes = prefix + b'%PDF-1.4\n...'
        indicators = {}
        detect_polyglot_file(pdf_bytes, indicators)
        self.assertIn('PolyglotFile', indicators)
        self.assertEqual(indicators['PolyglotFile']['status'], 'SUSPICIOUS')
        self.assertEqual(indicators['PolyglotFile']['pdf_header_offset'], 512)

    def test_suspicious_header_with_detected_format_zip(self):
        # Case: ZIP signature at start
        # PK\x03\x04
        prefix = b'PK\x03\x04' + b'some zip content'
        pdf_bytes = prefix + b'%PDF-1.4\n...'
        indicators = {}
        detect_polyglot_file(pdf_bytes, indicators)
        self.assertIn('PolyglotFile', indicators)
        self.assertEqual(indicators['PolyglotFile']['status'], 'SUSPICIOUS')
        self.assertIn('ZIP/Office/JAR', indicators['PolyglotFile']['detected_prefix_format'])

    def test_minor_offset(self):
        # Case: Header at small offset, no other format detected
        prefix = b'garbage'
        pdf_bytes = prefix + b'%PDF-1.4\n...'
        indicators = {}
        detect_polyglot_file(pdf_bytes, indicators)
        self.assertIn('PolyglotFile', indicators)
        self.assertEqual(indicators['PolyglotFile']['status'], 'Minor offset')
        self.assertEqual(indicators['PolyglotFile']['pdf_header_offset'], len(prefix))

    def test_header_beyond_spec(self):
        # Case: Header beyond 1024 bytes
        prefix = b'a' * 1025
        pdf_bytes = prefix + b'%PDF-1.4\n...'
        indicators = {}
        detect_polyglot_file(pdf_bytes, indicators)
        self.assertIn('PolyglotFile', indicators)
        self.assertEqual(indicators['PolyglotFile']['status'], 'CRITICAL: Header beyond spec')
        self.assertEqual(indicators['PolyglotFile']['pdf_header_offset'], 1025)

if __name__ == '__main__':
    unittest.main()
