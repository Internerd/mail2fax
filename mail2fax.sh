#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# mail2fax - LXC-Installation auf einem Proxmox-VE-Host
#
# Aufruf auf der PVE-Shell (als root):
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/Internerd/mail2fax/main/mail2fax.sh)"
#
# Das Skript legt einen unprivilegierten Debian-Container an und installiert
# mail2fax darin. Es ist eigenstaendig und laedt keine fremden Bibliotheken.
#
# Lizenz: MIT - siehe LICENSE
# ---------------------------------------------------------------------------
set -euo pipefail

APP="mail2fax"
REPO_RAW="${MAIL2FAX_REPO_RAW:-https://raw.githubusercontent.com/Internerd/mail2fax/main}"
DEFAULT_TEMPLATE_PATTERN="debian-12-standard"

# Vorgabewerte (koennen im Dialog "Erweitert" geaendert werden)
var_hostname="mail2fax"
var_disk="4"
var_cores="2"
var_ram="1024"
var_bridge="vmbr0"
var_net="dhcp"
var_gateway=""
var_unprivileged="1"
var_password=""
var_storage=""
var_ctid=""
var_start_on_boot="1"
var_libreoffice="no"
var_sip="no"

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'
BLUE=$'\033[0;34m'; BOLD=$'\033[1m'; RESET=$'\033[0m'
CHECK="${GREEN}✓${RESET}"; CROSS="${RED}✗${RESET}"

msg_info()  { echo -e " ${BLUE}▸${RESET} $1"; }
msg_ok()    { echo -e " ${CHECK} $1"; }
msg_warn()  { echo -e " ${YELLOW}!${RESET} $1"; }
msg_error() { echo -e " ${CROSS} ${RED}$1${RESET}" >&2; }

die() { msg_error "$1"; exit 1; }

cleanup_on_error() {
  local code=$?
  if [ "${code}" -ne 0 ] && [ -n "${var_ctid}" ] && pct status "${var_ctid}" >/dev/null 2>&1; then
    echo
    msg_warn "Die Einrichtung wurde abgebrochen."
    if whiptail --backtitle "${APP}" --title "Abbruch" \
        --yesno "Soll der unvollstaendige Container ${var_ctid} entfernt werden?" 10 60; then
      pct stop "${var_ctid}" >/dev/null 2>&1 || true
      pct destroy "${var_ctid}" >/dev/null 2>&1 || true
      msg_ok "Container ${var_ctid} entfernt."
    fi
  fi
  exit "${code}"
}
trap cleanup_on_error EXIT

