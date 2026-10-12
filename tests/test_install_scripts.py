"""Tests der Installationsskripte (ohne echte Installation).

Hintergrund: Beim Aufruf ueber 'bash -c "$(curl ...)"' - so wie in der
Anleitung - gibt es keine Skriptdatei. ``${BASH_SOURCE[0]}`` ist dann leer und
brach mit ``set -u`` ab; zudem fiel das Quellverzeichnis auf das aktuelle
Arbeitsverzeichnis zurueck.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install" / "install.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash fehlt")


def _erkennungsblock() -> str:
    """Der Teil von install.sh, der das Quellverzeichnis bestimmt."""
    text = INSTALL.read_text(encoding="utf-8")
    start = text.index('SCRIPT_PATH="${BASH_SOURCE[0]:-}"')
    ende = text.index("then", text.index("grep -q '^name = \"mail2fax\"'")) + len("then")
    return text[start:ende] + "\n  echo LOKAL\nelse\n  echo GITHUB\nfi\n"


def test_no_unguarded_bash_source_in_scripts():
    for skript in [ROOT / "mail2fax.sh", *sorted((ROOT / "install").glob("*.sh"))]:
        assert "${BASH_SOURCE[0]}" not in skript.read_text(encoding="utf-8"), skript.name


def test_piped_invocation_downloads_from_github(tmp_path):
    """Wie in der Anleitung: bash -c "$(curl ...)" - auch mit Koeder im Arbeitsverzeichnis."""
    koeder = tmp_path / "fremd"
    (koeder / "unterordner").mkdir(parents=True)
    (koeder / "pyproject.toml").write_text('[project]\nname = "fremd"\n')

    ergebnis = subprocess.run(
        ["bash", "-c", "set -euo pipefail\n" + _erkennungsblock()],
        cwd=koeder / "unterordner", capture_output=True, text=True, check=False,
    )
    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "unbound variable" not in ergebnis.stderr
    assert ergebnis.stdout.strip() == "GITHUB"


def test_script_from_checkout_installs_locally(tmp_path):
    """Aus einem Checkout gestartet, wird von dort installiert."""
    checkout = tmp_path / "mail2fax"
    (checkout / "install").mkdir(parents=True)
    (checkout / "pyproject.toml").write_text('[project]\nname = "mail2fax"\n')
    skript = checkout / "install" / "erkennung.sh"
    skript.write_text("set -euo pipefail\n" + _erkennungsblock())

    ergebnis = subprocess.run(["bash", str(skript)], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert ergebnis.returncode == 0, ergebnis.stderr
    assert ergebnis.stdout.strip() == "LOKAL"


def test_scripts_use_a_locale_that_always_exists():
    """Die Locale des Proxmox-Hosts fehlt im Container meist - C.UTF-8 nie."""
    for skript in ("install/install.sh", "install/update.sh", "install/sip-setup.sh"):
        assert "LC_ALL=C.UTF-8" in (ROOT / skript).read_text(encoding="utf-8"), skript
    assert "env LANG=C.UTF-8 LC_ALL=C.UTF-8 bash -c" in (ROOT / "mail2fax.sh").read_text(encoding="utf-8")


# -- Verwaltung aus der Weboberflaeche und Rechte ------------------------------


def _text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _funktion(text: str, name: str) -> str:
    start = text.index(f"{name}() {{")
    return text[start:text.index("\n}\n", start)]


@pytest.mark.parametrize("skript", ["install/install.sh", "install/update.sh"])
def test_scripts_install_admin_helpers(skript):
    text = _text(skript)
    assert "install_admin_helpers()" in text
    # Aufgerufen wird die Funktion, nicht nur definiert.
    assert text.count("install_admin_helpers") >= 2
    rumpf = _funktion(text, "install_admin_helpers")
    for unit in ("mail2fax-aktion@.service", "mail2fax-update.path", "mail2fax-sip-setup.path"):
        assert unit in rumpf
    # Die Root-Skripte gehoeren root und liegen ausserhalb von /opt/mail2fax.
    assert "/usr/local/lib/mail2fax" in rumpf
    assert "-o root -g root -m 0755" in rumpf
    assert "/var/lib/mail2fax-admin" in rumpf
    assert "REVISION" in text


@pytest.mark.parametrize("skript", ["install/install.sh", "install/update.sh"])
def test_program_code_belongs_to_root(skript):
    """root fuehrt beim Update pip aus - der Dienst darf den Code nicht aendern koennen."""
    text = _text(skript)
    assert 'chown -R root:root "${APP_DIR}"' in text
    assert 'chown -R "${SERVICE_USER}:${SERVICE_USER}" "${APP_DIR}"' not in text


def test_update_keeps_asterisk_group_on_spool():
    """Frueher setzte update.sh die Gruppe zurueck - danach las Asterisk keine Faxe mehr."""
    text = _text("install/update.sh")
    assert 'chown -R "${SERVICE_USER}" "${DATA_DIR}"' in text
    assert 'chown -R "${SERVICE_USER}:${SERVICE_USER}" "${DATA_DIR}"' not in text


def test_update_rebuilds_venv_not_owned_by_root():
    assert '! -user root' in _text("install/update.sh")


def test_sip_setup_always_restarts_mail2fax():
    """Ohne Neustart bleibt /etc/asterisk/mail2fax fuer den Dienst schreibgeschuetzt."""
    text = _text("install/sip-setup.sh")
    assert "if systemctl is-active --quiet mail2fax; then\n  systemctl restart mail2fax" in text


def test_host_script_asks_for_sip_in_both_paths():
    """Die SIP-Frage stand frueher nur in den erweiterten Einstellungen."""
    text = _text("mail2fax.sh")
    assert "    advanced_settings\n  fi\n  ask_sip\n" in text
    assert _funktion(text, "advanced_settings").count("var_sip") == 0


def test_update_script_defines_all_helpers():
    """Jede benutzte Ausgabefunktion muss definiert sein (set -u bricht sonst ab)."""
    for skript in sorted((ROOT / "install").glob("*.sh")):
        text = skript.read_text(encoding="utf-8")
        for funktion in ("info", "ok", "warn", "die"):
            if f"\n  {funktion} " in text or f"|| {funktion} " in text:
                assert f"{funktion}()" in text, f"{skript.name}: {funktion}"
