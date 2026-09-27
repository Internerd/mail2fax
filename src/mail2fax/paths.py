"""Zentrale Pfade.

Alle Pfade lassen sich ueber Umgebungsvariablen umbiegen, damit die Anwendung
sowohl aus dem Git-Checkout (Entwicklung) als auch aus dem LXC-Layout
(/etc, /var/lib) heraus laeuft.
"""

from __future__ import annotations

import contextlib
import os
import time
import uuid
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("MAIL2FAX_CONFIG", "/etc/mail2fax/config.yaml"))
DATA_DIR = Path(os.environ.get("MAIL2FAX_DATA_DIR", "/var/lib/mail2fax"))

SPOOL_DIR = DATA_DIR / "spool"
DB_PATH = DATA_DIR / "mail2fax.db"


def ensure_dirs() -> None:
    """Legt die Datenverzeichnisse an (idempotent).

    Die Rechte werden nur beim Anlegen gesetzt. Bestehende Verzeichnisse
    bleiben unangetastet - der SIP-Versand braucht etwa ein Spool-Verzeichnis
    mit setgid-Bit und der Gruppe "asterisk", damit Asterisk die Faxdateien
    lesen kann. Das wuerde ein unbedingtes chmod wieder zerstoeren.
    """
    for directory in (DATA_DIR, SPOOL_DIR):
        if directory.exists():
            continue
        directory.mkdir(parents=True, exist_ok=True)
        # 0750: Dienstbenutzer und Gruppe duerfen hinein, sonst niemand.
        with contextlib.suppress(PermissionError):
            os.chmod(directory, 0o750)  # noqa: S103 - bewusst gewaehlte Maske


def make_workdir(base: Path, prefix: str = "") -> Path:
    """Legt ein eindeutiges Arbeitsverzeichnis fuer einen Auftrag an.

    Zeitstempel allein genuegen nicht: Zwei Auftraege in derselben Sekunde
    teilten sich sonst ein Verzeichnis, und das Aufraeumen des einen loeschte
    die Dokumente des anderen.

    Bewusst ``mkdir`` statt ``tempfile.mkdtemp``: mkdtemp legt 0700 an, und
    ein nachtraegliches chmod koennte das vom Spool-Verzeichnis geerbte
    setgid-Bit loeschen - dann koennte Asterisk die Faxdateien nicht lesen.
    """
    base.mkdir(parents=True, exist_ok=True)
    while True:
        workdir = base / f"{prefix}{int(time.time())}-{uuid.uuid4().hex[:12]}"
        try:
            workdir.mkdir(exist_ok=False)
        except FileExistsError:  # pragma: no cover - praktisch ausgeschlossen
            continue
        return workdir
