"""Faxversand ueber einen Fax-per-E-Mail-Dienst.

Viele Telefonanlagen und Anbieter (z. B. sipgate, Placetel, 3CX, aber auch
Inhouse-Gateways) nehmen Faxe per E-Mail entgegen: Die Zielrufnummer steht in
der Empfaengeradresse, das Dokument im Anhang.

Datenschutzhinweis: Bei externen Anbietern verlassen die Faxinhalte das eigene
Netz. Dafuer ist in der Regel ein Auftragsverarbeitungsvertrag nach Art. 28
DSGVO erforderlich - siehe docs/DATENSCHUTZ.md.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from ..config import AppConfig, MailGatewayConfig, SmtpConfig
from ..rules import Number
from .base import FaxBackend, FaxError, FaxResult

LOGGER = logging.getLogger(__name__)


class MailGatewayBackend(FaxBackend):
    """Versendet das Fax als E-Mail an ein Fax-Gateway."""

    name = "Fax per E-Mail (Gateway/Provider)"

    def __init__(self, config: AppConfig) -> None:
        super().__init__(config)
        self.settings: MailGatewayConfig = config.fax.mailgateway

    def _smtp_settings(self) -> SmtpConfig:
        """Eigene SMTP-Daten des Gateways oder der globale Postausgang."""
        if self.settings.host:
            return SmtpConfig(
                enabled=True,
                host=self.settings.host,
                port=self.settings.port,
                security=self.settings.security,
                username=self.settings.username,
                password=self.settings.password,
                from_address=self.settings.from_address or self.config.smtp.from_address,
                verify_tls=self.settings.verify_tls,
            )
        smtp = self.config.smtp
        if not smtp.host:
            raise FaxError(
                "Fuer das Fax-Gateway ist kein SMTP-Server hinterlegt "
                "(weder beim Gateway noch global)",
                permanent=True,
            )
        return smtp

    def _recipient(self, number: Number) -> str:
        country = self.config.security.default_country_code
        try:
            return self.settings.recipient_template.format(
                number=number.e164,
                number_digits=number.digits,
                number_national=number.formatted_national(country),
            )
        except KeyError as error:
            raise FaxError(
                f"Unbekannter Platzhalter {error} in der Empfaengervorlage", permanent=True
            ) from error

    def send(self, number: Number, documents: list[Path], *, subject: str = "") -> FaxResult:
        if not documents:
            raise FaxError("Es liegen keine Dokumente zum Versand vor", permanent=True)

        smtp = self._smtp_settings()
        recipient = self._recipient(number)
        if "@" not in recipient:
            raise FaxError(
                f"Aus der Vorlage entstand keine gueltige Adresse: {recipient}", permanent=True
            )
        sender = smtp.from_address or smtp.username
        if not sender:
            raise FaxError("Fuer das Fax-Gateway ist keine Absenderadresse hinterlegt", permanent=True)

        message = EmailMessage()
        message["From"] = sender
        message["To"] = recipient
        message["Subject"] = self.settings.subject_template.format(
            number=number.e164, subject=subject or "Fax"
        )
        message.set_content(
            self.settings.body_template.format(number=number.e164, subject=subject or "")
        )
        for document in documents:
            message.add_attachment(
                document.read_bytes(),
                maintype="application",
                subtype="pdf",
                filename=document.name,
            )

        _send_via_smtp(smtp, message)
        return FaxResult(success=True, detail=f"Fax als E-Mail an {recipient} uebergeben")

    def test(self) -> str:
        smtp = self._smtp_settings()
        with _connect(smtp):
            pass
        return f"SMTP-Verbindung zu {smtp.host}:{smtp.port} erfolgreich."


def _context(verify_tls: bool) -> ssl.SSLContext:
    context = ssl.create_default_context()
    if not verify_tls:
        LOGGER.warning("TLS-Zertifikatspruefung fuer SMTP ist deaktiviert!")
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def _connect(smtp: SmtpConfig) -> smtplib.SMTP:
    context = _context(smtp.verify_tls)
    try:
        if smtp.security == "ssl":
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                smtp.host, smtp.port, timeout=60, context=context
            )
        else:
            client = smtplib.SMTP(smtp.host, smtp.port, timeout=60)
            if smtp.security == "starttls":
                client.starttls(context=context)
        if smtp.username:
            client.login(smtp.username, smtp.password)
    except (OSError, smtplib.SMTPException, ssl.SSLError) as error:
        raise FaxError(f"SMTP-Verbindung zu {smtp.host}:{smtp.port} fehlgeschlagen: {error}") from error
    return client


def _send_via_smtp(smtp: SmtpConfig, message: EmailMessage) -> None:
    client = _connect(smtp)
    try:
        client.send_message(message)
    except smtplib.SMTPException as error:
        permanent = isinstance(error, smtplib.SMTPRecipientsRefused | smtplib.SMTPSenderRefused)
        raise FaxError(f"Versand ueber SMTP fehlgeschlagen: {error}", permanent=permanent) from error
    finally:
        try:
            client.quit()
        except smtplib.SMTPException:  # pragma: no cover
            client.close()
