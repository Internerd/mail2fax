"""Erzeugt aus Mailtext und Anhaengen faxfaehige PDF-Dokumente."""

from __future__ import annotations

import html
import logging
import re
import shutil
import subprocess
import textwrap
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from .config import ContentConfig

LOGGER = logging.getLogger(__name__)

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN_X = 20 * mm
MARGIN_TOP = 20 * mm
MARGIN_BOTTOM = 18 * mm
FONT_NAME = "Helvetica"
FONT_SIZE = 10
LINE_HEIGHT = 13
#: Zeichen pro Zeile bei 10pt Helvetica auf A4 mit 20 mm Rand.
WRAP_WIDTH = 95


class RenderError(Exception):
    """Fehler bei der Dokumentenaufbereitung."""


@dataclass
class Document:
    """Ein fertig aufbereitetes Dokument."""

    path: Path
    #: Urspruenglicher Dateiname (fuer Protokoll und Statusmail).
    name: str
    pages: int


def _strip_html(raw: str) -> str:
    """Macht aus HTML einen lesbaren Text (ohne externe Abhaengigkeit)."""
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n\n", text)
    text = re.sub(r"(?i)</(div|tr|li|h[1-6])\s*>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _wrap(text: str, width: int = WRAP_WIDTH) -> list[str]:
    lines: list[str] = []
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = raw_line.rstrip()
        if not stripped:
            lines.append("")
            continue
        lines.extend(
            textwrap.wrap(
                stripped,
                width=width,
                replace_whitespace=False,
                drop_whitespace=False,
                break_long_words=True,
                break_on_hyphens=False,
            )
            or [""]
        )
    return lines


def text_to_pdf(
    text: str,
    target: Path,
    *,
    header: dict[str, str] | None = None,
    title: str = "mail2fax",
) -> Document:
    """Schreibt Text als PDF - fuer Mails ohne (nutzbaren) Anhang."""
    target.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(target), pagesize=A4)
    pdf.setTitle(title)
    pdf.setAuthor("mail2fax")

    lines: list[str] = []
    if header:
        for key, value in header.items():
            if value:
                lines.extend(_wrap(f"{key}: {value}"))
        lines.append("-" * WRAP_WIDTH)
        lines.append("")
    lines.extend(_wrap(text or "(Diese Nachricht enthielt keinen Text.)"))

    y = PAGE_HEIGHT - MARGIN_TOP
    pages = 1
    pdf.setFont(FONT_NAME, FONT_SIZE)
    for line in lines:
        if y < MARGIN_BOTTOM:
            pdf.showPage()
            pdf.setFont(FONT_NAME, FONT_SIZE)
            pages += 1
            y = PAGE_HEIGHT - MARGIN_TOP
        pdf.drawString(MARGIN_X, y, line)
        y -= LINE_HEIGHT
    pdf.save()
    return Document(path=target, name=target.name, pages=pages)


def image_to_pdf(source: Path, target: Path) -> Document:
    """Skaliert ein Bild seitenfuellend auf A4 und speichert es als PDF."""
    from PIL import Image, ImageSequence

    target.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(target), pagesize=A4)
    pages = 0
    with Image.open(source) as image:
        for frame in ImageSequence.Iterator(image):
            converted = frame.convert("RGB")
            width, height = converted.size
            scale = min(
                (PAGE_WIDTH - 2 * MARGIN_X) / width,
                (PAGE_HEIGHT - 2 * MARGIN_TOP) / height,
            )
            draw_width = width * scale
            draw_height = height * scale
            from reportlab.lib.utils import ImageReader

            pdf.drawImage(
                ImageReader(converted),
                (PAGE_WIDTH - draw_width) / 2,
                (PAGE_HEIGHT - draw_height) / 2,
                width=draw_width,
                height=draw_height,
                preserveAspectRatio=True,
            )
            pdf.showPage()
            pages += 1
    if pages == 0:
        raise RenderError(f"Bilddatei {source.name} enthaelt keine Seiten")
    pdf.save()
    return Document(path=target, name=source.name, pages=pages)


def count_pdf_pages(path: Path) -> int:
    """Ermittelt die Seitenzahl eines PDFs."""
    try:
        from pypdf import PdfReader

        return len(PdfReader(str(path)).pages)
    except Exception as error:  # pragma: no cover - defekte PDFs
        raise RenderError(f"PDF {path.name} konnte nicht gelesen werden: {error}") from error


