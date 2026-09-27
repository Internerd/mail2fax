"""Tests des SIP-Backends gegen einen simulierten Asterisk.

Der Fake spricht dasselbe AMI-Protokoll wie Asterisk, sodass Anmeldung,
Originate, Ereignisauswertung und Fehlerpfade ohne echte Telefonanlage
geprueft werden koennen.
"""

from __future__ import annotations

import socket
import threading
import time

import pytest

from mail2fax.config import AppConfig
from mail2fax.fax import FaxError, get_backend
from mail2fax.fax.ami import AmiClient, AmiError, parse_packet
from mail2fax.fax.sip import SipBackend
from mail2fax.render import text_to_pdf
from mail2fax.rules import Number

# -- Simulierter Asterisk ---------------------------------------------------


class FakeAsterisk:
    """Minimaler AMI-Server fuer die Tests.

    Bewusst ohne Vererbung von ``threading.Thread``: Python 3.13 belegt dort
    das Attribut ``_handle`` selbst, was gleichnamige Methoden einer
    Unterklasse ueberschreiben wuerde.
    """

    def __init__(self, *, secret="geheim", result=None, originate_error=None, delay=0.0):
        self.secret = secret
        self.result = result
        self.originate_error = originate_error
        self.delay = delay
        self.received: list[dict] = []
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(1)
        self.port = self._server.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, name="fake-asterisk", daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._server.close()

    def _serve(self):
        try:
            connection, _ = self._server.accept()
        except OSError:
            return
        with connection:
            connection.sendall(b"Asterisk Call Manager/9.0.0\r\n")
            buffer = b""
            while not self._stop.is_set():
                try:
                    connection.settimeout(0.5)
                    chunk = connection.recv(4096)
                except TimeoutError:
                    continue  # Leerlauf ist normal - Asterisk haelt die Verbindung
                except OSError:
                    return
                if not chunk:
                    return
                buffer += chunk
                while b"\r\n\r\n" in buffer:
                    raw, _, buffer = buffer.partition(b"\r\n\r\n")
                    self._handle_action(connection, raw.decode())

    def _handle_action(self, connection, raw):
        packet = parse_packet(raw)
        self.received.append(dict(packet))
        action = packet.get("action", "").lower()
        action_id = packet.get("actionid", "")

        def send(text):
            connection.sendall(text.replace("\n", "\r\n").encode())

        if action == "login":
            if packet.get("secret") == self.secret:
                send(f"Response: Success\nActionID: {action_id}\nMessage: Authentication accepted\n\n")
            else:
                send(f"Response: Error\nActionID: {action_id}\nMessage: Authentication failed\n\n")
        elif action == "logoff":
            send("Response: Goodbye\n\n")
        elif action == "ping":
            send(f"Response: Success\nActionID: {action_id}\nPing: Pong\n\n")
        elif action == "command":
            befehl = packet.get("command", "")
            ausgabe = self._command_output(befehl)
            send(
                f"Response: Success\nActionID: {action_id}\nMessage: Command output follows\n"
                + "".join(f"Output: {zeile}\n" for zeile in ausgabe.splitlines())
                + "\n"
            )
        elif action == "originate":
            if self.originate_error:
                send(f"Response: Error\nActionID: {action_id}\nMessage: {self.originate_error}\n\n")
                return
            send(f"Response: Success\nActionID: {action_id}\nMessage: Originate successfully queued\n\n")
            reference = ""
            for key, value in packet.items():
                if key == "variable" and "M2F_REF=" in value:
                    reference = value.split("M2F_REF=", 1)[1].splitlines()[0]
            threading.Thread(target=self._answer, args=(connection, reference), daemon=True).start()

    def _answer(self, connection, reference):
        time.sleep(self.delay)
        if self.result is None:
            return  # gar keine Rueckmeldung - laeuft in den Zeitablauf
        try:
            if self.result == "dialfailure":
                connection.sendall(
                    b"Event: OriginateResponse\r\nResponse: Failure\r\nReason: 5\r\n\r\n"
                )
                return
            felder = "".join(f"{k}: {v}\r\n" for k, v in self.result.items())
            connection.sendall(
                f"Event: UserEvent\r\nUserEvent: mail2faxresult\r\nRef: {reference}\r\n".encode()
                + felder.encode()
                + b"\r\n"
            )
        except OSError:
            pass  # Test ist bereits beendet und hat die Verbindung geschlossen

    @staticmethod
    def _command_output(befehl):
        if "res_fax_spandsp" in befehl:
            return "res_fax_spandsp.so  Spandsp G.711 and T.38 FAX Technologies  0  Running\n1 modules loaded"
        if "registrations" in befehl:
            return "mail2fax-tk/sip:fritz.box   mail2fax-tk-auth   Registered\nObjects found: 1"
        return "OK"


