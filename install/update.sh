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

REPO_TARBALL="${MAIL2FAX_REPO_TARBALL:-https://github.com/Internerd/mail2fax/archive/refs/heads/main.tar.gz}"
APP_DIR="/opt/mail2fax"
CONFIG_DIR="/etc/mail2fax"
DATA_DIR="/var/lib/mail2fax"
VENV="${APP_DIR}/venv"

GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; RED=$'\033[0;31m'; BLUE=$'\033[0;34m'; RESET=$'\033[0m'
info() { echo "${BLUE}==>${RESET} $*"; }
ok()   { echo "${GREEN} ok ${RESET} $*"; }
die()  { echo "${RED}FEHLER${RESET} $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Bitte als root ausfuehren."
[ -x "${VENV}/bin/mail2fax" ] || die "Keine bestehende Installation gefunden (${VENV})."

ALT="$("${VENV}/bin/mail2fax" --version 2>/dev/null | awk '{print $2}')"
info "Installierte Version: ${ALT:-unbekannt}"

# --- Sicherung -------------------------------------------------------------
BACKUP="/var/backups/mail2fax-$(date +%Y%m%d-%H%M%S).tar.gz"
mkdir -p /var/backups
tar -czf "${BACKUP}" -C / "etc/mail2fax" "var/lib/mail2fax" 2>/dev/null || true
ok "Sicherung angelegt: ${BACKUP}"

# --- Quellcode -------------------------------------------------------------
info "Lade aktuelle Version ..."
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT
curl -fsSL "${REPO_TARBALL}" -o "${TMP_DIR}/mail2fax.tar.gz" || die "Download fehlgeschlagen."
tar -xzf "${TMP_DIR}/mail2fax.tar.gz" -C "${TMP_DIR}"
SOURCE_DIR="$(find "${TMP_DIR}" -maxdepth 1 -type d -name 'mail2fax-*' | head -n1)"
[ -n "${SOURCE_DIR}" ] || die "Archiv enthaelt kein Quellverzeichnis."

# --- Installation ----------------------------------------------------------
info "Stoppe den Dienst ..."
systemctl stop mail2fax || true

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

chown -R mail2fax:mail2fax "${CONFIG_DIR}" "${DATA_DIR}" "${APP_DIR}"
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
