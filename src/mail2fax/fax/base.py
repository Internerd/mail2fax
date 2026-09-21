"""Gemeinsame Schnittstelle aller Fax-Backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from ..config import AppConfig
from ..rules import Number


class FaxError(Exception):
    """Fehler beim Faxversand.

    ``permanent=True`` bedeutet: ein erneuter Versuch ist zwecklos
    (z. B. ungueltige Rufnummer, Konfigurationsfehler).
    """

    def __init__(self, message: str, *, permanent: bool = False) -> None:
        super().__init__(message)
        self.permanent = permanent


@dataclass
class FaxResult:
    """Ergebnis eines Versandversuchs."""

    success: bool
    detail: str = ""
    #: Auftragsnummer der Gegenstelle, falls vorhanden.
    remote_id: str = ""


class FaxBackend(ABC):
    """Basisklasse fuer alle Versandwege."""

    #: Anzeigename in der Weboberflaeche.
    name = "unbekannt"

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    @abstractmethod
    def send(self, number: Number, documents: list[Path], *, subject: str = "") -> FaxResult:
        """Versendet die Dokumente an die Rufnummer.

        Die Dokumente liegen als PDF vor. Backends, die nur eine Datei
        annehmen, fuehren sie selbst zusammen oder senden sie nacheinander.
        """

    def test(self) -> str:
        """Prueft die Erreichbarkeit/Konfiguration (fuer die Weboberflaeche)."""
        return "Fuer dieses Backend ist kein Verbindungstest hinterlegt."
