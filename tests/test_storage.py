"""Tests der Auftragsverwaltung."""

from __future__ import annotations

import time

from mail2fax.storage import STATUS_QUEUED, STATUS_SENT, Storage


def test_create_and_read_job(storage):
    job = storage.create_job(sender="a@example.com", subject="Test", number="+49301234567")
    assert job.id > 0
    assert storage.get_job(job.id).number == "+49301234567"


def test_message_id_prevents_duplicates(storage):
    storage.create_job(sender="a@example.com", subject="x", number="+4930", message_id="<1@x>")
    assert storage.message_seen("<1@x>") is True
    assert storage.message_seen("<2@x>") is False
    assert storage.message_seen(None) is False


def test_documents_roundtrip(storage):
    job = storage.create_job(
        sender="a@example.com", subject="x", number="+4930", documents=["/tmp/a.pdf", "/tmp/b.pdf"]
    )
    assert storage.get_job(job.id).documents == ["/tmp/a.pdf", "/tmp/b.pdf"]


def test_update_job(storage):
    job = storage.create_job(sender="a@example.com", subject="x", number="+4930")
    storage.update_job(job.id, status=STATUS_SENT, pages=3)
    updated = storage.get_job(job.id)
    assert updated.status == STATUS_SENT
    assert updated.pages == 3
    assert updated.updated_at >= job.updated_at


def test_due_jobs_respects_schedule(storage):
    ready = storage.create_job(sender="a@example.com", subject="x", number="+4930")
    later = storage.create_job(sender="a@example.com", subject="y", number="+4931")
    storage.update_job(later.id, next_attempt_at=time.time() + 3600)
    due_ids = [job.id for job in storage.due_jobs()]
    assert ready.id in due_ids
    assert later.id not in due_ids


def test_stats(storage):
    storage.create_job(sender="a@example.com", subject="x", number="+4930")
    storage.create_job(sender="a@example.com", subject="y", number="+4931", status=STATUS_SENT)
    stats = storage.stats()
    assert stats[STATUS_QUEUED] == 1
    assert stats[STATUS_SENT] == 1


def test_count_recent_filters_sender(storage):
    storage.create_job(sender="a@example.com", subject="x", number="+4930")
    storage.create_job(sender="b@example.com", subject="y", number="+4931")
    since = time.time() - 60
    assert storage.count_recent(since=since) == 2
    assert storage.count_recent(since=since, sender="a@example.com") == 1


def test_events(storage):
    job = storage.create_job(sender="a@example.com", subject="x", number="+4930")
    storage.log_event("Etwas passiert", job_id=job.id)
    storage.log_event("Allgemein")
    assert len(storage.list_events(job_id=job.id)) == 1
    assert len(storage.list_events()) == 2


def test_purge_old_removes_finished_jobs(storage):
    old = storage.create_job(sender="a@example.com", subject="x", number="+4930", status=STATUS_SENT)
    storage.update_job(old.id, created_at=time.time() - 100 * 86400)
    assert storage.purge_old(90) == 1
    assert storage.get_job(old.id) is None


def test_purge_disabled(storage):
    storage.create_job(sender="a@example.com", subject="x", number="+4930", status=STATUS_SENT)
    assert storage.purge_old(0) == 0


def test_schema_is_idempotent(tmp_path):
    path = tmp_path / "wieder.db"
    first = Storage(path)
    first.create_job(sender="a@example.com", subject="x", number="+4930")
    first.close()
    second = Storage(path)
    assert len(second.list_jobs()) == 1
    second.close()
