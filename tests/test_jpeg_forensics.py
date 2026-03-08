import unittest
from src.jpeg_forensics import extract_jpeg_qt_from_bytes, KNOWN_QT_SIGNATURES

class TestExtractJpegQtFromBytes(unittest.TestCase):

    def test_valid_jpeg_extraction(self):
        # Construct a valid JPEG with a known QT table
        # SOI (FF D8)
        # DQT (FF DB)
        # Length (00 43) -> 67 bytes (2 for length + 1 for precision/ID + 64 for table)
        # Precision/ID (00) -> 8-bit, ID 0
        # Table (64 bytes) -> 0x01, 0x02, ... 0x40

        soi = b'\xff\xd8'
        dqt_marker = b'\xff\xdb'
        length = b'\x00\x43'
        prec_id = b'\x00'
        # Create a table with distinctive values to avoid "all identical" warning
        # but simple enough to verify signature
        qt_table = bytes(range(1, 65)) # 1 to 64

        jpeg_bytes = soi + dqt_marker + length + prec_id + qt_table + b'\xff\xd9' # EOI

        result = extract_jpeg_qt_from_bytes(jpeg_bytes)

        self.assertNotIn('error', result)
        self.assertEqual(result['table_id'], 0)
        self.assertEqual(result['precision'], '8-bit')
        self.assertEqual(len(result['full_qt']), 64)
        self.assertEqual(result['full_qt'], list(range(1, 65)))

        # Verify signature: first 16 bytes
        expected_signature = ''.join(f'{v:02x}' for v in range(1, 17))
        self.assertEqual(result['signature'], expected_signature)

    def test_invalid_jpeg_missing_soi(self):
        jpeg_bytes = b'\x00\x00' + b'\xff\xdb'
        result = extract_jpeg_qt_from_bytes(jpeg_bytes)
        self.assertEqual(result, {'error': 'Not a valid JPEG (missing SOI marker)'})

    def test_missing_dqt_marker(self):
        jpeg_bytes = b'\xff\xd8' + b'\x00\x00'
        result = extract_jpeg_qt_from_bytes(jpeg_bytes)
        self.assertEqual(result, {'error': 'No quantization table found'})

    def test_truncated_dqt_marker(self):
        # Case 1: Ends right after FF DB
        jpeg_bytes = b'\xff\xd8' + b'\xff\xdb'
        result = extract_jpeg_qt_from_bytes(jpeg_bytes)
        self.assertEqual(result, {'error': 'Truncated DQT marker'})

        # Case 2: Ends with only 1 byte of length
        jpeg_bytes = b'\xff\xd8' + b'\xff\xdb' + b'\x00'
        result = extract_jpeg_qt_from_bytes(jpeg_bytes)
        self.assertEqual(result, {'error': 'Truncated DQT marker'})

    def test_truncated_dqt_data(self):
        # Length exists, but precision byte is missing
        jpeg_bytes = b'\xff\xd8' + b'\xff\xdb' + b'\x00\x43'
        result = extract_jpeg_qt_from_bytes(jpeg_bytes)
        self.assertEqual(result, {'error': 'Truncated DQT data'})

    def test_truncated_quantization_table(self):
        # Precision byte exists, but table is incomplete
        # We need 64 bytes, provide fewer
        jpeg_bytes = b'\xff\xd8' + b'\xff\xdb' + b'\x00\x43' + b'\x00' + bytes(range(60))
        result = extract_jpeg_qt_from_bytes(jpeg_bytes)
        self.assertEqual(result, {'error': 'Truncated quantization table'})

    def test_warnings_identical_values(self):
        soi = b'\xff\xd8'
        dqt_marker = b'\xff\xdb'
        length = b'\x00\x43'
        prec_id = b'\x00'
        qt_table = b'\x05' * 64

        jpeg_bytes = soi + dqt_marker + length + prec_id + qt_table

        result = extract_jpeg_qt_from_bytes(jpeg_bytes)
        self.assertNotIn('error', result)
        self.assertIn('CRITICAL: All QT values identical (likely forged)', result['warnings'])

    def test_known_signature_matching(self):
        # Pick a known signature: Photoshop Quality 100
        # '03020202020303020202030302030303': 'Photoshop Quality 100 (Maximum)'

        sig_hex = '03020202020303020202030302030303'
        # Convert hex string to bytes
        sig_bytes = bytes.fromhex(sig_hex)

        # Fill the rest of the table with dummy data (needs 64 bytes total, signature is 16 bytes)
        qt_table = sig_bytes + bytes([10] * (64 - 16))

        soi = b'\xff\xd8'
        dqt_marker = b'\xff\xdb'
        length = b'\x00\x43'
        prec_id = b'\x00'

        jpeg_bytes = soi + dqt_marker + length + prec_id + qt_table

        result = extract_jpeg_qt_from_bytes(jpeg_bytes)
        self.assertNotIn('error', result)
        self.assertEqual(result['match'], 'Photoshop Quality 100 (Maximum)')

if __name__ == '__main__':
    unittest.main()
