"""IMAP-Zugriff auf das ueberwachte Postfach."""

from __future__ import annotations

import email
import imaplib
import logging
import re
import ssl
from dataclasses import dataclass, field
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime
from typing import Any

from .config import ImapConfig

LOGGER = logging.getLogger(__name__)

#: IMAP erlaubt keine beliebigen Zeichen in Ordnernamen - grob absichern.
_FOLDER_SAFE = re.compile(r'^[^"\r\n\x00]{1,255}$')


class MailboxError(Exception):
    """Fehler beim Zugriff auf das Postfach."""


@dataclass
class Attachment:
    """Ein Anhang einer E-Mail."""

    filename: str
    content: bytes

    @property
    def size(self) -> int:
        return len(self.content)


@dataclass
class MailMessage:
    """Eine geladene E-Mail in aufbereiteter Form."""

    uid: str
    message_id: str | None
    sender: str
    subject: str
    date: str
    text: str
    attachments: list[Attachment] = field(default_factory=list)
    raw_size: int = 0


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value))).strip()
    except Exception:  # pragma: no cover - defekte Header
        return value.strip()


def _body_text(message: Message) -> str:
    """Extrahiert den Nachrichtentext; bevorzugt text/plain."""
    from .render import html_to_text

    plain_parts: list[str] = []
    html_parts: list[str] = []

    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue
        disposition = (part.get_content_disposition() or "").lower()
        if disposition == "attachment":
            continue
        content_type = part.get_content_type()
        if content_type not in ("text/plain", "text/html"):
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):  # pragma: no cover - exotische Charsets
            text = payload.decode("utf-8", errors="replace")
        if content_type == "text/plain":
            plain_parts.append(text)
        else:
            html_parts.append(text)

    if plain_parts:
        return "\n".join(plain_parts).strip()
    if html_parts:
        return html_to_text("\n".join(html_parts))
    return ""


def _attachments(message: Message) -> list[Attachment]:
    result: list[Attachment] = []
    for index, part in enumerate(message.walk(), start=1):
        if part.get_content_maintype() == "multipart":
            continue
        disposition = (part.get_content_disposition() or "").lower()
        filename = _decode(part.get_filename())
        if disposition != "attachment" and not filename:
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        if not filename:
            extension = part.get_content_subtype() or "bin"
            filename = f"anhang-{index}.{extension}"
        # Pfadanteile aus dem Dateinamen entfernen (Schutz vor Path Traversal).
        filename = filename.replace("\\", "/").split("/")[-1].strip() or f"anhang-{index}.bin"
        result.append(Attachment(filename=filename, content=payload))
    return result


def parse_message(raw: bytes, uid: str = "") -> MailMessage:
    """Wandelt eine Rohnachricht in ein :class:`MailMessage`."""
    message = email.message_from_bytes(raw)
    date_header = message.get("Date", "")
    try:
        date_text = parsedate_to_datetime(date_header).strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError):
        date_text = _decode(date_header)
    return MailMessage(
        uid=uid,
        message_id=(message.get("Message-ID") or "").strip() or None,
        sender=_decode(message.get("From")),
        subject=_decode(message.get("Subject")),
        date=date_text,
        text=_body_text(message),
        attachments=_attachments(message),
        raw_size=len(raw),
    )


