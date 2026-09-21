#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# mail2fax - Installation innerhalb eines Debian/Ubuntu-Systems
#
# Dieses Skript wird IM CONTAINER (bzw. auf der Ziel-VM) ausgefuehrt.
# Fuer die Einrichtung eines neuen LXC auf einem Proxmox-Host nutzen Sie
# stattdessen mail2fax.sh auf dem PVE-Host.
#
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/Internerd/mail2fax/main/install/install.sh)"
# ---------------------------------------------------------------------------
set -euo pipefail

REPO_RAW="${MAIL2FAX_REPO_RAW:-https://raw.githubusercontent.com/Internerd/mail2fax/main}"
REPO_TARBALL="${MAIL2FAX_REPO_TARBALL:-https://github.com/Internerd/mail2fax/archive/refs/heads/main.tar.gz}"
APP_DIR="/opt/mail2fax"
CONFIG_DIR="/etc/mail2fax"
DATA_DIR="/var/lib/mail2fax"
SERVICE_USER="mail2fax"
VENV="${APP_DIR}/venv"

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; BLUE=$'\033[0;34m'; RESET=$'\033[0m'
info()  { echo "${BLUE}==>${RESET} $*"; }
ok()    { echo "${GREEN} ok ${RESET} $*"; }
warn()  { echo "${YELLOW}warn${RESET} $*"; }
die()   { echo "${RED}FEHLER${RESET} $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Bitte als root ausfuehren."
command -v apt-get >/dev/null 2>&1 || die "Dieses Skript setzt ein Debian- oder Ubuntu-System voraus."

WITH_LIBREOFFICE="${MAIL2FAX_LIBREOFFICE:-no}"

# --- Pakete ----------------------------------------------------------------
info "Installiere Systempakete ..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
  python3 python3-venv python3-pip ca-certificates curl tar >/dev/null
if [ "${WITH_LIBREOFFICE}" = "yes" ]; then
  info "Installiere LibreOffice fuer die Wandlung von Office-Dokumenten ..."
  apt-get install -y -qq --no-install-recommends libreoffice-core libreoffice-writer fonts-dejavu-core >/dev/null
fi
ok "Systempakete installiert"

# --- Benutzer und Verzeichnisse -------------------------------------------
if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd --system --home-dir "${APP_DIR}" --shell /usr/sbin/nologin "${SERVICE_USER}"
  ok "Systembenutzer ${SERVICE_USER} angelegt"
fi
mkdir -p "${APP_DIR}" "${CONFIG_DIR}" "${DATA_DIR}"

# --- Quellcode -------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR=""
if [ -f "${SCRIPT_DIR}/../pyproject.toml" ]; then
  SOURCE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
  info "Installiere aus lokalem Verzeichnis ${SOURCE_DIR}"
else
  info "Lade Quellcode von GitHub ..."
  TMP_DIR="$(mktemp -d)"
  trap 'rm -rf "${TMP_DIR}"' EXIT
  curl -fsSL "${REPO_TARBALL}" -o "${TMP_DIR}/mail2fax.tar.gz" \
    || die "Quellcode konnte nicht geladen werden (${REPO_TARBALL})"
  tar -xzf "${TMP_DIR}/mail2fax.tar.gz" -C "${TMP_DIR}"
  SOURCE_DIR="$(find "${TMP_DIR}" -maxdepth 1 -type d -name 'mail2fax-*' | head -n1)"
  [ -n "${SOURCE_DIR}" ] || die "Entpacktes Archiv enthaelt kein Quellverzeichnis."
fi

# --- Python-Umgebung -------------------------------------------------------
info "Richte Python-Umgebung ein (das dauert einen Moment) ..."
if [ ! -x "${VENV}/bin/python" ]; then
  python3 -m venv "${VENV}"
fi
"${VENV}/bin/pip" install --quiet --upgrade pip wheel
"${VENV}/bin/pip" install --quiet "${SOURCE_DIR}" || die "Installation der Python-Pakete fehlgeschlagen."
ok "mail2fax $("${VENV}/bin/mail2fax" --version | awk '{print $2}') installiert"

# Beispielkonfiguration und Dokumentation mitliefern
install -d "${APP_DIR}/doc"
[ -f "${SOURCE_DIR}/config/config.example.yaml" ] && \
  install -m 0644 "${SOURCE_DIR}/config/config.example.yaml" "${APP_DIR}/doc/config.example.yaml"
[ -d "${SOURCE_DIR}/docs" ] && cp -r "${SOURCE_DIR}/docs/." "${APP_DIR}/doc/" 2>/dev/null || true

# --- Konfiguration ---------------------------------------------------------
ADMIN_PASSWORD=""
if [ ! -f "${CONFIG_DIR}/config.yaml" ]; then
  info "Erzeuge Grundkonfiguration ..."
  "${VENV}/bin/mail2fax" init-config >/dev/null
  # Zufaelliges Erstpasswort fuer die Weboberflaeche
  ADMIN_PASSWORD="$("${VENV}/bin/python" - <<'PY'
import secrets, string
alphabet = string.ascii_letters + string.digits
print("M2F-" + "".join(secrets.choice(alphabet) for _ in range(16)) + "!")
PY
)"
  "${VENV}/bin/mail2fax" passwd --password "${ADMIN_PASSWORD}" >/dev/null
  ok "Konfiguration unter ${CONFIG_DIR}/config.yaml angelegt"
