import unittest
import datetime
import sys
import os

# Add parent directory to path so we can import pdfrecon
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pdfrecon.advanced_forensics import detect_temporal_anomalies

class TestDetectTemporalAnomalies(unittest.TestCase):
    def setUp(self):
        # We will use a fixed 'now' for testing
        self.fixed_now = datetime.datetime(2023, 1, 1, 12, 0, 0)
        self.indicators = {}

    def test_future_date_detection(self):
        # A date in the future relative to 2023-01-01
        future_date_txt = "D:20230105120000" # 2023-01-05

        detect_temporal_anomalies(future_date_txt, self.indicators, now=self.fixed_now)

        self.assertIn('FutureDatedTimestamps', self.indicators)
        self.assertEqual(self.indicators['FutureDatedTimestamps']['count'], 1)
        self.assertEqual(self.indicators['FutureDatedTimestamps']['dates'][0]['date'], '2023-01-05')
        self.assertEqual(self.indicators['FutureDatedTimestamps']['dates'][0]['days_ahead'], 3)

    def test_past_date_ignored(self):
        # A date in the past relative to 2023-01-01
        past_date_txt = "D:20221231120000" # 2022-12-31

        detect_temporal_anomalies(past_date_txt, self.indicators, now=self.fixed_now)

        self.assertNotIn('FutureDatedTimestamps', self.indicators)

    def test_invalid_date_format(self):
        # Invalid date format
        invalid_date_txt = "D:20231301" # Month 13

        detect_temporal_anomalies(invalid_date_txt, self.indicators, now=self.fixed_now)

        self.assertNotIn('FutureDatedTimestamps', self.indicators)

    def test_edge_case_tomorrow(self):
        # Exactly 1 day ahead (tomorrow)
        # Logic says: if days_ahead > 1

        # 2023-01-02 00:00:00 vs 2023-01-01 12:00:00
        # diff = 0 days, 12 hours. .days = 0.

        tomorrow_txt = "D:20230102120000"
        detect_temporal_anomalies(tomorrow_txt, self.indicators, now=self.fixed_now)

        self.assertNotIn('FutureDatedTimestamps', self.indicators)

        # Let's try 2 days ahead
        # 2023-01-03 00:00:00 vs 2023-01-01 12:00:00
        # diff = 1 day, 12 hours. .days = 1.

        day_after_tomorrow_txt = "D:20230103120000"
        detect_temporal_anomalies(day_after_tomorrow_txt, self.indicators, now=self.fixed_now)
        # days_ahead = 1.
        self.assertNotIn('FutureDatedTimestamps', self.indicators)

        # 3 days ahead
        # 2023-01-04 00:00:00 vs 2023-01-01 12:00:00
        # diff = 2 days, 12 hours. .days = 2.
        # 2 > 1 is True.
        three_days_ahead_txt = "D:20230104120000"
        detect_temporal_anomalies(three_days_ahead_txt, self.indicators, now=self.fixed_now)
        self.assertIn('FutureDatedTimestamps', self.indicators)

if __name__ == '__main__':
    unittest.main()
