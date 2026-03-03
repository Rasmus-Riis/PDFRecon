import sys
import os
import pytest

# Ensure pdfrecon is in the path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from pdfrecon.advanced_forensics import detect_emails_and_urls

def test_detect_emails_valid():
    text = "Contact us at support@example.com for assistance."
    indicators = {}
    detect_emails_and_urls(text, indicators)

    assert 'EmailAddresses' in indicators
    assert indicators['EmailAddresses']['count'] == 1
    assert 'support@example.com' in indicators['EmailAddresses']['emails']

def test_detect_urls_valid_simple():
    text = "Visit our website at https://www.example.com"
    indicators = {}
    detect_emails_and_urls(text, indicators)

    assert 'URLs' in indicators
    assert indicators['URLs']['count'] == 1
    assert 'www.example.com' in indicators['URLs']['domains'] or 'example.com' in indicators['URLs']['domains']

def test_detect_urls_with_trailing_punctuation():
    # This test currently fails because the regex captures the trailing dot
    text = "Visit our website at https://www.example.com."
    indicators = {}
    detect_emails_and_urls(text, indicators)

    assert 'URLs' in indicators
    assert indicators['URLs']['count'] == 1
    # We expect the trailing dot to NOT be part of the domain/URL
    url_found = False
    for domain in indicators['URLs']['domains']:
        if domain == 'www.example.com' or domain == 'example.com':
            url_found = True
            break

    if not url_found:
        pytest.fail(f"Expected domain 'www.example.com' or 'example.com', but got {indicators['URLs']['domains']}")

def test_detect_mixed_content():
    text = "Email: test@test.com, Website: http://test.com"
    indicators = {}
    detect_emails_and_urls(text, indicators)

    assert 'EmailAddresses' in indicators
    assert indicators['EmailAddresses']['count'] == 1
    assert 'test@test.com' in indicators['EmailAddresses']['emails']

    assert 'URLs' in indicators
    assert indicators['URLs']['count'] == 1
    assert 'test.com' in indicators['URLs']['domains']

def test_no_emails_urls():
    text = "This is a plain text with no contact info."
    indicators = {}
    detect_emails_and_urls(text, indicators)

    assert 'EmailAddresses' not in indicators
    assert 'URLs' not in indicators

def test_empty_string():
    text = ""
    indicators = {}
    detect_emails_and_urls(text, indicators)

    assert 'EmailAddresses' not in indicators
    assert 'URLs' not in indicators

def test_invalid_email_url():
    # "user@domain..com" might be partially matched depending on regex,
    # but "http:/broken-url" definitely shouldn't be matched as a URL.
    text = "http:/broken-url"
    indicators = {}
    detect_emails_and_urls(text, indicators)

    # Assert no URL found for malformed http
    if 'URLs' in indicators:
        assert indicators['URLs']['count'] == 0

def test_multiple_emails_urls():
    text = "e1@a.com e2@b.com https://site1.com http://site2.org"
    indicators = {}
    detect_emails_and_urls(text, indicators)

    assert 'EmailAddresses' in indicators
    assert indicators['EmailAddresses']['count'] == 2
    assert set(indicators['EmailAddresses']['emails']) == {'e1@a.com', 'e2@b.com'}

    assert 'URLs' in indicators
    assert indicators['URLs']['count'] == 2
    assert indicators['URLs']['unique_domains'] == 2
    assert set(indicators['URLs']['domains']) == {'site1.com', 'site2.org'}

def test_duplicate_emails_urls():
    text = "test@test.com test@test.com https://test.com https://test.com"
    indicators = {}
    detect_emails_and_urls(text, indicators)

    assert 'EmailAddresses' in indicators
    assert indicators['EmailAddresses']['count'] == 1
    assert indicators['EmailAddresses']['emails'] == ['test@test.com']

    assert 'URLs' in indicators
    assert indicators['URLs']['count'] == 1
    assert indicators['URLs']['unique_domains'] == 1
    assert indicators['URLs']['domains'] == ['test.com']

def test_email_regex_edge_cases():
    # Test valid but unusual email formats if supported by regex
    text = "user.name+tag@example.co.uk"
    indicators = {}
    detect_emails_and_urls(text, indicators)

    assert 'EmailAddresses' in indicators
    assert 'user.name+tag@example.co.uk' in indicators['EmailAddresses']['emails']

def test_url_regex_edge_cases():
    # Test URLs with paths and query parameters
    text = "https://example.com/path?query=1"
    indicators = {}
    detect_emails_and_urls(text, indicators)

    assert 'URLs' in indicators
    assert indicators['URLs']['count'] == 1
    assert 'example.com' in indicators['URLs']['domains']
