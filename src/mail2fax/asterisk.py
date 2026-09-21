"""Erzeugt die Asterisk-Konfiguration fuer den Faxversand ueber SIP.

mail2fax schreibt ausschliesslich in ein eigenes Verzeichnis (Vorgabe
/etc/asterisk/mail2fax). Die mitgelieferten Dateien von Asterisk werden nur
um jeweils eine ``#include``-Zeile ergaenzt - das erledigt das Einrichtungs-
skript einmalig als root.
"""

from __future__ import annotations

import logging
import os
import secrets
import tempfile
from pathlib import Path

from .config import SipConfig

LOGGER = logging.getLogger(__name__)

#: Kontext, in den mail2fax die Faxanrufe einspeist.
DIALPLAN_CONTEXT = "mail2fax-send"
#: Erweiterung innerhalb dieses Kontexts.
DIALPLAN_EXTEN = "fax"
#: Name des UserEvent, mit dem der Dialplan das Ergebnis zurueckmeldet.
RESULT_EVENT = "mail2faxresult"

_HEADER = """;
; Von mail2fax erzeugt - Aenderungen gehen beim naechsten "sip-apply" verloren.
; Passen Sie stattdessen die Einstellungen in mail2fax an.
;
"""


def _quote(value: str) -> str:
    """Entfernt Zeichen, mit denen sich eine Konfigurationszeile einschleusen liesse.

    Entfernt werden Steuerzeichen (vor allem Zeilenumbrueche) und das
    Kommentarzeichen ";". Sie werden ersatzlos gestrichen und nicht durch ein
    Leerzeichen ersetzt, damit aus einem Wert keine zwei Woerter entstehen.
    """
    text = str(value or "")
    return "".join(char for char in text if char >= " " and char not in ";\x7f").strip()


def render_pjsip(sip: SipConfig) -> str:
    """Registrierung, Authentifizierung und Endpunkt fuer die Anlage."""
    name = _quote(sip.endpoint_name) or "mail2fax-tk"
    server = _quote(sip.server)
    user = _quote(sip.username)
    password = _quote(sip.password)
    transport = f"transport-{sip.transport}-mail2fax"
    server_uri = f"sip:{server}:{sip.port}" if sip.port != 5060 else f"sip:{server}"

    lines = [
        _HEADER,
        f"[{transport}]",
        "type=transport",
        f"protocol={sip.transport}",
        "bind=0.0.0.0",
        "",
        f"[{name}-auth]",
        "type=auth",
        "auth_type=userpass",
        f"username={user}",
        f"password={password}",
        "",
        f"[{name}]",
        "type=registration",
        f"transport={transport}",
        f"outbound_auth={name}-auth",
        f"server_uri={server_uri}",
        f"client_uri=sip:{user}@{server}",
        "retry_interval=60",
        "forbidden_retry_interval=600",
        "expiration=600",
        "line=yes",
        f"endpoint={name}",
        "",
        f"[{name}]",
        "type=aor",
        f"contact={server_uri}",
        "qualify_frequency=60",
        "",
        f"[{name}]",
        "type=endpoint",
        f"transport={transport}",
        f"context={DIALPLAN_CONTEXT}-in",
        "disallow=all",
        # Fax vertraegt keine komprimierenden Codecs - nur G.711.
        "allow=alaw",
        "allow=ulaw",
        f"outbound_auth={name}-auth",
        f"aors={name}",
        f"from_user={user}",
        f"from_domain={server}",
        # Medien muessen ueber Asterisk laufen, sonst sieht spandsp nichts.
        "direct_media=no",
        "rtp_symmetric=yes",
        "force_rport=yes",
        "rewrite_contact=yes",
        "dtmf_mode=rfc4733",
        # Faxerkennung auf eingehenden Anrufen ist hier nicht noetig.
        "fax_detect=no",
    ]

    if sip.t38:
        lines += [
            "t38_udptl=yes",
            "t38_udptl_ec=redundancy",
            "t38_udptl_maxdatagram=400",
            "t38_udptl_nat=yes",
        ]
    else:
        lines.append("t38_udptl=no")

    lines += [
        "",
        f"[{name}-identify]",
        "type=identify",
        f"endpoint={name}",
        f"match={server}",
        "",
    ]
    return "\n".join(lines)


