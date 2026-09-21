"""Kommandozeile von mail2fax."""

from __future__ import annotations

import argparse
import getpass
import sys
import time
from pathlib import Path

from . import __version__
from .config import AppConfig, generate_secret_key, load_config, save_config
from .logging_setup import setup_logging
from .paths import CONFIG_PATH, ensure_dirs


def _config_path(args: argparse.Namespace) -> Path:
    return Path(args.config) if args.config else CONFIG_PATH


def cmd_web(args: argparse.Namespace) -> int:
    """Startet Weboberflaeche und Hintergrunddienst."""
    import uvicorn

    path = _config_path(args)
    config = load_config(path)
    setup_logging(config.log_level)
    ensure_dirs()

    from .web.app import create_app

    app = create_app(path, start_worker=not args.no_worker)
    uvicorn.run(
        app,
        host=args.host or config.web.host,
        port=args.port or config.web.port,
        log_level=config.log_level.lower(),
        access_log=False,
        server_header=False,
        date_header=True,
    )
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Startet nur den Hintergrunddienst (ohne Weboberflaeche)."""
    from .storage import Storage
    from .worker import Worker

    path = _config_path(args)
    config = load_config(path)
    setup_logging(config.log_level)
    ensure_dirs()

    storage = Storage()
    worker = Worker(storage, config_provider=lambda: load_config(path))
    worker.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Beende...", file=sys.stderr)
    finally:
        worker.stop()
        storage.close()
    return 0


def cmd_check_mail(args: argparse.Namespace) -> int:
    """Fragt das Postfach genau einmal ab (fuer Tests und Cron)."""
    from .storage import Storage
    from .worker import Worker

    path = _config_path(args)
    config = load_config(path)
    setup_logging("DEBUG" if args.verbose else config.log_level)
    ensure_dirs()

    storage = Storage()
    worker = Worker(storage, config_provider=lambda: load_config(path))
    try:
        processed = worker.poll_mailbox(config)
        handled = worker.process_queue(config)
        print(f"{processed} Nachricht(en) verarbeitet, {handled} Auftrag/Auftraege abgearbeitet.")
        state = worker.state.snapshot()
        if state["last_poll_error"]:
            print(f"Fehler: {state['last_poll_error']}", file=sys.stderr)
            return 1
    finally:
        storage.close()
    return 0


def cmd_test_fax(args: argparse.Namespace) -> int:
    """Versendet ein Testfax an die angegebene Rufnummer."""
    from .fax import FaxError, get_backend
    from .render import text_to_pdf
    from .rules import RuleError, check_number_allowed, normalise_number

    path = _config_path(args)
    config = load_config(path)
    setup_logging("DEBUG" if args.verbose else config.log_level)
    ensure_dirs()

    try:
        number = normalise_number(args.number, config.security)
        check_number_allowed(number, config.security)
    except RuleError as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return 2

    from .paths import SPOOL_DIR

    document = text_to_pdf(
        "Testfax von mail2fax.\n\n"
        f"Erzeugt am {time.strftime('%d.%m.%Y um %H:%M:%S')}.\n"
        "Wenn Sie diese Seite lesen koennen, funktioniert der Faxversand.",
        SPOOL_DIR / f"testfax-{int(time.time())}.pdf",
        title="mail2fax Testfax",
    )
    try:
        result = get_backend(config).send(number, [document.path], subject="Testfax")
    except FaxError as error:
        print(f"Versand fehlgeschlagen: {error}", file=sys.stderr)
        return 1
    print(f"Erfolgreich: {result.detail}")
    return 0


def cmd_test_backend(args: argparse.Namespace) -> int:
    """Prueft die Erreichbarkeit des konfigurierten Fax-Backends."""
    from .fax import FaxError, get_backend

    config = load_config(_config_path(args))
    setup_logging(config.log_level)
    try:
        print(get_backend(config).test())
    except FaxError as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return 1
    return 0


def cmd_test_imap(args: argparse.Namespace) -> int:
    """Prueft die IMAP-Verbindung."""
    from .mailbox import MailboxError, test_connection

    config = load_config(_config_path(args))
    setup_logging("DEBUG" if args.verbose else config.log_level)
    try:
        print(test_connection(config.imap))
    except MailboxError as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return 1
    return 0


def cmd_passwd(args: argparse.Namespace) -> int:
    """Setzt das Passwort der Weboberflaeche."""
    from .web.auth import hash_password, password_strength_error

    path = _config_path(args)
    config = load_config(path)
    password = args.password
    if not password:
        password = getpass.getpass("Neues Passwort: ")
        if password != getpass.getpass("Passwort wiederholen: "):
            print("Die Passwoerter stimmen nicht ueberein.", file=sys.stderr)
            return 2

    problem = password_strength_error(password)
    if problem:
        if args.force:
            print(f"Warnung: {problem}", file=sys.stderr)
        else:
            print(f"Fehler: {problem}", file=sys.stderr)
            return 2

    config.web.password_hash = hash_password(password)
    if not config.web.secret_key:
        config.web.secret_key = generate_secret_key()
    save_config(config, path)
    print(f"Passwort gesetzt (gespeichert in {path}).")
    return 0


def cmd_init_config(args: argparse.Namespace) -> int:
    """Legt eine Standardkonfiguration an."""
    path = _config_path(args)
    if path.exists() and not args.force:
        print(f"{path} existiert bereits (--force zum Ueberschreiben).", file=sys.stderr)
        return 1
    config = AppConfig()
    config.web.secret_key = generate_secret_key()
    save_config(config, path)
    ensure_dirs()
    print(f"Konfiguration angelegt: {path}")
    return 0


def cmd_show_config(args: argparse.Namespace) -> int:
    """Zeigt die Konfiguration ohne Passwoerter an."""
    import yaml

    config = load_config(_config_path(args))
    data = config.model_dump(mode="json")

    def redact(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("password", "password_hash", "secret_key") and value:
                    node[key] = "***"
                else:
                    redact(value)

    redact(data)
    print(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
    return 0


def cmd_sip_apply(args: argparse.Namespace) -> int:
    """Schreibt die Asterisk-Konfiguration aus den SIP-Einstellungen."""
    from .asterisk import generate_ami_secret, reload_asterisk, write_config

    path = _config_path(args)
    config = load_config(path)
    setup_logging("DEBUG" if args.verbose else config.log_level)
    sip = config.fax.sip

    if not sip.username or not sip.password:
        print(
            "Fehler: Fuer die SIP-Anbindung fehlen Benutzername oder Passwort. "
            "Bitte zuerst in der Weboberflaeche unter 'Fax' eintragen.",
            file=sys.stderr,
        )
        return 2

    if not sip.ami_password:
        sip.ami_password = generate_ami_secret()
        save_config(config, path)
        print("Zugangsdaten fuer die Asterisk-Steuerung (AMI) erzeugt.")

    try:
        written = write_config(sip)
    except OSError as error:
        print(
            f"Fehler: Konfiguration konnte nicht geschrieben werden: {error}\n"
            f"Existiert {sip.config_dir} und ist es beschreibbar? "
            "Die Einrichtung erledigt install/sip-setup.sh.",
            file=sys.stderr,
        )
        return 1

    for datei in written:
        print(f"Geschrieben: {datei}")

    if args.no_reload:
        print("Neuladen uebersprungen (--no-reload).")
        return 0
    try:
        print(reload_asterisk(sip))
    except RuntimeError as error:
        print(f"Warnung: {error}", file=sys.stderr)
        return 1
    return 0


def cmd_sip_status(args: argparse.Namespace) -> int:
    """Zeigt den Zustand der SIP-Registrierung und der Faxmodule."""
    from .fax.ami import AmiClient, AmiError

    config = load_config(_config_path(args))
    setup_logging("DEBUG" if args.verbose else config.log_level)
    sip = config.fax.sip
    try:
        with AmiClient(sip.ami_host, sip.ami_port, sip.ami_user, sip.ami_password) as client:
            print("== Registrierung ==")
            print(client.command("pjsip show registrations").strip() or "(keine)")
            print("\n== Endpunkt ==")
            print(client.command(f"pjsip show endpoint {sip.endpoint_name}").split("ParameterName")[0].strip())
            print("\n== Faxmodule ==")
            print(client.command("module show like fax").strip())
            print("\n== Aktive Kanaele ==")
            print(client.command("core show channels").strip())
    except AmiError as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mail2fax",
        description="E-Mail-zu-Fax-Gateway: ueberwacht ein Postfach und versendet "
        "Anhaenge bzw. den Mailtext als Fax.",
    )
    parser.add_argument("--version", action="version", version=f"mail2fax {__version__}")
    parser.add_argument("-c", "--config", help=f"Pfad der Konfiguration (Vorgabe: {CONFIG_PATH})")
    parser.add_argument("-v", "--verbose", action="store_true", help="Ausfuehrliche Ausgabe")

    subparsers = parser.add_subparsers(dest="command", required=True)

    web = subparsers.add_parser("web", help="Weboberflaeche und Dienst starten")
    web.add_argument("--host", help="Adresse, an die gebunden wird")
    web.add_argument("--port", type=int, help="Port")
    web.add_argument("--no-worker", action="store_true", help="Ohne Hintergrunddienst starten")
    web.set_defaults(func=cmd_web)

    run = subparsers.add_parser("run", help="Nur den Hintergrunddienst starten")
    run.set_defaults(func=cmd_run)

    check = subparsers.add_parser("check-mail", help="Postfach einmalig abfragen")
    check.set_defaults(func=cmd_check_mail)

    test_fax = subparsers.add_parser("test-fax", help="Testfax versenden")
    test_fax.add_argument("number", help="Zielrufnummer, z. B. +49301234567")
    test_fax.set_defaults(func=cmd_test_fax)

    subparsers.add_parser("test-backend", help="Fax-Backend pruefen").set_defaults(func=cmd_test_backend)

    sip_apply = subparsers.add_parser(
        "sip-apply", help="Asterisk-Konfiguration aus den SIP-Einstellungen schreiben"
    )
    sip_apply.add_argument(
        "--no-reload", action="store_true", help="Nur schreiben, Asterisk nicht neu laden"
    )
    sip_apply.set_defaults(func=cmd_sip_apply)

    subparsers.add_parser(
        "sip-status", help="Zustand der SIP-Registrierung anzeigen"
    ).set_defaults(func=cmd_sip_status)
    subparsers.add_parser("test-imap", help="IMAP-Verbindung pruefen").set_defaults(func=cmd_test_imap)

    passwd = subparsers.add_parser("passwd", help="Passwort der Weboberflaeche setzen")
    passwd.add_argument("--password", help="Passwort (sonst interaktive Abfrage)")
    passwd.add_argument("--force", action="store_true", help="Schwaches Passwort zulassen")
    passwd.set_defaults(func=cmd_passwd)

    init = subparsers.add_parser("init-config", help="Standardkonfiguration anlegen")
    init.add_argument("--force", action="store_true", help="Vorhandene Datei ueberschreiben")
    init.set_defaults(func=cmd_init_config)

    subparsers.add_parser("show-config", help="Konfiguration anzeigen (ohne Passwoerter)").set_defaults(
        func=cmd_show_config
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        if getattr(args, "verbose", False):
            raise
        print(f"Fehler: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
