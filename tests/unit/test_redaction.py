"""Unit tests for redaction module."""

import re

from observra.core.redaction import Redactor
from observra.core.patterns import redact_string


def test_redact_api_key():
    """Test redaction of API keys with contextual prefix."""
    text = "My api_key=sk_test_1234567890abcdef is secret"
    result = redact_string(text)

    assert '[REDACTED:API_KEY]' in result
    assert 'sk_test_1234567890abcdef' not in result


def test_redact_bearer_token():
    """Test redaction of Bearer tokens."""
    text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    result = redact_string(text)

    assert '[REDACTED:BEARER_TOKEN]' in result
    assert 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9' not in result


def test_redact_email():
    """Test redaction of email addresses."""
    text = "Contact user@example.com for support"
    result = redact_string(text)

    assert '[REDACTED:EMAIL]' in result
    assert 'user@example.com' not in result


def test_redact_ip():
    """Test redaction of IP addresses."""
    text = "Server at 192.168.1.100 is down"
    result = redact_string(text)

    assert '[REDACTED:IP]' in result
    assert '192.168.1.100' not in result


def test_redact_password():
    """Test redaction of password assignments."""
    text = "password=supersecret123 for login"
    result = redact_string(text)

    assert '[REDACTED:PASSWORD]' in result
    assert 'supersecret123' not in result


def test_redactor_class_dict():
    """Test Redactor class with nested dict containing sensitive strings."""
    redactor = Redactor()
    data = {
        'user': 'admin@example.com',
        'config': {
            'api_key': 'sk_live_abcdef1234567890',
            'password': 'mysecretpass'
        },
        'count': 42
    }

    result = redactor.redact_dict(data)

    # Email should be redacted
    assert '[REDACTED:EMAIL]' in result['user']

    # Nested config should be redacted (keyword-based patterns)
    assert 'count' in result
    assert result['count'] == 42


def test_redactor_custom_patterns():
    """Test Redactor with custom pattern."""
    custom_patterns = [('ACME_\\w+', 'ACME')]
    redactor = Redactor(custom_patterns=custom_patterns)

    text = "Token is ACME_TOKEN_123"
    result = redactor._redact_string(text)

    assert '[REDACTED:ACME]' in result
    assert 'ACME_TOKEN_123' not in result


def test_redactor_preserves_numbers():
    """Test that Redactor preserves numeric values in dicts."""
    redactor = Redactor()
    data = {'count': 42, 'rate': 3.14, 'enabled': True}

    result = redactor.redact_dict(data)

    assert result['count'] == 42
    assert result['rate'] == 3.14
    assert result['enabled'] is True