@pytest.fixture
def asterisk():
    server = FakeAsterisk()
    server.start()
    yield server
    server.stop()


@pytest.fixture
def config(asterisk):
    config = AppConfig()
    config.fax.backend = "sip"
    sip = config.fax.sip
    sip.ami_host, sip.ami_port, sip.ami_password = "127.0.0.1", asterisk.port, "geheim"
    sip.username, sip.password = "620", "sip-geheim"
    sip.sender_number = "+49301234567"
    return config


@pytest.fixture
def document(tmp_path):
    return text_to_pdf("Faxinhalt", tmp_path / "fax.pdf").path


needs_ghostscript = pytest.mark.skipif(
    __import__("shutil").which("gs") is None, reason="Ghostscript ist nicht installiert"
)


# -- AMI-Protokoll ----------------------------------------------------------


def test_parse_packet_reads_headers():
    packet = parse_packet("Response: Success\r\nActionID: 42\r\nMessage: Alles gut")
    assert packet.is_success
    assert packet["actionid"] == "42"
    assert packet.message == "Alles gut"


def test_parse_packet_joins_repeated_keys():
    """Die Ausgabe von "Action: Command" kommt als viele Output-Zeilen."""
    packet = parse_packet("Response: Success\r\nOutput: Zeile 1\r\nOutput: Zeile 2")
    assert packet["output"] == "Zeile 1\nZeile 2"


def test_ami_login_and_ping(asterisk):
    with AmiClient("127.0.0.1", asterisk.port, "mail2fax", "geheim") as client:
        assert "Asterisk Call Manager" in client.banner
        assert client.ping() is True


def test_ami_login_with_wrong_password(asterisk):
    with pytest.raises(AmiError, match="Anmeldung"):
        AmiClient("127.0.0.1", asterisk.port, "mail2fax", "falsch").connect()


def test_ami_login_error_is_permanent(asterisk):
    try:
        AmiClient("127.0.0.1", asterisk.port, "mail2fax", "falsch").connect()
    except AmiError as error:
        assert error.permanent is True


def test_ami_unreachable():
    with pytest.raises(AmiError, match="nicht erreichbar"):
        AmiClient("127.0.0.1", 1, "mail2fax", "geheim").connect()


def test_ami_command_output(asterisk):
    with AmiClient("127.0.0.1", asterisk.port, "mail2fax", "geheim") as client:
        assert "Registered" in client.command("pjsip show registrations")


def test_ami_waits_beyond_socket_timeout(asterisk):
    """Eine Faxuebertragung dauert Minuten ohne ein einziges Paket.

    Ein kurzer Socket-Ablauf darf die Ereignisschleife nicht beenden.
    """
    asterisk.delay = 6.5  # laenger als die interne Wartezeit von 5 s
    asterisk.result = {"Status": "SUCCESS", "Pages": "1", "Rate": "14400"}
    with AmiClient("127.0.0.1", asterisk.port, "mail2fax", "geheim") as client:
        client.request({"Action": "Originate", "Channel": "x"}, extra=[("Variable", "M2F_REF=abc")])
        ereignisse = [packet for packet in client.events(20) if packet.event == "UserEvent"]
    assert ereignisse, "Ereignis nach dem kurzen Socket-Ablauf ging verloren"