header() {
  clear
  cat <<'BANNER'
                 _ _ ____   __
   _ __ ___   __ _(_) |___ \ / _| __ ___  __
  | '_ ` _ \ / _` | | | __) | |_ / _` \ \/ /
  | | | | | | (_| | | |/ __/|  _| (_| |>  <
  |_| |_| |_|\__,_|_|_|_____|_|  \__,_/_/\_\

BANNER
  echo "  E-Mail-zu-Fax-Gateway als Proxmox-LXC"
  echo "  ---------------------------------------------------"
  echo
}

# --- Vorpruefungen ---------------------------------------------------------

check_environment() {
  [ "$(id -u)" -eq 0 ] || die "Bitte als root auf dem Proxmox-Host ausfuehren."
  command -v pveversion >/dev/null 2>&1 || die "Dieses Skript laeuft nur auf einem Proxmox-VE-Host."
  command -v whiptail  >/dev/null 2>&1 || die "whiptail fehlt (apt install whiptail)."
  command -v pct       >/dev/null 2>&1 || die "pct fehlt - ist Proxmox VE vollstaendig installiert?"

  local version
  version="$(pveversion | grep -oP 'pve-manager/\K[0-9]+' | head -n1)"
  if [ -n "${version}" ] && [ "${version}" -lt 7 ]; then
    die "Proxmox VE ${version} wird nicht unterstuetzt. Benoetigt wird Version 7 oder neuer."
  fi
  msg_ok "Proxmox VE erkannt ($(pveversion | head -n1))"
}

next_free_ctid() {
  local id
  id="$(pvesh get /cluster/nextid 2>/dev/null || true)"
  if [ -z "${id}" ]; then
    id=100
    while pct status "${id}" >/dev/null 2>&1; do id=$((id + 1)); done
  fi
  echo "${id}"
}

# --- Auswahl der Speicherorte ---------------------------------------------

select_storage() {
  # $1 = Inhaltstyp (rootdir oder vztmpl)
  local content="$1" title="$2"
  local -a options=()
  local name type avail line

  while read -r line; do
    name="$(echo "${line}" | awk '{print $1}')"
    type="$(echo "${line}" | awk '{print $2}')"
    # Spalten von "pvesm status": Name Type Status Total Used Available %
    avail="$(echo "${line}" | awk '{print $6}')"
    [ -z "${name}" ] && continue
    options+=("${name}" "Typ: ${type} | frei: $((avail / 1024 / 1024)) GiB" "OFF")
  done < <(pvesm status -content "${content}" 2>/dev/null | awk 'NR>1 {print}')

  [ "${#options[@]}" -eq 0 ] && die "Kein Speicher mit Inhaltstyp '${content}' gefunden."

  if [ "${#options[@]}" -eq 3 ]; then
    echo "${options[0]}"
    return 0
  fi

  options[2]="ON"
  local choice
  choice="$(whiptail --backtitle "${APP}" --title "${title}" \
    --radiolist "Speicherort auswaehlen (Leertaste = auswaehlen):" 16 70 6 \
    "${options[@]}" 3>&1 1>&2 2>&3)" || die "Abgebrochen."
  echo "${choice}"
}

# --- Einstellungen ---------------------------------------------------------

default_settings() {
  var_ctid="$(next_free_ctid)"
  msg_ok "Standardeinstellungen werden verwendet"
  echo "     Container-ID : ${var_ctid}"
  echo "     Hostname     : ${var_hostname}"
  echo "     CPU / RAM    : ${var_cores} Kerne / ${var_ram} MiB"
  echo "     Festplatte   : ${var_disk} GiB"
  echo "     Netzwerk     : ${var_bridge}, DHCP"
  echo "     Typ          : unprivilegiert"
  echo
}

advanced_settings() {
  var_ctid="$(whiptail --backtitle "${APP}" --title "Container-ID" --inputbox \
    "Container-ID" 8 60 "$(next_free_ctid)" 3>&1 1>&2 2>&3)" || die "Abgebrochen."
  pct status "${var_ctid}" >/dev/null 2>&1 && die "Container-ID ${var_ctid} ist bereits vergeben."

  var_hostname="$(whiptail --backtitle "${APP}" --title "Hostname" --inputbox \
    "Hostname des Containers" 8 60 "${var_hostname}" 3>&1 1>&2 2>&3)" || die "Abgebrochen."

  var_disk="$(whiptail --backtitle "${APP}" --title "Festplatte" --inputbox \
    "Groesse der Festplatte in GiB" 8 60 "${var_disk}" 3>&1 1>&2 2>&3)" || die "Abgebrochen."

  var_cores="$(whiptail --backtitle "${APP}" --title "CPU" --inputbox \
    "Anzahl CPU-Kerne" 8 60 "${var_cores}" 3>&1 1>&2 2>&3)" || die "Abgebrochen."

  var_ram="$(whiptail --backtitle "${APP}" --title "Arbeitsspeicher" --inputbox \
    "Arbeitsspeicher in MiB" 8 60 "${var_ram}" 3>&1 1>&2 2>&3)" || die "Abgebrochen."

  var_bridge="$(whiptail --backtitle "${APP}" --title "Netzwerkbruecke" --inputbox \
    "Netzwerkbruecke" 8 60 "${var_bridge}" 3>&1 1>&2 2>&3)" || die "Abgebrochen."

  var_net="$(whiptail --backtitle "${APP}" --title "IP-Adresse" --inputbox \
    "IP-Adresse in CIDR-Schreibweise oder 'dhcp'\n\nBeispiel: 192.168.1.50/24" \
    11 60 "${var_net}" 3>&1 1>&2 2>&3)" || die "Abgebrochen."

  if [ "${var_net}" != "dhcp" ]; then
    var_gateway="$(whiptail --backtitle "${APP}" --title "Gateway" --inputbox \
      "Gateway-Adresse" 8 60 "192.168.1.1" 3>&1 1>&2 2>&3)" || die "Abgebrochen."
  fi

  if whiptail --backtitle "${APP}" --title "Container-Typ" \
      --yesno "Unprivilegierten Container anlegen?\n\n(Empfohlen - sicherer.)" 11 60; then
    var_unprivileged="1"
  else
    var_unprivileged="0"
  fi

  var_password="$(whiptail --backtitle "${APP}" --title "root-Passwort" --passwordbox \
    "root-Passwort des Containers\n\n(Leer lassen: nur Anmeldung ueber die PVE-Konsole.)" \
    11 60 3>&1 1>&2 2>&3)" || die "Abgebrochen."

  if whiptail --backtitle "${APP}" --title "Faxversand ueber SIP" \
      --yesno "Faxversand ueber SIP einrichten?\n\nmail2fax meldet sich dann als IP-Telefon an Ihrer FRITZ!Box oder Telefonanlage an und faxt selbst (Asterisk wird mitinstalliert).\n\nBenoetigt rund 200 MiB zusaetzlich." 14 68; then
    var_sip="yes"
    var_ram="$(( var_ram < 1024 ? 1024 : var_ram ))"
    var_disk="$(( var_disk < 6 ? 6 : var_disk ))"
  fi

  if whiptail --backtitle "${APP}" --title "Office-Dokumente" \
      --yesno "LibreOffice mitinstallieren?\n\nErmoeglicht das Faxen von Word-/ODT-Anhaengen, belegt aber rund 500 MiB zusaetzlich." 12 65; then
    var_libreoffice="yes"
    var_disk="$(( var_disk < 8 ? 8 : var_disk ))"
  fi

  whiptail --backtitle "${APP}" --title "Autostart" \
    --yesno "Container beim Start des Hosts automatisch starten?" 9 60 \
    && var_start_on_boot="1" || var_start_on_boot="0"
}

# --- Vorlage ---------------------------------------------------------------

ensure_template() {
  local template_storage="$1"
  msg_info "Suche Container-Vorlage ..."
  pveam update >/dev/null 2>&1 || msg_warn "Vorlagenliste konnte nicht aktualisiert werden."

  local existing
  existing="$(pveam list "${template_storage}" 2>/dev/null \
    | awk '{print $1}' | grep -E "${DEFAULT_TEMPLATE_PATTERN}.*\.(tar\.zst|tar\.gz|tar\.xz)$" | tail -n1 || true)"

  if [ -n "${existing}" ]; then
    TEMPLATE_VOLUME="${existing}"
    msg_ok "Vorlage vorhanden: $(basename "${TEMPLATE_VOLUME}")"
    return 0
  fi

  local available
  available="$(pveam available -section system 2>/dev/null \
    | awk '{print $2}' | grep -E "^${DEFAULT_TEMPLATE_PATTERN}" | tail -n1 || true)"
  [ -n "${available}" ] || die "Keine ${DEFAULT_TEMPLATE_PATTERN}-Vorlage verfuegbar."

  msg_info "Lade Vorlage ${available} (das kann einige Minuten dauern) ..."
  pveam download "${template_storage}" "${available}" >/dev/null 2>&1 \
    || die "Vorlage konnte nicht geladen werden."
  TEMPLATE_VOLUME="${template_storage}:vztmpl/${available}"
  msg_ok "Vorlage geladen: ${available}"
}

# --- Container -------------------------------------------------------------

create_container() {
  msg_info "Lege Container ${var_ctid} an ..."
  local -a args=(
    "${var_ctid}" "${TEMPLATE_VOLUME}"
    --hostname "${var_hostname}"
    --cores "${var_cores}"
    --memory "${var_ram}"
    --swap 512
    --rootfs "${var_storage}:${var_disk}"
    --unprivileged "${var_unprivileged}"
    --features nesting=1
    --onboot "${var_start_on_boot}"
    --ostype debian
    --tags "mail2fax"
  )

  if [ "${var_net}" = "dhcp" ]; then
    args+=(--net0 "name=eth0,bridge=${var_bridge},ip=dhcp")
  else
    args+=(--net0 "name=eth0,bridge=${var_bridge},ip=${var_net},gw=${var_gateway}")
  fi
  [ -n "${var_password}" ] && args+=(--password "${var_password}")

  pct create "${args[@]}" >/dev/null || die "Container konnte nicht angelegt werden."
  msg_ok "Container ${var_ctid} angelegt"

  msg_info "Starte Container ..."
  pct start "${var_ctid}" >/dev/null || die "Container konnte nicht gestartet werden."

  local tries=0
  until pct exec "${var_ctid}" -- test -f /run/systemd/system 2>/dev/null || [ "${tries}" -ge 30 ]; do
    sleep 2; tries=$((tries + 1))
  done
  msg_ok "Container laeuft"

  msg_info "Warte auf die Netzwerkverbindung ..."
  tries=0
  until pct exec "${var_ctid}" -- getent hosts deb.debian.org >/dev/null 2>&1 || [ "${tries}" -ge 30 ]; do
    sleep 2; tries=$((tries + 1))
  done
  if [ "${tries}" -ge 30 ]; then
    die "Der Container hat keine Netzwerkverbindung. Bitte Bruecke und IP-Einstellungen pruefen."
  fi
  msg_ok "Netzwerkverbindung steht"
}

install_application() {
  msg_info "Installiere ${APP} im Container (das dauert einige Minuten) ..."
  pct exec "${var_ctid}" -- bash -c "
    set -e
    export DEBIAN_FRONTEND=noninteractive MAIL2FAX_LIBREOFFICE='${var_libreoffice}'
    apt-get update -qq
    apt-get install -y -qq --no-install-recommends curl ca-certificates >/dev/null
    bash -c \"\$(curl -fsSL ${REPO_RAW}/install/install.sh)\"
  " || die "Die Installation im Container ist fehlgeschlagen. Details: pct enter ${var_ctid}"

  if [ "${var_sip}" = "yes" ]; then
    msg_info "Richte Asterisk fuer den Faxversand ueber SIP ein ..."
    pct exec "${var_ctid}" -- bash -c "
      set -e
      export DEBIAN_FRONTEND=noninteractive
      bash -c \"\$(curl -fsSL ${REPO_RAW}/install/sip-setup.sh)\"
    " || die "Die SIP-Einrichtung ist fehlgeschlagen. Details: pct enter ${var_ctid}"
    msg_ok "SIP-Faxversand vorbereitet"
  fi
}

summary() {
  local ip
  ip="$(pct exec "${var_ctid}" -- hostname -I 2>/dev/null | awk '{print $1}')"
  echo
  echo "${BOLD}==================================================================${RESET}"
  echo " ${GREEN}${APP} wurde erfolgreich eingerichtet.${RESET}"
  echo
  echo "   Container-ID   : ${var_ctid}"
  echo "   Hostname       : ${var_hostname}"
  echo "   IP-Adresse     : ${ip:-unbekannt}"
  echo "   Weboberflaeche : ${BOLD}http://${ip:-<IP>}:8080${RESET}"
  echo
  echo "   Das Erstpasswort steht in der Ausgabe oberhalb dieser Zusammenfassung."
  echo "   Es kann jederzeit neu gesetzt werden mit:"
  echo "     pct exec ${var_ctid} -- /opt/mail2fax/venv/bin/mail2fax passwd"
  echo
  if [ "${var_sip}" = "yes" ]; then
  echo "   Fuer den SIP-Versand legen Sie in der FRITZ!Box ein IP-Telefon an:"
  echo "     Telefonie -> Telefoniegeraete -> Neues Geraet -> Telefon -> LAN/WLAN"
  echo "   Dessen Zugangsdaten tragen Sie in der Oberflaeche unter 'Fax' ein."
  echo
  fi
  echo "   ${YELLOW}Wichtig:${RESET} Die Oberflaeche gehoert nicht ins Internet."
  echo "   Richten Sie dafuer keine Portweiterleitung ein."
  echo "${BOLD}==================================================================${RESET}"
}

# --- Ablauf ----------------------------------------------------------------

main() {
  header
  check_environment

  if ! whiptail --backtitle "${APP}" --title "${APP} installieren" \
      --yesno "Dieses Skript legt einen Debian-LXC an und installiert darin ${APP}.\n\nFortfahren?" 11 62; then
    trap - EXIT
    echo "Abgebrochen."
    exit 0
  fi

  if whiptail --backtitle "${APP}" --title "Einstellungen" \
      --yesno "Standardeinstellungen verwenden?\n\nJa   = 2 Kerne, 1 GiB RAM, 4 GiB Platte, DHCP\nNein = alle Werte selbst festlegen" 12 62; then
    default_settings
  else
    advanced_settings
  fi

  var_storage="$(select_storage rootdir 'Speicher fuer den Container')"
  msg_ok "Container-Speicher: ${var_storage}"
  local template_storage
  template_storage="$(select_storage vztmpl 'Speicher fuer die Vorlage')"

  ensure_template "${template_storage}"
  create_container
  install_application
  summary

  trap - EXIT
}

main "$@"
