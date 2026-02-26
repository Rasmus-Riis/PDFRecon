import unittest
from unittest.mock import MagicMock
from pdfrecon.advanced_forensics import detect_encryption_status

class TestDetectEncryptionStatus(unittest.TestCase):

    def test_doc_is_encrypted_needs_pass(self):
        doc = MagicMock()
        doc.is_encrypted = True
        doc.needs_pass = True
        txt = ""
        indicators = {}

        detect_encryption_status(doc, txt, indicators)

        self.assertIn('Encrypted', indicators)
        self.assertEqual(indicators['Encrypted']['status'], 'Yes')
        self.assertIn('PasswordRequired', indicators)
        self.assertEqual(indicators['PasswordRequired']['status'], 'User password required')

    def test_doc_is_encrypted_no_pass_needed(self):
        doc = MagicMock()
        doc.is_encrypted = True
        doc.needs_pass = False
        txt = ""
        indicators = {}

        detect_encryption_status(doc, txt, indicators)

        self.assertIn('Encrypted', indicators)
        self.assertEqual(indicators['Encrypted']['status'], 'Yes')
        self.assertIn('EncryptedButOpen', indicators)
        self.assertEqual(indicators['EncryptedButOpen']['status'], 'Opened without password (empty or known)')

    def test_doc_not_encrypted(self):
        doc = MagicMock()
        doc.is_encrypted = False
        txt = ""
        indicators = {}

        detect_encryption_status(doc, txt, indicators)

        self.assertNotIn('Encrypted', indicators)

    def test_encryption_dictionary_regex(self):
        doc = MagicMock()
        doc.is_encrypted = False
        txt = "some content /Encrypt 123 0 R some other content"
        indicators = {}

        detect_encryption_status(doc, txt, indicators)

        self.assertIn('EncryptionDictionary', indicators)
        self.assertEqual(indicators['EncryptionDictionary']['status'], 'Encryption dictionary present')

    def test_permissions_regex_no_restrictions(self):
        # Perm value -1 means all bits set (no restrictions usually, depending on PDF version but here checking specific bits)
        doc = MagicMock()
        doc.is_encrypted = False
        txt = "/P -1"
        indicators = {}

        detect_encryption_status(doc, txt, indicators)

        self.assertNotIn('SecurityRestrictions', indicators)

    def test_permissions_regex_printing_restricted(self):
        # Bit 3 (value 4) is for printing. If 0, printing is restricted.
        # We want a negative number where bit 2 (value 4) is 0.
        # -5 is ...11111011. (-5 & 4) is 0.
        doc = MagicMock()
        doc.is_encrypted = False
        txt = "/P -5"
        indicators = {}

        detect_encryption_status(doc, txt, indicators)

        self.assertIn('SecurityRestrictions', indicators)
        self.assertEqual(indicators['SecurityRestrictions']['permissions_value'], -5)
        self.assertIn('Printing restricted', indicators['SecurityRestrictions']['restrictions'])

    def test_permissions_regex_modification_restricted(self):
        # Bit 4 (value 8) is for modification.
        # -9 is ...11110111. (-9 & 8) is 0.
        doc = MagicMock()
        doc.is_encrypted = False
        txt = "/P -9"
        indicators = {}

        detect_encryption_status(doc, txt, indicators)

        self.assertIn('SecurityRestrictions', indicators)
        self.assertIn('Modification restricted', indicators['SecurityRestrictions']['restrictions'])

    def test_permissions_regex_copying_restricted(self):
        # Bit 5 (value 16) is for copying.
        # -17 is ...11101111. (-17 & 16) is 0.
        doc = MagicMock()
        doc.is_encrypted = False
        txt = "/P -17"
        indicators = {}

        detect_encryption_status(doc, txt, indicators)

        self.assertIn('SecurityRestrictions', indicators)
        self.assertIn('Copying restricted', indicators['SecurityRestrictions']['restrictions'])

    def test_permissions_regex_annotations_restricted(self):
        # Bit 6 (value 32) is for annotations.
        # -33 is ...11011111. (-33 & 32) is 0.
        doc = MagicMock()
        doc.is_encrypted = False
        txt = "/P -33"
        indicators = {}

        detect_encryption_status(doc, txt, indicators)

        self.assertIn('SecurityRestrictions', indicators)
        self.assertIn('Annotations restricted', indicators['SecurityRestrictions']['restrictions'])

    def test_multiple_restrictions(self):
        # Restrict printing (4) and copying (16).
        # We need bits 2 and 4 to be 0.
        # -21 is ...11101011.
        # (-21 & 4) is 0. (-21 & 16) is 0.
        doc = MagicMock()
        doc.is_encrypted = False
        txt = "/P -21"
        indicators = {}

        detect_encryption_status(doc, txt, indicators)

        self.assertIn('SecurityRestrictions', indicators)
        restrictions = indicators['SecurityRestrictions']['restrictions']
        self.assertIn('Printing restricted', restrictions)
        self.assertIn('Copying restricted', restrictions)
        self.assertNotIn('Modification restricted', restrictions) # bit 3 (8) is 1
        self.assertNotIn('Annotations restricted', restrictions) # bit 5 (32) is 1

if __name__ == '__main__':
    unittest.main()
