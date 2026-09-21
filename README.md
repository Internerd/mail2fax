# mail2fax

**E-Mail-zu-Fax-Gateway für den Betrieb als LXC-Container auf Proxmox VE.**

mail2fax überwacht ein Postfach. Trifft dort eine E-Mail von einem zugelassenen
Absender ein, wird die **Zielrufnummer aus dem Betreff** gelesen und

* der **Anhang** als Fax versendet – oder,
* falls kein verwertbarer Anhang vorhanden ist, der **Text der E-Mail** selbst.

Konfiguriert wird alles über eine deutschsprachige Weboberfläche, die
ausschließlich aus dem lokalen Netz erreichbar ist.

[![CI](https://github.com/Internerd/mail2fax/actions/workflows/ci.yml/badge.svg)](https://github.com/Internerd/mail2fax/actions/workflows/ci.yml)
[![Lizenz: MIT](https://img.shields.io/badge/Lizenz-MIT-blue.svg)](LICENSE)

> **Hinweis zur Entstehung:** Dieses Projekt wurde unter Einsatz generativer KI
> entwickelt. Einzelheiten dazu stehen in [docs/KI-NUTZUNG.md](docs/KI-NUTZUNG.md).

---

## Inhalt

- [Funktionsumfang](#funktionsumfang)
- [Schnellinstallation auf Proxmox VE](#schnellinstallation-auf-proxmox-ve)
- [Erste Schritte nach der Installation](#erste-schritte-nach-der-installation)
- [So wird ein Fax ausgelöst](#so-wird-ein-fax-ausgelöst)
- [Versandwege](#versandwege)
- [Sicherheit](#sicherheit)
- [Betrieb](#betrieb)
- [Rechtliches](#rechtliches)
- [Mitwirken](#mitwirken)

---

## Funktionsumfang

| Bereich | Umsetzung |
|---|---|
| Posteingang | IMAP (SSL/TLS, STARTTLS), einstellbares Abfrageintervall |
| Faxinhalt | Anhang bevorzugt (PDF, Bilder, Text; optional Office über LibreOffice), sonst der Mailtext als PDF |
| Zielrufnummer | aus dem Betreff, z. B. `+49301234567` – auch `0301234567` oder `030/123 4567` |
| Zugangsschutz | Absender-Whitelist (Pflicht), Rufnummernsperren, Mengenbegrenzung |
| Versandwege | SIP (FRITZ!Box/TK-Anlage), HylaFAX, Fax-per-E-Mail-Gateway, beliebiges Kommando |
| Weboberfläche | Konfiguration, Auftragsübersicht, Protokoll, Tests – nur im lokalen Netz |
| Quittungen | optionale Statusmeldungen per SMTP an Absender und Administrator |
| Betrieb | systemd-Dienst, Wiederholversuche, Auftragshistorie mit Löschfrist |

## Schnellinstallation auf Proxmox VE

Auf der **Shell des Proxmox-Hosts** als `root` ausführen:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Internerd/mail2fax/main/mail2fax.sh)"
```

Das Skript legt einen unprivilegierten Debian-Container an, installiert
mail2fax darin und nennt am Ende die Adresse der Weboberfläche sowie das
zufällig erzeugte Erstpasswort.

**Standardwerte:** 2 CPU-Kerne, 1 GiB RAM, 4 GiB Festplatte, DHCP.
Über den Dialog „Einstellungen“ lässt sich jeder Wert anpassen.

> Führen Sie Skripte aus dem Internet nie ungelesen aus. Der Quelltext von
> [`mail2fax.sh`](mail2fax.sh) ist bewusst kurz und kommentiert gehalten.

**Alternativen** (bestehender Container, VM oder Server):

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Internerd/mail2fax/main/install/install.sh)"
```

Ausführliche Anleitung: **[docs/INSTALL.md](docs/INSTALL.md)**

## Erste Schritte nach der Installation

1. **Weboberfläche öffnen:** `http://<IP-des-Containers>:8080`
2. **Anmelden** mit dem Erstpasswort aus der Installationsausgabe und es unter
   *Sicherheit* ändern.
3. **Absender-Whitelist füllen** (*Sicherheit*). Solange sie leer ist, wird
   bewusst **keine** Nachricht verarbeitet.
4. **Postfach eintragen** (*E-Mail*) und „IMAP-Verbindung testen“ drücken.
5. **Versandweg wählen** (*Fax*) und ein Testfax senden.

## So wird ein Fax ausgelöst

Eine E-Mail an das überwachte Postfach senden – die Zielrufnummer steht im
Betreff:

```
An:       fax@example.com
Betreff:  +49301234567
Anhang:   rechnung.pdf
```

* **Mit Anhang** → der Anhang wird gefaxt.
* **Ohne Anhang** → der Text der E-Mail wird gesetzt und gefaxt.

Erkannt werden unter anderem:

| Betreff | Ergebnis |
|---|---|
| `+49301234567` | `+49301234567` |
| `Fax an +49 30 123 4567` | `+49301234567` |
| `030/1234567 – Angebot` | `+49301234567` |
| `0049 30 1234567` | `+49301234567` |
| `Rechnung Nr. 12` | abgelehnt (keine Rufnummer) |

## Versandwege

| Backend | Wofür |
|---|---|
| **SIP** | FRITZ!Box und Telefonanlagen – mail2fax meldet sich als IP-Telefon an und faxt selbst |
| **HylaFAX** | vorhandene Faxserver mit T.38-/ISDN-Gateway |
| **Fax per E-Mail** | Anbieter und Anlagen, die Faxe per Mail annehmen |
| **Externes Kommando** | alles Übrige (Asterisk, 3CX, CapiSuite, eigene Skripte) |
| **FRITZ!Box (Weboberfläche)** | Rückfallebene, wenn sich kein IP-Telefon einrichten lässt |
| **Testbetrieb** | nimmt Aufträge an, sendet nichts – für die Inbetriebnahme |

Einrichtung, Besonderheiten und Fehlersuche je Backend:
**[docs/FAX-BACKENDS.md](docs/FAX-BACKENDS.md)**

### SIP – der empfohlene Weg zur FRITZ!Box

Statt die Weboberfläche des Routers fernzusteuern, **telefoniert mail2fax
regulär**: Es meldet sich wie ein IP-Telefon an der FRITZ!Box oder
Telefonanlage an und überträgt das Fax selbst. Die Signalverarbeitung
(T.30/T.38) übernimmt ein mitinstallierter Asterisk mit spandsp.

```
E-Mail ─▶ mail2fax ─▶ PDF→TIFF ─▶ Asterisk (spandsp) ─SIP─▶ FRITZ!Box ─▶ Fax
```

Einrichtung im Container:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Internerd/mail2fax/main/install/sip-setup.sh)"
```

Danach in der FRITZ!Box ein IP-Telefon anlegen (*Telefonie → Telefoniegeräte →
Neues Gerät → Telefon → LAN/WLAN*) und dessen Zugangsdaten in mail2fax unter
*Fax* eintragen. Details, T.38-Hinweise und Fehlersuche:
[docs/FAX-BACKENDS.md](docs/FAX-BACKENDS.md#sip--fritzbox-oder-telefonanlage)

> **Zur FRITZ!Box über die Weboberfläche:** Dieser ältere Weg bleibt als
> Rückfallebene erhalten. AVM bietet dafür keine dokumentierte Schnittstelle;
> ein FRITZ!OS-Update kann ihn verändern. Endpunkt und Formularfelder sind
> deshalb konfigurierbar. Wo möglich, ist SIP vorzuziehen.

## Sicherheit

* **Absender-Whitelist ist Pflicht.** Ohne Eintrag wird nichts verarbeitet.
* **Die Weboberfläche gehört nicht ins Internet.** Der Zugriff ist auf
  konfigurierte Netze begrenzt; richten Sie keine Portweiterleitung ein.
* **Absenderadressen sind fälschbar.** Prüfen Sie SPF/DKIM/DMARC auf dem
  Mailserver oder nutzen Sie ein nur intern erreichbares Postfach.
* **Rufnummernsperren** verhindern standardmäßig Faxe an Sonderrufnummern
  (0900, 0137, 0180 …).
* **Mengenbegrenzung** bremst Fehlkonfigurationen und Mailschleifen aus.
* Der Dienst läuft als eigener Systembenutzer mit abgesicherter systemd-Unit.

Einzelheiten und Meldewege: [SECURITY.md](SECURITY.md) ·
[docs/SICHERHEIT.md](docs/SICHERHEIT.md)

## Betrieb

```bash
systemctl status mail2fax          # Zustand
journalctl -u mail2fax -f          # Protokoll mitlesen
/opt/mail2fax/venv/bin/mail2fax --help
```

| Aufgabe | Befehl |
|---|---|
| Passwort neu setzen | `mail2fax passwd` |
| Postfach einmalig prüfen | `mail2fax check-mail` |
| Testfax senden | `mail2fax test-fax +49301234567` |
| Verbindungen prüfen | `mail2fax test-imap` / `mail2fax test-backend` |
| SIP-Konfiguration anwenden | `mail2fax sip-apply` |
| SIP-Zustand anzeigen | `mail2fax sip-status` |
| Konfiguration anzeigen | `mail2fax show-config` (ohne Passwörter) |

Aktualisieren:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Internerd/mail2fax/main/install/update.sh)"
```

Sicherung, Wiederherstellung und Fehlersuche: **[docs/BETRIEB.md](docs/BETRIEB.md)**

## Rechtliches

Faxversand ist rechtlich nicht beliebig. Vor dem Produktiveinsatz bitte lesen:

* **[docs/RECHTLICHES.md](docs/RECHTLICHES.md)** – u. a. § 7 UWG (Werbefaxe sind
  ohne vorherige ausdrückliche Einwilligung unzulässig), Fernmeldegeheimnis,
  Haftungsausschluss
* **[docs/DATENSCHUTZ.md](docs/DATENSCHUTZ.md)** – DSGVO: Rechtsgrundlagen,
  Auftragsverarbeitung bei externen Fax-Anbietern, Löschfristen, TOM
* **[docs/KI-NUTZUNG.md](docs/KI-NUTZUNG.md)** – Einsatz generativer KI bei der
  Entwicklung, Urheberrecht, EU-KI-Verordnung

**Diese Unterlagen sind eine Hilfestellung, keine Rechtsberatung.**

Lizenz: [MIT](LICENSE). Die Software wird **ohne Gewähr** bereitgestellt –
insbesondere besteht keine Zusicherung, dass ein Fax zugestellt wird.

## Mitwirken

Fehlerberichte und Verbesserungen sind willkommen:
[CONTRIBUTING.md](CONTRIBUTING.md) · [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

### Entwicklung

```bash
git clone https://github.com/Internerd/mail2fax.git
cd mail2fax
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest                             # Tests
ruff check src tests               # Linter
MAIL2FAX_CONFIG=./dev.yaml MAIL2FAX_DATA_DIR=./dev-data \
  mail2fax init-config && mail2fax web --host 127.0.0.1 --port 8080
```
