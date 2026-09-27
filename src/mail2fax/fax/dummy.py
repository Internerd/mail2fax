"""Testbackend - schreibt die Dokumente nur ins Protokoll."""

from __future__ import annotations

import logging
from pathlib import Path

from ..rules import Number
from .base import FaxBackend, FaxResult

LOGGER = logging.getLogger(__name__)


class DummyBackend(FaxBackend):
    """Versendet nichts. Sinnvoll fuer Inbetriebnahme und Tests."""

    name = "Testbetrieb (kein Versand)"

    def send(self, number: Number, documents: list[Path], *, subject: str = "") -> FaxResult:
        names = ", ".join(document.name for document in documents)
        LOGGER.info("Testbetrieb: Fax an %s waere gesendet worden (%s)", number.e164, names)
        return FaxResult(
            success=True,
            detail=f"Testbetrieb - es wurde nichts gesendet ({len(documents)} Dokument(e): {names})",
            confirmed=False,
        )

    def test(self) -> str:
        return "Testbackend ist aktiv. Es werden keine Faxe versendet."
