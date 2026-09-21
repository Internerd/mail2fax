# Installation

## Voraussetzungen

* **Proxmox VE 7 oder neuer** (für die LXC-Installation) – alternativ ein
  beliebiges Debian 12/13- oder Ubuntu-22.04/24.04-System
* Ein **E-Mail-Postfach mit IMAP-Zugang**, das überwacht werden soll
* Ein **Versandweg für Faxe**: SIP-Anbindung an FRITZ!Box oder Telefonanlage,
  HylaFAX, ein Fax-per-E-Mail-Dienst oder ein eigenes Kommando
  (siehe [FAX-BACKENDS.md](FAX-BACKENDS.md))
* Etwa **4 GiB Festplatte**, 1 GiB RAM, 2 CPU-Kerne – mit SIP-Versand
  (Asterisk) 6 GiB, mit LibreOffice 8 GiB

---

## Weg 1 – LXC auf Proxmox VE (empfohlen)

Auf der Shell des **Proxmox-Hosts** als `root`:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Internerd/mail2fax/main/mail2fax.sh)"
```

Der Ablauf:

1. Rückfrage, ob die **Standardeinstellungen** genügen (2 Kerne, 1 GiB RAM,
   4 GiB Platte, DHCP, unprivilegiert) oder ob Sie alles selbst festlegen
   möchten.
2. Auswahl des **Speicherorts** für Container und Vorlage.
3. Die **Debian-Vorlage** wird geladen, falls sie noch fehlt.
4. Der Container wird angelegt, gestartet und mail2fax darin installiert.
5. Am Ende erscheinen **IP-Adresse, Adresse der Weboberfläche und das
   Erstpasswort**.

> Notieren Sie das Erstpasswort. Es wird nur einmal angezeigt. Vergessen ist
> kein Problem – ein neues setzen Sie jederzeit mit
> `pct exec <CTID> -- /opt/mail2fax/venv/bin/mail2fax passwd`.

Bricht die Installation ab, bietet das Skript an, den unvollständigen
Container wieder zu entfernen.

### Skript vorher ansehen

Empfehlenswert – Skripte aus dem Internet gehören nicht ungelesen ausgeführt:

```bash
curl -fsSL https://raw.githubusercontent.com/Internerd/mail2fax/main/mail2fax.sh -o mail2fax.sh
less mail2fax.sh
bash mail2fax.sh
```

---

## Weg 2 – In einem bestehenden Container, einer VM oder auf einem Server

Auf dem Zielsystem als `root`:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Internerd/mail2fax/main/install/install.sh)"
```

Mit LibreOffice für Word-/ODT-Anhänge:

```bash
MAIL2FAX_LIBREOFFICE=yes bash -c "$(curl -fsSL https://raw.githubusercontent.com/Internerd/mail2fax/main/install/install.sh)"
```

Das Skript legt an:

| Pfad | Inhalt |
|---|---|
| `/opt/mail2fax/venv` | Python-Umgebung mit der Anwendung |
| `/etc/mail2fax/config.yaml` | Konfiguration (Rechte `0640`) |
| `/var/lib/mail2fax/` | Auftragsdatenbank und Spool-Verzeichnis |
| `/etc/systemd/system/mail2fax.service` | Dienst |
| Systembenutzer `mail2fax` | Dienstkonto ohne Anmeldemöglichkeit |

---

## Weg 3 – Aus dem Quelltext (Entwicklung)

```bash
git clone https://github.com/Internerd/mail2fax.git
cd mail2fax
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

export MAIL2FAX_CONFIG=./dev-config.yaml
export MAIL2FAX_DATA_DIR=./dev-data
mail2fax init-config
mail2fax passwd
mail2fax web --host 127.0.0.1 --port 8080
```

Tests und Linter:

```bash
pytest
ruff check src tests
shellcheck mail2fax.sh install/*.sh
```

---

## Einrichtung nach der Installation

### 1. Anmelden

`http://<IP-des-Containers>:8080` im Browser öffnen und mit dem Erstpasswort
anmelden. Unter **Sicherheit → Passwort ändern** ein eigenes Passwort setzen.

Die IP-Adresse finden Sie über:

