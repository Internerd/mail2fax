"""Statusmeldungen per E-Mail an Absender und Administrator."""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from .config import AppConfig, SmtpConfig

LOGGER = logging.getLogger(__name__)


class NotifyError(Exception):
    """Fehler beim Versand einer Statusmeldung."""


def _context(verify_tls: bool) -> ssl.SSLContext:
    context = ssl.create_default_context()
    if not verify_tls:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def send_mail(smtp: SmtpConfig, to_address: str, subject: str, body: str) -> None:
    """Versendet eine einfache Textnachricht."""
    if not smtp.host:
        raise NotifyError("Es ist kein SMTP-Server konfiguriert")
    sender = smtp.from_address or smtp.username
    if not sender:
        raise NotifyError("Es ist keine Absenderadresse konfiguriert")

    message = EmailMessage()
    message["From"] = sender
    message["To"] = to_address
    message["Subject"] = subject
    message["Auto-Submitted"] = "auto-replied"  # verhindert Mailschleifen (RFC 3834)
    message.set_content(body)

    context = _context(smtp.verify_tls)
    try:
        if smtp.security == "ssl":
            client: smtplib.SMTP = smtplib.SMTP_SSL(smtp.host, smtp.port, timeout=60, context=context)
        else:
            client = smtplib.SMTP(smtp.host, smtp.port, timeout=60)
            if smtp.security == "starttls":
                client.starttls(context=context)
        try:
            if smtp.username:
                client.login(smtp.username, smtp.password)
            client.send_message(message)
        finally:
            try:
                client.quit()
            except smtplib.SMTPException:  # pragma: no cover
                client.close()
    except (OSError, smtplib.SMTPException, ssl.SSLError) as error:
        raise NotifyError(f"Statusmeldung an {to_address} fehlgeschlagen: {error}") from error


def notify_success(config: AppConfig, to_address: str, number: str, subject: str, pages: int) -> None:
    """Quittung ueber einen erfolgreichen Versand."""
    if not (config.smtp.enabled and config.smtp.notify_sender and to_address):
        return
    body = (
        "Ihr Fax wurde erfolgreich uebergeben.\n\n"
        f"Empfaenger : {number}\n"
        f"Betreff    : {subject}\n"
        f"Seiten     : {pages}\n\n"
        "Hinweis: Die Bestaetigung bezieht sich auf die Uebergabe an das "
        "Faxsystem. Eine Zustellgarantie ist damit nicht verbunden.\n\n"
        "-- \nAutomatisch erzeugt von mail2fax"
    )
    _try(config, to_address, f"Fax an {number} versendet", body)


def notify_failure(config: AppConfig, to_address: str, number: str, subject: str, reason: str) -> None:
    """Meldung ueber einen fehlgeschlagenen oder abgelehnten Auftrag."""
    if not (config.smtp.enabled and to_address):
        return
    body = (
        "Ihr Fax konnte NICHT versendet werden.\n\n"
        f"Empfaenger : {number or '(nicht ermittelbar)'}\n"
        f"Betreff    : {subject}\n"
        f"Grund      : {reason}\n\n"
        "-- \nAutomatisch erzeugt von mail2fax"
    )
    if config.smtp.notify_sender:
        _try(config, to_address, f"Fax an {number or 'unbekannt'} fehlgeschlagen", body)
    if config.smtp.admin_address and config.smtp.admin_address != to_address:
        _try(
            config,
            config.smtp.admin_address,
            f"[mail2fax] Fehlgeschlagener Auftrag ({number or 'unbekannt'})",
            body + f"\nUrspruenglicher Absender: {to_address}\n",
        )


def _try(config: AppConfig, to_address: str, subject: str, body: str) -> None:
    """Statusmeldungen duerfen den Betrieb nie zum Scheitern bringen."""
    try:
        send_mail(config.smtp, to_address, subject, body)
    except NotifyError as error:
        LOGGER.warning("%s", error)
