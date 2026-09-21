"""Integrationstests des Hintergrunddienstes mit simuliertem Postfach."""

from __future__ import annotations

from email.message import EmailMessage

import pytest

from mail2fax import processor
from mail2fax import worker as worker_module
from mail2fax.mailbox import MailboxError, parse_message
from mail2fax.storage import STATUS_REJECTED, STATUS_SENT
from mail2fax.worker import Worker


def mail(subject="+49301234567", sender="chef@example.com", body="Text", attachment=None):
    message = EmailMessage()
    message["From"] = sender
    message["Subject"] = subject
    message["Message-ID"] = f"<{abs(hash((subject, sender, body)))}@example.com>"
    message["Date"] = "Mon, 21 Sep 2026 10:00:00 +0200"
    message.set_content(body)
    if attachment:
        name, content = attachment
        message.add_attachment(content, maintype="application", subtype="pdf", filename=name)
    return parse_message(message.as_bytes(), uid=str(abs(hash(body)) % 1000))


class FakeMailbox:
    """Ersetzt die IMAP-Verbindung im Test."""

    def __init__(self, messages, *, fail=False):
        self.messages = {message.uid: message for message in messages}
        self.fail = fail
        self.finished: list[tuple[str, bool]] = []

    def __call__(self, _config):
        if self.fail:
            raise MailboxError("Server nicht erreichbar")
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def select_folder(self, folder=None):
        return len(self.messages)

    def unseen_uids(self):
        return list(self.messages)

    def message_size(self, uid):
        return self.messages[uid].raw_size

    def fetch(self, uid):
        return self.messages[uid]

    def finish_message(self, uid, *, rejected=False):
        self.finished.append((uid, rejected))
        self.messages.pop(uid, None)


@pytest.fixture
def spool(tmp_path, monkeypatch):
    directory = tmp_path / "spool"
    directory.mkdir()
    monkeypatch.setattr(processor, "SPOOL_DIR", directory)
    return directory


@pytest.fixture
def worker(storage, config):
    return Worker(storage, config_provider=lambda: config)


def test_poll_and_send_end_to_end(worker, storage, config, spool, monkeypatch):
    config.imap.enabled = True
    box = FakeMailbox([mail()])
    monkeypatch.setattr(worker_module, "Mailbox", box)

    assert worker.poll_mailbox(config) == 1
    assert worker.process_queue(config) == 1

    job = storage.list_jobs()[0]
    assert job.status == STATUS_SENT
    assert job.number == "+49301234567"
    assert box.finished == [(mail().uid, False)]


def test_attachment_is_preferred(worker, storage, config, spool, monkeypatch, tmp_path):
    from mail2fax.render import text_to_pdf

    config.imap.enabled = True
    pdf = text_to_pdf("Rechnung", tmp_path / "quelle.pdf").path
    box = FakeMailbox([mail(attachment=("rechnung.pdf", pdf.read_bytes()))])
    monkeypatch.setattr(worker_module, "Mailbox", box)

    worker.poll_mailbox(config)
    job = storage.list_jobs()[0]
    assert any("rechnung" in document for document in job.documents)


def test_rejected_message_is_moved_to_rejected(worker, storage, config, spool, monkeypatch):
    config.imap.enabled = True
    nachricht = mail(sender="fremd@example.org")
    box = FakeMailbox([nachricht])
    monkeypatch.setattr(worker_module, "Mailbox", box)

    worker.poll_mailbox(config)
    assert storage.list_jobs()[0].status == STATUS_REJECTED
    assert box.finished == [(nachricht.uid, True)]


def test_duplicate_message_id_is_skipped(worker, storage, config, spool, monkeypatch):
    config.imap.enabled = True
    nachricht = mail()
    monkeypatch.setattr(worker_module, "Mailbox", FakeMailbox([nachricht]))
    worker.poll_mailbox(config)
    assert len(storage.list_jobs()) == 1

    # Dieselbe Nachricht erneut im Postfach
    monkeypatch.setattr(worker_module, "Mailbox", FakeMailbox([nachricht]))
    worker.poll_mailbox(config)
    assert len(storage.list_jobs()) == 1


def test_oversized_message_is_skipped(worker, storage, config, spool, monkeypatch):
    config.imap.enabled = True
    config.imap.max_message_size_mb = 1
    nachricht = mail(body="x" * 10)
    nachricht.raw_size = 5 * 1024 * 1024
    box = FakeMailbox([nachricht])
    monkeypatch.setattr(worker_module, "Mailbox", box)

    worker.poll_mailbox(config)
    assert storage.list_jobs() == []
    assert box.finished == [(nachricht.uid, True)]
    assert any("zu gross" in event["message"] or "ueberschreitet" in event["message"]
               for event in storage.list_events())


def test_disabled_imap_does_nothing(worker, config, storage):
    config.imap.enabled = False
    assert worker.poll_mailbox(config) == 0


def test_connection_error_is_recorded(worker, config, monkeypatch):
    config.imap.enabled = True
    monkeypatch.setattr(worker_module, "Mailbox", FakeMailbox([], fail=True))
    assert worker.poll_mailbox(config) == 0
    assert "nicht erreichbar" in worker.state.snapshot()["last_poll_error"]


def test_state_is_reset_after_successful_poll(worker, config, spool, monkeypatch):
    config.imap.enabled = True
    monkeypatch.setattr(worker_module, "Mailbox", FakeMailbox([], fail=True))
    worker.poll_mailbox(config)
    assert worker.state.snapshot()["last_poll_error"]

    monkeypatch.setattr(worker_module, "Mailbox", FakeMailbox([]))
    worker.poll_mailbox(config)
    assert worker.state.snapshot()["last_poll_error"] == ""


def test_start_and_stop(worker, config):
    config.imap.enabled = False
    worker.start()
    assert worker.state.snapshot()["running"] is True
    worker.trigger()
    worker.stop()
    assert worker.state.snapshot()["running"] is False


def test_broken_config_does_not_kill_worker(storage):
    def broken():
        raise ValueError("kaputte Konfiguration")

    failing = Worker(storage, config_provider=broken)
    failing.start()
    failing.stop()
    assert "Konfigurationsfehler" in failing.state.snapshot()["last_poll_error"]


def test_stale_sending_jobs_are_requeued_on_start(worker, storage, config):
    """Ein Absturz mitten im Versand darf den Auftrag nicht dauerhaft blockieren."""
    from mail2fax.storage import STATUS_QUEUED, STATUS_SENDING

    job = storage.create_job(
        sender="chef@example.com", subject="x", number="+49301234567", status=STATUS_SENDING
    )
    assert worker.recover_stale_jobs() == 1
    assert storage.get_job(job.id).status == STATUS_QUEUED
    assert any("Neustart" in event["message"] for event in storage.list_events(job_id=job.id))


def test_recover_leaves_other_jobs_alone(worker, storage):
    from mail2fax.storage import STATUS_SENT

    sent = storage.create_job(
        sender="chef@example.com", subject="x", number="+49301234567", status=STATUS_SENT
    )
    assert worker.recover_stale_jobs() == 0
    assert storage.get_job(sent.id).status == STATUS_SENT