def render_extensions(sip: SipConfig) -> str:
    """Dialplan, der das Fax sendet und das Ergebnis per UserEvent meldet.

    Die Faxparameter kommen als Kanalvariablen aus der Originate-Aktion,
    damit der Dialplan bei Aenderungen nicht neu geladen werden muss.
    """
    return f"""{_HEADER}
[{DIALPLAN_CONTEXT}]
; Wird von mail2fax ueber AMI "Originate" angesprungen, sobald die
; Gegenstelle abgehoben hat.
exten => {DIALPLAN_EXTEN},1,NoOp(mail2fax: Fax ${{M2F_REF}} an ${{M2F_NUMBER}})
 same => n,Set(FAXOPT(localstationid)=${{M2F_STATIONID}})
 same => n,Set(FAXOPT(headerinfo)=${{M2F_HEADER}})
 same => n,Set(FAXOPT(ecm)=${{M2F_ECM}})
 same => n,Set(FAXOPT(minrate)=${{M2F_MINRATE}})
 same => n,Set(FAXOPT(maxrate)=${{M2F_MAXRATE}})
 same => n,SendFAX(${{M2F_FILE}},${{M2F_OPTIONS}})
 same => n,NoOp(mail2fax: Status=${{FAXOPT(status)}} Seiten=${{FAXOPT(pages)}})
 same => n,UserEvent({RESULT_EVENT},Ref: ${{M2F_REF}},Status: ${{FAXOPT(status)}},Pages: ${{FAXOPT(pages)}},Rate: ${{FAXOPT(rate)}},Resolution: ${{FAXOPT(resolution)}},Error: ${{FAXOPT(error)}},Detail: ${{FAXOPT(statusstr)}})
 same => n,Hangup()

; Auch bei Abbruch (Gegenstelle legt auf, Fehler im Modem) soll mail2fax
; eine Rueckmeldung bekommen, statt in den Zeitablauf zu laufen.
exten => h,1,NoOp(mail2fax: Verbindung beendet - Status=${{FAXOPT(status)}})
 same => n,UserEvent({RESULT_EVENT},Ref: ${{M2F_REF}},Status: ${{FAXOPT(status)}},Pages: ${{FAXOPT(pages)}},Rate: ${{FAXOPT(rate)}},Resolution: ${{FAXOPT(resolution)}},Error: ${{FAXOPT(error)}},Detail: ${{FAXOPT(statusstr)}})
 same => n,Return()

exten => failed,1,NoOp(mail2fax: Verbindungsaufbau gescheitert - ${{REASON}})
 same => n,UserEvent({RESULT_EVENT},Ref: ${{M2F_REF}},Status: FAILED,Pages: 0,Error: DIAL,Detail: Verbindungsaufbau gescheitert (${{REASON}}))
 same => n,Hangup()

[{DIALPLAN_CONTEXT}-in]
; Eingehende Anrufe nimmt mail2fax nicht entgegen.
exten => _[0-9a-zA-Z*#+].,1,NoOp(mail2fax: eingehender Anruf wird abgewiesen)
 same => n,Hangup(21)
exten => s,1,NoOp(mail2fax: eingehender Anruf wird abgewiesen)
 same => n,Hangup(21)
"""