# -- Rufnummernbildung ------------------------------------------------------


@pytest.mark.parametrize(
    ("national", "prefix", "erwartet"),
    [
        (True, "", "0301234567"),
        (False, "", "+49301234567"),
        (True, "0", "00301234567"),
        (False, "9", "9+49301234567"),
    ],
)
def test_dial_string(config, national, prefix, erwartet):
    config.fax.sip.dial_national = national
    config.fax.sip.dial_prefix = prefix
    assert SipBackend(config).dial_string(Number("+49301234567")) == erwartet


# -- Versand ----------------------------------------------------------------


@needs_ghostscript
def test_successful_transmission(config, asterisk, document):
    asterisk.result = {"Status": "SUCCESS", "Pages": "2", "Rate": "14400", "Detail": "OK"}
    result = get_backend(config).send(Number("+49301234567"), [document], subject="Rechnung")
    assert result.success
    assert "2 Seite(n)" in result.detail
    assert "14400" in result.detail


@needs_ghostscript
def test_originate_carries_all_parameters(config, asterisk, document):
    asterisk.result = {"Status": "SUCCESS", "Pages": "1"}
    get_backend(config).send(Number("+49301234567"), [document])

    originate = next(p for p in asterisk.received if p.get("action") == "Originate")
    assert originate["channel"] == "PJSIP/0301234567@mail2fax-tk"
    assert originate["context"] == "mail2fax-send"
    assert originate["exten"] == "fax"
    variablen = originate["variable"]
    assert "M2F_STATIONID=+49301234567" in variablen
    assert "M2F_ECM=no" in variablen
    assert "M2F_OPTIONS=f" in variablen, "ohne T.38 wird im Audiomodus gefaxt"
    assert ".tif" in variablen, "Asterisk bekommt ein TIFF, kein PDF"


@needs_ghostscript
def test_t38_requests_reinvite(config, asterisk, document):
    config.fax.sip.t38 = True
    asterisk.result = {"Status": "SUCCESS", "Pages": "1"}
    get_backend(config).send(Number("+49301234567"), [document])
    originate = next(p for p in asterisk.received if p.get("action") == "Originate")
    assert "M2F_OPTIONS=fz" in originate["variable"]


@needs_ghostscript
def test_failed_transmission(config, asterisk, document):
    asterisk.result = {"Status": "FAILED", "Pages": "0", "Detail": "Keine Antwort der Gegenstelle"}
    with pytest.raises(FaxError, match="Keine Antwort der Gegenstelle"):
        get_backend(config).send(Number("+49301234567"), [document])


@needs_ghostscript
def test_busy_number(config, asterisk, document):
    asterisk.result = "dialfailure"
    with pytest.raises(FaxError, match=r"[Bb]esetzt"):
        get_backend(config).send(Number("+49301234567"), [document])


@needs_ghostscript
def test_no_response_runs_into_timeout(config, asterisk, document):
    config.fax.sip.timeout = 60  # Mindestwert des Modells
    asterisk.result = None
    backend = get_backend(config)
    backend.settings.timeout = 2  # fuer den Test verkuerzen
    with pytest.raises(FaxError, match="nicht zurueckgemeldet"):
        backend.send(Number("+49301234567"), [document])


@needs_ghostscript
def test_asterisk_rejects_originate(config, asterisk, document):
    asterisk.originate_error = "Extension does not exist"
    with pytest.raises(FaxError, match="nicht angenommen"):
        get_backend(config).send(Number("+49301234567"), [document])


def test_send_requires_sender_number(config, document):
    config.fax.sip.sender_number = ""
    with pytest.raises(FaxError, match="Faxnummer"):
        get_backend(config).send(Number("+49301234567"), [document])


def test_send_requires_username(config, document):
    config.fax.sip.username = ""
    with pytest.raises(FaxError, match="Benutzername"):
        get_backend(config).send(Number("+49301234567"), [document])


