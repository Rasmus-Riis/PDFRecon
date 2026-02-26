
import unittest
from unittest.mock import MagicMock
import sys
from pathlib import Path

# Ensure pdfrecon can be imported
sys.path.append(str(Path(__file__).parent.parent))

from pdfrecon.scanner import _detect_image_anomalies

class TestImageExtraction(unittest.TestCase):
    def test_duplicate_detection(self):
        """Test that duplicate images with different XREFs are detected."""
        doc = MagicMock()
        doc.__len__.return_value = 1
        # Page 0 has two images: xref 1 and xref 2
        # Mock get_page_images(page_num) -> [(xref, smask, ...)]
        doc.get_page_images.return_value = [(1, 0, 0, 0, 0, 0, 0, 0, 0), (2, 0, 0, 0, 0, 0, 0, 0, 0)]

        # Both images have SAME content
        content = b"fake_image_content"
        # xref_stream returns content for both xrefs
        doc.xref_stream.side_effect = lambda x: content

        indicators = {}
        # Call the function
        _detect_image_anomalies(doc, Path("dummy.pdf"), indicators)

        # Should detect duplicate
        self.assertIn('DuplicateImagesWithDifferentXrefs', indicators, "Should detect duplicate images")
        details = indicators['DuplicateImagesWithDifferentXrefs']
        # The order of xrefs depends on processing order.
        # First one (1) is processed, added to map. Second one (2) triggers detection.
        # So xrefs should be [1, 2]
        self.assertEqual(sorted(details['xrefs']), [1, 2])

        # Verify xref_stream was called twice (once for each xref)
        self.assertEqual(doc.xref_stream.call_count, 2)

    def test_exif_detection(self):
        """Test that images with EXIF data are counted correctly."""
        doc = MagicMock()
        doc.__len__.return_value = 1
        # Page 0 has one image, xref 1
        doc.get_page_images.return_value = [(1, 0, 0, 0, 0, 0, 0, 0, 0)]

        # Image content has "Exif" header
        # Using b"Exif" string directly as per logic: b"Exif" in img_bytes[:1000]
        content = b"\xff\xd8\xff\xe1\x00\x10Exif\x00\x00" + b"A"*100
        doc.xref_stream.return_value = content

        indicators = {}
        _detect_image_anomalies(doc, Path("dummy.pdf"), indicators)

        self.assertIn('ImagesWithEXIF', indicators)
        self.assertEqual(indicators['ImagesWithEXIF']['count'], 1)

    def test_caching_behavior(self):
        """Test that repeated image XREFs are cached and not re-extracted."""
        doc = MagicMock()
        # Document has 2 pages
        doc.__len__.return_value = 2

        # Page 0 has image 1. Page 1 has image 1.
        # Both pages reference the SAME image object (xref=1)
        image_list = [(1, 0, 0, 0, 0, 0, 0, 0, 0)]
        doc.get_page_images.side_effect = [image_list, image_list]

        content = b"unique_content"
        doc.xref_stream.return_value = content

        indicators = {}
        _detect_image_anomalies(doc, Path("dummy.pdf"), indicators)

        # doc.xref_stream should be called ONLY ONCE for xref 1
        doc.xref_stream.assert_called_once_with(1)

        # Verify no indicators if content is normal
        self.assertNotIn('DuplicateImagesWithDifferentXrefs', indicators)
        self.assertNotIn('ImagesWithEXIF', indicators)

    def test_caching_with_exif(self):
        """Test that caching preserves EXIF detection for repeated images."""
        doc = MagicMock()
        doc.__len__.return_value = 2

        # Page 0 has image 1. Page 1 has image 1.
        image_list = [(1, 0, 0, 0, 0, 0, 0, 0, 0)]
        doc.get_page_images.side_effect = [image_list, image_list]

        # Image has Exif
        content = b"SomeHeaderExifData..."
        doc.xref_stream.return_value = content

        indicators = {}
        _detect_image_anomalies(doc, Path("dummy.pdf"), indicators)

        # doc.xref_stream called once
        doc.xref_stream.assert_called_once_with(1)

        # Count should be 2 because it appears on 2 pages
        self.assertIn('ImagesWithEXIF', indicators)
        self.assertEqual(indicators['ImagesWithEXIF']['count'], 2)

if __name__ == '__main__':
    unittest.main()
