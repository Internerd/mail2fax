"""Tests der Weboberflaeche (Zugriffsschutz, Anmeldung, Formulare)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mail2fax.config import AppConfig, load_config, save_config
from mail2fax.web import app as webapp
from mail2fax.web import auth
from mail2fax.web.app import create_app

PASSWORT = "Sicher-Genug-2026!"


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    """Frische Konfiguration samt eigenem Datenverzeichnis."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr("mail2fax.paths.DATA_DIR", data_dir)
    monkeypatch.setattr("mail2fax.paths.SPOOL_DIR", data_dir / "spool")
    monkeypatch.setattr("mail2fax.paths.DB_PATH", data_dir / "mail2fax.db")

    path = tmp_path / "config.yaml"
    config = AppConfig()
    config.web.password_hash = auth.hash_password(PASSWORT)
    config.security.sender_whitelist = ["chef@example.com"]
    save_config(config, path)
    return path


@pytest.fixture
def client(config_file):
    webapp.sessions.clear()
    app = create_app(config_file, start_worker=False)
    # Der TestClient meldet sich sonst als Host "testclient" - das ist keine
    # IP-Adresse und wird von der Netzsperre (korrekt) abgewiesen.
    with TestClient(app, client=("127.0.0.1", 50000)) as test_client:
        yield test_client


@pytest.fixture
def angemeldet(client):
    response = client.post("/login", data={"password": PASSWORT}, follow_redirects=False)
    assert response.status_code == 303
    return client


# -- Zugriffsschutz ---------------------------------------------------------


def test_client_outside_local_network_is_rejected(config_file):
    """Eine Anfrage aus einem oeffentlichen Netz wird abgewiesen - auch /healthz."""
    app = create_app(config_file, start_worker=False)
    with TestClient(app, client=("203.0.113.5", 50000)) as fremd:
        for pfad in ("/", "/login", "/healthz"):
            response = fremd.get(pfad, follow_redirects=False)
            assert response.status_code == 403, pfad
            assert "lokalen Netz" in response.text


def test_is_allowed_client_blocks_public_addresses():
    networks = AppConfig().web.allowed_networks
    assert auth.is_allowed_client("192.168.1.10", networks) is True
    assert auth.is_allowed_client("127.0.0.1", networks) is True
    assert auth.is_allowed_client("10.1.2.3", networks) is True
    assert auth.is_allowed_client("172.16.5.5", networks) is True
    assert auth.is_allowed_client("8.8.8.8", networks) is False
    assert auth.is_allowed_client("172.32.0.1", networks) is False
    assert auth.is_allowed_client("kaputt", networks) is False


def test_without_valid_networks_only_localhost():
    assert auth.is_allowed_client("127.0.0.1", ["unsinn"]) is True
    assert auth.is_allowed_client("192.168.1.1", ["unsinn"]) is False


def test_dashboard_requires_login(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_security_headers_are_set(client):
    response = client.get("/login")
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


# -- Anmeldung --------------------------------------------------------------


def test_login_with_correct_password(client):
    response = client.post("/login", data={"password": PASSWORT}, follow_redirects=False)
    assert response.status_code == 303
    assert auth.SESSION_COOKIE in response.cookies


def test_login_with_wrong_password(client):
    response = client.post("/login", data={"password": "falsch"})
    assert response.status_code == 200
    assert "falsch" in response.text.lower()
    assert auth.SESSION_COOKIE not in response.cookies


def test_login_throttle_blocks_after_many_failures(client, config_file):
    config = load_config(config_file)
    config.web.login_attempts = 3
    save_config(config, config_file)
    webapp.throttle.reset("127.0.0.1")
    for _ in range(3):
        client.post("/login", data={"password": "falsch"})
    response = client.post("/login", data={"password": PASSWORT})
    assert "Fehlversuche" in response.text
    webapp.throttle.reset("127.0.0.1")


def test_logout_ends_session(angemeldet):
    angemeldet.get("/logout", follow_redirects=False)
    assert angemeldet.get("/", follow_redirects=False).status_code == 303


# -- Seiten -----------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/", "/auftraege", "/einstellungen/mail", "/einstellungen/fax", "/einstellungen/sicherheit", "/protokoll"],
)
def test_pages_render(angemeldet, path):
    response = angemeldet.get(path)
    assert response.status_code == 200
    assert "mail2fax" in response.text


def test_healthz_is_public(client):
    assert client.get("/healthz").text == "ok"


def test_api_status(angemeldet):
    data = angemeldet.get("/api/status").json()
    assert data["backend"] == "dummy"
    assert "jobs" in data


def test_job_detail_404(angemeldet):
    assert angemeldet.get("/auftraege/9999").status_code == 404


# -- Formulare --------------------------------------------------------------


def test_save_mail_settings(angemeldet, config_file):
    response = angemeldet.post(
        "/einstellungen/mail",
        data={
            "imap_enabled": "on",
            "imap_host": "imap.example.com",
            "imap_port": "993",
            "imap_security": "ssl",
            "imap_username": "fax@example.com",
            "imap_password": "geheim123",
            "imap_folder": "INBOX",
            "imap_poll_interval": "30",
            "imap_max_size": "25",
            "imap_processed_action": "seen",
            "imap_verify_tls": "on",
            "smtp_port": "587",
            "smtp_security": "starttls",
        },
    )
    assert response.status_code == 200
    config = load_config(config_file)
    assert config.imap.host == "imap.example.com"
    assert config.imap.password == "geheim123"
    assert config.imap.poll_interval == 30