def test_send_without_setup_is_permanent(config, document):
    config.fax.sip.ami_password = ""
    with pytest.raises(FaxError, match="sip-apply") as info:
        get_backend(config).send(Number("+49301234567"), [document])
    assert info.value.permanent is True


# -- Auswertung der Rueckmeldung -------------------------------------------


def test_success_despite_hangup_error_field():
    """res_fax meldet auch bei Erfolg "HANGUP" im Feld Error."""
    from mail2fax.fax.ami import AmiMessage

    packet = AmiMessage({"status": "SUCCESS", "pages": "1", "rate": "14400", "error": "HANGUP"})
    assert SipBackend._evaluate(packet).success


def test_empty_status_is_reported_clearly():
    from mail2fax.fax.ami import AmiMessage

    with pytest.raises(FaxError, match="ohne Faxuebertragung"):
        SipBackend._evaluate(AmiMessage({"status": "", "pages": "0"}))


# -- Selbsttest -------------------------------------------------------------


@needs_ghostscript
def test_backend_test_reports_registration(config):
    meldung = get_backend(config).test()
    assert "res_fax_spandsp geladen" in meldung
    assert "Registered" in meldung


def test_registration_state_parsing():
    ausgabe = "mail2fax-tk/sip:fritz.box   mail2fax-tk-auth   Rejected   (exp. 12s ago)"
    assert SipBackend._registration_state(ausgabe, "mail2fax-tk") == "Rejected"
    assert SipBackend._registration_state(ausgabe, "anderer") == "nicht gefunden"


# -- Sendebericht: Quittung der Gegenstelle --------------------------------


@needs_ghostscript
def test_successful_transmission_is_confirmed(config, asterisk, document):
    """res_fax meldet SUCCESS - also hat die Gegenstelle quittiert."""
    asterisk.result = {
        "Status": "SUCCESS", "Pages": "2", "Rate": "14400",
        "Resolution": "8031x7700", "Remotestation": "+4930999888", "Detail": "OK",
    }
    result = get_backend(config).send(Number("+49301234567"), [document])
    assert result.confirmed is True
    assert result.pages_sent == 2
    assert result.rate == "14400"
    assert result.resolution == "204 x 196 dpi (fein)"
    assert result.remote_station == "+4930999888"
    assert result.duration is not None and result.duration >= 0


@pytest.mark.parametrize(
    ("roh", "erwartet"),
    [
        ("8031x7700", "204 x 196 dpi (fein)"),
        ("8031x3850", "204 x 98 dpi (Standard)"),
        ("8031x15400", "204 x 391 dpi (superfein)"),
        ("", ""),
        ("unbekannt", "unbekannt"),
    ],
)
def test_resolution_is_made_readable(roh, erwartet):
    """Asterisk meldet Punkte je Meter - im Bericht stehen dpi."""
    from mail2fax.fax.sip import _format_resolution

    assert _format_resolution(roh) == erwartet


def test_partially_transmitted_pages_appear_in_the_error():
    from mail2fax.fax.ami import AmiMessage

    with pytest.raises(FaxError, match="nach 2 uebertragener"):
        SipBackend._evaluate(AmiMessage({"status": "FAILED", "pages": "2", "detail": "Abbruch"}))


def test_foreign_number_is_dialled_with_00(config):
    """An der Anlage ist "+" oft nicht waehlbar - Auslandsnummern beginnen mit 00."""
    config.fax.sip.dial_national = True
    assert SipBackend(config).dial_string(Number("+431234567")) == "00431234567"


def test_trunk_zero_notation_is_not_dialled_abroad(config):
    """"+49 (0)30 1234567" wurde frueher als 0030… gewaehlt - also nach Griechenland."""
    from mail2fax.rules import extract_number

    nummer = extract_number("+49 (0)30 1234567", config.security)
    assert SipBackend(config).dial_string(nummer) == "0301234567"
