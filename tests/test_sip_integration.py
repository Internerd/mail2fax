"""Integrationstest gegen ein echtes Asterisk.

Sendet ein Fax per SendFAX an ReceiveFAX ueber einen Local-Kanal. Damit
werden in einem Durchlauf geprueft: die erzeugte Asterisk-Konfiguration, das
Fax-TIFF, der Dialplan, die AMI-Steuerung und die Auswertung der Rueckmeldung.

Der Test laeuft nur, wenn Asterisk samt res_fax_spandsp und Ghostscript
vorhanden ist und die von mail2fax erzeugte Konfiguration eingebunden wurde
(install/sip-setup.sh). Andernfalls wird er uebersprungen.

Gezielt ausfuehren:  pytest -m integration
"""

from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from mail2fax.asterisk import DIALPLAN_CONTEXT, DIALPLAN_EXTEN
from mail2fax.fax.ami import AmiClient, AmiError
from mail2fax.fax.sip import SipBackend
from mail2fax.render import text_to_pdf

pytestmark = pytest.mark.integration

SELFTEST_CONTEXT = "mail2fax-selftest"


def _asterisk_cli(command: str) -> str:
    binary = shutil.which("asterisk")
    if not binary:
        pytest.skip("Asterisk ist nicht installiert")
    try:
        completed = subprocess.run(
            [binary, "-rx", command], check=False, capture_output=True, timeout=20
        )
    except (OSError, subprocess.TimeoutExpired):
        pytest.skip("Asterisk laeuft nicht")
    if completed.returncode != 0:
        pytest.skip("Asterisk laeuft nicht oder ist nicht bedienbar")
    return completed.stdout.decode("utf-8", "replace")


@pytest.fixture(scope="module")
def asterisk_bereit():
    """Prueft, ob diese Maschine den Integrationstest ausfuehren kann."""
    if not shutil.which("gs"):
        pytest.skip("Ghostscript ist nicht installiert")
    if "res_fax_spandsp.so" not in _asterisk_cli("module show like res_fax_spandsp"):
        pytest.skip("res_fax_spandsp ist nicht geladen")
    if DIALPLAN_CONTEXT not in _asterisk_cli(f"dialplan show {DIALPLAN_CONTEXT}"):
        pytest.skip(
            f"Der Kontext {DIALPLAN_CONTEXT} ist nicht geladen "
            "(install/sip-setup.sh und mail2fax sip-apply ausfuehren)"
        )
    if SELFTEST_CONTEXT not in _asterisk_cli(f"dialplan show {SELFTEST_CONTEXT}"):
        pytest.skip(f"Der Empfangskontext {SELFTEST_CONTEXT} fehlt (siehe docs/FAX-BACKENDS.md)")
    return True


@pytest.fixture
def ami_zugang():
    """AMI-Zugangsdaten aus der Konfiguration dieser Maschine."""
    from mail2fax.config import load_config

    sip = load_config().fax.sip
    if not sip.ami_password:
        pytest.skip("Es sind keine AMI-Zugangsdaten hinterlegt (mail2fax sip-apply)")
    return sip


def test_fax_wird_tatsaechlich_uebertragen(asterisk_bereit, ami_zugang, tmp_path):
    """Ein echtes Fax von SendFAX nach ReceiveFAX."""
    from mail2fax.render import pdf_to_tiff

    empfangen = Path("/tmp/mail2fax-integrationstest.tif")
    empfangen.unlink(missing_ok=True)

    pdf = text_to_pdf(
        "mail2fax Integrationstest\n\nDiese Seite laeuft durch SendFAX und ReceiveFAX.",
        tmp_path / "test.pdf",
    )
    tiff = pdf_to_tiff(pdf.path, tmp_path / "test.tif").path
    tiff.chmod(0o644)
    tmp_path.chmod(0o755)

    referenz = uuid.uuid4().hex[:12]
    try:
        with AmiClient(
            ami_zugang.ami_host, ami_zugang.ami_port, ami_zugang.ami_user, ami_zugang.ami_password
        ) as client:
            antwort = client.request(
                {
                    "Action": "Originate",
                    # /n verhindert, dass Asterisk den Kanal wegoptimiert -
                    # das wuerde die Faxuebertragung abbrechen.
                    "Channel": f"Local/recv@{SELFTEST_CONTEXT}/n",
                    "Context": DIALPLAN_CONTEXT,
                    "Exten": DIALPLAN_EXTEN,
                    "Priority": "1",
                    "CallerID": "mail2fax <+49301234567>",
                    "Timeout": "30000",
                    "Async": "true",
                },
                extra=[
                    ("Variable", f"M2F_REF={referenz}"),
                    ("Variable", "M2F_NUMBER=selbsttest"),
                    ("Variable", f"M2F_FILE={tiff}"),
                    ("Variable", "M2F_STATIONID=+49301234567"),
                    ("Variable", "M2F_HEADER=mail2fax Test"),
                    ("Variable", "M2F_ECM=no"),
                    ("Variable", "M2F_MINRATE=2400"),
                    ("Variable", "M2F_MAXRATE=14400"),
                    ("Variable", "M2F_OPTIONS=f"),
                ],
                timeout=30.0,
            )
            assert antwort.is_success, antwort.message

            ergebnis = None
            for paket in client.events(180):
                if SipBackend._is_result(paket, referenz):
                    ergebnis = paket
                    break
            assert ergebnis is not None, "Asterisk hat sich nicht zurueckgemeldet"
    except AmiError as error:
        pytest.skip(f"AMI nicht nutzbar: {error}")

    # Das Backend muss die Rueckmeldung als Erfolg erkennen.
    result = SipBackend._evaluate(ergebnis)
    assert result.success
    assert ergebnis.get("status") == "SUCCESS"
    assert ergebnis.get("pages") == "1"

    # Und die Gegenstelle muss eine lesbare Faxseite erhalten haben.
    assert empfangen.exists(), "ReceiveFAX hat keine Datei geschrieben"
    from PIL import Image

    with Image.open(empfangen) as bild:
        assert bild.size[0] == 1728, "Fax verlangt 1728 Pixel je Zeile"
        assert bild.mode == "1"
        assert bild.tag_v2.get(282) == 204
    empfangen.unlink(missing_ok=True)
