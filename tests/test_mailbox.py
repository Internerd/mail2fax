"""Tests des Mail-Parsings (ohne echten IMAP-Server)."""

from __future__ import annotations

from email.message import EmailMessage

from mail2fax.mailbox import parse_message


def make(subject="+49301234567", sender="chef@example.com"):
    message = EmailMessage()
    message["From"] = sender
    message["Subject"] = subject
    message["Message-ID"] = "<abc@example.com>"
    message["Date"] = "Mon, 21 Sep 2026 10:00:00 +0200"
    return message


def test_plain_text_mail():
    message = make()
    message.set_content("Hallo Welt")
    parsed = parse_message(message.as_bytes())
    assert parsed.sender == "chef@example.com"
    assert parsed.subject == "+49301234567"
    assert parsed.text.strip() == "Hallo Welt"
    assert parsed.attachments == []
    assert parsed.message_id == "<abc@example.com>"
    assert parsed.date == "21.09.2026 10:00"


def test_encoded_headers_are_decoded():
    message = make(subject="Fax für Müller +49301234567", sender="Müller <mueller@example.com>")
    message.set_content("Text")
    parsed = parse_message(message.as_bytes())
    assert "Müller" in parsed.subject
    assert "mueller@example.com" in parsed.sender


def test_html_only_mail_is_converted_to_text():
    message = make()
    message.set_content("<p>Formatierter <b>Text</b> &amp; Zeichen</p>", subtype="html")
    parsed = parse_message(message.as_bytes())
    assert "Formatierter Text & Zeichen" in parsed.text
    assert "<" not in parsed.text


def test_plain_part_is_preferred_over_html():
    message = make()
    message.set_content("Reiner Text")
    message.add_alternative("<p>HTML-Fassung</p>", subtype="html")
    parsed = parse_message(message.as_bytes())
    assert parsed.text.strip() == "Reiner Text"


def test_attachments_are_extracted():
    message = make()
    message.set_content("Siehe Anhang")
    message.add_attachment(b"%PDF-1.4 inhalt", maintype="application", subtype="pdf", filename="doc.pdf")
    parsed = parse_message(message.as_bytes())
    assert len(parsed.attachments) == 1
    assert parsed.attachments[0].filename == "doc.pdf"
    assert parsed.attachments[0].content.startswith(b"%PDF")


def test_attachment_path_is_stripped():
    message = make()
    message.set_content("Text")
    message.add_attachment(b"x", maintype="application", subtype="pdf", filename="../../evil.pdf")
    parsed = parse_message(message.as_bytes())
    assert parsed.attachments[0].filename == "evil.pdf"


def test_inline_body_parts_are_not_attachments():
    message = make()
    message.set_content("Nur Text")
    parsed = parse_message(message.as_bytes())
    assert parsed.attachments == []


def test_missing_headers_do_not_crash():
    parsed = parse_message(b"Subject: Test\r\n\r\nInhalt")
    assert parsed.subject == "Test"
    assert parsed.sender == ""
    assert parsed.message_id is None
