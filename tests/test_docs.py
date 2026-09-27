"""Die Beispiele der Dokumentation muessen zum Code passen.

Die Tabellen in docs/RUFNUMMERN.md werden direkt aus der Datei gelesen und
gegen die Rufnummernerkennung geprueft. Aendert sich das Verhalten, faellt
eine veraltete Doku sofort auf.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mail2fax.config import SecurityConfig
from mail2fax.rules import RuleError, check_number_allowed, extract_number

DOCS = Path(__file__).resolve().parents[1] / "docs"


def _tabelle(abschnitt: str) -> list[tuple[str, str]]:
    """Liest die ersten beiden Spalten einer Tabelle unter einer Ueberschrift."""
    text = (DOCS / "RUFNUMMERN.md").read_text(encoding="utf-8")
    teil = text.split(f"## {abschnitt}", 1)[1].split("\n## ", 1)[0]
    zeilen = []
    for zeile in teil.splitlines():
        spalten = [s.strip() for s in zeile.strip().strip("|").split("|")]
        if len(spalten) < 2 or not spalten[0].startswith("`"):
            continue
        zeilen.append((spalten[0].strip("`"), spalten[1]))
    assert zeilen, f"Keine Tabelle unter '{abschnitt}' gefunden"
    return zeilen


def _pruefen(betreff: str) -> str:
    security = SecurityConfig()
    nummer = extract_number(betreff, security)
    check_number_allowed(nummer, security)
    return nummer.e164


@pytest.mark.parametrize(("betreff", "ergebnis"), _tabelle("Was erkannt wird"))
def test_documented_recognitions(betreff, ergebnis):
    assert _pruefen(betreff) == ergebnis.strip("`")


@pytest.mark.parametrize(("betreff", "grund"), _tabelle("Wann abgelehnt wird"))
def test_documented_rejections(betreff, grund):
    with pytest.raises(RuleError):
        _pruefen(betreff)


def test_documented_dial_strings():
    from mail2fax.rules import Number

    text = (DOCS / "RUFNUMMERN.md").read_text(encoding="utf-8")
    teil = text.split("## Gewählt wird", 1)[1].split("\n## ", 1)[0]
    paare = re.findall(r"\|\s*`(\+\d+)`[^|]*\|\s*`(\d+)`", teil)
    assert paare
    for e164, gewaehlt in paare:
        assert Number(e164).formatted_national("+49") == gewaehlt


def test_readme_examples_match():
    """Auch die Kurzuebersicht im README muss stimmen."""
    readme = (DOCS.parent / "README.md").read_text(encoding="utf-8")
    teil = readme.split("Erkannt werden unter anderem:", 1)[1].split("\n## ", 1)[0]
    for zeile in teil.splitlines():
        spalten = [s.strip() for s in zeile.strip().strip("|").split("|")]
        if len(spalten) < 2 or not spalten[0].startswith("`"):
            continue
        betreff, ergebnis = spalten[0].strip("`"), spalten[1]
        if ergebnis.startswith("abgelehnt"):
            with pytest.raises(RuleError):
                _pruefen(betreff)
        else:
            assert _pruefen(betreff) == ergebnis.strip("`"), betreff


def test_every_setting_is_documented():
    """Jede Einstellung des Konfigurationsmodells steht in der Referenz.

    Kommt eine Einstellung hinzu, ohne dass sie dokumentiert wird, schlaegt
    dieser Test fehl.
    """
    from pydantic import BaseModel

    from mail2fax.config import AppConfig

    referenz = (DOCS / "KONFIGURATION.md").read_text(encoding="utf-8")
    fehlend: list[str] = []

    def pruefen(modell: type[BaseModel], pfad: str = "") -> None:
        for name, feld in modell.model_fields.items():
            typ = feld.annotation
            if isinstance(typ, type) and issubclass(typ, BaseModel):
                pruefen(typ, f"{pfad}{name}.")
            elif f"`{name}`" not in referenz:
                fehlend.append(f"{pfad}{name}")

    pruefen(AppConfig)
    assert not fehlend, f"Nicht in docs/KONFIGURATION.md: {', '.join(fehlend)}"