def test_empty_password_field_keeps_stored_password(angemeldet, config_file):
    config = load_config(config_file)
    config.imap.password = "altes-geheimnis"
    save_config(config, config_file)
    angemeldet.post(
        "/einstellungen/mail",
        data={"imap_host": "imap.example.com", "imap_port": "993", "imap_security": "ssl",
              "imap_password": "", "smtp_port": "587", "smtp_security": "starttls"},
    )
    assert load_config(config_file).imap.password == "altes-geheimnis"


def test_save_security_settings(angemeldet, config_file):
    angemeldet.post(
        "/einstellungen/sicherheit",
        data={
            "sender_whitelist": "chef@example.com\n*@intern.example.com",
            "allowed_prefixes": "+49",
            "blocked_prefixes": "+49900",
            "country_code": "+49",
            "rate_limit": "5",
            "rate_limit_sender": "2",
            "accept_national": "on",
            "allowed_networks": "192.168.0.0/16",
            "session_timeout": "60",
            "retention": "30",
        },
    )
    config = load_config(config_file)
    assert config.security.sender_whitelist == ["chef@example.com", "*@intern.example.com"]
    assert config.security.rate_limit_per_hour == 5
    assert config.web.allowed_networks == ["192.168.0.0/16"]


def test_save_fax_settings(angemeldet, config_file):
    angemeldet.post(
        "/einstellungen/fax",
        data={
            "backend": "mailgateway",
            "max_attempts": "5",
            "retry_delay": "120",
            "gw_recipient": "{number_digits}@fax.example.net",
            "gw_port": "587",
            "gw_security": "starttls",
            "attachment_mode": "all",
            "allowed_extensions": "pdf, png, txt",
            "max_attachment_size": "10",
            "max_pages": "20",
            "hy_port": "4559",
        },
    )
    config = load_config(config_file)
    assert config.fax.backend == "mailgateway"
    assert config.fax.max_attempts == 5
    assert config.content.allowed_extensions == ["pdf", "png", "txt"]


def test_invalid_backend_is_ignored(angemeldet, config_file):
    angemeldet.post(
        "/einstellungen/fax",
        data={"backend": "boeses_backend", "max_attempts": "3", "retry_delay": "300",
              "attachment_mode": "first", "max_attachment_size": "20", "max_pages": "30",
              "gw_port": "587", "gw_security": "starttls", "hy_port": "4559"},
    )
    assert load_config(config_file).fax.backend == "dummy"


def test_change_password(angemeldet, config_file):
    neu = "Noch-Sicherer-2027!"
    response = angemeldet.post(
        "/einstellungen/passwort",
        data={"current": PASSWORT, "password": neu, "password2": neu},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert auth.verify_password(neu, load_config(config_file).web.password_hash)


def test_change_password_requires_current(angemeldet):
    response = angemeldet.post(
        "/einstellungen/passwort",
        data={"current": "falsch", "password": "Neu-Passwort-123!", "password2": "Neu-Passwort-123!"},
    )
    assert "falsch" in response.text.lower()


def test_weak_password_is_rejected(angemeldet):
    response = angemeldet.post(
        "/einstellungen/passwort",
        data={"current": PASSWORT, "password": "kurz", "password2": "kurz"},
    )
    assert "12 Zeichen" in response.text


def test_test_fax_creates_job(angemeldet):
    response = angemeldet.post(
        "/einstellungen/fax/testfax", data={"test_number": "+49301234567"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert "/auftraege/" in response.headers["location"]


def test_test_fax_rejects_invalid_number(angemeldet):
    response = angemeldet.post("/einstellungen/fax/testfax", data={"test_number": "keine nummer"})
    assert response.status_code == 200
    assert "ungueltig" in response.text.lower() or "rufnummer" in response.text.lower()


# -- Ersteinrichtung --------------------------------------------------------


def test_setup_flow(tmp_path, monkeypatch):
    data_dir = tmp_path / "data2"
    data_dir.mkdir()
    monkeypatch.setattr("mail2fax.paths.DATA_DIR", data_dir)
    monkeypatch.setattr("mail2fax.paths.SPOOL_DIR", data_dir / "spool")
    monkeypatch.setattr("mail2fax.paths.DB_PATH", data_dir / "neu.db")

    path = tmp_path / "neu.yaml"
    save_config(AppConfig(), path)
    webapp.sessions.clear()
    with TestClient(create_app(path, start_worker=False), client=("127.0.0.1", 50000)) as client:
        assert client.get("/", follow_redirects=False).headers["location"] == "/einrichtung"
        assert client.get("/einrichtung").status_code == 200
        response = client.post(
            "/einrichtung",
            data={"password": "Erstes-Passwort-99!", "password2": "Erstes-Passwort-99!"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert auth.verify_password("Erstes-Passwort-99!", load_config(path).web.password_hash)
        # Danach ist die Einrichtung gesperrt
        assert client.get("/einrichtung", follow_redirects=False).headers["location"] == "/login"


def test_setup_rejects_mismatched_passwords(tmp_path, monkeypatch):
    data_dir = tmp_path / "data3"
    data_dir.mkdir()
    monkeypatch.setattr("mail2fax.paths.DATA_DIR", data_dir)
    monkeypatch.setattr("mail2fax.paths.SPOOL_DIR", data_dir / "spool")
    monkeypatch.setattr("mail2fax.paths.DB_PATH", data_dir / "neu.db")
    path = tmp_path / "neu.yaml"
    save_config(AppConfig(), path)
    with TestClient(create_app(path, start_worker=False), client=("127.0.0.1", 50000)) as client:
        response = client.post(
            "/einrichtung", data={"password": "Passwort-Eins-1!", "password2": "Passwort-Zwei-2!"}
        )
        assert "überein" in response.text or "ueberein" in response.text
