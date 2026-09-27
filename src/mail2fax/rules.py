"""Regelwerk: Rufnummer aus dem Betreff, Absenderpruefung, Nummernpruefung."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass

from .config import SecurityConfig, whitelist_entry_problem

#: Zeichen, die in Rufnummern als Trenner vorkommen duerfen.
_SEPARATORS = " \t-/(). ‐‑‒–—"

#: Kandidaten im Betreff: internationale (+49…, 0049…) und nationale (0…) Form.
#: Das Muster ist bewusst grosszuegig; welche Fundstelle eine Rufnummer ist,
#: entscheidet erst extract_number().
_NUMBER_PATTERN = re.compile(
    r"(?<![0-9A-Za-z])"               # kein direkt vorangehendes Zeichen
    r"(\+|00)?"                        # optionaler internationaler Praefix
    r"[0-9][0-9 \t\-/().\u00a0]{4,40}"  # Ziffern mit erlaubten Trennern
    r"[0-9]"                           # muss auf einer Ziffer enden
)

#: "(0)" kennzeichnet die Verkehrsausscheidungsziffer, die bei internationaler
#: Wahl entfaellt: "+49 (0)30 1234567" meint "+49 30 1234567".
_TRUNK_ZERO = re.compile(r"\(\s*0\s*\)")

#: Mindestzahl an Ziffern (Landesvorwahl und Rufnummer), ab der eine
#: Ziffernfolge als eigenstaendige Rufnummer gilt. Fuer Deutschland entspricht
#: das einer nationalen Rufnummer von mindestens 7 Stellen ohne fuehrende 0 -
#: kuerzer ist keine reale Faxnummer. Kuerzere Ziffernfolgen im Betreff sind
#: Aktenzeichen, Rechnungs- oder Seitenzahlen.
PLAUSIBLE_DIGITS = 9


class RuleError(Exception):
    """Fachlicher Fehler bei der Regelpruefung (Ablehnungsgrund)."""


@dataclass(frozen=True)
class Number:
    """Eine geprueffte Zielrufnummer."""

    #: E.164-Schreibweise, z. B. "+4930123456".
    e164: str

    @property
    def digits(self) -> str:
        """Nur Ziffern, ohne fuehrendes Plus (z. B. "4930123456")."""
        return self.e164.lstrip("+")

    @property
    def digit_count(self) -> int:
        """Anzahl der Ziffern einschliesslich Landesvorwahl."""
        return len(self.digits)

    def formatted_national(self, country_code: str) -> str:
        """Die Rufnummer so, wie sie im Inland gewaehlt wird.

        Inlandsnummern erhalten die Verkehrsausscheidungsziffer 0
        ("+49301234567" -> "0301234567"), Auslandsnummern die internationale
        Vorwahl 00 ("+431234567" -> "00431234567"). Ein vorangestelltes "+"
        waere an vielen Anlagen nicht waehlbar.
        """
        if country_code and self.e164.startswith(country_code):
            return "0" + self.e164[len(country_code):]
        return "00" + self.digits

    def __str__(self) -> str:  # pragma: no cover - triviale Darstellung
        return self.e164


def _strip_separators(value: str) -> str:
    return "".join(char for char in value if char not in _SEPARATORS)


def normalise_number(raw: str, security: SecurityConfig) -> Number:
    """Bringt eine Rufnummer in E.164-Form.

    Akzeptiert werden "+49…", "0049…" sowie - falls erlaubt - "0…" in
    nationaler Schreibweise. Trennzeichen (Leerzeichen, /, -, Klammern)
    werden entfernt.
    """
    text = _TRUNK_ZERO.sub("", raw.strip())
    cleaned = _strip_separators(text)
    if not cleaned:
        raise RuleError("Keine Rufnummer angegeben")

    if cleaned.startswith("+"):
        candidate = "+" + cleaned[1:]
    elif cleaned.startswith("00"):
        candidate = "+" + cleaned[2:]
    elif cleaned.startswith("0"):
        if not security.accept_national_format:
            raise RuleError(
                "Rufnummern muessen international angegeben werden (z. B. +49301234567)"
            )
        country = security.default_country_code or "+49"
        candidate = country + cleaned[1:]
    else:
        raise RuleError(
            f"Rufnummer '{raw.strip()}' ist weder international (+49…) noch national (0…)"
        )

    # Deutsche Rufnummern beginnen nach der Landesvorwahl nie mit 0. "+49030…"
    # ist ein haeufiger Schreibfehler fuer "+4930…" - unkorrigiert wuerde die
    # Anlage "0030…" waehlen, also ins Ausland (Griechenland).
    if candidate.startswith("+490"):
        candidate = "+49" + candidate[3:].lstrip("0")

    # E.164: hoechstens 15 Ziffern einschliesslich Landesvorwahl.
    if not re.fullmatch(r"\+[1-9][0-9]{5,14}", candidate):
        raise RuleError(f"Rufnummer '{raw.strip()}' ist ungueltig")
    return Number(candidate)


def _trim_candidate(raw: str) -> str:
    """Kuerzt eine Fundstelle auf den Teil, der zur Rufnummer gehoeren kann.

    Das Suchmuster ist grosszuegig und laesst Bindestriche und Klammern zu,
    denn "030 1234567-89" (Durchwahl) und "+49 (0)30 1234567" sind gaengig.
    Zwei Dinge gehoeren aber nie zu einer Rufnummer:

    * ein Gedankenstrich mit Leerzeichen ("+49 30 1234567 - 2 Seiten"),
    * eine Klammer ohne Gegenstueck ("+49 30 1234567 (2 Seiten)").
    """
    text = re.split(r"\s[-\u2013\u2014]\s", raw, maxsplit=1)[0]
    for position, zeichen in enumerate(text):
        if zeichen == "(" and ")" not in text[position:]:
            text = text[:position]
            break
    # Die Fundstelle muss auf einer Ziffer enden.
    while text and not text[-1].isdigit():
        text = text[:-1]
    return text.strip()


def _readings(raw: str, security: SecurityConfig) -> tuple[list[Number], RuleError | None]:
    """Alle plausiblen Lesarten einer Fundstelle im Betreff.

    Leerzeichen gliedern eine Rufnummer ("+49 30 1234567"), trennen sie aber
    ebenso vom folgenden Text ("+49 30 1234567 2 Seiten"). Jede Kuerzung an
    einem Leerzeichen, die fuer sich eine plausible Rufnummer ergibt, ist
    deshalb eine eigene Lesart. Gibt es mehr als eine, ist der Betreff
    mehrdeutig.

    Liefert die Lesarten und - falls die vollstaendige Fundstelle unzulaessig
    war - den Grund dafuer.
    """
    bloecke = raw.split()
    lesarten: list[Number] = []
    grund: RuleError | None = None
    for anzahl in range(len(bloecke), 0, -1):
        teil = " ".join(bloecke[:anzahl])
        try:
            nummer = normalise_number(teil, security)
        except RuleError as error:
            if anzahl == len(bloecke):
                grund = error
            continue
        vollstaendig = anzahl == len(bloecke)
        if not vollstaendig and nummer.digit_count < PLAUSIBLE_DIGITS:
            continue  # zu kurz, um fuer sich eine Rufnummer zu sein
        if nummer not in lesarten:
            lesarten.append(nummer)
    return lesarten, grund


def extract_number(subject: str, security: SecurityConfig) -> Number:
    """Ermittelt die Zielrufnummer aus dem Betreff der E-Mail.

    Grundsatz: **Im Zweifel ablehnen statt raten.** Ein Fax an die falsche
    Nummer ist eine Datenpanne; eine abgelehnte Nachricht dagegen nur ein
    Hinweis an den Absender, der ihn per Fehlerbericht erreicht.

    Regeln:

    1. Eine international geschriebene Rufnummer (+49…, 0049…) hat Vorrang
       vor national geschriebenen Ziffernfolgen - so stoeren Aktenzeichen
       oder Rechnungsnummern mit fuehrender 0 nicht.
    2. National geschriebene Ziffernfolgen gelten erst ab einer realistischen
       Laenge als Rufnummer (siehe ``PLAUSIBLE_DIGITS``).
    3. Laesst sich nicht erkennen, wo die Rufnummer endet, oder enthaelt der
       Betreff mehrere verschiedene Rufnummern, wird abgelehnt.
    """
    if not subject or not subject.strip():
        raise RuleError("Betreff ist leer - es kann keine Zielrufnummer ermittelt werden")

    international: list[tuple[str, list[Number]]] = []
    national: list[tuple[str, list[Number]]] = []
    letzter_grund: RuleError | None = None

    for match in _NUMBER_PATTERN.finditer(subject):
        raw = _trim_candidate(match.group(0))
        if not raw:
            continue
        lesarten, grund = _readings(raw, security)
        if grund is not None:
            letzter_grund = grund
        if raw.startswith(("+", "00")):
            if lesarten:
                international.append((raw, lesarten))
        else:
            lesarten = [n for n in lesarten if n.digit_count >= PLAUSIBLE_DIGITS]
            if lesarten:
                national.append((raw, lesarten))

    fundstellen = international or national
    if not fundstellen:
        if letzter_grund is not None:
            raise letzter_grund
        raise RuleError(
            "Im Betreff wurde keine Rufnummer gefunden "
            "(erwartet wird z. B. '+49301234567')"
        )

    for raw, lesarten in fundstellen:
        if len(lesarten) > 1:
            # Keine der Lesarten wird bevorzugt - welche gemeint ist, weiss
            # nur der Absender.
            varianten = " oder ".join(n.e164 for n in sorted(lesarten, key=lambda n: n.digit_count))
            raise RuleError(
                f"Im Betreff ist nicht eindeutig, wo die Rufnummer endet: "
                f"'{raw}' kann {varianten} bedeuten. Bitte die Rufnummer ohne "
                f"Leerzeichen schreiben oder durch ein Satzzeichen vom uebrigen "
                f"Text trennen."
            )

    verschiedene: list[Number] = []
    for _raw, lesarten in fundstellen:
        if lesarten[0] not in verschiedene:
            verschiedene.append(lesarten[0])
    if len(verschiedene) > 1:
        raise RuleError(
            "Der Betreff enthaelt mehrere Rufnummern ("
            + ", ".join(n.e164 for n in verschiedene)
            + "). Bitte nur die Zielrufnummer angeben."
        )
    return verschiedene[0]


def check_number_allowed(number: Number, security: SecurityConfig) -> None:
    """Prueft die Rufnummer gegen Positiv- und Negativliste."""
    for blocked in security.blocked_number_prefixes:
        prefix = _strip_separators(blocked)
        if prefix and number.e164.startswith(prefix):
            raise RuleError(f"Rufnummer {number.e164} ist gesperrt (Praefix {prefix})")

    allowed = [_strip_separators(item) for item in security.allowed_number_prefixes]
    allowed = [item for item in allowed if item]
    if allowed and not any(number.e164.startswith(prefix) for prefix in allowed):
        raise RuleError(
            f"Rufnummer {number.e164} liegt ausserhalb der erlaubten Vorwahlen "
            f"({', '.join(allowed)})"
        )


def normalise_address(address: str) -> str:
    """Reduziert eine Adressangabe auf die reine E-Mail-Adresse in Kleinschrift."""
    from email.utils import parseaddr

    _, addr = parseaddr(address or "")
    return addr.strip().lower()


def _domain_matches(muster: str, domain: str) -> bool:
    """Exakter Vergleich - oder Subdomain bei einem fuehrenden "*."."""
    if muster.startswith("*."):
        endung = muster[1:]  # ".example.com"
        return domain.endswith(endung) and len(domain) > len(endung)
    return domain == muster


def is_sender_allowed(sender: str, security: SecurityConfig) -> bool:
    """Prueft den Absender gegen die Whitelist.

    Unterstuetzt vollstaendige Adressen ("chef@example.com"), Platzhalter im
    Teil vor dem @ ("*@example.com", "fax-*@example.com") und Subdomains
    ("*@*.example.com"). Die Domain wird nie per Mustervergleich geprueft,
    sondern exakt bzw. als Endung ab einem Punkt - so passt "*@example.com"
    nicht auf "boese@nichtexample.com".
    """
    address = normalise_address(sender)
    if not address or address.count("@") != 1:
        return False
    lokal, domain = address.split("@")
    if not lokal or not domain:
        return False
    for entry in security.sender_whitelist:
        muster = entry.strip().lower()
        if whitelist_entry_problem(muster):
            continue  # unzulaessige Eintraege wirken nie
        muster_lokal, muster_domain = muster.split("@")
        if not _domain_matches(muster_domain, domain):
            continue
        if muster_lokal == lokal or fnmatch.fnmatchcase(lokal, muster_lokal):
            return True
    return False


def check_sender_allowed(sender: str, security: SecurityConfig) -> str:
    """Wie :func:`is_sender_allowed`, wirft aber einen sprechenden Fehler."""
    address = normalise_address(sender)
    if not security.sender_whitelist:
        raise RuleError(
            "Die Absender-Whitelist ist leer - aus Sicherheitsgruenden wird "
            "keine Nachricht verarbeitet"
        )
    if not is_sender_allowed(sender, security):
        raise RuleError(f"Absender '{address or sender}' steht nicht auf der Whitelist")
    return address
