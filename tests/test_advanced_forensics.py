import pytest
from pdfrecon.advanced_forensics import detect_unc_paths

def test_detect_unc_paths_valid():
    indicators = {}
    txt = r"This is a path \\server\share and another \\192.168.1.1\hidden$"
    detect_unc_paths(txt, indicators)
    assert 'UNCPaths' in indicators
    assert indicators['UNCPaths']['count'] == 2
    paths = indicators['UNCPaths']['paths']
    assert r"\\server\share" in paths
    assert r"\\192.168.1.1\hidden$" in paths

def test_detect_unc_paths_multiple():
    indicators = {}
    txt = r"Path1 \\server1\share1 Path2 \\server2\share2 Path3 \\server3\share3"
    detect_unc_paths(txt, indicators)
    assert indicators['UNCPaths']['count'] == 3
    paths = indicators['UNCPaths']['paths']
    assert len(paths) == 3
    assert r"\\server1\share1" in paths
    assert r"\\server2\share2" in paths
    assert r"\\server3\share3" in paths

def test_detect_unc_paths_no_match():
    indicators = {}
    txt = "No paths here C:\\local\\path /usr/bin/path"
    detect_unc_paths(txt, indicators)
    assert 'UNCPaths' not in indicators

def test_detect_unc_paths_empty():
    indicators = {}
    detect_unc_paths("", indicators)
    assert 'UNCPaths' not in indicators

def test_detect_unc_paths_none():
    indicators = {}
    # detect_unc_paths expects txt to be a string.
    # If passed None, re.findall raises TypeError.
    # The function catches Exception, so it should handle it gracefully (no crash).
    detect_unc_paths(None, indicators)
    assert 'UNCPaths' not in indicators

def test_detect_unc_paths_duplicates():
    indicators = {}
    txt = r"\\server\share \\server\share \\server\share"
    detect_unc_paths(txt, indicators)
    assert indicators['UNCPaths']['count'] == 1
    assert len(indicators['UNCPaths']['paths']) == 1
    assert indicators['UNCPaths']['paths'][0] == r"\\server\share"

def test_detect_unc_paths_limit():
    indicators = {}
    # Create 6 unique paths
    paths = [f"\\\\server\\share{i}" for i in range(6)]
    txt = " ".join(paths)
    detect_unc_paths(txt, indicators)

    assert indicators['UNCPaths']['count'] == 6
    # The code limits the returned list to 5 items: list(unc_paths)[:5]
    assert len(indicators['UNCPaths']['paths']) == 5