class Mailbox:
    """Kontextmanager fuer eine IMAP-Verbindung."""

    def __init__(self, config: ImapConfig) -> None:
        self.config = config
        self._imap: imaplib.IMAP4 | None = None

    def __enter__(self) -> Mailbox:
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def imap(self) -> imaplib.IMAP4:
        if self._imap is None:
            raise MailboxError("Keine IMAP-Verbindung aufgebaut")
        return self._imap

    def _ssl_context(self) -> ssl.SSLContext:
        context = ssl.create_default_context()
        if not self.config.verify_tls:
            LOGGER.warning(
                "TLS-Zertifikatspruefung fuer IMAP ist deaktiviert - nur fuer Testsysteme!"
            )
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        return context

    def connect(self) -> None:
        config = self.config
        if not config.host or not config.username:
            raise MailboxError("IMAP ist nicht vollstaendig konfiguriert")
        try:
            if config.security == "ssl":
                self._imap = imaplib.IMAP4_SSL(
                    config.host, config.port, ssl_context=self._ssl_context(), timeout=30
                )
            else:
                self._imap = imaplib.IMAP4(config.host, config.port, timeout=30)
                if config.security == "starttls":
                    self._imap.starttls(self._ssl_context())
            self._imap.login(config.username, config.password)
        except (OSError, imaplib.IMAP4.error, ssl.SSLError) as error:
            raise MailboxError(f"IMAP-Verbindung fehlgeschlagen: {error}") from error

    def close(self) -> None:
        if self._imap is None:
            return
        try:
            if self._imap.state == "SELECTED":
                self._imap.close()
            self._imap.logout()
        except (OSError, imaplib.IMAP4.error):  # pragma: no cover - Verbindungsabbruch
            pass
        finally:
            self._imap = None

    def _check(self, result: tuple[str, Any], action: str) -> list[Any]:
        status, data = result
        if status != "OK":
            detail = data[0] if data else b""
            if isinstance(detail, bytes):
                detail = detail.decode("utf-8", "replace")
            raise MailboxError(f"{action} fehlgeschlagen: {detail}")
        return list(data)

    def select_folder(self, folder: str | None = None) -> int:
        """Waehlt den Ordner aus und liefert die Anzahl der Nachrichten."""
        name = folder or self.config.folder or "INBOX"
        if not _FOLDER_SAFE.match(name):
            raise MailboxError(f"Ungueltiger Ordnername: {name!r}")
        data = self._check(self.imap.select(f'"{name}"'), f"Auswahl von {name}")
        try:
            return int(data[0])
        except (TypeError, ValueError, IndexError):  # pragma: no cover
            return 0

    def list_folders(self) -> list[str]:
        status, data = self.imap.list()
        if status != "OK":
            return []
        folders: list[str] = []
        for entry in data:
            if not isinstance(entry, bytes):
                continue
            text = entry.decode("utf-8", "replace")
            match = re.search(r'"(?:[^"]*)"\s+"?([^"]+)"?$', text)
            if match:
                folders.append(match.group(1))
        return folders

    def unseen_uids(self) -> list[str]:
        """UIDs aller ungelesenen Nachrichten im gewaehlten Ordner."""
        self.select_folder()
        data = self._check(self.imap.uid("SEARCH", None, "UNSEEN"), "Suche nach neuen Mails")
        raw = data[0] or b""
        if isinstance(raw, bytes):
            raw = raw.decode("ascii", "replace")
        return [uid for uid in str(raw).split() if uid.isdigit()]

    def fetch(self, uid: str) -> MailMessage:
        """Laedt eine Nachricht, ohne sie als gelesen zu markieren."""
        data = self._check(
            self.imap.uid("FETCH", uid, "(BODY.PEEK[])"), f"Laden der Nachricht {uid}"
        )
        for item in data:
            if isinstance(item, tuple) and len(item) > 1 and isinstance(item[1], bytes):
                return parse_message(item[1], uid=uid)
        raise MailboxError(f"Nachricht {uid} konnte nicht geladen werden")

    def message_size(self, uid: str) -> int:
        """Groesse einer Nachricht in Byte (vor dem Laden pruefbar)."""
        data = self._check(
            self.imap.uid("FETCH", uid, "(RFC822.SIZE)"), f"Groesse der Nachricht {uid}"
        )
        for item in data:
            text = item.decode("ascii", "replace") if isinstance(item, bytes) else str(item)
            match = re.search(r"RFC822\.SIZE\s+(\d+)", text)
            if match:
                return int(match.group(1))
        return 0

    def mark_seen(self, uid: str) -> None:
        self.imap.uid("STORE", uid, "+FLAGS", "(\\Seen)")

    def move(self, uid: str, folder: str) -> None:
        """Verschiebt eine Nachricht; legt den Zielordner bei Bedarf an."""
        if not folder or not _FOLDER_SAFE.match(folder):
            raise MailboxError(f"Ungueltiger Zielordner: {folder!r}")
        self.imap.create(f'"{folder}"')  # Fehler ist unkritisch (Ordner existiert bereits)
        status, _ = self.imap.uid("MOVE", uid, f'"{folder}"')
        if status != "OK":
            # Aeltere Server kennen MOVE nicht (RFC 6851) - COPY + Loeschmarke.
            self._check(self.imap.uid("COPY", uid, f'"{folder}"'), "Kopieren der Nachricht")
            self.imap.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
            self.imap.expunge()

    def delete(self, uid: str) -> None:
        self.imap.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
        self.imap.expunge()

    def finish_message(self, uid: str, *, rejected: bool = False) -> None:
        """Schliesst die Verarbeitung gemaess der konfigurierten Nachbehandlung ab."""
        config = self.config
        if rejected and config.rejected_folder and config.processed_action == "move":
            self.mark_seen(uid)
            self.move(uid, config.rejected_folder)
            return
        if config.processed_action == "delete" and not rejected:
            self.delete(uid)
        elif config.processed_action == "move" and not rejected:
            self.mark_seen(uid)
            self.move(uid, config.processed_folder)
        else:
            self.mark_seen(uid)


def test_connection(config: ImapConfig) -> str:
    """Verbindungstest fuer die Weboberflaeche."""
    with Mailbox(config) as mailbox:
        count = mailbox.select_folder()
        unseen = len(mailbox.unseen_uids())
    return f"Verbindung erfolgreich - {count} Nachrichten im Ordner, davon {unseen} ungelesen."
