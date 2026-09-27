"""Tests der Verarbeitungskette: Mail -> Auftrag -> Versand."""

from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path

import pytest

from mail2fax import processor
from mail2fax.mailbox import parse_message
from mail2fax.processor import RejectedError, build_documents, cleanup_documents, enqueue, prepare, send_job
from mail2fax.render import text_to_pdf
from mail2fax.storage import STATUS_FAILED, STATUS_REJECTED, STATUS_SENT


def build_mail(
    *,
    sender: str = "chef@example.com",
    subject: str = "+49301234567",
    body: str = "Bitte dieses Fax senden.",
    attachments: list[tuple[str, bytes, str, str]] | None = None,
    html: str | None = None,
):
    """Erzeugt eine realistische E-Mail und parst sie wie aus dem Postfach."""
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "fax@example.com"
    message["Subject"] = subject
    message["Message-ID"] = f"<{abs(hash((sender, subject, body)))}@example.com>"
    message["Date"] = "Mon, 21 Sep 2026 10:00:00 +0200"
    message.set_content(body)
    if html:
        message.add_alternative(html, subtype="html")
    for filename, content, maintype, subtype in attachments or []:
        message.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)
    return parse_message(message.as_bytes(), uid="1")


@pytest.fixture
def spool(tmp_path, monkeypatch):
    directory = tmp_path / "spool"
    directory.mkdir()
    monkeypatch.setattr(processor, "SPOOL_DIR", directory)
    return directory


# -- Auswahl des Faxinhalts -------------------------------------------------


def test_body_is_faxed_when_no_attachment(config, tmp_path):
    message = build_mail(body="Nur Text, kein Anhang.")
    documents = build_documents(config, message, tmp_path / "w")
    assert len(documents) == 1
    assert documents[0].path.name == "nachricht.pdf"
    assert documents[0].pages == 1


def test_attachment_is_faxed_when_present(config, tmp_path):
    pdf = text_to_pdf("Rechnungsinhalt", tmp_path / "quelle.pdf").path
    message = build_mail(attachments=[("rechnung.pdf", pdf.read_bytes(), "application", "pdf")])
    documents = build_documents(config, message, tmp_path / "w")
    assert len(documents) == 1
    assert documents[0].name == "rechnung.pdf"


def test_unsupported_attachment_falls_back_to_body(config, tmp_path):
    message = build_mail(attachments=[("virus.exe", b"MZ-Programm", "application", "octet-stream")])
    documents = build_documents(config, message, tmp_path / "w")
    assert documents[0].path.name == "nachricht.pdf"


def test_oversized_attachment_falls_back_to_body(config, tmp_path):
    config.content.max_attachment_size_mb = 1
    payload = b"%PDF-1.4\n" + b"0" * (2 * 1024 * 1024)
    message = build_mail(attachments=[("gross.pdf", payload, "application", "pdf")])
    documents = build_documents(config, message, tmp_path / "w")
    assert documents[0].path.name == "nachricht.pdf"


def test_all_attachments_mode(config, tmp_path):
    first = text_to_pdf("Eins", tmp_path / "eins.pdf").path
    second = text_to_pdf("Zwei", tmp_path / "zwei.pdf").path
    config.content.attachment_mode = "all"
    message = build_mail(
        attachments=[
            ("eins.pdf", first.read_bytes(), "application", "pdf"),
            ("zwei.pdf", second.read_bytes(), "application", "pdf"),
        ]
    )
    documents = build_documents(config, message, tmp_path / "w")
    assert len(documents) == 2


def test_first_attachment_mode_takes_only_one(config, tmp_path):
    pdf = text_to_pdf("Eins", tmp_path / "eins.pdf").path
    message = build_mail(
        attachments=[
            ("eins.pdf", pdf.read_bytes(), "application", "pdf"),
            ("zwei.pdf", pdf.read_bytes(), "application", "pdf"),
        ]
    )
    documents = build_documents(config, message, tmp_path / "w")
    assert len(documents) == 1


def test_page_limit_rejects(config, tmp_path):
    config.content.max_pages = 1
    long_text = "\n".join(f"Zeile {index}" for index in range(500))
    message = build_mail(body=long_text)
    with pytest.raises(RejectedError, match="Seiten"):
        build_documents(config, message, tmp_path / "w")


