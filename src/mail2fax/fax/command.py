"""Faxversand ueber ein frei konfigurierbares Kommando.

Damit laesst sich jede Telefonanlage anbinden, fuer die es ein CLI-Werkzeug
gibt (Asterisk, CapiSuite, T.38-Gateways, eigene Skripte ...).

Platzhalter in den Argumenten:
  {number}           Zielrufnummer in E.164 (+49301234567)
  {number_digits}    nur Ziffern (49301234567)
  {number_national}  nationale Schreibweise (030123456)
  {file}             Pfad des (ersten bzw. zusammengefuehrten) PDF
  {subject}          Betreff der Ursprungsmail

Das Kommando wird ohne Shell ausgefuehrt; es findet keine Interpretation von
Sonderzeichen statt.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from ..config import AppConfig
from ..rules import Number
from .base import FaxBackend, FaxError, FaxResult

LOGGER = logging.getLogger(__name__)


class CommandBackend(FaxBackend):
    """Ruft ein externes Programm fuer den Versand auf."""

    name = "Externes Kommando"

    def __init__(self, config: AppConfig) -> None:
        super().__init__(config)
        self.settings = config.fax.command

    def send(self, number: Number, documents: list[Path], *, subject: str = "") -> FaxResult:
        from ..render import merge_pdfs

        if not self.settings.argv:
            raise FaxError("Es ist kein Kommando hinterlegt", permanent=True)
        if not documents:
            raise FaxError("Es liegen keine Dokumente zum Versand vor", permanent=True)

        document = documents[0] if len(documents) == 1 else merge_pdfs(
            documents, documents[0].parent / "fax-gesamt.pdf"
        )
        values = {
            "number": number.e164,
            "number_digits": number.digits,
            "number_national": number.formatted_national(
                self.config.security.default_country_code
            ),
            "file": str(document),
            "subject": subject or "",
        }
        try:
            argv = [argument.format(**values) for argument in self.settings.argv]
        except KeyError as error:
            raise FaxError(f"Unbekannter Platzhalter {error} im Kommando", permanent=True) from error

        environment = os.environ.copy()
        environment.update(self.settings.env)

        LOGGER.debug("Starte Versandkommando: %s", argv[0])
        try:
            completed = subprocess.run(  # noqa: S603 - Argumentliste, keine Shell
                argv,
                check=False,
                capture_output=True,
                timeout=self.settings.timeout,
                env=environment,
            )
        except FileNotFoundError as error:
            raise FaxError(f"Kommando '{argv[0]}' wurde nicht gefunden", permanent=True) from error
        except subprocess.TimeoutExpired as error:
            raise FaxError(f"Kommando hat nach {self.settings.timeout}s nicht geantwortet") from error
        except OSError as error:
            raise FaxError(f"Kommando konnte nicht gestartet werden: {error}") from error

        stdout = completed.stdout.decode("utf-8", "replace").strip()
        stderr = completed.stderr.decode("utf-8", "replace").strip()
        if completed.returncode != 0:
            raise FaxError(
                f"Kommando endete mit Code {completed.returncode}: {stderr or stdout}"
            )
        return FaxResult(success=True, detail=stdout or "Kommando erfolgreich ausgefuehrt")

    def test(self) -> str:
        if not self.settings.argv:
            raise FaxError("Es ist kein Kommando hinterlegt", permanent=True)
        program = Path(self.settings.argv[0])
        if not program.is_absolute():
            return f"Kommando '{program}' wird ueber den Suchpfad aufgeloest."
        if not program.is_file():
            raise FaxError(f"Kommando '{program}' existiert nicht", permanent=True)
        if not os.access(program, os.X_OK):
            raise FaxError(f"Kommando '{program}' ist nicht ausfuehrbar", permanent=True)
        return f"Kommando '{program}' ist vorhanden und ausfuehrbar."
