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
    """Ergebnis eines Versandversuchs.

    Der Unterschied zwischen ``success`` und ``confirmed`` ist wesentlich:

    * ``success`` heisst nur, dass der Versandweg keinen Fehler gemeldet hat.
    * ``confirmed`` heisst, dass die **Gegenstelle den Empfang bestaetigt**
      hat - bei Fax die Quittung des empfangenden Geraets am Ende der
      T.30-Uebertragung. Nur dann darf ein Sendebericht behaupten, das Fax
      sei tatsaechlich uebertragen worden.

    Backends, die einen Auftrag lediglich an ein nachgelagertes System
    uebergeben (Fax-per-E-Mail, HylaFAX-Warteschlange), setzen ``confirmed``
    deshalb nicht.
    """

    success: bool
    detail: str = ""
    #: Auftragsnummer der Gegenstelle, falls vorhanden.
    remote_id: str = ""

    #: Die Gegenstelle hat den Empfang quittiert.
    confirmed: bool = False
    #: Tatsaechlich uebertragene Seiten (kann von der Vorlage abweichen).
    pages_sent: int | None = None
    #: Uebertragungsrate in bit/s, z. B. "14400".
    rate: str = ""
    #: Aufloesung, wie das Backend sie meldet.
    resolution: str = ""
    #: Kennung der Gegenstelle (bei Fax die Stationskennung, CSI).
    remote_station: str = ""
    #: Dauer der Uebertragung in Sekunden.
    duration: float | None = None


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
