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


# -- Logiktest: Rufnummern, die zu einem falschen Empfaenger fuehrten -------
#
# Grundsatz: Im Zweifel ablehnen statt raten. Ein Fax an die falsche Nummer
# ist eine Datenpanne; eine Ablehnung erreicht den Absender als Fehlerbericht.


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        # "(0)" ist die Verkehrsausscheidungsziffer und entfaellt international
        ("+49 (0)30 1234567", "+49301234567"),
        ("+49(0)301234567", "+49301234567"),
        ("0049 (0) 30 1234567", "+49301234567"),
        # "+490…" ist ein Schreibfehler - deutsche Nummern beginnen nach +49 nie mit 0
        ("+49030 1234567", "+49301234567"),
        ("+490301234567", "+49301234567"),
    ],
)
def test_trunk_zero_is_removed(security, subject, expected):
    assert extract_number(subject, security).e164 == expected


def test_trunk_zero_never_dials_abroad(security):
    """Der eigentliche Schaden: "+49 (0)30…" wurde als 0030… gewaehlt - Griechenland."""
    nummer = extract_number("+49 (0)30 1234567", security)
    assert nummer.formatted_national("+49") == "0301234567"
    assert not nummer.formatted_national("+49").startswith("00")


def test_international_number_beats_reference_number(security):
    """Eine Referenznummer mit fuehrender 0 darf nicht zur Zielrufnummer werden."""
    assert extract_number("Rechnung 0123456 an +49 30 1234567", security).e164 == "+49301234567"
    assert extract_number("Az. 01234567 / Fax +49 30 1234567", security).e164 == "+49301234567"


@pytest.mark.parametrize(
    "subject",
    [
        "+49 30 1234567 2 Seiten",
        "0301234567 3 Anlagen",
        "Fax an +49 30 1234567 12",
    ],
)
def test_trailing_digits_make_the_subject_ambiguous(security, subject):
    """Ziffern hinter der Rufnummer duerfen nicht an sie angehaengt werden."""
    with pytest.raises(RuleError, match="nicht eindeutig"):
        extract_number(subject, security)


def test_ambiguity_message_names_both_readings(security):
    with pytest.raises(RuleError) as info:
        extract_number("+49 30 1234567 2 Seiten", security)
    meldung = str(info.value)
    assert "+49301234567" in meldung
    assert "+493012345672" in meldung
    assert "ohne Leerzeichen" in meldung


@pytest.mark.parametrize(
    "subject",
    [
        "+49 30 1234567 2 Seiten".replace(" 2", ", 2"),  # Komma trennt eindeutig
        "+49 30 1234567 - 2 Seiten",
        "+49 30 1234567 (2 Seiten)",
    ],
)
def test_punctuation_resolves_the_ambiguity(security, subject):
    assert extract_number(subject, security).e164 == "+49301234567"


def test_two_different_numbers_are_rejected(security):
    with pytest.raises(RuleError, match="mehrere Rufnummern"):
        extract_number("+49 30 1234567 oder +49 40 7654321", security)
    with pytest.raises(RuleError, match="mehrere Rufnummern"):
        extract_number("Vorgang 04711001 an 030 1234567", security)


def test_same_number_twice_is_fine(security):
    assert extract_number("+49 30 1234567 / +49301234567", security).e164 == "+49301234567"


@pytest.mark.parametrize(
    "subject",
    [
        "Vorgang 047110 an 030 1234567",   # 047110: zu kurz fuer eine Rufnummer
        "Kundennr 012345, Fax 030 1234567",
        "Rechnung 2026-0815 an 030 1234567",
    ],
)
def test_short_reference_numbers_are_ignored(security, subject):
    assert extract_number(subject, security).e164 == "+49301234567"


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        ("030 123 4567", "+49301234567"),
        ("+49 30 12 34 56", "+4930123456"),
        ("+49 89 1234567-89", "+4989123456789"),
        ("+49 221 12345678", "+4922112345678"),
        ("0049 30 1234567", "+49301234567"),
        ("030/1234567", "+49301234567"),
        ("+49 30 1234567, Rechnung 42", "+49301234567"),
    ],
)
def test_common_notations_still_work(security, subject, expected):
    assert extract_number(subject, security).e164 == expected


def test_e164_allows_at_most_15_digits(security):
    assert normalise_number("+491234567890123", security).e164 == "+491234567890123"
    with pytest.raises(RuleError):
        normalise_number("+4912345678901234", security)


def test_foreign_numbers_are_dialled_with_international_prefix():
    """Ein "+" ist an vielen Anlagen nicht waehlbar - im Inland waehlt man 00."""
    from mail2fax.rules import Number

    assert Number("+431234567").formatted_national("+49") == "00431234567"
    assert Number("+49301234567").formatted_national("+49") == "0301234567"


# -- Logiktest: Whitelist ----------------------------------------------------


@pytest.mark.parametrize(
    ("entry", "sender"),
    [
        ("*@example.com", "boese@nichtexample.com"),
        ("*@example.com", "chef@example.com.boese.org"),
        ("*@*.example.com", "x@boese-example.com"),
        ("*@*.intern.example.com", "x@boese-intern.example.com"),
    ],
)
def test_lookalike_domains_are_not_allowed(entry, sender):
    assert is_sender_allowed(sender, SecurityConfig(sender_whitelist=[entry])) is False


def test_subdomain_wildcard():
    security = SecurityConfig(sender_whitelist=["*@*.example.com"])
    assert is_sender_allowed("x@abt.example.com", security) is True
    assert is_sender_allowed("x@a.b.example.com", security) is True
    # Nur Subdomains - die Domain selbst muss eigens eingetragen werden.
    assert is_sender_allowed("x@example.com", security) is False


@pytest.mark.parametrize(
    "entry", ["*example.com", "*@*example.com", "*", "*@*", "*@*.com", "chef@", "@example.com", "a@b@c"]
)
def test_unsafe_whitelist_entries_are_rejected(entry):
    from mail2fax.config import whitelist_entry_problem

    assert whitelist_entry_problem(entry) is not None


@pytest.mark.parametrize(
    "entry", ["chef@example.com", "*@example.com", "fax-*@example.com", "*@*.example.com", "admin@localhost"]
)
def test_safe_whitelist_entries_are_accepted(entry):
    from mail2fax.config import whitelist_entry_problem

    assert whitelist_entry_problem(entry) is None


def test_unsafe_entries_never_take_effect():
    """Auch von Hand in die YAML-Datei geschrieben, wirkt ein unsicherer Eintrag nicht."""
    security = SecurityConfig(sender_whitelist=["*example.com", "chef@example.com"])
    assert security.sender_whitelist == ["chef@example.com"]
    assert is_sender_allowed("boese@nichtexample.com", security) is False
