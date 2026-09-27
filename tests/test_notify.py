"""Tests der Sende- und Fehlerberichte.

Zwei Eigenschaften sind sicherheitsrelevant und werden hier festgeschrieben:

* Berichte gehen nur an Absender auf der Whitelist.
* Ein Sendebericht behauptet eine Uebertragung nur mit Quittung.
"""

from __future__ import annotations

import email
import email.policy
import socket
import threading

import pytest

from mail2fax import notify
from mail2fax.config import AppConfig
from mail2fax.storage import Job

# -- Hilfen -----------------------------------------------------------------


@pytest.fixture
def config():
    config = AppConfig()
    config.smtp.enabled = True
    config.smtp.host = "smtp.example.com"
    config.smtp.from_address = "fax@example.com"
    config.smtp.admin_address = ""
    config.security.sender_whitelist = ["chef@example.com", "*@intern.example.com"]
    return config


@pytest.fixture
def postfach(monkeypatch):
    """Faengt alle ausgehenden Nachrichten ab."""
    gesendet: list[dict] = []

    def fake_send(_smtp, to_address, subject, body):
        gesendet.append({"to": to_address, "subject": subject, "body": body})

    monkeypatch.setattr(notify, "send_mail", fake_send)
    return gesendet


def auftrag(**felder) -> Job:
    werte = {
        "id": 42,
        "created_at": 1_790_000_000.0,
        "updated_at": 1_790_000_100.0,
        "message_id": "<1@example.com>",
        "sender": "chef@example.com",
        "subject": "Rechnung 2026-001",
        "number": "+49301234567",
        "source": "mail",
        "status": "sent",
        "attempts": 1,
        "next_attempt_at": 0.0,
        "pages": 3,
        "documents": [],
        "error": None,
        "backend": "sip",
    }
    werte.update(felder)
    return Job(**werte)


# -- Whitelist als Voraussetzung -------------------------------------------


@pytest.mark.parametrize(
    ("adresse", "erwartet"),
    [
        ("chef@example.com", True),
        ("Chef <CHEF@Example.COM>", True),
        ("mitarbeiter@intern.example.com", True),
        ("fremd@example.org", False),
        ("chef@example.com.angreifer.org", False),
        ("", False),
        ("keine-adresse", False),
    ],
)
def test_only_whitelisted_addresses_receive_reports(config, adresse, erwartet):
    assert notify.may_report_to(config, adresse) is erwartet


def test_no_report_when_smtp_disabled(config):
    config.smtp.enabled = False
    assert notify.may_report_to(config, "chef@example.com") is False


def test_no_report_when_switched_off(config):
    config.smtp.notify_sender = False
    assert notify.may_report_to(config, "chef@example.com") is False


def test_stranger_gets_no_answer_at_all(config, postfach):
    """Der Kern: Auf eine Nachricht von ausserhalb wird nicht geantwortet.

    Der From-Header ist fälschbar. Wuerde mail2fax antworten, liesse sich der
    Dienst als Absender fremder Post missbrauchen.
    """
    assert notify.report_rejection(
        config, "fremd@example.org", "+49301234567", "Absender steht nicht auf der Whitelist"
    ) is False
    assert postfach == []


def test_whitelisted_sender_gets_rejection_report(config, postfach):
    """Ein berechtigter Absender erfaehrt, warum es nicht geklappt hat."""
    assert notify.report_rejection(
        config, "chef@example.com", "Bitte faxen", "Im Betreff wurde keine Rufnummer gefunden"
    ) is True
    assert len(postfach) == 1
    assert postfach[0]["to"] == "chef@example.com"
    assert "FEHLERBERICHT" in postfach[0]["body"]
    assert "keine Rufnummer" in postfach[0]["body"]
    assert "+49301234567" in postfach[0]["body"]  # Beispiel in der Anleitung


def test_transmission_report_goes_only_to_whitelisted(config, postfach):
    assert notify.report_transmission(config, auftrag(sender="fremd@example.org", confirmed=True)) is False
    assert postfach == []