def render_manager(sip: SipConfig) -> str:
    """AMI-Benutzer fuer mail2fax - nur lokal und mit engen Rechten."""
    user = _quote(sip.ami_user) or "mail2fax"
    return f"""{_HEADER}
[{user}]
secret = {_quote(sip.ami_password)}
; Nur vom selben Rechner aus erreichbar.
; Reihenfolge ist wichtig: Asterisk wertet deny und permit von oben nach
; unten aus - ein nachgestelltes "deny" wuerde alles wieder sperren.
deny = 0.0.0.0/0.0.0.0
permit = 127.0.0.1/255.255.255.255
; originate: Fax senden | command: Zustand abfragen und neu laden
; call/user: Rueckmeldungen des Dialplans empfangen
read = call,user,system
write = originate,command,reload
eventfilter = Event: UserEvent
eventfilter = Event: OriginateResponse
eventfilter = Event: Hangup
"""


def generate_ami_secret() -> str:
    """Erzeugt ein Passwort fuer den AMI-Zugang."""
    return secrets.token_urlsafe(30)


def _write(path: Path, content: str, *, mode: int = 0o640) -> None:
    """Schreibt eine Datei atomar mit restriktiven Rechten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(temp_name, mode)
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def write_config(sip: SipConfig, directory: Path | None = None) -> list[Path]:
    """Schreibt alle Asterisk-Dateien und liefert deren Pfade."""
    target = Path(directory) if directory else Path(sip.config_dir)
    files = {
        "pjsip.conf": render_pjsip(sip),
        "extensions.conf": render_extensions(sip),
        "manager.conf": render_manager(sip),
    }
    written: list[Path] = []
    for name, content in files.items():
        path = target / name
        _write(path, content)
        written.append(path)
    LOGGER.info("Asterisk-Konfiguration geschrieben: %s", ", ".join(str(p) for p in written))
    return written


def include_line(directory: Path, filename: str) -> str:
    """Die ``#include``-Zeile, die in Asterisks Hauptdatei gehoert."""
    return f'#include "{Path(directory) / filename}"'


#: Module, die nach einer Aenderung neu geladen werden muessen.
RELOAD_COMMANDS = ("manager reload", "pjsip reload", "dialplan reload")


def reload_asterisk(sip: SipConfig) -> str:
    """Laedt die geaenderte Konfiguration in Asterisk neu.

    Bevorzugt wird die Kommandozeile (funktioniert auch, wenn sich die
    AMI-Zugangsdaten gerade geaendert haben). Steht sie nicht zur Verfuegung -
    etwa weil der Dienstbenutzer die Weboberflaeche bedient -, wird der
    Neuaufbau ueber AMI angestossen.
    """
    import shutil
    import subprocess

    binary = shutil.which("asterisk")
    if binary:
        fehler: list[str] = []
        for command in RELOAD_COMMANDS:
            try:
                completed = subprocess.run(  # noqa: S603 - feste Argumentliste
                    [binary, "-rx", command], check=False, capture_output=True, timeout=30
                )
            except (OSError, subprocess.TimeoutExpired) as error:  # pragma: no cover
                fehler.append(f"{command}: {error}")
                continue
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or b"").decode("utf-8", "replace")
                fehler.append(f"{command}: {detail.strip()[:120]}")
        if not fehler:
            return "Asterisk hat die Konfiguration neu geladen."
        LOGGER.warning("Neuladen ueber die Kommandozeile unvollstaendig: %s", "; ".join(fehler))

    # Zweiter Versuch ueber AMI (z. B. aus der Weboberflaeche heraus).
    from .fax.ami import AmiClient, AmiError

    try:
        with AmiClient(sip.ami_host, sip.ami_port, sip.ami_user, sip.ami_password) as client:
            for command in RELOAD_COMMANDS:
                client.command(command)
        return "Asterisk hat die Konfiguration ueber AMI neu geladen."
    except AmiError as error:
        raise RuntimeError(
            f"Die Konfiguration wurde geschrieben, aber Asterisk konnte sie nicht neu "
            f"laden: {error}. Bitte von Hand ausfuehren: asterisk -rx 'core reload'"
        ) from error
