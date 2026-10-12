#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# mail2fax - Update einer bestehenden Installation
#
# Im Container ausfuehren:
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/Internerd/mail2fax/main/install/update.sh)"
#
# Konfiguration und Auftragshistorie bleiben erhalten.
# ---------------------------------------------------------------------------
set -euo pipefail

# Der Proxmox-Host reicht seine Locale (z. B. en_US.UTF-8) in den Container
# durch, wo sie meist nicht installiert ist - das fuehrt zu Warnungen von
# perl und apt. C.UTF-8 ist in jedem Debian/Ubuntu vorhanden.
export LANG=C.UTF-8 LC_ALL=C.UTF-8
unset LANGUAGE

REPO_SLUG="${MAIL2FAX_REPO_SLUG:-Internerd/mail2fax}"
REPO_TARBALL="${MAIL2FAX_REPO_TARBALL:-https://github.com/${REPO_SLUG}/archive/refs/heads/main.tar.gz}"
APP_DIR="/opt/mail2fax"
CONFIG_DIR="/etc/mail2fax"
DATA_DIR="/var/lib/mail2fax"
VENV="${APP_DIR}/venv"
SERVICE_USER="mail2fax"

GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; RED=$'\033[0;31m'; BLUE=$'\033[0;34m'; RESET=$'\033[0m'
info() { echo "${BLUE}==>${RESET} $*"; }
ok()   { echo "${GREEN} ok ${RESET} $*"; }
die()  { echo "${RED}FEHLER${RESET} $*" >&2; exit 1; }
warn() { echo "${YELLOW}warn${RESET} $*"; }

[ "$(id -u)" -eq 0 ] || die "Bitte als root ausfuehren."
[ -x "${VENV}/bin/mail2fax" ] || die "Keine bestehende Installation gefunden (${VENV})."

ALT="$("${VENV}/bin/mail2fax" --version 2>/dev/null | awk '{print $2}')"
info "Installierte Version: ${ALT:-unbekannt}"

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

# --- Sicherung -------------------------------------------------------------
BACKUP="/var/backups/mail2fax-$(date +%Y%m%d-%H%M%S).tar.gz"
mkdir -p /var/backups
tar -czf "${BACKUP}" -C / "etc/mail2fax" "var/lib/mail2fax" 2>/dev/null || true
ok "Sicherung angelegt: ${BACKUP}"

# --- Quellcode -------------------------------------------------------------
REVISION=""
TMP_DIR=""
SCRIPT_PATH="${BASH_SOURCE[0]:-}"
if [ -n "${MAIL2FAX_SOURCE_DIR:-}" ]; then
  # Fuer Tests und Installationen ohne Internetzugang: lokales Quellverzeichnis.
  SOURCE_DIR="${MAIL2FAX_SOURCE_DIR}"
  info "Aktualisiere aus ${SOURCE_DIR}"
else
  info "Lade aktuelle Version ..."
  TMP_DIR="$(mktemp -d)"
  trap 'rm -rf "${TMP_DIR}"' EXIT
  REVISION="$(curl -fsSL -H 'Accept: application/vnd.github+json' \
      "https://api.github.com/repos/${REPO_SLUG}/commits/main" 2>/dev/null \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["sha"], d["commit"]["committer"]["date"])' \
      2>/dev/null || true)"
  TARBALL="${REPO_TARBALL}"
  if [ -n "${REVISION}" ]; then
    TARBALL="https://github.com/${REPO_SLUG}/archive/${REVISION%% *}.tar.gz"
  fi
  curl -fsSL "${TARBALL}" -o "${TMP_DIR}/mail2fax.tar.gz" || die "Download fehlgeschlagen."
  tar -xzf "${TMP_DIR}/mail2fax.tar.gz" -C "${TMP_DIR}"
  SOURCE_DIR="$(find "${TMP_DIR}" -maxdepth 1 -type d -name 'mail2fax-*' | head -n1)"
  [ -n "${SOURCE_DIR}" ] || die "Archiv enthaelt kein Quellverzeichnis."
fi
: "${SCRIPT_PATH}"

# --- Installation ----------------------------------------------------------
# Seit 1.1 fuer Sonderzeichen auf dem Fax noetig (siehe install.sh).
if ! dpkg -s fonts-dejavu-core >/dev/null 2>&1; then
  info "Installiere die Schrift DejaVu Sans ..."
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends fonts-dejavu-core >/dev/null \
    || echo "${YELLOW}Hinweis:${RESET} fonts-dejavu-core konnte nicht installiert werden."
fi

info "Stoppe den Dienst ..."
systemctl stop mail2fax || true

# Gehoert die Python-Umgebung noch dem Dienstbenutzer (Installationen vor
# 1.1), wird sie neu aufgebaut: Root soll keinen Code ausfuehren, den der
# Dienst haette veraendern koennen.
if [ -n "$(find "${VENV}" ! -user root -print -quit 2>/dev/null)" ]; then
  info "Baue die Python-Umgebung neu auf (sie gehoerte bisher dem Dienstbenutzer) ..."
  rm -rf "${VENV}"
  python3 -m venv "${VENV}"
fi

info "Aktualisiere die Python-Pakete ..."
"${VENV}/bin/pip" install --quiet --upgrade pip wheel
"${VENV}/bin/pip" install --quiet --upgrade "${SOURCE_DIR}" || die "Aktualisierung fehlgeschlagen."

if [ -f "${SOURCE_DIR}/systemd/mail2fax.service" ]; then
  install -m 0644 "${SOURCE_DIR}/systemd/mail2fax.service" /etc/systemd/system/mail2fax.service
  systemctl daemon-reload
fi

install -d "${APP_DIR}/doc"
[ -f "${SOURCE_DIR}/config/config.example.yaml" ] && \
  install -m 0644 "${SOURCE_DIR}/config/config.example.yaml" "${APP_DIR}/doc/config.example.yaml"
if [ -d "${SOURCE_DIR}/docs" ]; then
  cp -r "${SOURCE_DIR}/docs/." "${APP_DIR}/doc/" 2>/dev/null || true
fi

echo "${REVISION:-unbekannt}" > "${APP_DIR}/REVISION"
install_admin_helpers "${SOURCE_DIR}"

# Rechte. Beim Datenverzeichnis nur den Eigentuemer setzen, nicht die Gruppe:
# Fuer den SIP-Versand gehoert das Spool-Verzeichnis der Gruppe asterisk.
# Frueher setzte dieses Skript sie zurueck - danach konnte Asterisk die
# Faxdateien nicht mehr lesen.
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${CONFIG_DIR}"
chown -R "${SERVICE_USER}" "${DATA_DIR}"
chown -R root:root "${APP_DIR}"
chmod 0755 "${APP_DIR}"
chmod 0750 "${CONFIG_DIR}" "${DATA_DIR}"
[ -f "${CONFIG_DIR}/config.yaml" ] && chmod 0640 "${CONFIG_DIR}/config.yaml"

info "Starte den Dienst ..."
systemctl start mail2fax
sleep 3
systemctl is-active --quiet mail2fax || {
  journalctl -u mail2fax -n 30 --no-pager || true
  die "Der Dienst startet nicht. Sicherung: ${BACKUP}"
}

NEU="$("${VENV}/bin/mail2fax" --version 2>/dev/null | awk '{print $2}')"
ok "Aktualisiert: ${ALT:-unbekannt} -> ${NEU:-unbekannt}"
echo "${YELLOW}Hinweis:${RESET} Die Sicherung liegt unter ${BACKUP}."
