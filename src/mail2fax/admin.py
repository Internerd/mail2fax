"""Verwaltungsaktionen mit Root-Rechten, angestossen aus der Weboberflaeche.

Der Webdienst laeuft bewusst ohne Sonderrechte (eigener Benutzer,
``NoNewPrivileges``, ``ProtectSystem=strict``). Ein Update oder die
Einrichtung von Asterisk braucht aber root. Die Bruecke ist so gebaut, dass
der Webdienst nichts bestimmen kann ausser *welche* von zwei festen Aktionen
laufen soll:

1. Die Weboberflaeche legt eine leere Anforderungsdatei an, etwa
   ``/var/lib/mail2fax/control/update.request``. Ihr Inhalt wird ignoriert.
2. Eine systemd-Pfad-Unit (``mail2fax-update.path``) bemerkt die Datei und
   startet ``mail2fax-aktion@update.service`` als root.
3. Dieser Dienst fuehrt ein root-eigenes Skript aus
   (``/usr/local/lib/mail2fax/update.sh``) - nie Code, den der Webdienst
   veraendern koennte.
4. Status und Protokoll schreibt root nach ``/var/lib/mail2fax-admin``, ein
   Verzeichnis, das dem Webdienst nicht gehoert. So laesst sich root kein
   Symlink auf eine fremde Datei unterschieben.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from . import paths

#: Die einzigen Aktionen, die die Weboberflaeche anfordern kann.
ACTIONS: dict[str, str] = {
    "update": "mail2fax aktualisieren",
    "sip-setup": "Asterisk fuer den Faxversand ueber SIP einrichten",
}

#: Woher Updates kommen. Fest im Code - nicht aus der Konfiguration.
UPDATE_REPO = "Internerd/mail2fax"

#: Nach dieser Zeit gilt ein "laeuft" ohne Abschluss als abgebrochen.
STALE_AFTER = 2 * 3600

#: Wird eine Anforderung so lange nicht abgeholt, laeuft die Pfad-Unit nicht.
PICKUP_TIMEOUT = 120

#: Farbcodes der Installationsskripte - im Browser nur Zeichensalat.
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

ADMIN_DIR = Path(os.environ.get("MAIL2FAX_ADMIN_DIR", "/var/lib/mail2fax-admin"))
HELPER_DIR = Path(os.environ.get("MAIL2FAX_HELPER_DIR", "/usr/local/lib/mail2fax"))
UNIT_DIR = Path(os.environ.get("MAIL2FAX_UNIT_DIR", "/etc/systemd/system"))
APP_DIR = Path(os.environ.get("MAIL2FAX_APP_DIR", "/opt/mail2fax"))
ASTERISK_ETC = Path(os.environ.get("MAIL2FAX_ASTERISK_ETC", "/etc/asterisk"))


class AdminError(Exception):
    """Eine Verwaltungsaktion kann nicht angefordert werden."""


@dataclass
class ActionState:
    """Zustand einer Verwaltungsaktion fuer die Anzeige."""

    name: str
    #: idle, pending, running, success, failed, stale
    state: str
    since: float | None = None
    detail: str = ""
    log: str = ""

    @property
    def busy(self) -> bool:
        return self.state in ("pending", "running")


def control_dir() -> Path:
    return paths.DATA_DIR / "control"


def _request_file(name: str) -> Path:
    return control_dir() / f"{name}.request"


def helper_installed(name: str) -> bool:
    """Ob Root-Skript und Pfad-Unit fuer diese Aktion eingerichtet sind.

    Installationen von vor dieser Funktion haben sie noch nicht; dort muss
    das Update einmal von Hand laufen.
    """
    return (HELPER_DIR / f"{name}.sh").is_file() and (UNIT_DIR / f"mail2fax-{name}.path").is_file()


def request_action(name: str) -> None:
    """Fordert eine Aktion an, indem die Anforderungsdatei angelegt wird."""
    if name not in ACTIONS:
        raise AdminError(f"Unbekannte Aktion: {name}")
    if not helper_installed(name):
        raise AdminError(
            "Diese Installation kann Verwaltungsaktionen noch nicht aus der "
            "Weboberflaeche ausfuehren. Bitte einmalig im Container das Update "
            "von Hand starten (siehe Hinweis auf dieser Seite)."
        )
    zustand = action_state(name)
    if zustand.busy:
        raise AdminError(f"'{ACTIONS[name]}' ist bereits angefordert oder laeuft noch.")

    control_dir().mkdir(parents=True, exist_ok=True)
    # Eine nie abgeholte Anforderung blockiert sonst jeden neuen Versuch.
    _request_file(name).unlink(missing_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(_request_file(name), flags, 0o640)
    except FileExistsError as error:
        raise AdminError(f"'{ACTIONS[name]}' ist bereits angefordert.") from error
    os.close(descriptor)


def action_state(name: str, *, log_lines: int = 60) -> ActionState:
    """Liest Status und Protokoll einer Aktion."""
    log = _tail(ADMIN_DIR / f"{name}.log", log_lines)
    try:
        angefordert = _request_file(name).lstat().st_mtime
    except OSError:
        angefordert = None
    if angefordert is not None:
        if time.time() - angefordert > PICKUP_TIMEOUT:
            return ActionState(
                name, "stale", angefordert,
                "angefordert, aber nicht gestartet - laeuft die Pfad-Unit "
                f"mail2fax-{name}.path? (systemctl status mail2fax-{name}.path)",
                log,
            )
        return ActionState(name, "pending", angefordert, "angefordert, startet in Kuerze", log)

    status_file = ADMIN_DIR / f"{name}.status"
    try:
        felder = status_file.read_text(encoding="utf-8").split()
    except OSError:
        return ActionState(name, "idle", log=log)
    if not felder:
        return ActionState(name, "idle", log=log)

    ergebnis = felder[0]
    try:
        seit = float(felder[1]) if len(felder) > 1 else None
    except ValueError:
        seit = None

    if ergebnis == "running":
        if seit is not None and time.time() - seit > STALE_AFTER:
            return ActionState(name, "stale", seit, "laeuft seit ueber zwei Stunden - vermutlich abgebrochen", log)
        return ActionState(name, "running", seit, log=log)
    if ergebnis == "success":
        return ActionState(name, "success", seit, log=log)
    code = felder[2] if len(felder) > 2 else "?"
    return ActionState(name, "failed", seit, f"{ergebnis}, Rueckgabewert {code}", log)


def _tail(path: Path, lines: int) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            groesse = handle.tell()
            handle.seek(max(0, groesse - 64 * 1024))
            text = handle.read().decode("utf-8", "replace")
    except OSError:
        return ""
    return "\n".join(_ANSI.sub("", zeile) for zeile in text.splitlines()[-lines:])


# -- Versionsstand ----------------------------------------------------------


@dataclass
class Revision:
    sha: str
    date: str = ""
    message: str = ""

    @property
    def short(self) -> str:
        return self.sha[:7] if self.sha else "unbekannt"


def installed_revision() -> Revision | None:
    """Der installierte Stand, wie ihn install.sh bzw. update.sh vermerkt."""
    try:
        felder = (APP_DIR / "REVISION").read_text(encoding="utf-8").split(maxsplit=1)
    except OSError:
        return None
    if not felder:
        return None
    return Revision(sha=felder[0], date=felder[1].strip() if len(felder) > 1 else "")


def latest_revision(timeout: float = 10.0) -> Revision:
    """Fragt den neuesten Stand auf GitHub ab.

    Geschieht nur, wenn ein Administrator ausdruecklich danach fragt - mail2fax
    nimmt von sich aus keinen Kontakt nach aussen auf.
    """
    import httpx

    try:
        antwort = httpx.get(
            f"https://api.github.com/repos/{UPDATE_REPO}/commits/main",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "mail2fax"},
            timeout=timeout,
        )
        antwort.raise_for_status()
        daten = antwort.json()
    except (httpx.HTTPError, ValueError) as error:
        raise AdminError(f"GitHub ist nicht erreichbar: {error}") from error
    commit = daten.get("commit", {})
    return Revision(
        sha=str(daten.get("sha", "")),
        date=str(commit.get("committer", {}).get("date", "")),
        message=str(commit.get("message", "")).splitlines()[0] if commit.get("message") else "",
    )


# -- Asterisk ---------------------------------------------------------------


def asterisk_installed() -> bool:
    """Ob Asterisk in diesem Container eingerichtet ist."""
    return ASTERISK_ETC.is_dir() and shutil.which("asterisk") is not None
