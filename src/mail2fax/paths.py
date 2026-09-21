"""Zentrale Pfade.

Alle Pfade lassen sich ueber Umgebungsvariablen umbiegen, damit die Anwendung
sowohl aus dem Git-Checkout (Entwicklung) als auch aus dem LXC-Layout
(/etc, /var/lib) heraus laeuft.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("MAIL2FAX_CONFIG", "/etc/mail2fax/config.yaml"))
DATA_DIR = Path(os.environ.get("MAIL2FAX_DATA_DIR", "/var/lib/mail2fax"))

SPOOL_DIR = DATA_DIR / "spool"
DB_PATH = DATA_DIR / "mail2fax.db"


def ensure_dirs() -> None:
    """Legt die Datenverzeichnisse an (idempotent)."""
    for directory in (DATA_DIR, SPOOL_DIR):
        directory.mkdir(parents=True, exist_ok=True)
        # 0750: Dienstbenutzer und Gruppe duerfen hinein, sonst niemand.
        with contextlib.suppress(PermissionError):
            os.chmod(directory, 0o750)  # noqa: S103 - bewusst gewaehlte Maske
