"""Tests der Verwaltungsaktionen (Update und Asterisk-Einrichtung per Weboberflaeche).

Die systemd-Seite (Pfad-Unit -> Root-Dienst) laesst sich ohne systemd nicht
starten. Getestet werden daher die Bruecke auf Seiten von mail2fax, die
Auswertung der Status-Dateien und - in ``test_admin_unit_commands`` - die
Befehle der Unit-Datei, nachgestellt mit einer Shell.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mail2fax import admin
from mail2fax.config import AppConfig, save_config
from mail2fax.web import app as webapp
from mail2fax.web import auth
from mail2fax.web.app import create_app

ROOT = Path(__file__).resolve().parent.parent
PASSWORT = "Sicher-Genug-2026!"


@pytest.fixture
def umgebung(tmp_path, monkeypatch):
    """Verzeichnisse einer Installation mit eingerichteten Root-Helfern."""
    daten = tmp_path / "data"
    daten.mkdir()
    verwaltung = tmp_path / "admin"
    verwaltung.mkdir()
    helfer = tmp_path / "helper"
    helfer.mkdir()
    units = tmp_path / "units"
    units.mkdir()
    app_dir = tmp_path / "opt"
    app_dir.mkdir()
    monkeypatch.setattr("mail2fax.paths.DATA_DIR", daten)
    monkeypatch.setattr("mail2fax.paths.SPOOL_DIR", daten / "spool")
    monkeypatch.setattr("mail2fax.paths.DB_PATH", daten / "mail2fax.db")
    monkeypatch.setattr(admin, "ADMIN_DIR", verwaltung)
    monkeypatch.setattr(admin, "HELPER_DIR", helfer)
    monkeypatch.setattr(admin, "UNIT_DIR", units)
    monkeypatch.setattr(admin, "APP_DIR", app_dir)
    for name in admin.ACTIONS:
        (helfer / f"{name}.sh").write_text("#!/bin/sh\n")
        (units / f"mail2fax-{name}.path").write_text("[Path]\n")
    return tmp_path


# -- Anfordern ----------------------------------------------------------------


def test_request_creates_empty_request_file(umgebung):
    admin.request_action("update")
    datei = admin.control_dir() / "update.request"
    assert datei.is_file()
    assert datei.read_bytes() == b""
    assert admin.action_state("update").state == "pending"


def test_unknown_action_is_refused(umgebung):
    with pytest.raises(admin.AdminError, match="Unbekannte Aktion"):
        admin.request_action("rm -rf")
    with pytest.raises(admin.AdminError):
        admin.request_action("../update")
    assert not admin.control_dir().exists() or not any(admin.control_dir().iterdir())


def test_second_request_while_pending_is_refused(umgebung):
    admin.request_action("update")
    with pytest.raises(admin.AdminError, match="bereits"):
        admin.request_action("update")


def test_request_while_running_is_refused(umgebung):
    (admin.ADMIN_DIR / "update.status").write_text(f"running {time.time():.0f}\n")
    with pytest.raises(admin.AdminError, match="laeuft"):
        admin.request_action("update")


def test_request_without_helpers_explains_bootstrap(umgebung):
    (admin.HELPER_DIR / "sip-setup.sh").unlink()
    assert admin.helper_installed("sip-setup") is False
    with pytest.raises(admin.AdminError, match="einmalig"):
        admin.request_action("sip-setup")


def test_request_does_not_follow_symlink(umgebung, tmp_path):
    """Liegt an Stelle der Anforderung ein Symlink, wird er ersetzt, nie verfolgt."""
    opfer = tmp_path / "opfer.txt"
    opfer.write_text("unveraendert")
    admin.control_dir().mkdir(parents=True)
    link = admin.control_dir() / "update.request"
    link.symlink_to(opfer)
    # Ein alter Link gilt als (ueberfaellige) Anforderung ...
    os.utime(link, (time.time() - 3600, time.time() - 3600), follow_symlinks=False)
    admin.request_action("update")
    assert opfer.read_text() == "unveraendert"
    assert not (admin.control_dir() / "update.request").is_symlink()


def test_stale_request_can_be_renewed(umgebung):
    """Holt die Pfad-Unit eine Anforderung nie ab, blockiert sie nicht ewig."""
    admin.request_action("update")
    alt = time.time() - admin.PICKUP_TIMEOUT - 5
    os.utime(admin.control_dir() / "update.request", (alt, alt))
    zustand = admin.action_state("update")
    assert zustand.state == "stale"
    assert "mail2fax-update.path" in zustand.detail
    admin.request_action("update")
    assert admin.action_state("update").state == "pending"


# -- Status lesen ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("inhalt", "erwartet"),
    [
        ("success 1700000000 0", "success"),
        ("exit-code 1700000000 1", "failed"),
        ("timeout 1700000000 ", "failed"),
        ("", "idle"),
    ],
)
def test_status_file_is_interpreted(umgebung, inhalt, erwartet):
    (admin.ADMIN_DIR / "update.status").write_text(inhalt)
    assert admin.action_state("update").state == erwartet


def test_failed_state_names_exit_code(umgebung):
    (admin.ADMIN_DIR / "update.status").write_text("exit-code 1700000000 2\n")
    zustand = admin.action_state("update")
    assert "exit-code" in zustand.detail
    assert "2" in zustand.detail


def test_long_running_counts_as_stale(umgebung):
    alt = time.time() - admin.STALE_AFTER - 10
    (admin.ADMIN_DIR / "update.status").write_text(f"running {alt:.0f}\n")
    assert admin.action_state("update").state == "stale"
    # ... und blockiert einen neuen Versuch nicht.
    admin.request_action("update")


def test_no_status_means_idle(umgebung):
    assert admin.action_state("sip-setup").state == "idle"


def test_log_is_tailed_and_stripped_of_colours(umgebung):
    zeilen = [f"\x1b[0;34m==>\x1b[0m Schritt {i}" for i in range(100)]
    (admin.ADMIN_DIR / "update.log").write_text("\n".join(zeilen))
    log = admin.action_state("update", log_lines=5).log
    assert log.splitlines() == [f"==> Schritt {i}" for i in range(95, 100)]


# -- Versionsstand ---------------------------------------------------------------


def test_installed_revision_is_read(umgebung):
    (admin.APP_DIR / "REVISION").write_text("0123456789abcdef 2026-10-01T12:00:00Z\n")
    revision = admin.installed_revision()
    assert revision is not None
    assert revision.short == "0123456"
    assert revision.date == "2026-10-01T12:00:00Z"


def test_missing_revision_is_none(umgebung):
    assert admin.installed_revision() is None


def test_latest_revision_reports_unreachable_github(monkeypatch):
    import httpx

    def kaputt(*_args, **_kwargs):
        raise httpx.ConnectError("kein Netz")

    monkeypatch.setattr(httpx, "get", kaputt)
    with pytest.raises(admin.AdminError, match="nicht erreichbar"):
        admin.latest_revision()


def test_latest_revision_parses_github_answer(monkeypatch):
    import httpx

    class Antwort:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "sha": "fedcba9876543210",
                "commit": {"committer": {"date": "2026-10-12T08:00:00Z"}, "message": "Titel\n\nText"},
            }

    aufrufe = []

    def holen(url, **kwargs):
        aufrufe.append(url)
        return Antwort()

    monkeypatch.setattr(httpx, "get", holen)
    revision = admin.latest_revision()
    assert revision.short == "fedcba9"
    assert revision.message == "Titel"
    # Fest verdrahtet - nicht aus der Konfiguration.
    assert aufrufe == [f"https://api.github.com/repos/{admin.UPDATE_REPO}/commits/main"]


# -- Weboberflaeche ----------------------------------------------------------------


@pytest.fixture
def web(umgebung):
    path = umgebung / "config.yaml"
    config = AppConfig()
    config.web.password_hash = auth.hash_password(PASSWORT)
    config.security.sender_whitelist = ["chef@example.com"]
    save_config(config, path)
    webapp.sessions.clear()
    app = create_app(path, start_worker=False)
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        assert client.post("/login", data={"password": PASSWORT}, follow_redirects=False).status_code == 303
        yield client


def test_system_page_requires_login(umgebung):
    path = umgebung / "config.yaml"
    config = AppConfig()
    config.web.password_hash = auth.hash_password(PASSWORT)
    save_config(config, path)
    webapp.sessions.clear()
    app = create_app(path, start_worker=False)
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        for methode, pfad in (("get", "/system"), ("post", "/system/aktion/update"),
                              ("post", "/system/pruefen"), ("get", "/system/status")):
            antwort = getattr(client, methode)(pfad, follow_redirects=False)
            assert antwort.status_code == 303, pfad
            assert antwort.headers["location"] == "/login"
    assert not (admin.control_dir() / "update.request").exists()


def test_system_page_shows_revision_and_buttons(web):
    (admin.APP_DIR / "REVISION").write_text("0123456789abcdef 2026-10-01T12:00:00Z\n")
    seite = web.get("/system").text
    assert "0123456" in seite
    assert 'action="/system/aktion/update"' in seite
    assert 'action="/system/aktion/sip-setup"' in seite
    assert "einmalig" not in seite.lower()


def test_system_page_without_helpers_shows_bootstrap(web):
    (admin.UNIT_DIR / "mail2fax-update.path").unlink()
    seite = web.get("/system").text
    assert "install/update.sh" in seite
    assert 'action="/system/aktion/update"' not in seite


def test_update_button_creates_request(web):
    antwort = web.post("/system/aktion/update", follow_redirects=False)
    assert antwort.status_code == 303
    assert "hinweis=" in antwort.headers["location"]
    assert (admin.control_dir() / "update.request").exists()
    seite = web.get("/system").text
    assert "angefordert" in seite
    assert "/static/system.js" in seite  # Seite aktualisiert sich selbst
    assert web.get("/system/status").json()["update"]["busy"] is True


def test_unknown_action_via_web_is_refused(web):
    antwort = web.post("/system/aktion/shutdown", follow_redirects=False)
    assert "fehler=" in antwort.headers["location"]
    assert not admin.control_dir().exists() or not any(admin.control_dir().iterdir())


def test_update_check_only_on_demand(web, monkeypatch):
    """Die Seite selbst fragt GitHub nicht - nur die Schaltflaeche tut es."""
    aufrufe = []

    def neuester(*_args, **_kwargs):
        aufrufe.append(1)
        return admin.Revision("fedcba9876543210", "2026-10-12", "Neue Funktion")

    monkeypatch.setattr(admin, "latest_revision", neuester)
    web.get("/system")
    assert aufrufe == []
    seite = web.post("/system/pruefen").text
    assert aufrufe == [1]
    assert "fedcba9" in seite
    assert "neuerer Stand" in seite


def test_update_check_same_revision(web, monkeypatch):
    (admin.APP_DIR / "REVISION").write_text("fedcba9876543210 2026-10-12\n")
    monkeypatch.setattr(admin, "latest_revision", lambda *_a, **_k: admin.Revision("fedcba9876543210"))
    assert "neuesten Stand" in web.post("/system/pruefen").text


def test_finished_action_shows_log(web):
    (admin.ADMIN_DIR / "sip-setup.status").write_text("exit-code 1700000000 1\n")
    (admin.ADMIN_DIR / "sip-setup.log").write_text("FEHLER Asterisk startet nicht\n")
    seite = web.get("/system").text
    assert "fehlgeschlagen" in seite
    assert "Asterisk startet nicht" in seite
    assert "/static/system.js" not in seite


# -- systemd-Units ------------------------------------------------------------------


def _unit_befehle(unit: str, schluessel: str, instanz: str) -> list[str]:
    text = (ROOT / "systemd" / unit).read_text()
    befehle = re.findall(rf"^{schluessel}=(.+)$", text, flags=re.MULTILINE)
    return [b.replace("%i", instanz).replace("%%", "%") for b in befehle]


def test_path_units_match_actions():
    for name in admin.ACTIONS:
        text = (ROOT / "systemd" / f"mail2fax-{name}.path").read_text()
        assert f"PathExists=/var/lib/mail2fax/control/{name}.request" in text
        assert f"Unit=mail2fax-aktion@{name}.service" in text
        skript = ROOT / "install" / f"{name}.sh"
        assert skript.is_file(), skript


def test_service_unit_runs_root_owned_helper_only():
    text = (ROOT / "systemd" / "mail2fax-aktion@.service").read_text()
    assert "ExecStart=/usr/local/lib/mail2fax/%i.sh" in text
    # Kein Code aus dem Bereich, den der Webdienst beschreiben darf.
    for zeile in text.splitlines():
        if zeile.startswith("Exec"):
            assert "/opt/mail2fax" not in zeile
            assert "/etc/mail2fax" not in zeile
    assert "User=" not in text  # laeuft als root
    # truncate: wuerde bei jedem Exec-Schritt neu leeren (auch ExecStopPost).
    assert "StandardOutput=append:" in text


def test_admin_unit_commands(tmp_path):
    """Spielt die Befehle der Unit nach: Anforderung weg, Status, Protokoll."""
    steuerung = tmp_path / "var/lib/mail2fax/control"
    steuerung.mkdir(parents=True)
    verwaltung = tmp_path / "var/lib/mail2fax-admin"
    verwaltung.mkdir(parents=True)
    (steuerung / "update.request").touch()
    (verwaltung / "update.log").write_text("altes Protokoll\n")

    def ausfuehren(befehl: str, **umgebung: str) -> None:
        befehl = befehl.replace("/var/lib/", f"{tmp_path}/var/lib/")
        subprocess.run(["sh", "-c", befehl], check=True, env={**os.environ, **umgebung})

    for befehl in _unit_befehle("mail2fax-aktion@.service", "ExecStartPre", "update"):
        if befehl.startswith("/bin/sh -c "):
            befehl = befehl[len("/bin/sh -c "):].strip("'")
        ausfuehren(befehl)
    assert not (steuerung / "update.request").exists()
    assert (verwaltung / "update.log").read_text() == ""
    assert (verwaltung / "update.status").read_text().startswith("running ")

    for befehl in _unit_befehle("mail2fax-aktion@.service", "ExecStopPost", "update"):
        befehl = befehl[len("/bin/sh -c "):].strip("'")
        ausfuehren(befehl, SERVICE_RESULT="exit-code", EXIT_STATUS="3")
    felder = (verwaltung / "update.status").read_text().split()
    assert felder[0] == "exit-code"
    assert felder[2] == "3"
