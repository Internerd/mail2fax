"""Sende- und Fehlerberichte per E-Mail an den Absender.

Zwei Regeln bestimmen dieses Modul:

1. **Berichte gehen ausschliesslich an Absender auf der Whitelist.**
   Der ``From``-Header einer E-Mail ist fälschbar. Wuerde mail2fax auf jede
   beliebige Nachricht antworten, liesse sich der Dienst als Absender fremder
   Post missbrauchen (Rueckstreuung) - und ein Fremder erfuehre, dass die
   Adresse ueberhaupt existiert. Die Pruefung sitzt deshalb hier, an der
   einzigen Stelle, die Post nach draussen gibt.

2. **Ein Sendebericht behauptet eine Uebertragung nur, wenn sie quittiert
   ist.** Bei Fax heisst das: Das empfangende Geraet hat am Ende der
   T.30-Uebertragung den vollstaendigen Empfang bestaetigt. Versandwege, die
   einen Auftrag nur weiterreichen, koennen das nicht leisten; ihre Berichte
   sagen das ausdruecklich.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
import time
from datetime import datetime
from email.message import EmailMessage

from .config import AppConfig, SmtpConfig
from .rules import is_sender_allowed, normalise_address
from .storage import Job

LOGGER = logging.getLogger(__name__)


class NotifyError(Exception):
    """Fehler beim Versand einer Nachricht."""


# -- Versand ---------------------------------------------------------------


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
    message["X-Auto-Response-Suppress"] = "All"
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
        raise NotifyError(f"Nachricht an {to_address} fehlgeschlagen: {error}") from error


# -- Berechtigung ----------------------------------------------------------


def may_report_to(config: AppConfig, address: str) -> bool:
    """Prueft, ob an diese Adresse ein Bericht gehen darf.

    Nur Absender auf der Whitelist erhalten Post. Ohne diese Pruefung wuerde
    mail2fax auf beliebige - und fälschbare - Adressen antworten.
    """
    ziel = normalise_address(address) or (address or "").strip().lower()
    if not ziel or "@" not in ziel:
        return False
    if not config.smtp.enabled or not config.smtp.notify_sender:
        return False
    if not is_sender_allowed(ziel, config.security):
        LOGGER.info(
            "Kein Bericht an %s - die Adresse steht nicht auf der Absender-Whitelist", ziel
        )
        return False
    return True


def _deliver(config: AppConfig, address: str, subject: str, body: str) -> bool:
    """Versendet einen Bericht; Fehler beenden nie den Betrieb."""
    try:
        send_mail(config.smtp, address, subject, body)
    except NotifyError as error:
        LOGGER.warning("%s", error)
        return False
    LOGGER.info("Bericht an %s versendet: %s", address, subject)
    return True


# -- Bausteine der Berichte ------------------------------------------------

FOOTER = "-- \nAutomatisch erzeugt von mail2fax"


def _zeile(bezeichnung: str, wert: object) -> str:
    return f"  {bezeichnung:<22}: {wert}"


def _zeitpunkt(wert: float | None = None) -> str:
    return datetime.fromtimestamp(wert or time.time()).strftime("%d.%m.%Y um %H:%M:%S")


def _backend_name(name: str) -> str:
    from .fax import BACKEND_LABELS

    return BACKEND_LABELS.get(name, name or "unbekannt")


def _auftragsblock(job: Job) -> list[str]:
    zeilen = [
        "",
        "Ihre Nachricht",
        _zeile("Betreff", job.subject or "(ohne Betreff)"),
        _zeile("Eingegangen", _zeitpunkt(job.created_at)),
        _zeile("Auftragsnummer", f"#{job.id}"),
    ]
    return zeilen


def build_transmission_report(config: AppConfig, job: Job) -> tuple[str, str]:
    """Erzeugt Betreff und Text des Sendeberichts.

    Getrennt vom Versand, damit sich der Inhalt pruefen laesst.
    """
    seiten = job.pages_sent if job.pages_sent is not None else job.pages

    if job.confirmed:
        betreff = f"Sendebericht: Fax an {job.number} uebertragen"
        if seiten:
            betreff += f" ({seiten} Seite{'n' if seiten != 1 else ''})"
        kopf = [
            "SENDEBERICHT",
            "",
            "Das Fax wurde uebertragen und von der Gegenstelle quittiert.",
            "",
        ]
    else:
        betreff = f"Fax an {job.number} uebergeben - ohne Uebertragungsnachweis"
        kopf = [
            "UEBERGABEBESTAETIGUNG",
            "",
            f"Der Auftrag wurde an '{_backend_name(job.backend)}' uebergeben.",
            "Eine Quittung der Gegenstelle liegt NICHT vor: Dieser Versandweg",
            "liefert keine. Ob das Fax angekommen ist, ist damit nicht belegt.",
            "",
        ]

    zeilen = [*kopf, "Uebertragung", _zeile("Empfaenger", job.number)]
    if job.remote_station:
        zeilen.append(_zeile("Gegenstelle", job.remote_station))
    if seiten is not None:
        if job.pages and job.pages_sent is not None and job.pages_sent != job.pages:
            zeilen.append(_zeile("Seiten", f"{job.pages_sent} von {job.pages}"))
        else:
            zeilen.append(_zeile("Seiten", seiten))
    if job.resolution:
        zeilen.append(_zeile("Aufloesung", job.resolution))
    if job.rate:
        zeilen.append(_zeile("Uebertragungsrate", f"{job.rate} bit/s"))
    if job.duration is not None:
        zeilen.append(_zeile("Dauer", f"{job.duration:.0f} s"))
    zeilen.append(_zeile("Abgeschlossen", _zeitpunkt(job.updated_at)))
    zeilen.append(_zeile("Versandweg", _backend_name(job.backend)))
    if job.attempts > 1:
        zeilen.append(_zeile("Zustellversuche", job.attempts))

    zeilen += _auftragsblock(job)

    if job.confirmed:
        zeilen += [
            "",
            "Die Bestaetigung stammt vom empfangenden Geraet: Es hat am Ende der",
            "Uebertragung den vollstaendigen Empfang aller Seiten quittiert.",
            "Ein Sendebericht belegt die Uebertragung, nicht die Kenntnisnahme",
            "durch den Empfaenger.",
        ]
    else:
        zeilen += [
            "",
            "Sofern Ihr Anbieter eigene Bestaetigungen versendet, ist dessen",
            "Nachricht der Nachweis - nicht diese.",
        ]

    zeilen += ["", FOOTER]
    return betreff, "\n".join(zeilen)


def build_failure_report(
    config: AppConfig,
    job: Job,
    *,
    reason: str,
    final: bool,
) -> tuple[str, str]:
    """Erzeugt Betreff und Text des Fehlerberichts."""
    if final:
        betreff = f"Fehlerbericht: Fax an {job.number or 'unbekannt'} fehlgeschlagen"
        kopf = [
            "FEHLERBERICHT",
            "",
            "Das Fax konnte NICHT versendet werden. Es werden keine weiteren",
            "Versuche unternommen.",
            "",
        ]
    else:
        betreff = f"Fax an {job.number or 'unbekannt'}: Versuch fehlgeschlagen"
        kopf = [
            "ZWISCHENBERICHT",
            "",
            "Ein Zustellversuch ist fehlgeschlagen. mail2fax versucht es erneut.",
            "",
        ]

    zeilen = [
        *kopf,
        "Fehler",
        _zeile("Empfaenger", job.number or "(nicht ermittelbar)"),
        _zeile("Grund", reason),
        _zeile("Versuche", f"{job.attempts} von {config.fax.max_attempts}"),
        _zeile("Versandweg", _backend_name(job.backend)),
        _zeile("Zeitpunkt", _zeitpunkt(job.updated_at)),
    ]
    if job.pages_sent:
        zeilen.append(_zeile("Bereits uebertragen", f"{job.pages_sent} Seite(n)"))
    if not final and job.next_attempt_at:
        zeilen.append(_zeile("Naechster Versuch", _zeitpunkt(job.next_attempt_at)))

    zeilen += _auftragsblock(job)
    if final:
        zeilen += [
            "",
            "Bitte pruefen Sie die Zielrufnummer im Betreff und senden Sie die",
            "Nachricht anschliessend erneut.",
        ]
    zeilen += ["", FOOTER]
    return betreff, "\n".join(zeilen)


def build_rejection_report(subject: str, reason: str) -> tuple[str, str]:
    """Erzeugt Betreff und Text fuer eine abgelehnte Nachricht."""
    zeilen = [
        "FEHLERBERICHT",
        "",
        "Ihre Nachricht wurde nicht als Fax versendet.",
        "",
        "Grund",
        f"  {reason}",
        "",
        "Ihre Nachricht",
        _zeile("Betreff", subject or "(ohne Betreff)"),
        _zeile("Eingegangen", _zeitpunkt()),
        "",
        "So loesen Sie ein Fax aus: Die Zielrufnummer gehoert in den Betreff,",
        "zum Beispiel '+49301234567'. Liegt ein verwertbarer Anhang bei, wird",
        "dieser gefaxt, sonst der Text der Nachricht.",
        "",
        FOOTER,
    ]
    return "Fax abgelehnt", "\n".join(zeilen)


# -- Oeffentliche Einstiegspunkte ------------------------------------------


def report_transmission(config: AppConfig, job: Job) -> bool:
    """Sendebericht nach einem erfolgreichen Versand."""
    if not job.confirmed and not config.smtp.report_unconfirmed:
        LOGGER.info(
            "Kein Bericht fuer Auftrag #%s - es liegt keine Quittung der "
            "Gegenstelle vor und unbestaetigte Berichte sind abgeschaltet",
            job.id,
        )
        return False
    if not may_report_to(config, job.sender):
        return False
    betreff, text = build_transmission_report(config, job)
    return _deliver(config, job.sender, betreff, text)


def report_failure(config: AppConfig, job: Job, *, reason: str, final: bool = True) -> bool:
    """Fehlerbericht zu einem Auftrag."""
    gesendet = False
    if may_report_to(config, job.sender):
        betreff, text = build_failure_report(config, job, reason=reason, final=final)
        gesendet = _deliver(config, job.sender, betreff, text)

    # Der Administrator erfaehrt auch von Auftraegen, deren Absender keine
    # Post bekommt - er hat die Anlage zu betreuen.
    if final and config.smtp.enabled and config.smtp.admin_address:
        betreff, text = build_failure_report(config, job, reason=reason, final=final)
        _deliver(
            config,
            config.smtp.admin_address,
            f"[mail2fax] {betreff}",
            text + f"\n\nUrspruenglicher Absender: {job.sender or 'unbekannt'}\n",
        )
    return gesendet


def report_rejection(config: AppConfig, sender: str, subject: str, reason: str) -> bool:
    """Fehlerbericht fuer eine abgelehnte Nachricht.

    Wurde die Nachricht abgelehnt, weil der Absender nicht auf der Whitelist
    steht, geht bewusst keine Antwort hinaus - sonst wuerde mail2fax auf
    fremde, moeglicherweise gefaelschte Adressen antworten.
    """
    if not may_report_to(config, sender):
        return False
    betreff, text = build_rejection_report(subject, reason)
    return _deliver(config, sender, betreff, text)