def test_attachment_filename_with_path_is_sanitised(config, tmp_path):
    pdf = text_to_pdf("Inhalt", tmp_path / "quelle.pdf").path
    message = build_mail(attachments=[("../../etc/passwd.pdf", pdf.read_bytes(), "application", "pdf")])
    workdir = tmp_path / "w"
    documents = build_documents(config, message, workdir)
    assert documents[0].path.parent == workdir


# -- Annahme und Ablehnung --------------------------------------------------


def test_enqueue_accepts_valid_mail(config, storage, spool):
    job = enqueue(config, storage, build_mail())
    assert job.status == "queued"
    assert job.number == "+49301234567"
    assert job.sender == "chef@example.com"
    assert job.pages == 1


def test_enqueue_rejects_foreign_sender(config, storage, spool):
    job = enqueue(config, storage, build_mail(sender="fremd@example.org"))
    assert job.status == STATUS_REJECTED
    assert "Whitelist" in (job.error or "")


def test_enqueue_rejects_missing_number(config, storage, spool):
    job = enqueue(config, storage, build_mail(subject="Bitte faxen"))
    assert job.status == STATUS_REJECTED
    assert "Rufnummer" in (job.error or "")


def test_enqueue_rejects_blocked_number(config, storage, spool):
    job = enqueue(config, storage, build_mail(subject="+491900123456"))
    assert job.status == STATUS_REJECTED
    assert "gesperrt" in (job.error or "")


def test_rate_limit_per_sender(config, storage, spool):
    config.security.rate_limit_per_sender_per_hour = 2
    for _ in range(2):
        enqueue(config, storage, build_mail(body=str(_)))
    job = enqueue(config, storage, build_mail(body="drittes"))
    assert job.status == STATUS_REJECTED
    assert "Mengenbegrenzung" in (job.error or "")


def test_prepare_raises_for_rejected(config, storage, spool):
    with pytest.raises(RejectedError):
        prepare(config, storage, build_mail(sender="fremd@example.org"))


# -- Versand ----------------------------------------------------------------


def test_send_job_with_dummy_backend(config, storage, spool):
    job = enqueue(config, storage, build_mail())
    assert send_job(config, storage, job) is True
    assert storage.get_job(job.id).status == STATUS_SENT


def test_send_job_deletes_documents_afterwards(config, storage, spool):
    config.delete_documents_after_send = True
    job = enqueue(config, storage, build_mail())
    paths = [Path(path) for path in job.documents]
    send_job(config, storage, job)
    assert not any(path.exists() for path in paths)


def test_send_job_keeps_documents_when_configured(config, storage, spool):
    config.delete_documents_after_send = False
    job = enqueue(config, storage, build_mail())
    send_job(config, storage, job)
    assert all(Path(path).exists() for path in job.documents)


def test_send_job_retries_on_error(config, storage, spool, monkeypatch):
    from mail2fax.fax.base import FaxError

    config.fax.max_attempts = 3
    job = enqueue(config, storage, build_mail())

    def failing_send(*_args, **_kwargs):
        raise FaxError("Leitung belegt")

    monkeypatch.setattr("mail2fax.fax.dummy.DummyBackend.send", failing_send)
    assert send_job(config, storage, job) is False
    updated = storage.get_job(job.id)
    assert updated.status == "queued"
    assert updated.attempts == 1
    assert updated.next_attempt_at > job.created_at


def test_send_job_fails_permanently(config, storage, spool, monkeypatch):
    from mail2fax.fax.base import FaxError

    job = enqueue(config, storage, build_mail())

    def failing_send(*_args, **_kwargs):
        raise FaxError("Rufnummer existiert nicht", permanent=True)

    monkeypatch.setattr("mail2fax.fax.dummy.DummyBackend.send", failing_send)
    assert send_job(config, storage, job) is False
    assert storage.get_job(job.id).status == STATUS_FAILED


def test_send_job_gives_up_after_max_attempts(config, storage, spool, monkeypatch):
    from mail2fax.fax.base import FaxError

    config.fax.max_attempts = 1
    job = enqueue(config, storage, build_mail())
    monkeypatch.setattr(
        "mail2fax.fax.dummy.DummyBackend.send",
        lambda *a, **k: (_ for _ in ()).throw(FaxError("kaputt")),
    )
    send_job(config, storage, job)
    assert storage.get_job(job.id).status == STATUS_FAILED


