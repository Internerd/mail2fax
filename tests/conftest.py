"""Gemeinsame Test-Fixtures."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Datenverzeichnis umbiegen, bevor mail2fax importiert wird.
_TMP = tempfile.mkdtemp(prefix="mail2fax-tests-")
os.environ.setdefault("MAIL2FAX_DATA_DIR", _TMP)
os.environ.setdefault("MAIL2FAX_CONFIG", str(Path(_TMP) / "config.yaml"))


@pytest.fixture
def config():
    from mail2fax.config import AppConfig

    cfg = AppConfig()
    cfg.security.sender_whitelist = ["chef@example.com", "*@intern.example.com"]
    return cfg


@pytest.fixture
def storage(tmp_path):
    from mail2fax.storage import Storage

    store = Storage(tmp_path / "test.db")
    yield store
    store.close()
