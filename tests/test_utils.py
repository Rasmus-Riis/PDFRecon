import unittest
from unittest.mock import Mock, MagicMock
from pathlib import Path
from src.utils import safe_stat_times

class TestSafeStatTimes(unittest.TestCase):
    def test_safe_stat_times_success(self):
        """Test safe_stat_times returns correct tuple on success."""
        mock_path = MagicMock(spec=Path)
        mock_stat = Mock()
        mock_stat.st_atime = 100.0
        mock_stat.st_mtime = 200.0
        mock_stat.st_ctime = 300.0
        mock_path.stat.return_value = mock_stat

        result = safe_stat_times(mock_path)

        self.assertEqual(result, (100.0, 200.0, 300.0))
        mock_path.stat.assert_called_once()

    def test_safe_stat_times_exception(self):
        """Test safe_stat_times returns None when stat raises an exception."""
        mock_path = MagicMock(spec=Path)
        mock_path.stat.side_effect = Exception("Generic error")

        result = safe_stat_times(mock_path)

        self.assertIsNone(result)
        mock_path.stat.assert_called_once()

    def test_safe_stat_times_file_not_found(self):
        """Test safe_stat_times returns None when stat raises FileNotFoundError."""
        mock_path = MagicMock(spec=Path)
        mock_path.stat.side_effect = FileNotFoundError("File not found")

        result = safe_stat_times(mock_path)

        self.assertIsNone(result)
        mock_path.stat.assert_called_once()

    def test_safe_stat_times_permission_error(self):
        """Test safe_stat_times returns None when stat raises PermissionError."""
        mock_path = MagicMock(spec=Path)
        mock_path.stat.side_effect = PermissionError("Permission denied")

        result = safe_stat_times(mock_path)

        self.assertIsNone(result)
        mock_path.stat.assert_called_once()

if __name__ == '__main__':
    unittest.main()
