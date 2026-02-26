import unittest
from unittest.mock import MagicMock
from pdfrecon.advanced_forensics import detect_language

class TestDetectLanguage(unittest.TestCase):
    def setUp(self):
        self.doc = MagicMock()
        self.indicators = {}

    def test_doc_none(self):
        """Test detect_language with doc as None."""
        detect_language(None, self.indicators)
        self.assertEqual(self.indicators, {})

    def test_no_language(self):
        """Test detect_language with no language info."""
        self.doc.metadata = {}
        self.doc.pdf_catalog.return_value = {}
        detect_language(self.doc, self.indicators)
        self.assertNotIn('Languages', self.indicators)

    def test_metadata_language(self):
        """Test detect_language with language in metadata."""
        self.doc.metadata = {'language': 'en-US'}
        self.doc.pdf_catalog.return_value = {}
        detect_language(self.doc, self.indicators)
        self.assertIn('Languages', self.indicators)
        self.assertEqual(self.indicators['Languages']['count'], 1)
        self.assertIn('en-US', self.indicators['Languages']['languages'])

    def test_catalog_language(self):
        """Test detect_language with language in catalog."""
        self.doc.metadata = {}
        self.doc.pdf_catalog.return_value = {'/Lang': 'fr-FR'}
        detect_language(self.doc, self.indicators)
        self.assertIn('Languages', self.indicators)
        self.assertEqual(self.indicators['Languages']['count'], 1)
        self.assertIn('fr-FR', self.indicators['Languages']['languages'])

    def test_both_languages_different(self):
        """Test detect_language with different languages in metadata and catalog."""
        self.doc.metadata = {'language': 'en-US'}
        self.doc.pdf_catalog.return_value = {'/Lang': 'fr-FR'}
        detect_language(self.doc, self.indicators)
        self.assertIn('Languages', self.indicators)
        self.assertEqual(self.indicators['Languages']['count'], 2)
        self.assertIn('en-US', self.indicators['Languages']['languages'])
        self.assertIn('fr-FR', self.indicators['Languages']['languages'])

    def test_both_languages_same(self):
        """Test detect_language with same language in metadata and catalog."""
        self.doc.metadata = {'language': 'en-US'}
        self.doc.pdf_catalog.return_value = {'/Lang': 'en-US'}
        detect_language(self.doc, self.indicators)
        self.assertIn('Languages', self.indicators)
        self.assertEqual(self.indicators['Languages']['count'], 1)
        self.assertIn('en-US', self.indicators['Languages']['languages'])

    def test_catalog_exception(self):
        """Test detect_language when catalog access raises exception."""
        self.doc.metadata = {'language': 'en-US'}
        self.doc.pdf_catalog.side_effect = Exception("Catalog error")
        detect_language(self.doc, self.indicators)
        self.assertIn('Languages', self.indicators)
        self.assertEqual(self.indicators['Languages']['count'], 1)
        self.assertIn('en-US', self.indicators['Languages']['languages'])

    def test_metadata_none(self):
        """Test detect_language when metadata is None."""
        self.doc.metadata = None
        self.doc.pdf_catalog.return_value = {'/Lang': 'fr-FR'}
        detect_language(self.doc, self.indicators)
        self.assertIn('Languages', self.indicators)
        self.assertEqual(self.indicators['Languages']['count'], 1)
        self.assertIn('fr-FR', self.indicators['Languages']['languages'])

if __name__ == '__main__':
    unittest.main()
