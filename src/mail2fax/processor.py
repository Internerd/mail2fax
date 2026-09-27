"""Verarbeitungskette: E-Mail pruefen, Dokumente erzeugen, Fax versenden."""

from __future__ import annotations

import logging
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from . import notify
from .config import AppConfig
from .fax import FaxError, get_backend
from .mailbox import MailMessage
from .paths import SPOOL_DIR
from .render import Document, RenderError, build_mail_header, prepare_attachment, text_to_pdf
from .rules import (
    Number,
    RuleError,
    check_number_allowed,
    check_sender_allowed,
    extract_number,
    normalise_address,
)
from .storage import (
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_REJECTED,
    STATUS_SENDING,
    STATUS_SENT,
    Job,
    Storage,
)

LOGGER = logging.getLogger(__name__)

_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class RejectedError(Exception):
    """Die Nachricht wird nicht verarbeitet (Regelverstoss)."""


@dataclass
class Prepared:
    """Ergebnis der Vorbereitung einer Nachricht."""

    number: Number
    sender: str
    subject: str
    documents: list[Document]
    workdir: Path

    @property
    def pages(self) -> int:
        return sum(document.pages for document in self.documents)


def _safe_name(name: str) -> str:
    """Macht einen Dateinamen fuer das Spool-Verzeichnis unbedenklich."""
    cleaned = _UNSAFE_NAME.sub("_", Path(name).name).strip("._") or "datei"
    return cleaned[:120]


def check_rate_limit(config: AppConfig, storage: Storage, sender: str) -> None:
    """Prueft die Mengenbegrenzung (Schutz vor Schleifen und Missbrauch)."""
    security = config.security
    since = time.time() - 3600
    if security.rate_limit_per_hour > 0:
        total = storage.count_recent(since=since)
        if total >= security.rate_limit_per_hour:
            raise RejectedError(
                f"Mengenbegrenzung erreicht: {total} Faxe in der letzten Stunde "
                f"(erlaubt: {security.rate_limit_per_hour})"
            )
    if security.rate_limit_per_sender_per_hour > 0 and sender:
        per_sender = storage.count_recent(since=since, sender=sender)
        if per_sender >= security.rate_limit_per_sender_per_hour:
            raise RejectedError(
                f"Mengenbegrenzung fuer {sender} erreicht: {per_sender} Faxe in der "
                f"letzten Stunde (erlaubt: {security.rate_limit_per_sender_per_hour})"
            )


def build_documents(config: AppConfig, message: MailMessage, workdir: Path) -> list[Document]:
    """Erzeugt die zu faxenden PDF-Dokumente.

    Regel laut Anforderung: Gibt es einen verwertbaren Anhang, wird dieser
    gefaxt. Andernfalls wird der Mailtext selbst zu einer Faxseite.
    """
    content = config.content
    workdir.mkdir(parents=True, exist_ok=True)
    allowed = {extension.lower() for extension in content.allowed_extensions}
    if content.convert_office:
        allowed |= {extension.lower() for extension in content.office_extensions}

    limit_bytes = content.max_attachment_size_mb * 1024 * 1024
    documents: list[Document] = []
    skipped: list[str] = []

    for attachment in message.attachments:
        suffix = Path(attachment.filename).suffix.lower().lstrip(".")
        if suffix not in allowed:
            skipped.append(f"{attachment.filename} (Dateityp nicht zugelassen)")
            continue
        if attachment.size > limit_bytes:
            skipped.append(
                f"{attachment.filename} ({attachment.size // 1024} KiB > "
                f"{content.max_attachment_size_mb} MiB)"
            )
            continue

        source = workdir / _safe_name(attachment.filename)
        source.write_bytes(attachment.content)
        try:
            documents.append(prepare_attachment(source, attachment.filename, workdir, content))
        except RenderError as error:
            skipped.append(f"{attachment.filename}: {error}")
            continue
        if content.attachment_mode == "first":
            break

    if skipped:
        LOGGER.info("Nicht verwendete Anhaenge: %s", "; ".join(skipped))

    if not documents:
        header = (
            build_mail_header(message.sender, message.subject, message.date)
            if content.include_mail_header
            else None
        )
        body = message.text
        if skipped:
            body += "\n\n---\nNicht uebertragene Anhaenge:\n" + "\n".join(
                f"- {entry}" for entry in skipped
            )
        documents.append(
            text_to_pdf(
                body,
                workdir / "nachricht.pdf",
                header=header,
                title=message.subject or "Nachricht",
            )
        )

    if content.max_pages > 0:
        pages = sum(document.pages for document in documents)
        if pages > content.max_pages:
            raise RejectedError(
                f"Das Fax haette {pages} Seiten - erlaubt sind hoechstens "
                f"{content.max_pages}"
            )
    return documents