def test_send_job_fails_when_documents_vanished(config, storage, spool):
    job = enqueue(config, storage, build_mail())
    for path in job.documents:
        Path(path).unlink()
    assert send_job(config, storage, job) is False
    assert storage.get_job(job.id).status == STATUS_FAILED


def test_dry_run_does_not_call_backend(config, storage, spool, monkeypatch):
    config.fax.dry_run = True
    job = enqueue(config, storage, build_mail())

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Backend darf im Testbetrieb nicht aufgerufen werden")

    monkeypatch.setattr("mail2fax.fax.dummy.DummyBackend.send", unexpected)
    assert send_job(config, storage, job) is True


# -- Berichte an den Absender ----------------------------------------------


@pytest.fixture
def postfach(monkeypatch):
    """Faengt Berichte ab, die die Verarbeitungskette ausloest."""
    from mail2fax import notify

    gesendet: list[dict] = []
    monkeypatch.setattr(
        notify,
        "send_mail",
        lambda _smtp, to, subject, body: gesendet.append(
            {"to": to, "subject": subject, "body": body}
        ),
    )
    return gesendet


@pytest.fixture
def mit_postausgang(config):
    config.smtp.enabled = True
    config.smtp.host = "smtp.example.com"
    config.smtp.from_address = "fax@example.com"
    return config


def test_report_after_confirmed_transmission(mit_postausgang, storage, spool, postfach, monkeypatch):
    """Bestaetigt das Backend die Uebertragung, geht ein Sendebericht hinaus."""
    from mail2fax.fax.base import FaxResult

    monkeypatch.setattr(
        "mail2fax.fax.dummy.DummyBackend.send",
        lambda *a, **k: FaxResult(
            success=True, detail="ok", confirmed=True, pages_sent=1,
            rate="14400", resolution="204x196", remote_station="+4930999888", duration=12.0,
        ),
    )
    job = enqueue(mit_postausgang, storage, build_mail())
    assert send_job(mit_postausgang, storage, job) is True

    assert len(postfach) == 1
    assert "Sendebericht" in postfach[0]["subject"]
    assert "+4930999888" in postfach[0]["body"]

    gespeichert = storage.get_job(job.id)
    assert gespeichert.confirmed is True
    assert gespeichert.pages_sent == 1
    assert gespeichert.rate == "14400"
    assert gespeichert.remote_station == "+4930999888"
    assert gespeichert.reported_at is not None


def test_report_after_unconfirmed_handover(mit_postausgang, storage, spool, postfach):
    """Ohne Quittung wird das im Bericht ausdruecklich gesagt."""
    job = enqueue(mit_postausgang, storage, build_mail())
    send_job(mit_postausgang, storage, job)

    assert len(postfach) == 1
    assert "ohne Uebertragungsnachweis" in postfach[0]["subject"]
    assert storage.get_job(job.id).confirmed is False


def test_no_report_for_unlisted_sender_on_rejection(mit_postausgang, storage, spool, postfach):
    """Der Kernpunkt: Ein fremder Absender erhaelt keine Antwort."""
    job = enqueue(mit_postausgang, storage, build_mail(sender="fremd@example.org"))
    assert job.status == STATUS_REJECTED
    assert postfach == [], "An einen nicht gelisteten Absender darf keine Post gehen"


def test_report_for_listed_sender_on_rejection(mit_postausgang, storage, spool, postfach):
    """Ein berechtigter Absender erfaehrt, warum die Nachricht abgelehnt wurde."""
    job = enqueue(mit_postausgang, storage, build_mail(subject="Bitte faxen"))
    assert job.status == STATUS_REJECTED
    assert len(postfach) == 1
    assert postfach[0]["to"] == "chef@example.com"
    assert "Rufnummer" in postfach[0]["body"]


