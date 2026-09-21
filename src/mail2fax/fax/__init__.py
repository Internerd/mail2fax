"""Registry der verfuegbaren Fax-Backends."""

from __future__ import annotations

from ..config import AppConfig
from .base import FaxBackend, FaxError, FaxResult
from .command import CommandBackend
from .dummy import DummyBackend
from .fritzbox import FritzboxBackend
from .hylafax import HylafaxBackend
from .mailgateway import MailGatewayBackend
from .sip import SipBackend

BACKENDS: dict[str, type[FaxBackend]] = {
    "sip": SipBackend,
    "fritzbox": FritzboxBackend,
    "hylafax": HylafaxBackend,
    "mailgateway": MailGatewayBackend,
    "command": CommandBackend,
    "dummy": DummyBackend,
}

BACKEND_LABELS: dict[str, str] = {key: cls.name for key, cls in BACKENDS.items()}


def get_backend(config: AppConfig) -> FaxBackend:
    """Erzeugt das in der Konfiguration gewaehlte Backend."""
    name = config.fax.backend
    backend_class = BACKENDS.get(name)
    if backend_class is None:
        raise FaxError(f"Unbekanntes Fax-Backend: {name}", permanent=True)
    return backend_class(config)


__all__ = [
    "BACKENDS",
    "BACKEND_LABELS",
    "FaxBackend",
    "FaxError",
    "FaxResult",
    "get_backend",
]
