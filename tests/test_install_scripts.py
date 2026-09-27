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
