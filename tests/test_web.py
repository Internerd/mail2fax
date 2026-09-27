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


# -- SIP-Einstellungen ------------------------------------------------------


def basis_fax_formular(**extra):
    """Pflichtfelder des Fax-Formulars, damit Teiltests nicht alles wiederholen."""
    daten = {
        "backend": "sip", "max_attempts": "3", "retry_delay": "300",
        "attachment_mode": "first", "max_attachment_size": "20", "max_pages": "30",
        "gw_port": "587", "gw_security": "starttls", "hy_port": "4559",
        "sip_port": "5060", "sip_transport": "udp", "sip_maxrate": "14400",
        "sip_timeout": "900",
    }
    daten.update(extra)
    return daten


def test_save_sip_settings(angemeldet, config_file):
    angemeldet.post(
        "/einstellungen/fax",
        data=basis_fax_formular(
            sip_server="fritz.box", sip_username="620", sip_password="sip-geheim",
            sip_sender_number="+49301234567", sip_station_name="Buero",
            sip_dial_national="on", sip_ecm="on", sip_dial_prefix="0",
        ),
    )
    sip = load_config(config_file).fax.sip
    assert sip.server == "fritz.box"
    assert sip.username == "620"
    assert sip.password == "sip-geheim"
    assert sip.sender_number == "+49301234567"
    assert sip.dial_national is True
    assert sip.ecm is True
    assert sip.dial_prefix == "0"
    assert load_config(config_file).fax.backend == "sip"


def test_sip_password_is_kept_when_field_empty(angemeldet, config_file):
    angemeldet.post(
        "/einstellungen/fax",
        data=basis_fax_formular(sip_username="620", sip_password="erstes-geheim"),
    )
    angemeldet.post("/einstellungen/fax", data=basis_fax_formular(sip_username="620", sip_password=""))
    assert load_config(config_file).fax.sip.password == "erstes-geheim"


def test_t38_and_ecm_default_to_off(angemeldet, config_file):
    """Nicht angehakte Kaestchen muessen die Einstellung abschalten."""
    angemeldet.post(
        "/einstellungen/fax",
        data=basis_fax_formular(sip_username="620", sip_password="x", sip_t38="on", sip_ecm="on"),
    )
    assert load_config(config_file).fax.sip.t38 is True
    angemeldet.post("/einstellungen/fax", data=basis_fax_formular(sip_username="620"))
    sip = load_config(config_file).fax.sip
    assert sip.t38 is False
    assert sip.ecm is False


def test_sip_apply_needs_credentials(angemeldet):
    response = angemeldet.post(
        "/einstellungen/fax/sip-anwenden", data=basis_fax_formular(sip_username="", sip_password="")
    )
    assert response.status_code == 200
    assert "Benutzername oder Passwort" in response.text


def test_sip_apply_writes_configuration(angemeldet, config_file, tmp_path, monkeypatch):
    """Die Schaltflaeche erzeugt die Asterisk-Dateien und erzeugt AMI-Zugangsdaten."""
    ziel = tmp_path / "asterisk"
    config = load_config(config_file)
    config.fax.sip.config_dir = str(ziel)
    save_config(config, config_file)

    monkeypatch.setattr("mail2fax.asterisk.reload_asterisk", lambda _sip: "Neu geladen.")

    response = angemeldet.post(
        "/einstellungen/fax/sip-anwenden",
        data=basis_fax_formular(
            sip_server="fritz.box", sip_username="620", sip_password="sip-geheim",
            sip_sender_number="+49301234567",
        ),
    )
    assert response.status_code == 200
    assert "Neu geladen" in response.text
    assert (ziel / "pjsip.conf").exists()
    assert (ziel / "extensions.conf").exists()
    assert (ziel / "manager.conf").exists()
    assert load_config(config_file).fax.sip.ami_password != ""


def test_sip_apply_reports_write_error(angemeldet, config_file, monkeypatch):
    config = load_config(config_file)
    config.fax.sip.config_dir = "/nicht/beschreibbar/asterisk"
    save_config(config, config_file)
    response = angemeldet.post(
        "/einstellungen/fax/sip-anwenden",
        data=basis_fax_formular(sip_username="620", sip_password="x"),
    )
    assert "sip-setup.sh" in response.text


# -- Zugriffsschutz vor der Ersteinrichtung ---------------------------------


@pytest.fixture
def ohne_passwort(tmp_path, monkeypatch):
    """Eine Installation, bei der noch kein Passwort gesetzt wurde."""
    data_dir = tmp_path / "daten-offen"
    data_dir.mkdir()
    monkeypatch.setattr("mail2fax.paths.DATA_DIR", data_dir)
    monkeypatch.setattr("mail2fax.paths.SPOOL_DIR", data_dir / "spool")
    monkeypatch.setattr("mail2fax.paths.DB_PATH", data_dir / "offen.db")
    path = tmp_path / "offen.yaml"
    save_config(AppConfig(), path)
    webapp.sessions.clear()
    with TestClient(create_app(path, start_worker=False), client=("127.0.0.1", 50000)) as client:
        yield client


