import sys
import os
import pytest
import unittest.mock as mock
from pathlib import Path

# Ensure src is in the path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.scanner import _detect_object_anomalies, _detect_metadata_inconsistencies, _detect_structural_anomalies
from src.advanced_forensics import detect_stacked_filters

class TestEnhancedForensics:
    def test_detect_stacked_filters_positive(self):
        # Mock a document with multiple filters in a stream
        mock_doc = mock.Mock()
        # Mock xref_length as a property (int)
        mock_doc.xref_length = 10
        mock_doc.xref_object.return_value = "/Filter [/FlateDecode /ASCIIHexDecode]\nstream"
        
        indicators = {}
        # detect_stacked_filters(doc, txt, indicators)
        detect_stacked_filters(mock_doc, "/Filter [", indicators)
        
        assert 'StackedFilters' in indicators
        assert indicators['StackedFilters']['count'] >= 1
        assert 'FlateDecode' in indicators['StackedFilters']['details'][0]['filters']
        assert 'ASCIIHexDecode' in indicators['StackedFilters']['details'][0]['filters']

    def test_unbalanced_objects_count(self):
        # In scanner.py, _detect_object_anomalies(txt, doc, indicators)
        content = "1 0 obj ... endobj 2 0 obj ... 3 0 obj ... endobj"
        indicators = {}
        _detect_object_anomalies(content, mock.Mock(), indicators)
        
        assert 'UnbalancedObjects' in indicators
        assert indicators['UnbalancedObjects']['obj_count'] == 3
        assert indicators['UnbalancedObjects']['endobj_count'] == 2

    def test_duplicate_object_ids(self):
        content = "xref\n0 10\n0000000000 65535 f\n0000000010 00000 n\ntrailer\nxref\n0 10\n0000000000 65535 f\n0000000010 00000 n\ntrailer"
        indicators = {}
        _detect_object_anomalies(content, mock.Mock(), indicators)
        
        assert 'DuplicateObjectIDs' in indicators
        assert '0000000010' in indicators['DuplicateObjectIDs']['ids'] or '10' in indicators['DuplicateObjectIDs']['ids'] or '0' in indicators['DuplicateObjectIDs']['ids']

    def test_version_feature_contradiction(self):
        # _detect_metadata_inconsistencies(txt, txt_lower, doc, indicators)
        mock_doc = mock.Mock()
        mock_doc.pdf_version.return_value = '1.3'
        
        doc_text = "some text /ObjStm and /creator (Old Software)"
        indicators = {}
        _detect_metadata_inconsistencies(doc_text, doc_text.lower(), mock_doc, indicators)
        
        assert 'VersionFeatureContradiction' in indicators
        assert any("ObjStm" in c for c in indicators['VersionFeatureContradiction']['contradictions'])

if __name__ == "__main__":
    pytest.main([__file__])