def prepare(config: AppConfig, storage: Storage, message: MailMessage) -> Prepared:
    """Prueft eine Nachricht vollstaendig und bereitet die Dokumente auf.

    Wirft :class:`RejectedError`, wenn die Nachricht nicht gefaxt werden darf.
    """
    try:
        sender = check_sender_allowed(message.sender, config.security)
        number = extract_number(message.subject, config.security)
        check_number_allowed(number, config.security)
    except RuleError as error:
        raise RejectedError(str(error)) from error

    check_rate_limit(config, storage, sender)

    workdir = SPOOL_DIR / f"{int(time.time())}-{abs(hash(message.uid or message.subject)) % 10**8}"
    try:
        documents = build_documents(config, message, workdir)
    except RejectedError:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    except RenderError as error:
        shutil.rmtree(workdir, ignore_errors=True)
        raise RejectedError(f"Dokument konnte nicht aufbereitet werden: {error}") from error

    return Prepared(
        number=number,
        sender=sender,
        subject=message.subject,
        documents=documents,
        workdir=workdir,
    )


def enqueue(config: AppConfig, storage: Storage, message: MailMessage) -> Job:
    """Nimmt eine Nachricht an oder legt sie als abgelehnt ab."""
    sender_address = normalise_address(message.sender)
    try:
        prepared = prepare(config, storage, message)
    except RejectedError as error:
        LOGGER.warning("Nachricht abgelehnt (%s): %s", sender_address or "?", error)
        job = storage.create_job(
            sender=sender_address,
            subject=message.subject,
            number="",
            message_id=message.message_id,
            status=STATUS_REJECTED,
            error=str(error),
            backend=config.fax.backend,
        )
        storage.log_event(f"Abgelehnt: {error}", job_id=job.id, level="warning")
        notify.report_rejection(config, sender_address, message.subject, str(error))
        return job

    job = storage.create_job(
        sender=prepared.sender,
        subject=prepared.subject,
        number=prepared.number.e164,
        documents=[str(document.path) for document in prepared.documents],
        message_id=message.message_id,
        pages=prepared.pages,
        backend=config.fax.backend,
    )
    storage.log_event(
        f"Auftrag angenommen: {prepared.pages} Seite(n) an {prepared.number.e164}",
        job_id=job.id,
    )
    LOGGER.info(
        "Auftrag #%s angenommen: %s -> %s (%s Seiten)",
        job.id, prepared.sender, prepared.number.e164, prepared.pages,
    )
    return job


