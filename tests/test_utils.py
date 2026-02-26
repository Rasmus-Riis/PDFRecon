import sys
from unittest.mock import MagicMock

# Mock tkinter before importing pdfrecon.utils
mock_tkinter = MagicMock()
sys.modules["tkinter"] = mock_tkinter
sys.modules["tkinter.messagebox"] = MagicMock()

import hashlib
import pytest
from pathlib import Path
from pdfrecon.utils import md5_file

def test_md5_file_basic(tmp_path):
    """Test md5_file with a small file."""
    content = b"Hello, World!"
    test_file = tmp_path / "test_file.txt"
    test_file.write_bytes(content)

    expected_md5 = hashlib.md5(content).hexdigest()
    result_md5 = md5_file(test_file)

    assert result_md5 == expected_md5

def test_md5_file_empty(tmp_path):
    """Test md5_file with an empty file."""
    content = b""
    test_file = tmp_path / "empty_file.txt"
    test_file.write_bytes(content)

    expected_md5 = hashlib.md5(content).hexdigest()
    result_md5 = md5_file(test_file)

    assert result_md5 == expected_md5

def test_md5_file_large(tmp_path):
    """Test md5_file with a file larger than the default buffer size."""
    # Default buffer size is 4MB (4 * 1024 * 1024)
    # Create a 5MB file
    size = 5 * 1024 * 1024
    content = b"A" * size
    test_file = tmp_path / "large_file.txt"
    test_file.write_bytes(content)

    expected_md5 = hashlib.md5(content).hexdigest()
    result_md5 = md5_file(test_file)

    assert result_md5 == expected_md5

def test_md5_file_custom_buffer(tmp_path):
    """Test md5_file with a custom buffer size."""
    content = b"Hello, World!" * 1000
    test_file = tmp_path / "test_file_custom.txt"
    test_file.write_bytes(content)

    expected_md5 = hashlib.md5(content).hexdigest()
    # Use a small buffer size to force multiple reads
    result_md5 = md5_file(test_file, buf_size=128)

    assert result_md5 == expected_md5

def test_md5_file_not_found(tmp_path):
    """Test md5_file with a non-existent file."""
    test_file = tmp_path / "non_existent_file.txt"

    with pytest.raises(FileNotFoundError):
        md5_file(test_file)