def test_failure_report_after_last_attempt(mit_postausgang, storage, spool, postfach, monkeypatch):
    from mail2fax.fax.base import FaxError

    mit_postausgang.fax.max_attempts = 1
    monkeypatch.setattr(
        "mail2fax.fax.dummy.DummyBackend.send",
        lambda *a, **k: (_ for _ in ()).throw(FaxError("Gegenstelle antwortet nicht")),
    )
    job = enqueue(mit_postausgang, storage, build_mail())
    send_job(mit_postausgang, storage, job)

    assert storage.get_job(job.id).status == STATUS_FAILED
    assert len(postfach) == 1
    assert "Fehlerbericht" in postfach[0]["subject"]
    assert "Gegenstelle antwortet nicht" in postfach[0]["body"]


def test_no_report_while_retries_remain(mit_postausgang, storage, spool, postfach, monkeypatch):
    """Zwischenversuche loesen keine Post aus - erst das endgueltige Scheitern."""
    from mail2fax.fax.base import FaxError

    mit_postausgang.fax.max_attempts = 3
    monkeypatch.setattr(
        "mail2fax.fax.dummy.DummyBackend.send",
        lambda *a, **k: (_ for _ in ()).throw(FaxError("Leitung belegt")),
    )
    job = enqueue(mit_postausgang, storage, build_mail())
    send_job(mit_postausgang, storage, job)

    assert storage.get_job(job.id).status == "queued"
    assert postfach == []


def test_reports_stay_off_without_smtp(config, storage, spool, postfach):
    """Ohne eingerichteten Postausgang wird nichts versendet."""
    config.smtp.enabled = False
    job = enqueue(config, storage, build_mail())
    send_job(config, storage, job)
    assert postfach == []


def test_dry_run_report_is_not_confirmed(mit_postausgang, storage, spool, postfach):
    """Im Testbetrieb darf kein Bericht eine Uebertragung behaupten."""
    mit_postausgang.fax.dry_run = True
    job = enqueue(mit_postausgang, storage, build_mail())
    send_job(mit_postausgang, storage, job)

    assert storage.get_job(job.id).confirmed is False
    assert len(postfach) == 1
    assert "ohne Uebertragungsnachweis" in postfach[0]["subject"]


# -- Logiktest: Signatur-Logo darf nicht gefaxt werden ----------------------


def _mail_mit_logo(*, pdf: bytes | None = None):
    import io

    from PIL import Image

    puffer = io.BytesIO()
    Image.new("RGB", (120, 40), "navy").save(puffer, "PNG")
    message = EmailMessage()
    message["From"] = "chef@example.com"
    message["Subject"] = "+49301234567"
    message["Message-ID"] = f"<logo-{pdf is not None}@example.com>"
    message.set_content("Sehr geehrte Damen und Herren,\nanbei unser Angebot.")
    message.add_alternative('<p>Text</p><img src="cid:logo1@firma">', subtype="html")
    message.get_payload()[1].add_related(
        puffer.getvalue(), "image", "png", cid="<logo1@firma>", filename="logo.png"
    )
    if pdf is not None:
        message.add_attachment(pdf, maintype="application", subtype="pdf", filename="angebot.pdf")
    return parse_message(message.as_bytes(), uid="7")


def test_mail_text_is_faxed_instead_of_signature_logo(config, tmp_path):
    documents = build_documents(config, _mail_mit_logo(), tmp_path / "w")
    assert [d.path.name for d in documents] == ["nachricht.pdf"]


def test_pdf_is_faxed_instead_of_signature_logo(config, tmp_path):
    pdf = text_to_pdf("Angebot", tmp_path / "angebot.pdf").path.read_bytes()
    documents = build_documents(config, _mail_mit_logo(pdf=pdf), tmp_path / "w")
    assert [d.name for d in documents] == ["angebot.pdf"]


def test_skipped_embedded_images_are_noted_in_the_job(config, storage, spool):
    job = enqueue(config, storage, _mail_mit_logo())
    meldungen = [event["message"] for event in storage.list_events(job_id=job.id)]
    assert any("eingebettete Bilder" in m and "logo.png" in m for m in meldungen)


def test_each_job_gets_its_own_workdir(config, storage, spool):
    """Zwei Auftraege in derselben Sekunde duerfen sich kein Verzeichnis teilen."""
    erster = enqueue(config, storage, build_mail(body="eins"))
    zweiter = enqueue(config, storage, build_mail(body="zwei"))
    assert Path(erster.documents[0]).parent != Path(zweiter.documents[0]).parent

    cleanup_documents(erster)
    assert all(Path(p).exists() for p in zweiter.documents)
