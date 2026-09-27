"""Faxversand ueber eine SIP-Registrierung an FRITZ!Box oder Telefonanlage.

mail2fax meldet sich als IP-Telefon an der Anlage an und uebertraegt das Fax
selbst. Die Medienverarbeitung (T.30/T.38) uebernimmt ein lokaler Asterisk
mit res_fax_spandsp; mail2fax steuert ihn ueber AMI:

  1. Die PDF-Dokumente werden zu einem Fax-TIFF (Gruppe 4) gewandelt.
  2. Ueber AMI wird ein Anruf zur Zielrufnummer aufgebaut (Originate).
  3. Sobald die Gegenstelle abhebt, laeuft der von mail2fax erzeugte
     Dialplan und ruft SendFAX auf.
  4. Der Dialplan meldet das Ergebnis per UserEvent zurueck.

Im Unterschied zum Backend "fritzbox" wird hier keine Weboberflaeche
ferngesteuert, sondern regulaer telefoniert. Das ist unabhaengig von
FRITZ!OS-Aenderungen und funktioniert ebenso an anderen Telefonanlagen.
"""

from __future__ import annotations

import logging
import shutil
import time
import uuid
from pathlib import Path

from ..asterisk import DIALPLAN_CONTEXT, DIALPLAN_EXTEN, RESULT_EVENT
from ..config import AppConfig
from ..rules import Number
from .ami import AmiClient, AmiError, AmiMessage
from .base import FaxBackend, FaxError, FaxResult

LOGGER = logging.getLogger(__name__)

#: Rueckmeldungen von res_fax, die einen erfolgreichen Versand bedeuten.
SUCCESS_STATES = {"SUCCESS", "OK"}

#: Gruende aus OriginateResponse, die Asterisk dokumentiert.
DIAL_REASONS = {
    "0": "Verbindungsaufbau fehlgeschlagen",
    "1": "Gegenstelle hat aufgelegt",
    "2": "Rufnummer unbekannt oder nicht erreichbar",
    "3": "Keine Antwort",
    "5": "Besetzt",
    "8": "Leitung belegt (Congestion)",
}


