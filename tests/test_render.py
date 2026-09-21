"""Tests fuer die Dokumentenaufbereitung."""

from __future__ import annotations

import pytest

from mail2fax.config import ContentConfig
from mail2fax.render import (
    RenderError,
    build_mail_header,
    count_pdf_pages,
    html_to_text,
    image_to_pdf,
    merge_pdfs,
    prepare_attachment,
    text_to_pdf,
)


def test_text_to_pdf_creates_readable_pdf(tmp_path):
    document = text_to_pdf("Hallo Welt", tmp_path / "out.pdf")
    assert document.path.exists()
    assert document.pages == 1
    assert document.path.read_bytes().startswith(b"%PDF")
    assert count_pdf_pages(document.path) == 1


def test_text_to_pdf_paginates_long_text(tmp_path):
    long_text = "\n".join(f"Zeile {index}" for index in range(200))
    document = text_to_pdf(long_text, tmp_path / "lang.pdf")
    assert document.pages > 1
    assert count_pdf_pages(document.path) == document.pages


def test_text_to_pdf_with_header(tmp_path):
    header = build_mail_header("chef@example.com", "Testbetreff")
    document = text_to_pdf("Inhalt", tmp_path / "kopf.pdf", header=header)
    assert document.pages == 1


def test_text_to_pdf_handles_empty_text(tmp_path):
    document = text_to_pdf("", tmp_path / "leer.pdf")
    assert document.pages == 1


def test_text_to_pdf_wraps_very_long_line(tmp_path):
    document = text_to_pdf("x" * 5000, tmp_path / "breit.pdf")
    assert document.pages >= 1


def test_html_to_text():
    html = "<html><body><p>Erster Absatz</p><br><b>Fett</b> &amp; mehr<script>weg()</script></body></html>"
    text = html_to_text(html)
    assert "Erster Absatz" in text
    assert "Fett & mehr" in text
    assert "weg()" not in text
    assert "<" not in text


def test_image_to_pdf(tmp_path):
    from PIL import Image

    source = tmp_path / "bild.png"
    Image.new("RGB", (400, 300), "white").save(source)
    document = image_to_pdf(source, tmp_path / "bild.pdf")
    assert document.pages == 1
    assert count_pdf_pages(document.path) == 1


def test_prepare_attachment_pdf_passthrough(tmp_path):
    source = text_to_pdf("Inhalt", tmp_path / "quelle.pdf").path
    document = prepare_attachment(source, "rechnung.pdf", tmp_path, ContentConfig())
    assert document.name == "rechnung.pdf"
    assert document.path == source


def test_prepare_attachment_text(tmp_path):
    source = tmp_path / "notiz.txt"
    source.write_text("Ein Text", encoding="utf-8")
    document = prepare_attachment(source, "notiz.txt", tmp_path, ContentConfig())
    assert document.path.suffix == ".pdf"
    assert document.pages == 1


def test_prepare_attachment_rejects_unknown_type(tmp_path):
    source = tmp_path / "programm.exe"
    source.write_bytes(b"MZ")
    with pytest.raises(RenderError, match="nicht unterstuetzt"):
        prepare_attachment(source, "programm.exe", tmp_path, ContentConfig())


def test_merge_pdfs(tmp_path):
    first = text_to_pdf("Eins", tmp_path / "a.pdf").path
    second = text_to_pdf("Zwei", tmp_path / "b.pdf").path
    merged = merge_pdfs([first, second], tmp_path / "zusammen.pdf")
    assert count_pdf_pages(merged) == 2


def test_merge_pdfs_single_document_is_passthrough(tmp_path):
    only = text_to_pdf("Eins", tmp_path / "a.pdf").path
    assert merge_pdfs([only], tmp_path / "ziel.pdf") == only


def test_merge_pdfs_without_sources(tmp_path):
    with pytest.raises(RenderError):
        merge_pdfs([], tmp_path / "ziel.pdf")
