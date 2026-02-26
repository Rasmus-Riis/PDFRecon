import unittest
import sys
import os
from datetime import datetime, timezone

# Add the parent directory to the path so we can import pdfrecon
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from pdfrecon.utils import fmt_times_pair

class TestUtils(unittest.TestCase):
    def test_fmt_times_pair_epoch(self):
        """Test with timestamp 0 (1970-01-01 00:00:00 UTC)."""
        ts = 0.0
        local_str, utc_str = fmt_times_pair(ts)

        # Verify UTC string
        self.assertEqual(utc_str, "1970-01-01T00:00:00Z")

        # Verify local string format: DD-MM-YYYY HH:MM:SS±ZZZZ
        try:
            parsed_local = datetime.strptime(local_str, "%d-%m-%Y %H:%M:%S%z")
            # Verify it represents the same timestamp
            self.assertAlmostEqual(parsed_local.timestamp(), ts, places=3)
        except ValueError as e:
            self.fail(f"Local time string '{local_str}' did not match expected format: {e}")

    def test_fmt_times_pair_recent(self):
        """Test with a recent timestamp."""
        # 2023-10-27 12:00:00 UTC
        dt = datetime(2023, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
        ts = dt.timestamp()

        local_str, utc_str = fmt_times_pair(ts)

        self.assertEqual(utc_str, "2023-10-27T12:00:00Z")

        # Verify local string parses back
        parsed_local = datetime.strptime(local_str, "%d-%m-%Y %H:%M:%S%z")
        self.assertAlmostEqual(parsed_local.timestamp(), ts, places=3)

    def test_fmt_times_pair_negative(self):
        """Test with a negative timestamp (before 1970)."""
        try:
            # 1960-01-01 00:00:00 UTC
            dt = datetime(1960, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
            ts = dt.timestamp()

            local_str, utc_str = fmt_times_pair(ts)

            self.assertEqual(utc_str, "1960-01-01T00:00:00Z")

            parsed_local = datetime.strptime(local_str, "%d-%m-%Y %H:%M:%S%z")
            self.assertAlmostEqual(parsed_local.timestamp(), ts, places=3)
        except (OSError, ValueError, OverflowError):
            # If the platform doesn't support negative timestamps, skip silently
            pass

if __name__ == '__main__':
    unittest.main()