else
  warn "Bestehende Konfiguration ${CONFIG_DIR}/config.yaml bleibt unveraendert"
fi

# Rechte: nur root und der Dienstbenutzer duerfen die Zugangsdaten sehen.
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${CONFIG_DIR}" "${DATA_DIR}" "${APP_DIR}"
chmod 0750 "${CONFIG_DIR}" "${DATA_DIR}"
[ -f "${CONFIG_DIR}/config.yaml" ] && chmod 0640 "${CONFIG_DIR}/config.yaml"

# --- systemd ---------------------------------------------------------------
info "Richte den Dienst ein ..."
if [ -f "${SOURCE_DIR}/systemd/mail2fax.service" ]; then
  install -m 0644 "${SOURCE_DIR}/systemd/mail2fax.service" /etc/systemd/system/mail2fax.service
else
  curl -fsSL "${REPO_RAW}/systemd/mail2fax.service" -o /etc/systemd/system/mail2fax.service \
    || die "systemd-Unit konnte nicht geladen werden."
fi
systemctl daemon-reload
systemctl enable --now mail2fax >/dev/null 2>&1 || die "Dienst konnte nicht gestartet werden (journalctl -u mail2fax)."

sleep 3
if ! systemctl is-active --quiet mail2fax; then
  journalctl -u mail2fax -n 30 --no-pager || true
  die "Der Dienst laeuft nicht. Siehe Ausgabe oben."
fi
ok "Dienst mail2fax laeuft"

# --- Abschluss -------------------------------------------------------------
PORT="$(grep -E '^\s+port:\s*[0-9]+' "${CONFIG_DIR}/config.yaml" | tail -n1 | tr -dc '0-9')"
PORT="${PORT:-8080}"
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
IP="${IP:-<IP-des-Containers>}"

echo
echo "-------------------------------------------------------------------"
echo " mail2fax ist installiert."
echo
echo "   Weboberflaeche : http://${IP}:${PORT}"
if [ -n "${ADMIN_PASSWORD}" ]; then
echo "   Benutzer       : (keiner - nur Passwort)"
echo "   Passwort       : ${ADMIN_PASSWORD}"
echo
echo "   ${YELLOW}Bitte notieren und nach der ersten Anmeldung aendern.${RESET}"
fi
echo
echo " Naechste Schritte:"
echo "   1. Anmelden und unter 'Sicherheit' die Absender-Whitelist fuellen."
echo "      Ohne Whitelist wird bewusst KEINE Nachricht verarbeitet."
echo "   2. Unter 'E-Mail' das zu ueberwachende Postfach eintragen."
echo "   3. Unter 'Fax' den Versandweg waehlen und ein Testfax senden."
echo
echo " Protokoll ansehen : journalctl -u mail2fax -f"
echo " Konfiguration     : ${CONFIG_DIR}/config.yaml"
echo "-------------------------------------------------------------------"