def office_to_pdf(source: Path, target_dir: Path, *, timeout: int = 180) -> Document:
    """Wandelt Office-Dokumente mit LibreOffice (headless) nach PDF."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RenderError(
            "LibreOffice ist nicht installiert - Office-Dokumente koennen nicht "
            "gewandelt werden (apt install libreoffice-core libreoffice-writer)"
        )
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(  # noqa: S603 - feste Argumentliste, keine Shell
            [
                soffice, "--headless", "--norestore", "--nolockcheck",
                "--convert-to", "pdf", "--outdir", str(target_dir), str(source),
            ],
            check=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise RenderError(f"Wandlung von {source.name} hat zu lange gedauert") from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or b"").decode("utf-8", "replace").strip()
        raise RenderError(f"Wandlung von {source.name} fehlgeschlagen: {detail}") from error

    produced = target_dir / (source.stem + ".pdf")
    if not produced.exists():
        raise RenderError(f"LibreOffice hat fuer {source.name} kein PDF erzeugt")
    return Document(path=produced, name=source.name, pages=count_pdf_pages(produced))


def prepare_attachment(
    source: Path,
    original_name: str,
    workdir: Path,
    content: ContentConfig,
) -> Document:
    """Bereitet einen einzelnen Anhang als PDF auf."""
    suffix = Path(original_name).suffix.lower().lstrip(".")
    workdir.mkdir(parents=True, exist_ok=True)

    if suffix == "pdf":
        return Document(path=source, name=original_name, pages=count_pdf_pages(source))

    if suffix in {"png", "jpg", "jpeg", "gif", "bmp", "tif", "tiff", "webp"}:
        target = workdir / f"{source.stem}-bild.pdf"
        document = image_to_pdf(source, target)
        return Document(path=document.path, name=original_name, pages=document.pages)

    if suffix in {"txt", "log", "csv"}:
        target = workdir / f"{source.stem}-text.pdf"
        text = source.read_text(encoding="utf-8", errors="replace")
        document = text_to_pdf(text, target, title=original_name)
        return Document(path=document.path, name=original_name, pages=document.pages)

    if content.convert_office and suffix in set(content.office_extensions):
        document = office_to_pdf(source, workdir)
        return Document(path=document.path, name=original_name, pages=document.pages)

    raise RenderError(f"Dateityp '.{suffix}' wird nicht unterstuetzt ({original_name})")


def build_mail_header(sender: str, subject: str, date: str | None = None) -> dict[str, str]:
    """Kopfzeilen fuer die aus dem Mailtext erzeugte Faxseite."""
    return {
        "Von": sender,
        "Betreff": subject,
        "Datum": date or datetime.now().strftime("%d.%m.%Y %H:%M"),
        "Uebermittelt durch": "mail2fax",
    }


def html_to_text(raw: str) -> str:
    """Oeffentlicher Zugriff auf die HTML-Bereinigung."""
    return _strip_html(raw)


def merge_pdfs(sources: list[Path], target: Path) -> Path:
    """Fuehrt mehrere PDFs zu einem Dokument zusammen.

    Wird fuer Backends benoetigt, die je Auftrag nur eine Datei annehmen.
    """
    if not sources:
        raise RenderError("Es wurden keine Dokumente zum Zusammenfuehren uebergeben")
    if len(sources) == 1:
        return sources[0]
    try:
        from pypdf import PdfWriter

        writer = PdfWriter()
        for source in sources:
            writer.append(str(source))
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as handle:
            writer.write(handle)
        writer.close()
    except RenderError:
        raise
    except Exception as error:
        raise RenderError(f"Dokumente konnten nicht zusammengefuehrt werden: {error}") from error
    return target


#: Fax-Aufloesungen: (Pixel je Zeile, horizontale dpi, vertikale dpi).
FAX_RESOLUTIONS = {
    "standard": (1728, 204, 98),
    "fine": (1728, 204, 196),
    "superfine": (1728, 204, 391),
}


def pdf_to_tiff(
    source: Path,
    target: Path,
    *,
    resolution: str = "fine",
    timeout: int = 300,
) -> Document:
    """Wandelt ein PDF in ein Fax-TIFF (CCITT Gruppe 4, 1 Bit).

    Diese Form erwartet spandsp bzw. Asterisk fuer den Versand ueber SIP.
    Gewandelt wird mit Ghostscript, das in fast jeder Distribution vorliegt.
    """
    ghostscript = shutil.which("gs")
    if not ghostscript:
        raise RenderError(
            "Ghostscript wird fuer den SIP-Versand benoetigt, ist aber nicht "
            "installiert (apt install ghostscript)"
        )
    if resolution not in FAX_RESOLUTIONS:
        raise RenderError(f"Unbekannte Faxaufloesung: {resolution}")

    width, dpi_x, dpi_y = FAX_RESOLUTIONS[resolution]
    # Seitenhoehe in Pixeln fuer A4 (297 mm) bei der vertikalen Aufloesung.
    height = round(297 / 25.4 * dpi_y)

    target.parent.mkdir(parents=True, exist_ok=True)
    argv = [
        ghostscript,
        "-q",
        "-dNOPAUSE",
        "-dBATCH",
        "-dSAFER",
        "-sDEVICE=tiffg4",
        f"-r{dpi_x}x{dpi_y}",
        f"-g{width}x{height}",
        "-dPDFFitPage",
        "-dFIXEDMEDIA",
        f"-sOutputFile={target}",
        str(source),
    ]
    try:
        completed = subprocess.run(  # noqa: S603 - feste Argumentliste, keine Shell
            argv, check=False, capture_output=True, timeout=timeout
        )
    except subprocess.TimeoutExpired as error:
        raise RenderError(
            f"Wandlung von {source.name} nach TIFF hat zu lange gedauert"
        ) from error
    except OSError as error:
        raise RenderError(f"Ghostscript konnte nicht gestartet werden: {error}") from error

    if completed.returncode != 0 or not target.exists():
        detail = (completed.stderr or b"").decode("utf-8", "replace").strip()
        raise RenderError(f"Wandlung nach TIFF fehlgeschlagen: {detail or 'unbekannter Fehler'}")

    return Document(path=target, name=target.name, pages=count_tiff_pages(target))


def count_tiff_pages(path: Path) -> int:
    """Ermittelt die Seitenzahl eines (mehrseitigen) TIFF."""
    try:
        from PIL import Image

        with Image.open(path) as image:
            return getattr(image, "n_frames", 1)
    except Exception as error:  # pragma: no cover - defekte Dateien
        raise RenderError(f"TIFF {path.name} konnte nicht gelesen werden: {error}") from error
