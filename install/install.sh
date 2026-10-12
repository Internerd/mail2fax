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

# Der Proxmox-Host reicht seine Locale (z. B. en_US.UTF-8) in den Container
# durch, wo sie meist nicht installiert ist - das fuehrt zu Warnungen von
# perl und apt. C.UTF-8 ist in jedem Debian/Ubuntu vorhanden.
export LANG=C.UTF-8 LC_ALL=C.UTF-8
unset LANGUAGE

REPO_RAW="${MAIL2FAX_REPO_RAW:-https://raw.githubusercontent.com/Internerd/mail2fax/main}"
REPO_SLUG="${MAIL2FAX_REPO_SLUG:-Internerd/mail2fax}"
REPO_TARBALL="${MAIL2FAX_REPO_TARBALL:-https://github.com/${REPO_SLUG}/archive/refs/heads/main.tar.gz}"
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

# --- Verwaltung aus der Weboberflaeche ------------------------------------
# Update und Asterisk-Einrichtung brauchen root. Die Weboberflaeche legt nur
# eine Anforderungsdatei an; eine Pfad-Unit startet daraufhin ein
# root-eigenes Skript (siehe src/mail2fax/admin.py). Die Skripte liegen
# ausserhalb von /opt/mail2fax und gehoeren root - der Webdienst kann sie
# weder aendern noch austauschen.
install_admin_helpers() {
  local quelle="$1" ziel=/usr/local/lib/mail2fax skript tmp unit
  install -d -o root -g root -m 0755 "${ziel}"
  for skript in update sip-setup; do
    [ -f "${quelle}/install/${skript}.sh" ] || continue
    # Erst kopieren, dann umbenennen: Laeuft das Skript gerade selbst (Update
    # aus der Weboberflaeche), liest bash ungestoert die alte Datei weiter.
    tmp="$(mktemp "${ziel}/.${skript}.XXXXXX")"
    install -o root -g root -m 0755 "${quelle}/install/${skript}.sh" "${tmp}"
    mv -f "${tmp}" "${ziel}/${skript}.sh"
  done
  for unit in mail2fax-aktion@.service mail2fax-update.path mail2fax-sip-setup.path; do
    [ -f "${quelle}/systemd/${unit}" ] && install -m 0644 "${quelle}/systemd/${unit}" "/etc/systemd/system/${unit}"
  done
  install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" -m 0750 "${DATA_DIR}/control"
  # Status und Protokoll der Aktionen: root schreibt, mail2fax liest nur.
  install -d -o root -g "${SERVICE_USER}" -m 0750 /var/lib/mail2fax-admin
  systemctl daemon-reload
  systemctl enable --now mail2fax-update.path mail2fax-sip-setup.path >/dev/null 2>&1 \
    || warn "Pfad-Units fuer die Verwaltung aus der Weboberflaeche nicht aktiv"
}

# --- Pakete ----------------------------------------------------------------
info "Installiere Systempakete ..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
# fonts-dejavu-core: ohne sie kaemen Zeichen wie ł, ř, ş oder Kyrillisch als
# Kaestchen auf dem Fax an (die PDF-Standardschrift kennt nur Westeuropa).
apt-get install -y -qq --no-install-recommends \
  python3 python3-venv python3-pip ca-certificates curl tar fonts-dejavu-core >/dev/null
if [ "${WITH_LIBREOFFICE}" = "yes" ]; then
  info "Installiere LibreOffice fuer die Wandlung von Office-Dokumenten ..."
  apt-get install -y -qq --no-install-recommends libreoffice-core libreoffice-writer >/dev/null
fi
ok "Systempakete installiert"

# --- Benutzer und Verzeichnisse -------------------------------------------
if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd --system --home-dir "${APP_DIR}" --shell /usr/sbin/nologin "${SERVICE_USER}"
  ok "Systembenutzer ${SERVICE_USER} angelegt"
fi
mkdir -p "${APP_DIR}" "${CONFIG_DIR}" "${DATA_DIR}"

# --- Quellcode -------------------------------------------------------------
# Beim Aufruf ueber 'bash -c "$(curl ...)"' gibt es keine Skriptdatei -
# BASH_SOURCE ist dann leer. Nur wenn das Skript tatsaechlich aus einem
# Checkout gestartet wurde, wird von dort installiert; sonst von GitHub.
SCRIPT_PATH="${BASH_SOURCE[0]:-}"
SOURCE_DIR=""
REVISION=""
SCRIPT_DIR=""
if [ -n "${SCRIPT_PATH}" ] && [ -f "${SCRIPT_PATH}" ]; then
  SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_PATH}")" && pwd)"
fi
if [ -n "${SCRIPT_DIR}" ] && [ -f "${SCRIPT_DIR}/../pyproject.toml" ] \
   && grep -q '^name = "mail2fax"' "${SCRIPT_DIR}/../pyproject.toml"; then
  SOURCE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
  info "Installiere aus lokalem Verzeichnis ${SOURCE_DIR}"
else
  info "Lade Quellcode von GitHub ..."
  TMP_DIR="$(mktemp -d)"
  trap 'rm -rf "${TMP_DIR}"' EXIT
  # Den neuesten Stand als festen Commit aufloesen, damit sich spaeter sagen
  # laesst, was installiert ist (Anzeige in der Weboberflaeche).
  REVISION="$(curl -fsSL -H 'Accept: application/vnd.github+json' \
      "https://api.github.com/repos/${REPO_SLUG}/commits/main" 2>/dev/null \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["sha"], d["commit"]["committer"]["date"])' \
      2>/dev/null || true)"
  TARBALL="${REPO_TARBALL}"
  if [ -n "${REVISION}" ]; then
    TARBALL="https://github.com/${REPO_SLUG}/archive/${REVISION%% *}.tar.gz"
  fi
  curl -fsSL "${TARBALL}" -o "${TMP_DIR}/mail2fax.tar.gz" \
    || die "Quellcode konnte nicht geladen werden (${TARBALL})"
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
if [ -d "${SOURCE_DIR}/docs" ]; then
  cp -r "${SOURCE_DIR}/docs/." "${APP_DIR}/doc/" 2>/dev/null || true
fi

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

# Stand vermerken (lokale Installation: Commit des Checkouts, falls vorhanden)
if [ -z "${REVISION}" ] && command -v git >/dev/null 2>&1 && git -C "${SOURCE_DIR}" rev-parse HEAD >/dev/null 2>&1; then
  REVISION="$(git -C "${SOURCE_DIR}" log -1 --format='%H %cI')"
fi
echo "${REVISION:-unbekannt}" > "${APP_DIR}/REVISION"

# Rechte: nur root und der Dienstbenutzer duerfen die Zugangsdaten sehen.
# Programmcode (/opt/mail2fax) gehoert root: Der Dienst muss ihn nur lesen.
# Gehoerte er dem Dienstbenutzer, koennte ein kompromittierter Dienst Code
# hinterlegen, den root beim naechsten Update ausfuehrt.
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${CONFIG_DIR}" "${DATA_DIR}"
chown -R root:root "${APP_DIR}"
chmod 0755 "${APP_DIR}"
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
install_admin_helpers "${SOURCE_DIR}"

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