```bash
pct exec <CTID> -- hostname -I
```

### 2. Absender-Whitelist füllen (zwingend)

**Sicherheit → Absender-Whitelist.** Eine Adresse je Zeile:

```
chef@example.com
buchhaltung@example.com
*@intern.example.com
```

Solange die Liste leer ist, verarbeitet mail2fax **bewusst keine** Nachricht.

### 3. Postfach eintragen

**E-Mail → Posteingang (IMAP).** Typische Werte:

| Anbieter | Server | Port | Verschlüsselung |
|---|---|---|---|
| Allgemein (IMAPS) | `imap.example.com` | 993 | SSL/TLS |
| Allgemein (STARTTLS) | `imap.example.com` | 143 | STARTTLS |

Verwenden Sie ein **eigenes Postfach nur für den Faxversand** – nicht Ihr
persönliches. Wo verfügbar, nutzen Sie ein anwendungsspezifisches Passwort.

Anschließend **„IMAP-Verbindung testen"** drücken.

Unter *Nach der Verarbeitung* legen Sie fest, was mit erledigten Nachrichten
geschieht: als gelesen markieren, in einen Ordner verschieben oder löschen.
„Verschieben" ist übersichtlich, weil abgelehnte Nachrichten in einem eigenen
Ordner landen.

### 4. Statusmeldungen einrichten (optional)

**E-Mail → Postausgang (SMTP).** Damit erhält der Absender eine Rückmeldung,
ob sein Fax versendet wurde – und der Administrator eine Meldung bei Fehlern.

### 5. Versandweg einrichten

**Fax → Versandweg.** Siehe [FAX-BACKENDS.md](FAX-BACKENDS.md).

Für **FRITZ!Box oder Telefonanlage** ist SIP der empfohlene Weg. Falls noch
nicht bei der Installation mitgewählt, im Container nachholen:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Internerd/mail2fax/main/install/sip-setup.sh)"
```

Danach in der FRITZ!Box ein IP-Telefon anlegen (*Telefonie → Telefoniegeräte →
Neues Gerät → Telefon → LAN/WLAN*), dessen Zugangsdaten in mail2fax eintragen
und „Speichern und Asterisk-Konfiguration anwenden" drücken.

Danach „Backend prüfen" – es muss `Registered` melden – und ein **Testfax** an
eine eigene Nummer senden.

### 6. Probelauf

Senden Sie aus einem Postfach der Whitelist eine Mail an das überwachte
Postfach:

```
Betreff: +49301234567
Anhang:  test.pdf
```

Unter **Aufträge** verfolgen Sie den Verlauf. Läuft etwas schief, steht der
Grund im Auftragsdetail und im Protokoll.

---

## Fehlersuche bei der Installation

| Problem | Ursache und Abhilfe |
|---|---|
| `Dieses Skript laeuft nur auf einem Proxmox-VE-Host` | `mail2fax.sh` gehört auf den PVE-Host; im Container `install/install.sh` verwenden |
| `Kein Speicher mit Inhaltstyp 'vztmpl' gefunden` | In Proxmox unter *Datacenter → Storage* den Inhaltstyp „Container template" für einen Speicher aktivieren |
| `Der Container hat keine Netzwerkverbindung` | Netzwerkbrücke prüfen (`vmbr0`), bei statischer IP Gateway und Netzmaske kontrollieren |
| `Keine debian-12-standard-Vorlage verfuegbar` | `pveam update` auf dem Host ausführen |
| Installation im Container bricht ab | `pct enter <CTID>`, dann `journalctl -xe`; meist fehlender Internetzugang oder ein DNS-Problem |
| `Registrierung an …: Rejected` | Zugangsdaten des IP-Telefons stimmen nicht – in der FRITZ!Box neu setzen |
| Weboberfläche nicht erreichbar | `systemctl status mail2fax` im Container; Firewallregeln prüfen; IP mit `hostname -I` bestätigen |
| `Zugriff nur aus dem lokalen Netz erlaubt` | Ihr Netz unter *Sicherheit → Erlaubte Netze* ergänzen (CIDR, z. B. `192.168.178.0/24`) |

Weiteres in [BETRIEB.md](BETRIEB.md).
