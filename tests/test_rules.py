"""Tests fuer Rufnummernerkennung und Absenderpruefung."""

from __future__ import annotations

import pytest

from mail2fax.config import SecurityConfig
from mail2fax.rules import (
    RuleError,
    check_number_allowed,
    check_sender_allowed,
    extract_number,
    is_sender_allowed,
    normalise_number,
)


@pytest.fixture
def security():
    return SecurityConfig(sender_whitelist=["chef@example.com", "*@intern.example.com"])


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+49301234567", "+49301234567"),
        ("+49 30 1234567", "+49301234567"),
        ("+49 (30) 123-4567", "+49301234567"),
        ("0049301234567", "+49301234567"),
        ("030/1234567", "+49301234567"),
        ("0301234567", "+49301234567"),
        ("+43 1 234567", "+431234567"),
    ],
)
def test_normalise_number(security, raw, expected):
    assert normalise_number(raw, security).e164 == expected


def test_normalise_rejects_national_when_disabled(security):
    security.accept_national_format = False
    with pytest.raises(RuleError, match="international"):
        normalise_number("0301234567", security)


@pytest.mark.parametrize("raw", ["", "keine nummer", "+49", "12", "abc123def"])
def test_normalise_rejects_invalid(security, raw):
    with pytest.raises(RuleError):
        normalise_number(raw, security)


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        ("+49301234567", "+49301234567"),
        ("Fax an +49 30 1234567", "+49301234567"),
        ("Rechnung 2024 fuer +49301234567 bitte senden", "+49301234567"),
        ("FAX: 030 1234567 - Angebot", "+49301234567"),
        ("[Fax] +49(30)123-4567", "+49301234567"),
    ],
)
def test_extract_number_from_subject(security, subject, expected):
    assert extract_number(subject, security).e164 == expected


def test_extract_number_skips_unusable_candidates(security):
    # "2024" ist zu kurz, die Rufnummer dahinter muss gefunden werden.
    assert extract_number("Projekt 2024 Fax +49301234567", security).e164 == "+49301234567"


@pytest.mark.parametrize("subject", ["", "   ", "Kein Fax heute", "Rechnung Nr 12"])
def test_extract_number_without_match(security, subject):
    with pytest.raises(RuleError):
        extract_number(subject, security)


def test_blocked_prefix(security):
    number = normalise_number("+491900123456", security)
    with pytest.raises(RuleError, match="gesperrt"):
        check_number_allowed(number, security)


def test_allowed_prefix_restriction(security):
    number = normalise_number("+431234567", security)
    with pytest.raises(RuleError, match="ausserhalb"):
        check_number_allowed(number, security)


def test_allowed_prefix_passes(security):
    check_number_allowed(normalise_number("+49301234567", security), security)


def test_allowed_prefix_empty_allows_everything(security):
    security.allowed_number_prefixes = []
    check_number_allowed(normalise_number("+431234567", security), security)


@pytest.mark.parametrize(
    ("sender", "expected"),
    [
        ("chef@example.com", True),
        ("Chef <CHEF@Example.com>", True),
        ("mitarbeiter@intern.example.com", True),
        ("fremd@example.org", False),
        ("chef@example.com.evil.org", False),
        ("", False),
    ],
)
def test_sender_whitelist(security, sender, expected):
    assert is_sender_allowed(sender, security) is expected


def test_empty_whitelist_blocks_everything(security):
    security.sender_whitelist = []
    with pytest.raises(RuleError, match="Whitelist ist leer"):
        check_sender_allowed("chef@example.com", security)


def test_check_sender_returns_address(security):
    assert check_sender_allowed("Chef <chef@example.com>", security) == "chef@example.com"
