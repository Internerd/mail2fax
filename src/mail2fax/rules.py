"""Regelwerk: Rufnummer aus dem Betreff, Absenderpruefung, Nummernpruefung."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass

from .config import SecurityConfig

#: Zeichen, die in Rufnummern als Trenner vorkommen duerfen.
_SEPARATORS = " \t-/(). ‐‑‒–—"

#: Kandidaten im Betreff: internationale (+49…, 0049…) und nationale (0…) Form.
_NUMBER_PATTERN = re.compile(
    r"(?<![0-9A-Za-z])"          # kein direkt vorangehendes Zeichen
    r"(\+|00)?"                   # optionaler internationaler Praefix
    r"[0-9][0-9 \t\-/(). ]{4,30}"  # Ziffern mit erlaubten Trennern
    r"[0-9]"                      # muss auf einer Ziffer enden
)


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
    def national(self) -> str:
        """Nationale Schreibweise, sofern die Landesvorwahl passt."""
        return self.e164

    def formatted_national(self, country_code: str) -> str:
        """Nationale Schreibweise fuer die angegebene Landesvorwahl."""
        if country_code and self.e164.startswith(country_code):
            return "0" + self.e164[len(country_code):]
        return self.e164

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
    cleaned = _strip_separators(raw.strip())
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

    if not re.fullmatch(r"\+[1-9][0-9]{5,17}", candidate):
        raise RuleError(f"Rufnummer '{raw.strip()}' ist ungueltig")
    return Number(candidate)


def extract_number(subject: str, security: SecurityConfig) -> Number:
    """Ermittelt die Zielrufnummer aus dem Betreff der E-Mail.

    Es wird der erste Treffer verwendet, der sich zu einer gueltigen Rufnummer
    normalisieren laesst. So funktionieren sowohl "+49301234567" als auch
    Betreffzeilen wie "Fax an +49 30 123456 - Rechnung".
    """
    if not subject or not subject.strip():
        raise RuleError("Betreff ist leer - es kann keine Zielrufnummer ermittelt werden")

    last_error: RuleError | None = None
    for match in _NUMBER_PATTERN.finditer(subject):
        try:
            return normalise_number(match.group(0), security)
        except RuleError as error:
            last_error = error
            continue

    if last_error is not None:
        raise last_error
    raise RuleError(
        "Im Betreff wurde keine Rufnummer gefunden "
        "(erwartet wird z. B. '+49301234567')"
    )


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


def is_sender_allowed(sender: str, security: SecurityConfig) -> bool:
    """Prueft den Absender gegen die Whitelist.

    Unterstuetzt vollstaendige Adressen ("chef@example.com") und
    Platzhalter ("*@example.com", "fax-*@example.com").
    """
    address = normalise_address(sender)
    if not address:
        return False
    for entry in security.sender_whitelist:
        pattern = entry.strip().lower()
        if not pattern:
            continue
        if pattern == address:
            return True
        if ("*" in pattern or "?" in pattern) and fnmatch.fnmatch(address, pattern):
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
