"""Weboberflaeche zur Konfiguration und Ueberwachung.

Die Oberflaeche ist ausdruecklich fuer den Betrieb im lokalen Netz gedacht.
Eine Middleware weist Anfragen aus fremden Netzen ab, zusaetzlich schuetzt
eine Anmeldung mit Passwort.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import __version__
from ..config import (
    AppConfig,
    generate_secret_key,
    load_config,
    save_config,
    whitelist_entry_problem,
)
from ..fax import BACKEND_LABELS, FaxError, get_backend
from ..mailbox import MailboxError, test_connection
from ..notify import NotifyError, send_mail
from ..paths import CONFIG_PATH, SPOOL_DIR, ensure_dirs, make_workdir
from ..render import text_to_pdf
from ..rules import RuleError, check_number_allowed, normalise_number
from ..storage import STATUS_QUEUED, Storage
from ..worker import Worker
from .auth import (
    SESSION_COOKIE,
    LoginThrottle,
    SessionStore,
    hash_password,
    is_allowed_client,
    password_strength_error,
    verify_password,
)

LOGGER = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

sessions = SessionStore()
throttle = LoginThrottle()


def _format_timestamp(value: float | None) -> str:
    if not value:
        return "-"
    return datetime.fromtimestamp(value).strftime("%d.%m.%Y %H:%M:%S")


def _client_ip(request: Request) -> str:
    """Die echte Peer-Adresse.

    Es werden bewusst keine X-Forwarded-For-Header ausgewertet: Die Oberflaeche
    soll direkt im lokalen Netz erreichbar sein, und ein faelschbarer Header
    duerfte die Netzbeschraenkung sonst aushebeln.
    """
    return request.client.host if request.client else ""


def create_app(config_path: Path | None = None, *, start_worker: bool = True) -> FastAPI:
    """Baut die FastAPI-Anwendung."""
    ensure_dirs()
    path = config_path or CONFIG_PATH
    storage = Storage()
    worker = Worker(storage, config_provider=lambda: load_config(path))

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if start_worker:
            worker.start()
        try:
            yield
        finally:
            if start_worker:
                worker.stop()
            storage.close()

    app = FastAPI(
        title="mail2fax",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.storage = storage
    app.state.worker = worker
    app.state.config_path = path

    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
    templates.env.filters["ts"] = _format_timestamp
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    def current_config() -> AppConfig:
        return load_config(path)

    def store_config(config: AppConfig) -> None:
        save_config(config, path)

    # -- Middleware: nur lokales Netz -------------------------------------

    @app.middleware("http")
    async def restrict_network(request: Request, call_next: Callable) -> Response:
        try:
            config = current_config()
            allowed = config.web.allowed_networks
        except Exception:
            allowed = ["127.0.0.0/8", "::1/128"]
        client = _client_ip(request)
        if not is_allowed_client(client, allowed):
            LOGGER.warning("Zugriff von %s abgewiesen (ausserhalb der erlaubten Netze)", client)
            return PlainTextResponse(
                "Zugriff nur aus dem lokalen Netz erlaubt.", status_code=status.HTTP_403_FORBIDDEN
            )
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'",
        )
        return response

    # -- Anmeldung ---------------------------------------------------------

    def require_login(request: Request) -> None:
        """Laesst nur angemeldete Zugriffe durch.

        Ist noch kein Passwort gesetzt, ist ausschliesslich der
        Einrichtungsdialog erreichbar - keine andere Seite und auch nicht die
        Schnittstelle. So steht die Oberflaeche zu keinem Zeitpunkt offen.
        """
        config = current_config()
        if not config.web.password_hash:
            raise HTTPException(
                status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/einrichtung"}
            )
        session = sessions.get(request.cookies.get(SESSION_COOKIE))
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"}
            )
        sessions.refresh(session.token, config.web.session_timeout_minutes)

    def render(request: Request, template: str, **context: Any) -> HTMLResponse:
        config = current_config()
        base = {
            "request": request,
            "config": config,
            "version": __version__,
            "backends": BACKEND_LABELS,
            "setup_required": not config.web.password_hash,
        }
        base.update(context)
        return templates.TemplateResponse(request, template, base)

    @app.exception_handler(HTTPException)
    async def redirect_on_login(request: Request, exc: HTTPException) -> Response:
        if exc.status_code == status.HTTP_303_SEE_OTHER and "Location" in (exc.headers or {}):
            return RedirectResponse(exc.headers["Location"], status_code=303)
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return PlainTextResponse(str(exc.detail), status_code=exc.status_code)

    @app.get("/login", response_class=HTMLResponse)
    async def login_form(request: Request) -> Response:
        config = current_config()
        if not config.web.password_hash:
            return RedirectResponse("/einrichtung", status_code=303)
        if sessions.get(request.cookies.get(SESSION_COOKIE)):
            return RedirectResponse("/", status_code=303)
        return render(request, "login.html", error=None)

    @app.post("/login")
    async def login(request: Request, password: str = Form(...)) -> Response:
        config = current_config()
        client = _client_ip(request)
        if throttle.blocked(client, config.web.login_attempts):
            LOGGER.warning("Anmeldung von %s wegen zu vieler Fehlversuche gesperrt", client)
            return render(
                request,
                "login.html",
                error="Zu viele Fehlversuche. Bitte in 15 Minuten erneut versuchen.",
            )
        if not verify_password(password, config.web.password_hash):
            throttle.record_failure(client)
            LOGGER.warning("Fehlgeschlagene Anmeldung von %s", client)
            time.sleep(1)  # Bremst automatisiertes Durchprobieren zusaetzlich
            return render(request, "login.html", error="Passwort falsch.")

        throttle.reset(client)
        session = sessions.create(client, config.web.session_timeout_minutes)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            session.token,
            httponly=True,
            samesite="strict",
            max_age=config.web.session_timeout_minutes * 60,
            path="/",
        )
        LOGGER.info("Erfolgreiche Anmeldung von %s", client)
        return response

    @app.get("/logout")
    async def logout(request: Request) -> Response:
        sessions.delete(request.cookies.get(SESSION_COOKIE))
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    # -- Erstinbetriebnahme ------------------------------------------------

    @app.get("/einrichtung", response_class=HTMLResponse)
    async def setup_form(request: Request) -> Response:
        if current_config().web.password_hash:
            return RedirectResponse("/login", status_code=303)
        return render(request, "setup.html", error=None)

    @app.post("/einrichtung")
    async def setup(
        request: Request, password: str = Form(...), password2: str = Form(...)
    ) -> Response:
        config = current_config()
        if config.web.password_hash:
            return RedirectResponse("/login", status_code=303)
        if password != password2:
            return render(request, "setup.html", error="Die Passwoerter stimmen nicht ueberein.")
        problem = password_strength_error(password)
        if problem:
            return render(request, "setup.html", error=problem)
        config.web.password_hash = hash_password(password)
        if not config.web.secret_key:
            config.web.secret_key = generate_secret_key()
        store_config(config)
        LOGGER.info("Admin-Passwort wurde gesetzt")
        return RedirectResponse("/login", status_code=303)

    # -- Uebersicht --------------------------------------------------------

    @app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_login)])
    async def dashboard(request: Request) -> Response:
        return render(
            request,
            "dashboard.html",
            stats=storage.stats(),
            jobs=storage.list_jobs(limit=10),
            worker=worker.state.snapshot(),
            warnings=_configuration_warnings(current_config()),
        )

    @app.post("/pruefen", dependencies=[Depends(require_login)])
    async def poll_now() -> Response:
        worker.trigger()
        return RedirectResponse("/?hinweis=Postfachabfrage+angestossen", status_code=303)

    # -- Auftraege ---------------------------------------------------------

    @app.get("/auftraege", response_class=HTMLResponse, dependencies=[Depends(require_login)])
    async def jobs(request: Request, status_filter: str | None = None) -> Response:
        return render(
            request,
            "jobs.html",
            jobs=storage.list_jobs(limit=200, status=status_filter or None),
            status_filter=status_filter or "",
            stats=storage.stats(),
        )

    @app.get("/auftraege/{job_id}", response_class=HTMLResponse, dependencies=[Depends(require_login)])
    async def job_detail(request: Request, job_id: int) -> Response:
        job = storage.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Auftrag nicht gefunden")
        return render(request, "job_detail.html", job=job, events=storage.list_events(job_id=job_id))

    @app.post("/auftraege/{job_id}/wiederholen", dependencies=[Depends(require_login)])
    async def job_retry(job_id: int) -> Response:
        job = storage.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Auftrag nicht gefunden")
        missing = [path for path in job.documents if not Path(path).exists()]
        if missing:
            return RedirectResponse(
                f"/auftraege/{job_id}?fehler=Dokumente+wurden+bereits+geloescht", status_code=303
            )
        storage.update_job(job_id, status=STATUS_QUEUED, attempts=0, next_attempt_at=time.time(), error=None)
        storage.log_event("Manuell erneut eingeplant", job_id=job_id)
        worker.trigger()
        return RedirectResponse(f"/auftraege/{job_id}", status_code=303)

    # -- Einstellungen -----------------------------------------------------

    @app.get("/einstellungen/mail", response_class=HTMLResponse, dependencies=[Depends(require_login)])
    async def mail_settings(request: Request) -> Response:
        return render(request, "settings_mail.html", message=None, error=None)

    @app.post("/einstellungen/mail", dependencies=[Depends(require_login)])
    async def mail_settings_save(request: Request) -> Response:
        form = await request.form()
        config = current_config()
        imap = config.imap
        imap.enabled = form.get("imap_enabled") == "on"
        imap.host = str(form.get("imap_host", "")).strip()
        imap.port = _as_int(form.get("imap_port"), imap.port)
        imap.security = _choice(form.get("imap_security"), ["ssl", "starttls", "none"], imap.security)
        imap.username = str(form.get("imap_username", "")).strip()
        if str(form.get("imap_password", "")):
            imap.password = str(form.get("imap_password"))
        imap.folder = str(form.get("imap_folder", "INBOX")).strip() or "INBOX"
        imap.poll_interval = max(10, min(3600, _as_int(form.get("imap_poll_interval"), imap.poll_interval)))
        imap.processed_action = _choice(
            form.get("imap_processed_action"), ["seen", "move", "delete"], imap.processed_action
        )
        imap.processed_folder = str(form.get("imap_processed_folder", "")).strip()
        imap.rejected_folder = str(form.get("imap_rejected_folder", "")).strip()
        imap.verify_tls = form.get("imap_verify_tls") == "on"
        imap.max_message_size_mb = max(1, min(200, _as_int(form.get("imap_max_size"), imap.max_message_size_mb)))

        smtp = config.smtp
        smtp.enabled = form.get("smtp_enabled") == "on"
        smtp.host = str(form.get("smtp_host", "")).strip()
        smtp.port = _as_int(form.get("smtp_port"), smtp.port)
        smtp.security = _choice(form.get("smtp_security"), ["starttls", "ssl", "none"], smtp.security)
        smtp.username = str(form.get("smtp_username", "")).strip()
        if str(form.get("smtp_password", "")):
            smtp.password = str(form.get("smtp_password"))
        smtp.from_address = str(form.get("smtp_from", "")).strip()
        smtp.admin_address = str(form.get("smtp_admin", "")).strip()
        smtp.notify_sender = form.get("smtp_notify_sender") == "on"
        smtp.report_unconfirmed = form.get("smtp_report_unconfirmed") == "on"
        smtp.verify_tls = form.get("smtp_verify_tls") == "on"

        store_config(config)
        worker.trigger()
        return render(request, "settings_mail.html", message="Einstellungen gespeichert.", error=None)

    @app.post("/einstellungen/mail/test", dependencies=[Depends(require_login)])
    async def mail_test(request: Request) -> Response:
        config = current_config()
        try:
            message = test_connection(config.imap)
        except MailboxError as error:
            return render(request, "settings_mail.html", message=None, error=str(error))
        return render(request, "settings_mail.html", message=message, error=None)

    @app.post("/einstellungen/mail/test-smtp", dependencies=[Depends(require_login)])
    async def smtp_test(request: Request) -> Response:
        form = await request.form()
        config = current_config()
        recipient = str(form.get("test_recipient", "")).strip() or config.smtp.admin_address
        if not recipient:
            return render(
                request, "settings_mail.html", message=None,
                error="Bitte eine Empfaengeradresse fuer den Test angeben.",
            )
        try:
            send_mail(
                config.smtp, recipient, "mail2fax Testnachricht",
                "Diese Nachricht bestaetigt, dass der Postausgang funktioniert.",
            )
        except NotifyError as error:
            return render(request, "settings_mail.html", message=None, error=str(error))
        return render(
            request, "settings_mail.html", message=f"Testnachricht an {recipient} versendet.", error=None
        )

    @app.get("/einstellungen/fax", response_class=HTMLResponse, dependencies=[Depends(require_login)])
    async def fax_settings(request: Request) -> Response:
        return render(request, "settings_fax.html", message=None, error=None)

    @app.post("/einstellungen/fax", dependencies=[Depends(require_login)])
    async def fax_settings_save(request: Request) -> Response:
        form = await request.form()
        config = current_config()
        fax = config.fax
        fax.backend = _choice(form.get("backend"), list(BACKEND_LABELS), fax.backend)
        fax.max_attempts = max(1, min(10, _as_int(form.get("max_attempts"), fax.max_attempts)))
        fax.retry_delay = max(10, min(86400, _as_int(form.get("retry_delay"), fax.retry_delay)))
        fax.dry_run = form.get("dry_run") == "on"

        hyla = fax.hylafax
        hyla.binary = str(form.get("hy_binary", "")).strip() or hyla.binary
        hyla.host = str(form.get("hy_host", "")).strip() or hyla.host
        hyla.port = _as_int(form.get("hy_port"), hyla.port)
        hyla.user = str(form.get("hy_user", "")).strip()
        hyla.sender_number = str(form.get("hy_sender_number", "")).strip()

        gateway = fax.mailgateway
        gateway.recipient_template = str(form.get("gw_recipient", "")).strip() or gateway.recipient_template
        gateway.host = str(form.get("gw_host", "")).strip()
        gateway.port = _as_int(form.get("gw_port"), gateway.port)
        gateway.security = _choice(form.get("gw_security"), ["starttls", "ssl", "none"], gateway.security)
        gateway.username = str(form.get("gw_username", "")).strip()
        if str(form.get("gw_password", "")):
            gateway.password = str(form.get("gw_password"))
        gateway.from_address = str(form.get("gw_from", "")).strip()

        sip = fax.sip
        sip.server = str(form.get("sip_server", "")).strip() or sip.server
        sip.port = _as_int(form.get("sip_port"), sip.port)
        sip.transport = _choice(form.get("sip_transport"), ["udp", "tcp"], sip.transport)
        sip.username = str(form.get("sip_username", "")).strip()
        if str(form.get("sip_password", "")):
            sip.password = str(form.get("sip_password"))
        sip.sender_number = str(form.get("sip_sender_number", "")).strip()
        sip.station_name = str(form.get("sip_station_name", "")).strip() or "mail2fax"
        sip.dial_prefix = str(form.get("sip_dial_prefix", "")).strip()
        sip.dial_national = form.get("sip_dial_national") == "on"
        sip.t38 = form.get("sip_t38") == "on"
        sip.ecm = form.get("sip_ecm") == "on"
        sip.maxrate = _as_int(form.get("sip_maxrate"), sip.maxrate)
        sip.minrate = min(sip.minrate, sip.maxrate)
        sip.timeout = max(60, min(3600, _as_int(form.get("sip_timeout"), sip.timeout)))

        command_line = str(form.get("cmd_argv", "")).strip()
        fax.command.argv = [part.strip() for part in command_line.splitlines() if part.strip()]

        content = config.content
        content.attachment_mode = _choice(form.get("attachment_mode"), ["first", "all"], content.attachment_mode)
        content.allowed_extensions = _as_list(form.get("allowed_extensions"))
        content.convert_office = form.get("convert_office") == "on"
        content.max_attachment_size_mb = max(1, min(100, _as_int(form.get("max_attachment_size"), content.max_attachment_size_mb)))
        content.max_pages = max(0, min(500, _as_int(form.get("max_pages"), content.max_pages)))
        content.include_mail_header = form.get("include_mail_header") == "on"

        store_config(config)
        return render(request, "settings_fax.html", message="Einstellungen gespeichert.", error=None)


    @app.post("/einstellungen/fax/sip-anwenden", dependencies=[Depends(require_login)])
    async def sip_apply(request: Request) -> Response:
        """Speichert die Einstellungen und erzeugt die Asterisk-Konfiguration."""
        from ..asterisk import generate_ami_secret, reload_asterisk, write_config

        await fax_settings_save(request)
        config = current_config()
        sip = config.fax.sip

        if not sip.username or not sip.password:
            return render(
                request, "settings_fax.html", message=None,
                error="Fuer die SIP-Anbindung fehlen Benutzername oder Passwort.",
            )
        if not sip.ami_password:
            sip.ami_password = generate_ami_secret()
            store_config(config)

        try:
            write_config(sip)
        except OSError as error:
            return render(
                request, "settings_fax.html", message=None,
                error=(
                    f"Die Asterisk-Konfiguration konnte nicht geschrieben werden: {error}. "
                    f"Existiert {sip.config_dir} und darf mail2fax hineinschreiben? "
                    "Das richtet install/sip-setup.sh ein."
                ),
            )
        try:
            hinweis = reload_asterisk(sip)
        except RuntimeError as error:
            return render(request, "settings_fax.html", message=None, error=str(error))
        return render(
            request, "settings_fax.html",
            message=f"Einstellungen gespeichert. {hinweis}", error=None,
        )

    @app.post("/einstellungen/fax/test", dependencies=[Depends(require_login)])
    async def fax_test(request: Request) -> Response:
        config = current_config()
        try:
            message = get_backend(config).test()
        except FaxError as error:
            return render(request, "settings_fax.html", message=None, error=str(error))
        except Exception as error:
            return render(request, "settings_fax.html", message=None, error=f"Unerwarteter Fehler: {error}")
        return render(request, "settings_fax.html", message=message, error=None)

    @app.post("/einstellungen/fax/testfax", dependencies=[Depends(require_login)])
    async def send_test_fax(request: Request) -> Response:
        form = await request.form()
        config = current_config()
        raw_number = str(form.get("test_number", "")).strip()
        try:
            number = normalise_number(raw_number, config.security)
            check_number_allowed(number, config.security)
        except RuleError as error:
            return render(request, "settings_fax.html", message=None, error=str(error))

        workdir = make_workdir(SPOOL_DIR, prefix="test-")
        document = text_to_pdf(
            "Dies ist ein Testfax von mail2fax.\n\n"
            f"Erzeugt am {datetime.now().strftime('%d.%m.%Y um %H:%M:%S')}.\n"
            "Wenn Sie diese Seite lesen koennen, funktioniert der Faxversand.",
            workdir / "testfax.pdf",
            title="mail2fax Testfax",
        )
        job = storage.create_job(
            sender="(Weboberflaeche)",
            subject="Testfax",
            number=number.e164,
            documents=[str(document.path)],
            source="test",
            pages=document.pages,
            backend=config.fax.backend,
        )
        storage.log_event("Testfax ueber die Weboberflaeche eingeplant", job_id=job.id)
        worker.trigger()
        return RedirectResponse(f"/auftraege/{job.id}", status_code=303)

    @app.get("/einstellungen/sicherheit", response_class=HTMLResponse, dependencies=[Depends(require_login)])
    async def security_settings(request: Request) -> Response:
        return render(request, "settings_security.html", message=None, error=None)

    @app.post("/einstellungen/sicherheit", dependencies=[Depends(require_login)])
    async def security_settings_save(request: Request) -> Response:
        form = await request.form()
        config = current_config()
        security = config.security

        eintraege = _as_lines(form.get("sender_whitelist"))
        probleme = [
            f"'{eintrag}': {problem}"
            for eintrag in eintraege
            if (problem := whitelist_entry_problem(eintrag))
        ]
        if probleme:
            # Nichts speichern - ein halb uebernommener Zugriffsschutz waere
            # schlimmer als gar keine Aenderung.
            return render(
                request, "settings_security.html", message=None,
                error="Absender-Whitelist nicht gespeichert: " + "; ".join(probleme),
            )
        security.sender_whitelist = eintraege
        security.allowed_number_prefixes = _as_lines(form.get("allowed_prefixes"))
        security.blocked_number_prefixes = _as_lines(form.get("blocked_prefixes"))
        security.accept_national_format = form.get("accept_national") == "on"
        security.default_country_code = str(form.get("country_code", "+49")).strip() or "+49"
        security.rate_limit_per_hour = max(0, _as_int(form.get("rate_limit"), security.rate_limit_per_hour))
        security.rate_limit_per_sender_per_hour = max(
            0, _as_int(form.get("rate_limit_sender"), security.rate_limit_per_sender_per_hour)
        )

        web = config.web
        web.allowed_networks = _as_lines(form.get("allowed_networks"))
        web.session_timeout_minutes = max(5, min(10080, _as_int(form.get("session_timeout"), web.session_timeout_minutes)))
        config.history_retention_days = max(0, min(3650, _as_int(form.get("retention"), config.history_retention_days)))
        config.delete_documents_after_send = form.get("delete_documents") == "on"

        store_config(config)
        return render(request, "settings_security.html", message="Einstellungen gespeichert.", error=None)

    @app.post("/einstellungen/passwort", dependencies=[Depends(require_login)])
    async def change_password(
        request: Request,
        current: str = Form(...),
        password: str = Form(...),
        password2: str = Form(...),
    ) -> Response:
        config = current_config()
        if not verify_password(current, config.web.password_hash):
            return render(request, "settings_security.html", message=None, error="Aktuelles Passwort ist falsch.")
        if password != password2:
            return render(request, "settings_security.html", message=None, error="Die neuen Passwoerter stimmen nicht ueberein.")
        problem = password_strength_error(password)
        if problem:
            return render(request, "settings_security.html", message=None, error=problem)
        config.web.password_hash = hash_password(password)
        store_config(config)
        sessions.clear()
        LOGGER.info("Admin-Passwort wurde geaendert; alle Sitzungen beendet")
        return RedirectResponse("/login", status_code=303)

    # -- Protokoll und Status ---------------------------------------------

    @app.get("/protokoll", response_class=HTMLResponse, dependencies=[Depends(require_login)])
    async def events(request: Request) -> Response:
        return render(request, "events.html", events=storage.list_events(limit=300))

    @app.get("/api/status", dependencies=[Depends(require_login)])
    async def api_status() -> JSONResponse:
        config = current_config()
        return JSONResponse(
            {
                "version": __version__,
                "backend": config.fax.backend,
                "dry_run": config.fax.dry_run,
                "imap_enabled": config.imap.enabled,
                "worker": worker.state.snapshot(),
                "jobs": storage.stats(),
            }
        )

    @app.get("/healthz", response_class=PlainTextResponse)
    async def healthz() -> str:
        return "ok"

    return app


def _configuration_warnings(config: AppConfig) -> list[str]:
    """Hinweise, die auf der Uebersicht angezeigt werden."""
    warnings: list[str] = []
    if not config.security.sender_whitelist:
        warnings.append(
            "Die Absender-Whitelist ist leer. Es werden keine Faxe verarbeitet, "
            "bis mindestens eine Adresse eingetragen ist."
        )
    if not config.imap.enabled:
        warnings.append("Die Postfachueberwachung ist deaktiviert.")
    if config.fax.backend == "dummy":
        warnings.append("Es ist das Testbackend aktiv - es werden keine Faxe versendet.")
    if config.fax.dry_run:
        warnings.append("Der Testbetrieb (dry-run) ist aktiv - es werden keine Faxe versendet.")
    if not config.imap.verify_tls and config.imap.enabled:
        warnings.append("Die TLS-Zertifikatspruefung fuer IMAP ist abgeschaltet.")
    if config.smtp.enabled and config.smtp.notify_sender and not _backend_confirms(config):
        warnings.append(
            "Der gewaehlte Versandweg liefert keine Quittung der Gegenstelle. "
            "Berichte an den Absender koennen die Uebertragung daher nicht "
            "belegen - sie weisen ausdruecklich darauf hin. Ein belegter "
            "Sendebericht ist mit dem Versandweg 'SIP' moeglich."
        )
    return warnings


def _backend_confirms(config: AppConfig) -> bool:
    """Ob der eingestellte Versandweg eine Empfangsquittung liefern kann."""
    if config.fax.dry_run:
        return False
    if config.fax.backend == "sip":
        return True
    if config.fax.backend == "command":
        return config.fax.command.confirms_delivery
    return False


def _as_int(value: object, fallback: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return fallback


def _choice(value: object, options: list[str], fallback: str) -> Any:
    text = str(value or "").strip()
    return text if text in options else fallback


def _as_lines(value: object) -> list[str]:
    return [line.strip() for line in str(value or "").replace(",", "\n").splitlines() if line.strip()]


def _as_list(value: object) -> list[str]:
    return [item.strip().lstrip(".").lower() for item in str(value or "").replace("\n", ",").split(",") if item.strip()]
