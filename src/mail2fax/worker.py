"""Hintergrunddienst: Postfach abfragen, Warteschlange abarbeiten, aufraeumen."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from .config import AppConfig, load_config
from .mailbox import Mailbox, MailboxError
from .paths import ensure_dirs
from .processor import enqueue, send_job
from .storage import STATUS_QUEUED, STATUS_SENDING, Storage

LOGGER = logging.getLogger(__name__)


@dataclass
class WorkerState:
    """Laufzeitzustand fuer die Anzeige in der Weboberflaeche."""

    running: bool = False
    last_poll: float = 0.0
    last_poll_error: str = ""
    last_success: float = 0.0
    processed_total: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            return {
                "running": self.running,
                "last_poll": self.last_poll,
                "last_poll_error": self.last_poll_error,
                "last_success": self.last_success,
                "processed_total": self.processed_total,
            }


class Worker:
    """Ein Thread, der Postfach und Warteschlange in einer Schleife bearbeitet."""

    def __init__(self, storage: Storage, config_provider=load_config) -> None:
        self.storage = storage
        self._config_provider = config_provider
        self.state = WorkerState()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_purge = 0.0

    # -- Steuerung ---------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        ensure_dirs()
        self.recover_stale_jobs()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="mail2fax-worker", daemon=True)
        self._thread.start()
        with self.state.lock:
            self.state.running = True
        LOGGER.info("Hintergrunddienst gestartet")

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        with self.state.lock:
            self.state.running = False
        LOGGER.info("Hintergrunddienst beendet")

    def trigger(self) -> None:
        """Weckt den Dienst sofort (z. B. nach "Jetzt pruefen" im Webinterface)."""
        self._wake.set()

    def recover_stale_jobs(self) -> int:
        """Plant Auftraege wieder ein, die beim letzten Beenden mitten im Versand standen.

        Ohne diesen Schritt bliebe ein Auftrag nach einem Absturz oder einem
        Neustart waehrend der Uebertragung dauerhaft im Zustand "sending"
        haengen und wuerde nie erneut versucht.
        """
        stale = self.storage.list_jobs(limit=1000, status=STATUS_SENDING)
        for job in stale:
            self.storage.update_job(
                job.id, status=STATUS_QUEUED, next_attempt_at=time.time()
            )
            self.storage.log_event(
                "Auftrag stand beim Neustart noch im Versand und wurde erneut eingeplant",
                job_id=job.id,
                level="warning",
            )
        if stale:
            LOGGER.warning("%s unterbrochene(r) Auftrag/Auftraege wieder eingeplant", len(stale))
        return len(stale)

    # -- Schleife ----------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            config = self._safe_config()
            interval = config.imap.poll_interval if config else 60
            try:
                if config:
                    self.poll_mailbox(config)
                    self.process_queue(config)
                    self._maybe_purge(config)
            except Exception:
                LOGGER.exception("Unerwarteter Fehler im Hintergrunddienst")
            self._wake.wait(timeout=max(5, interval))
            self._wake.clear()

    def _safe_config(self) -> AppConfig | None:
        try:
            return self._config_provider()
        except Exception as error:
            LOGGER.error("Konfiguration konnte nicht geladen werden: %s", error)
            with self.state.lock:
                self.state.last_poll_error = f"Konfigurationsfehler: {error}"
            return None

    # -- Einzelschritte ----------------------------------------------------

    def poll_mailbox(self, config: AppConfig) -> int:
        """Holt neue Nachrichten und legt Auftraege an. Liefert die Anzahl."""
        if not config.imap.enabled:
            return 0
        processed = 0
        try:
            with Mailbox(config.imap) as mailbox:
                mailbox.select_folder()
                uids = mailbox.unseen_uids()
                if uids:
                    LOGGER.info("%s neue Nachricht(en) im Postfach", len(uids))
                limit = config.imap.max_message_size_mb * 1024 * 1024
                for uid in uids:
                    if self._stop.is_set():
                        break
                    try:
                        size = mailbox.message_size(uid)
                        if size and size > limit:
                            LOGGER.warning(
                                "Nachricht %s ist mit %s KiB zu gross und wird uebersprungen",
                                uid, size // 1024,
                            )
                            self.storage.log_event(
                                f"Nachricht {uid} uebersprungen: {size // 1024} KiB "
                                f"ueberschreitet das Limit",
                                level="warning",
                            )
                            mailbox.finish_message(uid, rejected=True)
                            continue

                        message = mailbox.fetch(uid)
                        if self.storage.message_seen(message.message_id):
                            LOGGER.info(
                                "Nachricht %s wurde bereits verarbeitet (Message-ID bekannt)",
                                uid,
                            )
                            mailbox.finish_message(uid)
                            continue

                        job = enqueue(config, self.storage, message)
                        mailbox.finish_message(uid, rejected=(job.status == "rejected"))
                        processed += 1
                    except MailboxError as error:
                        LOGGER.error("Nachricht %s konnte nicht verarbeitet werden: %s", uid, error)
                    except Exception:
                        LOGGER.exception("Fehler bei Nachricht %s", uid)
            with self.state.lock:
                self.state.last_poll = time.time()
                self.state.last_poll_error = ""
                self.state.processed_total += processed
        except MailboxError as error:
            LOGGER.error("Postfachabfrage fehlgeschlagen: %s", error)
            with self.state.lock:
                self.state.last_poll = time.time()
                self.state.last_poll_error = str(error)
        return processed

    def process_queue(self, config: AppConfig) -> int:
        """Arbeitet faellige Auftraege ab. Liefert die Anzahl der Versuche."""
        handled = 0
        for job in self.storage.due_jobs(limit=20):
            if self._stop.is_set():
                break
            if send_job(config, self.storage, job):
                with self.state.lock:
                    self.state.last_success = time.time()
            handled += 1
        return handled

    def _maybe_purge(self, config: AppConfig) -> None:
        """Loescht abgelaufene Historie hoechstens einmal pro Stunde."""
        if time.time() - self._last_purge < 3600:
            return
        self._last_purge = time.time()
        removed = self.storage.purge_old(config.history_retention_days)
        if removed:
            LOGGER.info("%s alte Auftraege aus der Historie entfernt", removed)