def _as_pages(value: str) -> int | None:
    """Wandelt die Seitenangabe von res_fax; leer oder unlesbar ergibt None."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


#: Uebliche vertikale Faxaufloesungen in dpi und ihre Bezeichnung.
RESOLUTION_NAMES = {98: "Standard", 196: "fein", 391: "superfein"}

#: Umrechnung der Angabe von res_fax (Punkte je Meter) in dpi.
_DOTS_PER_METRE_TO_DPI = 39.3701


def _format_resolution(value: str) -> str:
    """Macht aus der Angabe von res_fax eine lesbare Aufloesung.

    Asterisk meldet die Aufloesung in Punkten je Meter, etwa "8031x7700".
    Im Sendebericht steht das besser als "204 x 196 dpi (fein)".
    Unbekannte Formate werden unveraendert durchgereicht.
    """
    text = (value or "").strip().lower()
    if "x" not in text:
        return text
    waagerecht, _, senkrecht = text.partition("x")
    try:
        dpi_x = round(float(waagerecht) / _DOTS_PER_METRE_TO_DPI)
        dpi_y = round(float(senkrecht) / _DOTS_PER_METRE_TO_DPI)
    except ValueError:
        return text
    if not (50 <= dpi_x <= 1200 and 50 <= dpi_y <= 1200):
        return text
    bezeichnung = RESOLUTION_NAMES.get(dpi_y)
    lesbar = f"{dpi_x} x {dpi_y} dpi"
    return f"{lesbar} ({bezeichnung})" if bezeichnung else lesbar


class SipBackend(FaxBackend):
    """Versand ueber SIP mit Asterisk als Medien-Stack."""

    name = "SIP (FRITZ!Box / Telefonanlage)"

    def __init__(self, config: AppConfig) -> None:
        super().__init__(config)
        self.settings = config.fax.sip

    # -- Hilfen ------------------------------------------------------------

    def _client(self) -> AmiClient:
        settings = self.settings
        if not settings.ami_password:
            raise FaxError(
                "Die Asterisk-Anbindung ist noch nicht eingerichtet. Bitte einmal "
                "'mail2fax sip-apply' ausfuehren bzw. in der Weboberflaeche unter "
                "Fax die Schaltflaeche 'Asterisk-Konfiguration anwenden' benutzen.",
                permanent=True,
            )
        return AmiClient(
            settings.ami_host, settings.ami_port, settings.ami_user, settings.ami_password
        )

    def dial_string(self, number: Number) -> str:
        """Die Rufnummer, wie sie an die Anlage uebergeben wird.

        An einer FRITZ!Box wird ueblicherweise national gewaehlt
        (0301234567); TK-Anlagen brauchen haeufig zusaetzlich eine
        Amtsholung.
        """
        settings = self.settings
        if settings.dial_national:
            target = number.formatted_national(self.config.security.default_country_code)
        else:
            target = number.e164
        return f"{settings.dial_prefix}{target}"

    def _prepare_tiff(self, documents: list[Path]) -> Path:
        """Fuehrt die Dokumente zusammen und wandelt sie in ein Fax-TIFF."""
        from ..render import RenderError, merge_pdfs, pdf_to_tiff

        workdir = documents[0].parent
        try:
            merged = merge_pdfs(documents, workdir / "fax-gesamt.pdf")
            return pdf_to_tiff(merged, workdir / "fax.tif").path
        except RenderError as error:
            raise FaxError(str(error), permanent=True) from error

    # -- Versand -----------------------------------------------------------

    def send(self, number: Number, documents: list[Path], *, subject: str = "") -> FaxResult:
        settings = self.settings
        if not documents:
            raise FaxError("Es liegen keine Dokumente zum Versand vor", permanent=True)
        if not settings.username:
            raise FaxError(
                "Fuer die SIP-Anbindung ist kein Benutzername hinterlegt", permanent=True
            )
        if not settings.sender_number:
            raise FaxError(
                "Fuer die SIP-Anbindung ist keine eigene Faxnummer (Absenderkennung) "
                "hinterlegt - ohne sie weist die Gegenstelle das Fax haeufig ab",
                permanent=True,
            )

        tiff = self._prepare_tiff(documents)
        if not tiff.exists():
            raise FaxError("Das Fax-TIFF wurde nicht erzeugt", permanent=True)

        reference = uuid.uuid4().hex[:12]
        target = self.dial_string(number)
        LOGGER.info("Sende Fax %s an %s ueber SIP (%s)", reference, target, settings.endpoint_name)

        begonnen = time.monotonic()
        try:
            with self._client() as client:
                self._originate(client, target, tiff, reference, subject)
                result = self._await_result(client, reference)
        except AmiError as error:
            raise FaxError(str(error), permanent=error.permanent) from error

        result.duration = round(time.monotonic() - begonnen, 1)
        return result

    def _originate(
        self, client: AmiClient, target: str, tiff: Path, reference: str, subject: str
    ) -> None:
        settings = self.settings
        # "f" erlaubt den Versand als Software-Faxmodem ueber G.711,
        # "z" fordert zusaetzlich eine Umschaltung auf T.38 an.
        options = "fz" if settings.t38 else "f"
        variables = [
            ("Variable", f"M2F_REF={reference}"),
            ("Variable", f"M2F_NUMBER={target}"),
            ("Variable", f"M2F_FILE={tiff}"),
            ("Variable", f"M2F_STATIONID={settings.sender_number}"),
            ("Variable", f"M2F_HEADER={settings.station_name or 'mail2fax'}"),
            ("Variable", f"M2F_ECM={'yes' if settings.ecm else 'no'}"),
            ("Variable", f"M2F_MINRATE={settings.minrate}"),
            ("Variable", f"M2F_MAXRATE={settings.maxrate}"),
            ("Variable", f"M2F_OPTIONS={options}"),
        ]
        answer = client.request(
            {
                "Action": "Originate",
                "Channel": f"PJSIP/{target}@{settings.endpoint_name}",
                "Context": DIALPLAN_CONTEXT,
                "Exten": DIALPLAN_EXTEN,
                "Priority": "1",
                "CallerID": f"{settings.station_name} <{settings.sender_number}>",
                "Timeout": str(settings.dial_timeout * 1000),
                "Async": "true",
                "Codecs": "alaw,ulaw",
            },
            extra=variables,
            timeout=30.0,
        )
        if not answer.is_success:
            raise FaxError(
                f"Asterisk hat den Anruf nicht angenommen: "
                f"{answer.message or 'unbekannter Grund'}. "
                f"Ist der Endpunkt '{settings.endpoint_name}' registriert?"
            )
        LOGGER.debug("Anruf %s eingereiht (%s)", reference, subject or "ohne Betreff")

    def _await_result(self, client: AmiClient, reference: str) -> FaxResult:
        """Wartet auf die Rueckmeldung des Dialplans."""
        settings = self.settings
        for packet in client.events(settings.timeout):
            if self._is_result(packet, reference):
                return self._evaluate(packet)
            if packet.event == "OriginateResponse" and packet.get("response", "").lower() == "failure":
                reason = packet.get("reason", "")
                detail = DIAL_REASONS.get(reason, f"Grund {reason or 'unbekannt'}")
                raise FaxError(f"Anruf kam nicht zustande: {detail}")
        raise FaxError(
            f"Asterisk hat sich innerhalb von {settings.timeout}s nicht zurueckgemeldet. "
            "Pruefen Sie 'asterisk -rx \"core show channels\"' und das Asterisk-Protokoll."
        )

    @staticmethod
    def _is_result(packet: AmiMessage, reference: str) -> bool:
        return (
            packet.event == "UserEvent"
            and packet.get("userevent", "").lower() == RESULT_EVENT
            and packet.get("ref") == reference
        )

    @staticmethod
    def _evaluate(packet: AmiMessage) -> FaxResult:
        """Wertet die Rueckmeldung des Dialplans aus.

        Meldet res_fax "SUCCESS", hat die Gegenstelle am Ende der
        T.30-Uebertragung quittiert. Nur dann gilt das Fax als bestaetigt
        uebertragen - entsprechend wird ``confirmed`` gesetzt.
        """
        status = (packet.get("status") or "").strip().upper()
        pages = (packet.get("pages") or "").strip()
        detail = (packet.get("detail") or "").strip()
        error = (packet.get("error") or "").strip()
        rate = (packet.get("rate") or "").strip()
        resolution = (packet.get("resolution") or "").strip()
        remote = (packet.get("remotestation") or "").strip()

        if status in SUCCESS_STATES:
            uebertragen = _as_pages(pages)
            beschreibung = f"{uebertragen if uebertragen is not None else '?'} Seite(n) uebertragen"
            if rate:
                beschreibung += f" mit {rate} bit/s"
            if remote:
                beschreibung += f", Gegenstelle {remote}"
            return FaxResult(
                success=True,
                detail=beschreibung,
                confirmed=True,
                pages_sent=uebertragen,
                rate=rate,
                resolution=_format_resolution(resolution),
                remote_station=remote,
            )

        meldung = detail or error or status or "unbekannter Fehler"
        # Ein leerer Status bedeutet meist, dass die Verbindung abbrach,
        # bevor die Faxuebertragung begonnen hat.
        if not status:
            meldung = f"Verbindung endete ohne Faxuebertragung ({meldung})"
        uebertragen = _as_pages(pages)
        if uebertragen:
            meldung += f" - nach {uebertragen} uebertragener Seite(n)"
        raise FaxError(f"Faxuebertragung fehlgeschlagen: {meldung}")

    # -- Selbsttest --------------------------------------------------------

    def test(self) -> str:
        settings = self.settings
        meldungen: list[str] = []

        if not shutil.which("gs"):
            raise FaxError(
                "Ghostscript fehlt - ohne es koennen keine Fax-TIFF erzeugt werden "
                "(apt install ghostscript)",
                permanent=True,
            )
        meldungen.append("Ghostscript vorhanden")

        try:
            with self._client() as client:
                module = client.command("module show like res_fax_spandsp")
                if "res_fax_spandsp.so" not in module:
                    raise FaxError(
                        "Das Asterisk-Modul res_fax_spandsp ist nicht geladen - "
                        "ohne es kann Asterisk keine Faxe senden.",
                        permanent=True,
                    )
                meldungen.append("Asterisk erreichbar, res_fax_spandsp geladen")

                registrations = client.command("pjsip show registrations")
                zustand = self._registration_state(registrations, settings.endpoint_name)
                meldungen.append(f"Registrierung an {settings.server}: {zustand}")

                if "Registered" not in zustand:
                    meldungen.append(
                        "Hinweis: Solange die Registrierung nicht steht, koennen keine "
                        "Faxe gesendet werden. Pruefen Sie Benutzername und Passwort "
                        "des IP-Telefons in der Anlage."
                    )
        except AmiError as error:
            raise FaxError(str(error), permanent=error.permanent) from error

        return " | ".join(meldungen)

    @staticmethod
    def _registration_state(output: str, endpoint: str) -> str:
        """Liest den Registrierungszustand aus der CLI-Ausgabe."""
        for line in output.splitlines():
            if endpoint in line:
                for zustand in ("Registered", "Unregistered", "Rejected", "Stopped"):
                    if zustand in line:
                        return zustand
        return "nicht gefunden"
