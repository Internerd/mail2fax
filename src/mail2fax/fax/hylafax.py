"""Faxversand ueber HylaFAX bzw. HylaFAX+ (`sendfax`).

Typischer Weg fuer Telefonanlagen mit T.38-/ISDN-Gateway: HylaFAX nimmt den
Auftrag entgegen, mail2fax uebergibt lediglich Rufnummer und PDF.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from ..config import AppConfig
from ..rules import Number
from .base import FaxBackend, FaxError, FaxResult

LOGGER = logging.getLogger(__name__)


class HylafaxBackend(FaxBackend):
    """Uebergibt den Auftrag an einen HylaFAX-Server."""

    name = "HylaFAX"

    def __init__(self, config: AppConfig) -> None:
        super().__init__(config)
        self.settings = config.fax.hylafax

    def _binary(self) -> str:
        binary = self.settings.binary or "sendfax"
        resolved = shutil.which(binary) or (binary if Path(binary).is_file() else None)
        if not resolved:
            raise FaxError(
                f"HylaFAX-Client '{binary}' wurde nicht gefunden "
                "(apt install hylafax-client)",
                permanent=True,
            )
        return resolved

    def send(self, number: Number, documents: list[Path], *, subject: str = "") -> FaxResult:
        if not documents:
            raise FaxError("Es liegen keine Dokumente zum Versand vor", permanent=True)

        argv = [self._binary(), "-n", "-d", number.e164]
        if self.settings.host:
            argv += ["-h", f"{self.settings.host}:{self.settings.port}"]
        if self.settings.user:
            argv += ["-f", self.settings.user]
        if self.settings.sender_number:
            argv += ["-i", self.settings.sender_number]
        argv += list(self.settings.extra_args)
        argv += [str(document) for document in documents]

        LOGGER.debug("Starte HylaFAX-Auftrag: %s", " ".join(argv))
        try:
            completed = subprocess.run(  # noqa: S603 - feste Argumentliste, keine Shell
                argv, check=False, capture_output=True, timeout=self.settings.timeout
            )
        except subprocess.TimeoutExpired as error:
            raise FaxError(
                f"HylaFAX hat nach {self.settings.timeout}s nicht geantwortet"
            ) from error
        except OSError as error:
            raise FaxError(f"HylaFAX-Client konnte nicht gestartet werden: {error}") from error

        stdout = completed.stdout.decode("utf-8", "replace").strip()
        stderr = completed.stderr.decode("utf-8", "replace").strip()
        if completed.returncode != 0:
            raise FaxError(f"HylaFAX meldet Fehler (Code {completed.returncode}): {stderr or stdout}")

        remote_id = ""
        for line in stdout.splitlines():
            if "request id is" in line.lower():
                remote_id = line.split()[-1].strip(".")
                break
        return FaxResult(success=True, detail=stdout or "Auftrag an HylaFAX uebergeben", remote_id=remote_id)

    def test(self) -> str:
        binary = self._binary()
        return f"HylaFAX-Client gefunden: {binary} (Server {self.settings.host}:{self.settings.port})"
