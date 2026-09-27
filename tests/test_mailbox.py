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


# -- Logiktest: eingebettete Bilder sind kein Anhang ------------------------


def _logo() -> bytes:
    import io

    from PIL import Image

    puffer = io.BytesIO()
    Image.new("RGB", (120, 40), "navy").save(puffer, "PNG")
    return puffer.getvalue()


def _outlook_mail(*, pdf: bytes | None = None, logo_als_attachment: bool = False):
    """HTML-Mail mit Signatur-Logo, wie Outlook oder Apple Mail sie erzeugen."""
    message = make()
    message.set_content("Sehr geehrte Damen und Herren,\nanbei unser Angebot.")
    message.add_alternative(
        '<p>Sehr geehrte Damen und Herren,</p><img src="cid:logo1@firma">', subtype="html"
    )
    message.get_payload()[1].add_related(
        _logo(), "image", "png", cid="<logo1@firma>", filename="logo.png",
        disposition="attachment" if logo_als_attachment else "inline",
    )
    if pdf is not None:
        message.add_attachment(pdf, maintype="application", subtype="pdf", filename="angebot.pdf")
    return parse_message(message.as_bytes())


def test_signature_logo_is_not_an_attachment():
    parsed = _outlook_mail()
    assert parsed.attachments == []
    assert parsed.embedded == ["logo.png"]


def test_signature_logo_does_not_hide_real_attachment():
    parsed = _outlook_mail(pdf=b"%PDF-1.4 inhalt")
    assert [a.filename for a in parsed.attachments] == ["angebot.pdf"]
    assert parsed.embedded == ["logo.png"]


def test_referenced_image_counts_as_embedded_even_if_marked_attachment():
    """Outlook markiert Signaturbilder mitunter als "attachment" - der cid-Verweis zaehlt."""
    parsed = _outlook_mail(logo_als_attachment=True)
    assert parsed.attachments == []


def test_apple_mail_inline_attachment_is_still_an_attachment():
    """Apple Mail kennzeichnet echte Anhaenge als "inline", bindet sie aber nicht per cid ein."""
    message = make()
    message.set_content("Hier der Scan.")
    message.add_attachment(_logo(), maintype="image", subtype="png", filename="scan.png", disposition="inline")
    parsed = parse_message(message.as_bytes())
    assert [a.filename for a in parsed.attachments] == ["scan.png"]
    assert parsed.embedded == []


def test_url_encoded_cid_reference_is_recognised():
    message = make()
    message.set_content("Text")
    message.add_alternative('<img src="cid:logo%40firma">', subtype="html")
    message.get_payload()[1].add_related(_logo(), "image", "png", cid="<logo@firma>", filename="logo.png")
    assert parse_message(message.as_bytes()).attachments == []
