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


# -- Fax-TIFF (fuer den Versand ueber SIP) ----------------------------------

import shutil

import pytest as _pytest

needs_ghostscript = _pytest.mark.skipif(
    shutil.which("gs") is None, reason="Ghostscript ist nicht installiert"
)


@needs_ghostscript
def test_pdf_to_tiff_produces_group4_fax(tmp_path):
    from PIL import Image

    from mail2fax.render import pdf_to_tiff

    quelle = text_to_pdf("Inhalt der Faxseite", tmp_path / "quelle.pdf").path
    document = pdf_to_tiff(quelle, tmp_path / "fax.tif")

    assert document.pages == 1
    with Image.open(document.path) as image:
        assert image.format == "TIFF"
        assert image.mode == "1", "Fax-TIFF muss einfarbig (1 Bit) sein"
        assert image.size[0] == 1728, "Fax verlangt 1728 Pixel je Zeile"
        # Gruppe-4-Kompression (CCITT T.6)
        assert image.info.get("compression") == "group4"
        assert image.tag_v2.get(282) == 204, "horizontale Aufloesung 204 dpi"
        assert image.tag_v2.get(283) == 196, "vertikale Aufloesung 196 dpi"


@needs_ghostscript
def test_pdf_to_tiff_keeps_all_pages(tmp_path):
    from mail2fax.render import count_tiff_pages, pdf_to_tiff

    langer_text = "\n".join(f"Zeile {index}" for index in range(200))
    quelle = text_to_pdf(langer_text, tmp_path / "lang.pdf")
    document = pdf_to_tiff(quelle.path, tmp_path / "lang.tif")

    assert document.pages == quelle.pages > 1
    assert count_tiff_pages(document.path) == quelle.pages


@needs_ghostscript
def test_pdf_to_tiff_standard_resolution(tmp_path):
    from PIL import Image

    from mail2fax.render import pdf_to_tiff

    quelle = text_to_pdf("Inhalt", tmp_path / "quelle.pdf").path
    document = pdf_to_tiff(quelle, tmp_path / "fax.tif", resolution="standard")
    with Image.open(document.path) as image:
        assert image.tag_v2.get(283) == 98


def test_pdf_to_tiff_rejects_unknown_resolution(tmp_path):
    from mail2fax.render import pdf_to_tiff

    quelle = text_to_pdf("Inhalt", tmp_path / "quelle.pdf").path
    with _pytest.raises(RenderError, match=r"[Aa]ufloesung"):
        pdf_to_tiff(quelle, tmp_path / "fax.tif", resolution="gibtsnicht")


# -- Logiktest: nichts darf am Rand verloren gehen -------------------------


@_pytest.mark.parametrize(
    "text",
    [
        "GROSSBUCHSTABEN WIE IN EINER UEBERSCHRIFT ODER EINEM AKTENZEICHEN WERDEN BREIT " * 3,
        "W" * 300,
        "https://example.com/" + "sehr-langer-pfad/" * 20,
        "   eingerueckter Absatz mit etwas Text " * 5,
        "Normaler Fliesstext. " * 40,
    ],
)
def test_no_line_exceeds_the_printable_width(text):
    """Frueher wurde nach Zeichenzahl umgebrochen - breite Zeichen liefen ueber den Rand."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    from mail2fax.render import TEXT_WIDTH, _wrap, font_name

    zeilen = _wrap(text)
    for zeile in zeilen:
        assert stringWidth(zeile, font_name(), 10) <= TEXT_WIDTH + 0.01, zeile
    # Kein Zeichen darf beim Umbruch verloren gehen.
    assert "".join(text.split()) == "".join("".join(zeilen).split())


def test_indentation_is_kept():
    from mail2fax.render import _wrap

    assert _wrap("    eingerueckt")[0].startswith("    ")


def test_empty_lines_are_kept():
    from mail2fax.render import _wrap

    assert _wrap("oben\n\nunten") == ["oben", "", "unten"]


_DEJAVU = any(__import__("pathlib").Path(p).is_file() for p in __import__(
    "mail2fax.render", fromlist=["FONT_CANDIDATES"]).FONT_CANDIDATES)


@_pytest.mark.skipif(not _DEJAVU, reason="DejaVu Sans ist nicht installiert")
def test_dejavu_is_used_when_available():
    from mail2fax.render import font_name

    assert font_name() == "DejaVuSans"


@needs_ghostscript
@_pytest.mark.skipif(not _DEJAVU, reason="DejaVu Sans ist nicht installiert")
@_pytest.mark.parametrize(
    ("ascii_text", "text"),
    [("Lodz Dvorak Sisli", "Łódź Dvořák Şişli"), ("Ivanov Petrova", "Иванов Петрова")],
)
def test_foreign_letters_arrive_as_letters(tmp_path, ascii_text, text):
    """Ł, ř, ş oder Kyrillisch kamen als schwarze Kaestchen beim Empfaenger an.

    Kaestchen erkennt man an der Tinte: Sie verbrauchen ein Vielfaches der
    Schwaerzung eines Buchstabens.
    """
    from PIL import Image

    from mail2fax.render import pdf_to_tiff

    def tinte(inhalt: str, name: str) -> int:
        pdf = text_to_pdf(inhalt, tmp_path / f"{name}.pdf").path
        with Image.open(pdf_to_tiff(pdf, tmp_path / f"{name}.tif").path) as bild:
            graustufen = bild.convert("L")
            # Histogramm statt getdata(): versionsunabhaengig in Pillow
            return sum(graustufen.crop((0, 100, 1728, 400)).histogram()[:128])

    faktor = tinte(text, "probe") / tinte(ascii_text, "ascii")
    assert faktor < 1.6, f"Verdacht auf Ersatzkaestchen (Faktor {faktor:.2f})"
