import unittest
from unittest.mock import patch, mock_open
import os
import sys

# Ensure the root directory is in the path to import pdfrecon modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from pdfrecon.exporter import export_to_csv

class TestExporter(unittest.TestCase):
    def test_export_to_csv_open_error(self):
        # Setup dummy data
        file_path = "dummy.csv"
        report_data = []
        all_scan_data = {}
        file_annotations = {}
        exif_outputs = {}
        column_keys = ["col" + str(i) for i in range(11)]

        # Mock open to raise an exception
        with patch("builtins.open", mock_open()) as mocked_file:
            mocked_file.side_effect = IOError("Mocked IO Error")

            # Assert that the exception is raised and logged
            with self.assertLogs(level='ERROR') as cm:
                with self.assertRaises(IOError):
                    export_to_csv(file_path, report_data, all_scan_data, file_annotations, exif_outputs, column_keys)

            self.assertTrue(any("Error exporting to CSV" in o for o in cm.output))

    def test_export_to_csv_writer_error(self):
        # Setup dummy data
        file_path = "dummy.csv"
        # minimal row data, need at least 5 elements because path is at index 4
        report_data = [["data1", "data2", "data3", "data4", "path/to/file"]]
        all_scan_data = {}
        file_annotations = {}
        exif_outputs = {}
        # Ensure enough columns so the row is padded to at least index 10
        column_keys = ["col" + str(i) for i in range(11)]

        # Mock open (success) and csv.writer (error)
        with patch("builtins.open", mock_open()):
             with patch("csv.writer") as mock_writer:
                mock_writer_instance = mock_writer.return_value
                # Make writerow raise an exception
                # writerow is called for headers, so we can mock that or writerows for data
                # The code calls writer.writerow(headers) then writer.writerows(data_for_export)
                # Let's make writerow raise exception to fail fast
                mock_writer_instance.writerow.side_effect = Exception("Mocked CSV Error")

                with self.assertLogs(level='ERROR') as cm:
                    with self.assertRaises(Exception) as exc_cm:
                        export_to_csv(file_path, report_data, all_scan_data, file_annotations, exif_outputs, column_keys)

                self.assertIn("Mocked CSV Error", str(exc_cm.exception))
                self.assertTrue(any("Error exporting to CSV" in o for o in cm.output))