@pytest.mark.parametrize(
    "pfad",
    [
        "/", "/auftraege", "/protokoll", "/api/status",
        "/einstellungen/mail", "/einstellungen/fax", "/einstellungen/sicherheit",
    ],
)
def test_no_page_is_open_before_a_password_is_set(ohne_passwort, pfad):
    """Vor der Ersteinrichtung darf keine Seite Daten preisgeben."""
    response = ohne_passwort.get(pfad, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/einrichtung"


def test_settings_cannot_be_changed_before_setup(ohne_passwort, tmp_path):
    """Auch schreibende Zugriffe muessen vor der Einrichtung gesperrt sein."""
    response = ohne_passwort.post(
        "/einstellungen/sicherheit",
        data={"sender_whitelist": "angreifer@example.org", "allowed_networks": "0.0.0.0/0"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/einrichtung"
    assert load_config(tmp_path / "offen.yaml").security.sender_whitelist == []


def test_setup_page_stays_reachable(ohne_passwort):
    assert ohne_passwort.get("/einrichtung").status_code == 200


# -- Passwortschutz insgesamt ----------------------------------------------


def test_every_page_requires_login(client):
    """Mit gesetztem Passwort fuehrt jeder Aufruf ohne Sitzung zur Anmeldung."""
    for pfad in ("/", "/auftraege", "/protokoll", "/api/status",
                 "/einstellungen/mail", "/einstellungen/fax", "/einstellungen/sicherheit"):
        response = client.get(pfad, follow_redirects=False)
        assert response.status_code == 303, pfad
        assert response.headers["location"] == "/login", pfad


def test_password_is_never_stored_in_plain_text(angemeldet, config_file):
    inhalt = config_file.read_text(encoding="utf-8")
    assert PASSWORT not in inhalt
    assert load_config(config_file).web.password_hash.startswith("pbkdf2_sha256$")


def test_session_cookie_is_protected(client):
    response = client.post("/login", data={"password": PASSWORT}, follow_redirects=False)
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie


# -- Sendebericht in der Oberflaeche ---------------------------------------


def test_report_option_is_saved(angemeldet, config_file):
    angemeldet.post(
        "/einstellungen/mail",
        data={"imap_port": "993", "imap_security": "ssl", "smtp_port": "587",
              "smtp_security": "starttls", "smtp_enabled": "on",
              "smtp_notify_sender": "on", "smtp_report_unconfirmed": "on"},
    )
    smtp = load_config(config_file).smtp
    assert smtp.notify_sender is True
    assert smtp.report_unconfirmed is True

    angemeldet.post(
        "/einstellungen/mail",
        data={"imap_port": "993", "imap_security": "ssl", "smtp_port": "587",
              "smtp_security": "starttls", "smtp_enabled": "on", "smtp_notify_sender": "on"},
    )
    assert load_config(config_file).smtp.report_unconfirmed is False


def test_job_detail_shows_confirmed_transmission(angemeldet, client):
    storage = client.app.state.storage
    job = storage.create_job(sender="chef@example.com", subject="x", number="+49301234567")
    storage.update_job(
        job.id, status="sent", confirmed=1, pages_sent=2, rate="14400",
        resolution="204 x 196 dpi (fein)", remote_station="+4930999888", duration=48.2,
    )
    seite = angemeldet.get(f"/auftraege/{job.id}").text
    assert "quittiert" in seite
    assert "+4930999888" in seite
    assert "14400 bit/s" in seite
    assert "204 x 196 dpi (fein)" in seite
    assert "48 s" in seite


def test_job_detail_marks_missing_confirmation(angemeldet, client):
    storage = client.app.state.storage
    job = storage.create_job(sender="chef@example.com", subject="x", number="+49301234567")
    storage.update_job(job.id, status="sent", confirmed=0)
    seite = angemeldet.get(f"/auftraege/{job.id}").text
    assert "nicht quittiert" in seite
    assert "nicht belegt" in seite


def test_job_list_shows_confirmation_column(angemeldet, client):
    storage = client.app.state.storage
    bestaetigt = storage.create_job(sender="a@example.com", subject="ja", number="+4930")
    storage.update_job(bestaetigt.id, status="sent", confirmed=1)
    offen = storage.create_job(sender="a@example.com", subject="nein", number="+4931")
    storage.update_job(offen.id, status="sent", confirmed=0)

    seite = angemeldet.get("/auftraege").text
    assert "Quittung" in seite
    assert "bestätigt" in seite


def test_dashboard_warns_when_backend_cannot_confirm(angemeldet, config_file):
    config = load_config(config_file)
    config.smtp.enabled = True
    config.smtp.notify_sender = True
    config.fax.backend = "mailgateway"
    save_config(config, config_file)
    seite = angemeldet.get("/").text
    assert "keine Quittung der Gegenstelle" in seite


def test_dashboard_has_no_warning_for_sip(angemeldet, config_file):
    config = load_config(config_file)
    config.smtp.enabled = True
    config.smtp.notify_sender = True
    config.fax.backend = "sip"
    save_config(config, config_file)
    seite = angemeldet.get("/").text
    assert "keine Quittung der Gegenstelle" not in seite