# -- Sendebericht: bestaetigt ----------------------------------------------


def test_confirmed_report_states_the_transmission(config, postfach):
    job = auftrag(
        confirmed=True, pages_sent=3, rate="14400", resolution="204x196",
        remote_station="+4930999888", duration=47.6,
    )
    assert notify.report_transmission(config, job) is True
    bericht = postfach[0]

    assert "Sendebericht" in bericht["subject"]
    assert "uebertragen" in bericht["subject"]
    assert "3 Seiten" in bericht["subject"]

    text = bericht["body"]
    assert "SENDEBERICHT" in text
    assert "quittiert" in text
    assert "+49301234567" in text
    assert "+4930999888" in text
    assert "14400 bit/s" in text
    assert "204x196" in text
    assert "48 s" in text
    assert "Rechnung 2026-001" in text
    assert "#42" in text


def test_confirmed_report_names_partial_transmission(config, postfach):
    """Weichen uebertragene und vorbereitete Seiten ab, wird beides genannt."""
    notify.report_transmission(config, auftrag(confirmed=True, pages=3, pages_sent=2))
    assert "2 von 3" in postfach[0]["body"]


def test_confirmed_report_does_not_overclaim(config, postfach):
    """Der Bericht belegt die Uebertragung, nicht die Kenntnisnahme."""
    notify.report_transmission(config, auftrag(confirmed=True, pages_sent=1))
    text = postfach[0]["body"]
    assert "nicht die Kenntnisnahme" in text


# -- Sendebericht: unbestaetigt -------------------------------------------


def test_unconfirmed_report_is_clearly_marked(config, postfach):
    job = auftrag(confirmed=False, backend="mailgateway")
    assert notify.report_transmission(config, job) is True
    bericht = postfach[0]

    assert "ohne Uebertragungsnachweis" in bericht["subject"]
    assert "Sendebericht" not in bericht["subject"]
    text = bericht["body"]
    assert "UEBERGABEBESTAETIGUNG" in text
    assert "NICHT vor" in text
    assert "nicht belegt" in text
    assert "quittiert" not in text


def test_unconfirmed_report_can_be_switched_off(config, postfach):
    """Wer nur belegte Berichte will, schaltet unbestaetigte ab."""
    config.smtp.report_unconfirmed = False
    assert notify.report_transmission(config, auftrag(confirmed=False)) is False
    assert postfach == []
    # Bestaetigte Berichte gehen weiterhin hinaus.
    assert notify.report_transmission(config, auftrag(confirmed=True)) is True
    assert len(postfach) == 1


# -- Fehlerbericht ---------------------------------------------------------


def test_final_failure_report(config, postfach):
    job = auftrag(status="failed", attempts=3, error="Leitung belegt")
    assert notify.report_failure(config, job, reason="Leitung belegt", final=True) is True
    bericht = postfach[0]
    assert "Fehlerbericht" in bericht["subject"]
    assert "FEHLERBERICHT" in bericht["body"]
    assert "Leitung belegt" in bericht["body"]
    assert "3 von 3" in bericht["body"]
    assert "keine weiteren" in bericht["body"]


def test_interim_failure_report_announces_retry(config, postfach):
    job = auftrag(status="queued", attempts=1, next_attempt_at=1_790_000_400.0)
    notify.report_failure(config, job, reason="Keine Antwort", final=False)
    text = postfach[0]["body"]
    assert "ZWISCHENBERICHT" in text
    assert "versucht es erneut" in text
    assert "Naechster Versuch" in text


def test_admin_is_informed_even_for_unlisted_sender(config, postfach):
    """Der Betreiber soll von Fehlern erfahren - auch ohne Bericht an den Absender."""
    config.smtp.admin_address = "admin@example.com"
    job = auftrag(sender="fremd@example.org", status="failed", attempts=3)
    assert notify.report_failure(config, job, reason="Rufnummer ungueltig", final=True) is False

    assert len(postfach) == 1
    assert postfach[0]["to"] == "admin@example.com"
    assert "[mail2fax]" in postfach[0]["subject"]
    assert "fremd@example.org" in postfach[0]["body"]


