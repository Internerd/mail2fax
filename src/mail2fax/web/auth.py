"""Anmeldung, Sitzungen und Beschraenkung auf das lokale Netz."""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import logging
import secrets
import threading
import time
from dataclasses import dataclass

LOGGER = logging.getLogger(__name__)

PBKDF2_ITERATIONS = 240_000
ALGORITHM = "pbkdf2_sha256"
SESSION_COOKIE = "mail2fax_session"


# -- Passwoerter -----------------------------------------------------------


def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    """Erzeugt einen Passworthash im Format ``pbkdf2_sha256$iter$salt$hash``."""
    if not password:
        raise ValueError("Das Passwort darf nicht leer sein")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    parts = [
        ALGORITHM,
        str(iterations),
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    ]
    return "$".join(parts)


def verify_password(password: str, stored: str) -> bool:
    """Prueft ein Passwort gegen den gespeicherten Hash (zeitkonstant)."""
    if not password or not stored:
        return False
    try:
        algorithm, iterations, salt_b64, digest_b64 = stored.split("$")
        if algorithm != ALGORITHM:
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def password_strength_error(password: str) -> str | None:
    """Mindestanforderungen an das Admin-Passwort."""
    if len(password) < 12:
        return "Das Passwort muss mindestens 12 Zeichen lang sein."
    classes = sum(
        [
            any(char.islower() for char in password),
            any(char.isupper() for char in password),
            any(char.isdigit() for char in password),
            any(not char.isalnum() for char in password),
        ]
    )
    if classes < 3:
        return (
            "Das Passwort muss mindestens drei der vier Zeichenarten enthalten "
            "(Klein-, Grossbuchstaben, Ziffern, Sonderzeichen)."
        )
    return None


# -- Netzbeschraenkung -----------------------------------------------------


def parse_networks(entries: list[str]) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Wandelt CIDR-Angaben; ungueltige Eintraege werden protokolliert."""
    networks = []
    for entry in entries:
        text = entry.strip()
        if not text:
            continue
        try:
            networks.append(ipaddress.ip_network(text, strict=False))
        except ValueError:
            LOGGER.warning("Ungueltiger Netzeintrag in der Konfiguration: %s", text)
    return networks


def is_allowed_client(client_ip: str, allowed: list[str]) -> bool:
    """Prueft, ob eine IP-Adresse aus einem erlaubten Netz stammt."""
    if not client_ip:
        return False
    try:
        address = ipaddress.ip_address(client_ip.split("%")[0])
    except ValueError:
        return False
    networks = parse_networks(allowed)
    if not networks:
        # Ohne gueltige Konfiguration nur localhost zulassen (sichere Vorgabe).
        return address.is_loopback
    if address.version == 6 and address.ipv4_mapped:
        mapped = address.ipv4_mapped
        if any(mapped in network for network in networks if network.version == 4):
            return True
    return any(address in network for network in networks if network.version == address.version)


# -- Sitzungen -------------------------------------------------------------


@dataclass
class Session:
    token: str
    created_at: float
    expires_at: float
    client_ip: str


class SessionStore:
    """Sitzungen im Arbeitsspeicher - bei Neustart muss man sich neu anmelden."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self, client_ip: str, timeout_minutes: int) -> Session:
        token = secrets.token_urlsafe(32)
        now = time.time()
        session = Session(
            token=token,
            created_at=now,
            expires_at=now + timeout_minutes * 60,
            client_ip=client_ip,
        )
        with self._lock:
            self._prune_locked()
            self._sessions[token] = session
        return session

    def get(self, token: str | None) -> Session | None:
        if not token:
            return None
        with self._lock:
            session = self._sessions.get(token)
            if session is None:
                return None
            if session.expires_at < time.time():
                del self._sessions[token]
                return None
            return session

    def refresh(self, token: str, timeout_minutes: int) -> None:
        with self._lock:
            session = self._sessions.get(token)
            if session:
                session.expires_at = time.time() + timeout_minutes * 60

    def delete(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._sessions.pop(token, None)

    def clear(self) -> None:
        """Beendet alle Sitzungen (z. B. nach einem Passwortwechsel)."""
        with self._lock:
            self._sessions.clear()

    def _prune_locked(self) -> None:
        now = time.time()
        expired = [token for token, session in self._sessions.items() if session.expires_at < now]
        for token in expired:
            del self._sessions[token]


class LoginThrottle:
    """Einfache Bremse gegen das Durchprobieren von Passwoertern."""

    WINDOW = 900  # 15 Minuten

    def __init__(self) -> None:
        self._attempts: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def blocked(self, client_ip: str, limit: int) -> bool:
        now = time.time()
        with self._lock:
            attempts = [stamp for stamp in self._attempts.get(client_ip, []) if stamp > now - self.WINDOW]
            self._attempts[client_ip] = attempts
            return len(attempts) >= limit

    def record_failure(self, client_ip: str) -> None:
        with self._lock:
            self._attempts.setdefault(client_ip, []).append(time.time())

    def reset(self, client_ip: str) -> None:
        with self._lock:
            self._attempts.pop(client_ip, None)
