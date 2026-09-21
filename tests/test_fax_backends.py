"""Tests der Fax-Backends (ohne echte Gegenstellen)."""

from __future__ import annotations

import sys

import pytest

from mail2fax.config import AppConfig
from mail2fax.fax import BACKENDS, FaxError, get_backend
from mail2fax.fax.fritzbox import FritzboxSession
from mail2fax.render import text_to_pdf
from mail2fax.rules import Number


@pytest.fixture
def document(tmp_path):
    return text_to_pdf("Inhalt", tmp_path / "fax.pdf").path


def test_registry_covers_all_backends():
    assert set(BACKENDS) == {"sip", "fritzbox", "hylafax", "mailgateway", "command", "dummy"}


def test_unknown_backend_raises():
    config = AppConfig()
    config.fax.backend = "gibtsnicht"  # type: ignore[assignment]
    with pytest.raises(FaxError, match="Unbekanntes"):
        get_backend(config)


def test_dummy_backend_succeeds(document):
    result = get_backend(AppConfig()).send(Number("+49301234567"), [document])
    assert result.success


# -- FRITZ!Box: Challenge-Response ------------------------------------------


def test_fritzbox_pbkdf2_response_format():
    challenge = "2$10000$5A1711$2000$5A1722"
    response = FritzboxSession._response_pbkdf2(challenge, "geheim")
    salt2, digest = response.split("$")
    assert salt2 == "5A1722"
    assert len(digest) == 64  # SHA-256 als Hex


def test_fritzbox_pbkdf2_is_deterministic():
    challenge = "2$10000$5A1711$2000$5A1722"
    assert FritzboxSession._response_pbkdf2(challenge, "a") == FritzboxSession._response_pbkdf2(challenge, "a")
    assert FritzboxSession._response_pbkdf2(challenge, "a") != FritzboxSession._response_pbkdf2(challenge, "b")


def test_fritzbox_pbkdf2_rejects_malformed_challenge():
    with pytest.raises(FaxError):
        FritzboxSession._response_pbkdf2("2$kaputt", "geheim")


def test_fritzbox_md5_response_matches_avm_specification():
    # Beispiel aus der AVM-Dokumentation "Session-ID" (Challenge 1234567z,
    # Passwort "äbc"): erwartete Antwort laut Spezifikation.
    assert FritzboxSession._response_md5("1234567z", "äbc") == "1234567z-9e224a41eeefa284df7bb0f26c2913e2"


def test_fritzbox_requires_password():
    config = AppConfig()
    config.fax.backend = "fritzbox"
    config.fax.fritzbox.password = ""
    with pytest.raises(FaxError, match="kein Passwort"):
        get_backend(config).test()


def test_fritzbox_requires_sender_number(document):
    config = AppConfig()
    config.fax.backend = "fritzbox"
    config.fax.fritzbox.password = "geheim"
    config.fax.fritzbox.sender_number = ""
    with pytest.raises(FaxError, match="Faxnummer"):
        get_backend(config).send(Number("+49301234567"), [document])


# -- Kommando ---------------------------------------------------------------


def test_command_backend_runs_program(tmp_path, document):
    marker = tmp_path / "aufruf.txt"
    config = AppConfig()
    config.fax.backend = "command"
    config.fax.command.argv = [
        sys.executable, "-c",
        f"import sys,pathlib; pathlib.Path({str(marker)!r}).write_text(' '.join(sys.argv[1:]))",
        "{number}", "{file}",
    ]
    result = get_backend(config).send(Number("+49301234567"), [document], subject="Test")
    assert result.success
    written = marker.read_text()
    assert "+49301234567" in written
    assert str(document) in written


def test_command_backend_reports_failure(document):
    config = AppConfig()
    config.fax.backend = "command"
    config.fax.command.argv = [sys.executable, "-c", "import sys; sys.stderr.write('kaputt'); sys.exit(3)"]
    with pytest.raises(FaxError, match="Code 3"):
        get_backend(config).send(Number("+49301234567"), [document])


def test_command_backend_without_command(document):
    config = AppConfig()
    config.fax.backend = "command"
    with pytest.raises(FaxError, match="kein Kommando"):
        get_backend(config).send(Number("+49301234567"), [document])


def test_command_backend_rejects_unknown_placeholder(document):
    config = AppConfig()
    config.fax.backend = "command"
    config.fax.command.argv = ["/bin/true", "{unbekannt}"]
    with pytest.raises(FaxError, match="Platzhalter"):
        get_backend(config).send(Number("+49301234567"), [document])


def test_command_backend_missing_program(document):
    config = AppConfig()
    config.fax.backend = "command"
    config.fax.command.argv = ["/nicht/vorhanden/faxsend"]
    with pytest.raises(FaxError, match="nicht gefunden"):
        get_backend(config).send(Number("+49301234567"), [document])


# -- Fax per E-Mail ---------------------------------------------------------


def test_mailgateway_builds_recipient_from_template(document, monkeypatch):
    config = AppConfig()
    config.fax.backend = "mailgateway"
    config.fax.mailgateway.recipient_template = "{number_digits}@fax.example.net"
    config.fax.mailgateway.host = "smtp.example.net"
    config.fax.mailgateway.from_address = "fax@example.com"

    sent = {}

    def fake_send(_smtp, message):
        sent["to"] = message["To"]
        sent["attachments"] = [part.get_filename() for part in message.iter_attachments()]

    monkeypatch.setattr("mail2fax.fax.mailgateway._send_via_smtp", fake_send)
    result = get_backend(config).send(Number("+49301234567"), [document], subject="Rechnung")
    assert result.success
    assert sent["to"] == "49301234567@fax.example.net"
    assert sent["attachments"] == [document.name]


def test_mailgateway_national_placeholder(document, monkeypatch):
    config = AppConfig()
    config.fax.backend = "mailgateway"
    config.fax.mailgateway.recipient_template = "fax.{number_national}@example.net"
    config.fax.mailgateway.host = "smtp.example.net"
    config.fax.mailgateway.from_address = "fax@example.com"
    sent = {}
    monkeypatch.setattr(
        "mail2fax.fax.mailgateway._send_via_smtp", lambda _s, m: sent.update(to=m["To"])
    )
    get_backend(config).send(Number("+49301234567"), [document])
    assert sent["to"] == "fax.0301234567@example.net"


def test_mailgateway_without_smtp_server(document):
    config = AppConfig()
    config.fax.backend = "mailgateway"
    with pytest.raises(FaxError, match="kein SMTP-Server"):
        get_backend(config).send(Number("+49301234567"), [document])


def test_mailgateway_rejects_bad_template(document):
    config = AppConfig()
    config.fax.backend = "mailgateway"
    config.fax.mailgateway.host = "smtp.example.net"
    config.fax.mailgateway.from_address = "fax@example.com"
    config.fax.mailgateway.recipient_template = "ohne-at-zeichen"
    with pytest.raises(FaxError, match="gueltige Adresse"):
        get_backend(config).send(Number("+49301234567"), [document])


# -- HylaFAX ----------------------------------------------------------------


def test_hylafax_missing_binary(document):
    config = AppConfig()
    config.fax.backend = "hylafax"
    config.fax.hylafax.binary = "/nicht/vorhanden/sendfax"
    with pytest.raises(FaxError, match="nicht gefunden"):
        get_backend(config).send(Number("+49301234567"), [document])