def test_admin_copy_only_on_final_failure(config, postfach):
    config.smtp.admin_address = "admin@example.com"
    notify.report_failure(config, auftrag(sender="fremd@example.org"), reason="x", final=False)
    assert postfach == []


# -- Echter SMTP-Versand ---------------------------------------------------


class FakeSmtpServer:
    """Winziger SMTP-Server, der eine Nachricht annimmt und festhaelt."""

    def __init__(self):
        self.nachricht = ""
        self.empfaenger: list[str] = []
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(1)
        self.port = self._server.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._server.close()

    def _serve(self):
        try:
            verbindung, _ = self._server.accept()
        except OSError:
            return
        with verbindung:
            verbindung.sendall(b"220 fake.example.com ESMTP\r\n")
            daten_modus = False
            puffer = ""
            while True:
                try:
                    empfangen = verbindung.recv(4096).decode("utf-8", "replace")
                except OSError:
                    return
                if not empfangen:
                    return
                puffer += empfangen
                while "\r\n" in puffer:
                    zeile, _, puffer = puffer.partition("\r\n")
                    if daten_modus:
                        if zeile == ".":
                            daten_modus = False
                            verbindung.sendall(b"250 OK\r\n")
                        else:
                            self.nachricht += zeile + "\n"
                        continue
                    befehl = zeile.upper()
                    if befehl.startswith(("HELO", "EHLO")):
                        verbindung.sendall(b"250 fake.example.com\r\n")
                    elif befehl.startswith("MAIL FROM"):
                        verbindung.sendall(b"250 OK\r\n")
                    elif befehl.startswith("RCPT TO"):
                        self.empfaenger.append(zeile.split(":", 1)[1].strip().strip("<>"))
                        verbindung.sendall(b"250 OK\r\n")
                    elif befehl == "DATA":
                        daten_modus = True
                        verbindung.sendall(b"354 Ende mit .\r\n")
                    elif befehl == "QUIT":
                        verbindung.sendall(b"221 Bye\r\n")
                        return
                    else:
                        verbindung.sendall(b"250 OK\r\n")


@pytest.fixture
def smtp_server():
    server = FakeSmtpServer()
    server.start()
    yield server
    server.stop()


def test_report_reaches_a_real_smtp_server(config, smtp_server):
    """Der Bericht geht wirklich als Mail hinaus, nicht nur ins Protokoll."""
    config.smtp.host = "127.0.0.1"
    config.smtp.port = smtp_server.port
    config.smtp.security = "none"

    job = auftrag(confirmed=True, pages_sent=2, rate="9600", remote_station="+4930999888")
    assert notify.report_transmission(config, job) is True

    assert smtp_server.empfaenger == ["chef@example.com"]
    nachricht = email.message_from_string(smtp_server.nachricht, policy=email.policy.default)
    assert nachricht["To"] == "chef@example.com"
    assert nachricht["From"] == "fax@example.com"
    assert "Sendebericht" in nachricht["Subject"]
    # Schutz vor Mailschleifen (RFC 3834)
    assert nachricht["Auto-Submitted"] == "auto-replied"
    assert nachricht["X-Auto-Response-Suppress"] == "All"
    inhalt = nachricht.get_content()
    assert "quittiert" in inhalt
    assert "9600 bit/s" in inhalt
    assert "+4930999888" in inhalt


def test_smtp_failure_does_not_raise(config, monkeypatch):
    """Ein nicht erreichbarer Mailserver darf den Faxbetrieb nicht stoeren."""
    config.smtp.host = "127.0.0.1"
    config.smtp.port = 1  # dort hoert niemand
    config.smtp.security = "none"
    assert notify.report_transmission(config, auftrag(confirmed=True)) is False
