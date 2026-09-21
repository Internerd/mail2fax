#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# mail2fax - Asterisk fuer den Faxversand ueber SIP einrichten
#
# Im Container ausfuehren:
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/Internerd/mail2fax/main/install/sip-setup.sh)"
#
# Das Skript installiert Asterisk und Ghostscript, bindet das von mail2fax
# erzeugte Konfigurationsverzeichnis ein und vergibt die noetigen Rechte.
# Die eigentlichen Zugangsdaten der Anlage tragen Sie anschliessend in der
# Weboberflaeche unter "Fax" ein.
#
# Optional: --selftest legt zusaetzlich einen Empfangskontext an, mit dem sich
# der Faxweg ohne echte Telefonleitung pruefen laesst.
# ---------------------------------------------------------------------------
set -euo pipefail

APP_DIR="/opt/mail2fax"
VENV="${APP_DIR}/venv"
SERVICE_USER="mail2fax"
ASTERISK_ETC="/etc/asterisk"
M2F_ETC="${ASTERISK_ETC}/mail2fax"
SPOOL_DIR="/var/lib/mail2fax/spool"
SELFTEST="no"

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; BLUE=$'\033[0;34m'; RESET=$'\033[0m'
info() { echo "${BLUE}==>${RESET} $*"; }
ok()   { echo "${GREEN} ok ${RESET} $*"; }
warn() { echo "${YELLOW}warn${RESET} $*"; }
die()  { echo "${RED}FEHLER${RESET} $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --selftest) SELFTEST="yes" ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) die "Unbekannte Option: $1" ;;
  esac
  shift
done

[ "$(id -u)" -eq 0 ] || die "Bitte als root ausfuehren."
command -v apt-get >/dev/null 2>&1 || die "Dieses Skript setzt Debian oder Ubuntu voraus."
id -u "${SERVICE_USER}" >/dev/null 2>&1 || die "mail2fax ist nicht installiert (install/install.sh)."

# --- Pakete ----------------------------------------------------------------
info "Installiere Asterisk und Ghostscript (das dauert einige Minuten) ..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends asterisk ghostscript >/dev/null \
  || die "Installation fehlgeschlagen."

for modul in res_fax.so res_fax_spandsp.so; do
  find /usr/lib -name "${modul}" -print -quit 2>/dev/null | grep -q . \
    || die "Das Asterisk-Modul ${modul} fehlt. Ohne es kann Asterisk keine Faxe senden."
done
ok "Asterisk mit res_fax_spandsp und Ghostscript installiert"

# --- chan_sip abschalten ---------------------------------------------------
# Das veraltete chan_sip belegt sonst Port 5060, und der PJSIP-Transport von
# mail2fax kann sich nicht binden. In Asterisk 21 ist chan_sip ohnehin entfallen.
if [ -f "${ASTERISK_ETC}/modules.conf" ] && ! grep -q '^noload => chan_sip.so' "${ASTERISK_ETC}/modules.conf"; then
  cp -n "${ASTERISK_ETC}/modules.conf" "${ASTERISK_ETC}/modules.conf.vor-mail2fax" 2>/dev/null || true
  sed -i '/^\[modules\]/a noload => chan_sip.so ; mail2fax: belegt sonst Port 5060' "${ASTERISK_ETC}/modules.conf"
  ok "chan_sip abgeschaltet (gibt Port 5060 fuer PJSIP frei)"
fi

# --- Konfigurationsverzeichnis ---------------------------------------------
# Eigentuemer mail2fax (schreibt), Gruppe asterisk (liest). Das setgid-Bit
# sorgt dafuer, dass neue Dateien die Gruppe asterisk erben.
install -d -o "${SERVICE_USER}" -g asterisk -m 2750 "${M2F_ETC}"
ok "Konfigurationsverzeichnis ${M2F_ETC} angelegt"

# Asterisk muss die Faxdateien im Spool lesen koennen.
if [ -d "${SPOOL_DIR}" ]; then
  chgrp -R asterisk "${SPOOL_DIR}"
  chmod 2750 "${SPOOL_DIR}"
  ok "Spool-Verzeichnis fuer Asterisk lesbar gemacht"
fi

# --- Hauptkonfiguration einbinden ------------------------------------------
for datei in pjsip extensions manager; do
  ziel="${ASTERISK_ETC}/${datei}.conf"
  [ -f "${ziel}" ] || { warn "${ziel} fehlt - uebersprungen"; continue; }
  cp -n "${ziel}" "${ziel}.vor-mail2fax" 2>/dev/null || true
  if ! grep -q "mail2fax/${datei}.conf" "${ziel}"; then
    printf '\n; von mail2fax eingebunden\n#include "%s/%s.conf"\n' "${M2F_ETC}" "${datei}" >> "${ziel}"
    ok "${datei}.conf bindet die mail2fax-Konfiguration ein"
  fi
done

# AMI aktivieren - ohne sie kann mail2fax Asterisk nicht steuern.
if grep -qE '^\s*enabled\s*=\s*no' "${ASTERISK_ETC}/manager.conf"; then
  sed -i '0,/^\s*enabled\s*=.*/s//enabled = yes/' "${ASTERISK_ETC}/manager.conf"
  ok "Asterisk Manager Interface aktiviert"
fi
if ! grep -qE '^\s*bindaddr\s*=\s*127\.0\.0\.1' "${ASTERISK_ETC}/manager.conf"; then
  sed -i '0,/^\s*;\?\s*bindaddr\s*=.*/s//bindaddr = 127.0.0.1/' "${ASTERISK_ETC}/manager.conf"
  ok "AMI nur auf 127.0.0.1 erreichbar"
fi

# --- Optionaler Empfangskontext fuer den Selbsttest ------------------------
if [ "${SELFTEST}" = "yes" ]; then
  cat > "${M2F_ETC}/selftest.conf" <<'EOF'
; Empfangskontext fuer den Selbsttest (SendFAX -> ReceiveFAX).
; Nur zum Pruefen des Faxwegs ohne echte Telefonleitung.
[mail2fax-selftest]
exten => recv,1,Answer()
 same => n,Set(FAXOPT(ecm)=no)
 same => n,ReceiveFAX(/tmp/mail2fax-integrationstest.tif)
 same => n,Hangup()
EOF
  chown "${SERVICE_USER}:asterisk" "${M2F_ETC}/selftest.conf"
  chmod 0640 "${M2F_ETC}/selftest.conf"
  grep -q 'mail2fax/selftest.conf' "${ASTERISK_ETC}/extensions.conf" || \
    printf '#include "%s/selftest.conf"\n' "${M2F_ETC}" >> "${ASTERISK_ETC}/extensions.conf"
  ok "Empfangskontext fuer den Selbsttest angelegt"
fi

# --- systemd ---------------------------------------------------------------
systemctl enable asterisk >/dev/null 2>&1 || true
systemctl restart asterisk || die "Asterisk startet nicht (journalctl -u asterisk)."
sleep 5
systemctl is-active --quiet asterisk || die "Asterisk laeuft nicht (journalctl -u asterisk)."
ok "Asterisk laeuft"

# mail2fax darf in sein Asterisk-Verzeichnis schreiben.
if [ -f /etc/systemd/system/mail2fax.service ] && \
   ! grep -q 'asterisk/mail2fax' /etc/systemd/system/mail2fax.service; then
  sed -i 's|^ReadWritePaths=.*|& -/etc/asterisk/mail2fax|' /etc/systemd/system/mail2fax.service
  systemctl daemon-reload
  systemctl restart mail2fax || warn "mail2fax konnte nicht neu gestartet werden"
  ok "Schreibrecht fuer mail2fax ergaenzt"
fi

# --- Konfiguration erzeugen, sofern schon Zugangsdaten vorliegen -----------
if [ -x "${VENV}/bin/mail2fax" ] && "${VENV}/bin/mail2fax" show-config 2>/dev/null | grep -qE '^\s+username: .+' ; then
  info "Erzeuge Asterisk-Konfiguration aus den vorhandenen Einstellungen ..."
  # runuser gehoert zu util-linux und ist auch ohne sudo vorhanden.
  runuser -u "${SERVICE_USER}" -- "${VENV}/bin/mail2fax" sip-apply || \
    warn "Die Konfiguration konnte noch nicht erzeugt werden - bitte in der Weboberflaeche nachholen."
fi

echo
echo "-------------------------------------------------------------------"
echo " Asterisk ist fuer den Faxversand ueber SIP vorbereitet."
echo
echo " Naechste Schritte in der Weboberflaeche unter 'Fax':"
echo "   1. Versandweg 'SIP (FRITZ!Box / Telefonanlage)' auswaehlen."
echo "   2. Anlage, Benutzername, Passwort und eigene Faxnummer eintragen."
echo "      In der FRITZ!Box vorher ein IP-Telefon anlegen:"
echo "      Telefonie -> Telefoniegeraete -> Neues Geraet -> Telefon -> LAN/WLAN"
echo "   3. 'Speichern und Asterisk-Konfiguration anwenden' druecken."
echo "   4. 'Backend pruefen' muss ${GREEN}Registered${RESET} melden."
echo "   5. Testfax senden."
echo
echo " Zustand jederzeit pruefen:"
echo "   ${VENV}/bin/mail2fax sip-status"
echo "-------------------------------------------------------------------"
