"""Schmaler Client fuer das Asterisk Manager Interface (AMI).

AMI ist ein zeilenbasiertes Textprotokoll ueber TCP. Es werden nur die
wenigen Aktionen umgesetzt, die mail2fax fuer den Faxversand braucht -
bewusst ohne zusaetzliche Abhaengigkeit.
"""

from __future__ import annotations

import logging
import socket
import time
import uuid
from collections.abc import Iterator

LOGGER = logging.getLogger(__name__)

#: Ende eines AMI-Pakets.
TERMINATOR = b"\r\n\r\n"


class AmiError(Exception):
    """Fehler in der Kommunikation mit Asterisk.

    ``permanent=True`` bedeutet, dass ein erneuter Versuch zwecklos ist
    (etwa falsche Zugangsdaten).
    """

    def __init__(self, message: str, *, permanent: bool = False) -> None:
        super().__init__(message)
        self.permanent = permanent


class AmiMessage(dict):
    """Ein AMI-Paket als Zuordnung von Kopfzeilen (Schluessel kleingeschrieben)."""

    @property
    def event(self) -> str:
        return self.get("event", "")

    @property
    def response(self) -> str:
        return self.get("response", "")

    @property
    def is_success(self) -> bool:
        return self.response.lower() == "success"

    @property
    def message(self) -> str:
        return self.get("message", "")


def parse_packet(raw: str) -> AmiMessage:
    """Zerlegt ein AMI-Paket in seine Kopfzeilen.

    Mehrfach vorkommende Schluessel werden mit Zeilenumbruch verbunden;
    das betrifft vor allem die Ausgabe von ``Action: Command``.
    """
    packet = AmiMessage()
    for line in raw.split("\r\n"):
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key in packet:
            packet[key] = f"{packet[key]}\n{value}"
        else:
            packet[key] = value
    return packet


class AmiClient:
    """Verbindung zu Asterisk ueber AMI."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        *,
        connect_timeout: float = 10.0,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.connect_timeout = connect_timeout
        self._socket: socket.socket | None = None
        self._buffer = b""
        self.banner = ""

    # -- Verbindung --------------------------------------------------------

    def __enter__(self) -> AmiClient:
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def connect(self) -> None:
        try:
            self._socket = socket.create_connection(
                (self.host, self.port), timeout=self.connect_timeout
            )
        except OSError as error:
            raise AmiError(
                f"Asterisk ist unter {self.host}:{self.port} nicht erreichbar: {error}. "
                "Laeuft der Dienst (systemctl status asterisk) und ist AMI aktiviert?"
            ) from error
        self._socket.settimeout(self.connect_timeout)
        self.banner = self._read_line()
        if "asterisk" not in self.banner.lower():
            raise AmiError(
                f"Unerwartete Begruessung auf {self.host}:{self.port}: {self.banner!r} - "
                "antwortet dort wirklich Asterisk?",
                permanent=True,
            )
        self.login()

    def close(self) -> None:
        if self._socket is None:
            return
        try:
            self._send({"Action": "Logoff"})
        except (OSError, AmiError):  # pragma: no cover - Abmeldung ist unkritisch
            pass
        finally:
            try:
                self._socket.close()
            finally:
                self._socket = None

    def login(self) -> None:
        answer = self.request({"Action": "Login", "Username": self.username, "Secret": self.password})
        if not answer.is_success:
            raise AmiError(
                f"Anmeldung an Asterisk fehlgeschlagen: {answer.message or 'Zugangsdaten pruefen'}",
                permanent=True,
            )
        LOGGER.debug("An AMI angemeldet (%s)", self.banner.strip())

    # -- Ein- und Ausgabe --------------------------------------------------

    @property
    def socket(self) -> socket.socket:
        if self._socket is None:
            raise AmiError("Keine Verbindung zu Asterisk")
        return self._socket

    def _send(self, fields: dict[str, str], extra: list[tuple[str, str]] | None = None) -> None:
        lines = [f"{key}: {value}" for key, value in fields.items()]
        lines += [f"{key}: {value}" for key, value in (extra or [])]
        payload = ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8")
        try:
            self.socket.sendall(payload)
        except OSError as error:
            raise AmiError(f"Verbindung zu Asterisk abgebrochen: {error}") from error

    def _read_line(self, timeout: float | None = None) -> str:
        """Liest eine einzelne Zeile (fuer die Begruessung)."""
        deadline = time.monotonic() + (timeout or self.connect_timeout)
        while b"\r\n" not in self._buffer:
            self._fill(deadline)
        line, _, self._buffer = self._buffer.partition(b"\r\n")
        return line.decode("utf-8", "replace")

    def _fill(self, deadline: float) -> None:
        """Liest weitere Daten, bis die Gesamtfrist abgelaufen ist.

        Der Socket bekommt bewusst nur eine kurze Wartezeit, damit ein
        blockierendes recv unterbrechbar bleibt. Ein solcher Zwischenablauf
        ist noch kein Fehler - erst das Erreichen von ``deadline`` zaehlt.
        Eine Faxuebertragung dauert Minuten, in denen kein Paket kommt.
        """
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Zeitueberschreitung beim Lesen von Asterisk")
        self.socket.settimeout(min(remaining, 5.0))
        try:
            chunk = self.socket.recv(8192)
        except TimeoutError:
            return  # nur der kurze Zwischenablauf - erneut versuchen
        except OSError as error:
            raise AmiError(f"Verbindung zu Asterisk abgebrochen: {error}") from error
        if not chunk:
            raise AmiError("Asterisk hat die Verbindung geschlossen")
        self._buffer += chunk

    def read_packet(self, timeout: float = 10.0) -> AmiMessage:
        """Liest das naechste Paket; wirft ``TimeoutError`` bei Ablauf."""
        deadline = time.monotonic() + timeout
        while TERMINATOR not in self._buffer:
            self._fill(deadline)
        raw, _, self._buffer = self._buffer.partition(TERMINATOR)
        return parse_packet(raw.decode("utf-8", "replace"))

    def request(
        self,
        fields: dict[str, str],
        *,
        extra: list[tuple[str, str]] | None = None,
        timeout: float = 15.0,
    ) -> AmiMessage:
        """Sendet eine Aktion und liefert die zugehoerige Antwort.

        Ereignisse, die waehrenddessen eintreffen, werden uebersprungen.
        """
        action_id = fields.setdefault("ActionID", f"mail2fax-{uuid.uuid4().hex[:12]}")
        self._send(fields, extra)
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AmiError(f"Asterisk antwortet nicht auf {fields.get('Action')}")
            packet = self.read_packet(timeout=remaining)
            if packet.get("actionid") == action_id and packet.response:
                return packet
            if packet.response and "actionid" not in packet:
                return packet

    def events(self, timeout: float) -> Iterator[AmiMessage]:
        """Liefert eintreffende Ereignisse bis zum Ablauf der Frist."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            try:
                yield self.read_packet(timeout=remaining)
            except TimeoutError:
                return

    # -- Bequeme Aktionen --------------------------------------------------

    def command(self, command: str, *, timeout: float = 15.0) -> str:
        """Fuehrt ein CLI-Kommando aus und liefert dessen Ausgabe."""
        answer = self.request({"Action": "Command", "Command": command}, timeout=timeout)
        if not answer.is_success and answer.response.lower() == "error":
            raise AmiError(
                f"Kommando '{command}' abgelehnt: {answer.message or 'fehlende Berechtigung'}"
            )
        return answer.get("output") or answer.get("actionid_output") or ""

    def ping(self) -> bool:
        return self.request({"Action": "Ping"}).is_success