def send_job(config: AppConfig, storage: Storage, job: Job) -> bool:
    """Fuehrt einen Versandversuch aus und pflegt den Auftragsstatus."""
    from .rules import Number as NumberType

    storage.update_job(job.id, status=STATUS_SENDING, attempts=job.attempts + 1)
    attempt = job.attempts + 1
    documents = [Path(path) for path in job.documents]
    missing = [document for document in documents if not document.exists()]
    if missing:
        reason = "Dokumente sind nicht mehr vorhanden: " + ", ".join(d.name for d in missing)
        _fail(config, storage, job, reason, permanent=True)
        return False

    result = None
    try:
        if config.fax.dry_run:
            detail = "Testbetrieb (dry-run) - es wurde nichts gesendet"
        else:
            backend = get_backend(config)
            result = backend.send(NumberType(job.number), documents, subject=job.subject)
            if not result.success:
                raise FaxError(result.detail or "Backend meldet Misserfolg")
            detail = result.detail or "Erfolgreich uebergeben"
    except FaxError as error:
        _fail(config, storage, job, str(error), permanent=error.permanent, attempt=attempt)
        return False
    except Exception as error:
        LOGGER.exception("Unerwarteter Fehler beim Versand von Auftrag #%s", job.id)
        _fail(config, storage, job, f"Unerwarteter Fehler: {error}", attempt=attempt)
        return False

    felder: dict[str, object] = {"status": STATUS_SENT, "error": None}
    if result is not None:
        felder.update(
            confirmed=1 if result.confirmed else 0,
            pages_sent=result.pages_sent,
            rate=result.rate,
            resolution=result.resolution,
            remote_station=result.remote_station,
            duration=result.duration,
        )
    storage.update_job(job.id, **felder)

    bestaetigt = bool(result and result.confirmed)
    storage.log_event(
        f"{'Uebertragung bestaetigt' if bestaetigt else 'Uebergeben (ohne Quittung)'}: {detail}",
        job_id=job.id,
    )
    LOGGER.info(
        "Auftrag #%s an %s %s",
        job.id,
        job.number,
        "uebertragen und quittiert" if bestaetigt else "uebergeben (keine Quittung)",
    )

    aktuell = storage.get_job(job.id) or job
    if notify.report_transmission(config, aktuell):
        storage.update_job(job.id, reported_at=time.time())
        storage.log_event("Sendebericht an den Absender versendet", job_id=job.id)

    if config.delete_documents_after_send:
        cleanup_documents(job)
    return True


def _fail(
    config: AppConfig,
    storage: Storage,
    job: Job,
    reason: str,
    *,
    permanent: bool = False,
    attempt: int | None = None,
) -> None:
    """Markiert einen Versuch als fehlgeschlagen und plant ggf. eine Wiederholung."""
    attempts = attempt if attempt is not None else job.attempts + 1
    remaining = config.fax.max_attempts - attempts
    if permanent or remaining <= 0:
        storage.update_job(job.id, status=STATUS_FAILED, error=reason)
        storage.log_event(f"Endgueltig fehlgeschlagen: {reason}", job_id=job.id, level="error")
        LOGGER.error("Auftrag #%s endgueltig fehlgeschlagen: %s", job.id, reason)
        aktuell = storage.get_job(job.id) or job
        if notify.report_failure(config, aktuell, reason=reason, final=True):
            storage.update_job(job.id, reported_at=time.time())
            storage.log_event("Fehlerbericht an den Absender versendet", job_id=job.id)
        return

    delay = config.fax.retry_delay * (2 ** (attempts - 1))
    storage.update_job(
        job.id,
        status=STATUS_QUEUED,
        error=reason,
        next_attempt_at=time.time() + delay,
    )
    storage.log_event(
        f"Versuch {attempts} fehlgeschlagen ({reason}); naechster Versuch in {delay}s",
        job_id=job.id,
        level="warning",
    )
    LOGGER.warning(
        "Auftrag #%s: Versuch %s fehlgeschlagen (%s), Wiederholung in %ss",
        job.id, attempts, reason, delay,
    )


def cleanup_documents(job: Job) -> None:
    """Loescht die Faxdateien eines Auftrags (Datenminimierung)."""
    directories = set()
    for path_text in job.documents:
        path = Path(path_text)
        try:
            if path.is_file():
                path.unlink()
            if path.parent.is_relative_to(SPOOL_DIR) and path.parent != SPOOL_DIR:
                directories.add(path.parent)
        except OSError as error:  # pragma: no cover
            LOGGER.warning("Datei %s konnte nicht geloescht werden: %s", path, error)
    for directory in directories:
        shutil.rmtree(directory, ignore_errors=True)
