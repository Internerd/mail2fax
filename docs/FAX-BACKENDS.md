# Versandwege (Fax-Backends)

mail2fax kann Faxe auf vier Wegen versenden. Welcher passt, hängt davon ab,
was bei Ihnen vorhanden ist.

| Backend | Geeignet für | Zuverlässigkeit | Aufwand |
|---|---|---|---|
| [SIP](#sip--fritzbox-oder-telefonanlage) | FRITZ!Box, TK-Anlagen, SIP-Trunks | hoch | mittel |
| [Fax per E-Mail](#fax-per-e-mail) | Anbieter und Telefonanlagen mit Mail-Schnittstelle | hoch | gering |
| [HylaFAX](#hylafax) | ISDN-/T.38-Gateways, eigene Faxserver | hoch | mittel |
| [Externes Kommando](#externes-kommando) | Asterisk, 3CX, CapiSuite, eigene Skripte | hoch | mittel |
| [FRITZ!Box über die Weboberfläche](#fritzbox-über-die-weboberfläche) | AVM-Router, wenn SIP ausscheidet | eingeschränkt¹ | gering |
| [Testbetrieb](#testbetrieb) | Inbetriebnahme, keine echte Zustellung | – | – |

¹ AVM bietet für den Faxversand keine dokumentierte Schnittstelle. Siehe unten.

> **Für eine FRITZ!Box ist [SIP](#sip--fritzbox-oder-telefonanlage) der
> empfohlene Weg.** Dabei telefoniert mail2fax regulär, statt die
> Weboberfläche des Routers fernzusteuern – das bleibt von FRITZ!OS-Updates
> unberührt und funktioniert genauso an anderen Telefonanlagen.

---

## SIP – FRITZ!Box oder Telefonanlage

mail2fax meldet sich wie ein IP-Telefon an Ihrer Anlage an und überträgt das
Fax selbst. Die Signalverarbeitung (T.30 bzw. T.38) übernimmt ein lokaler
Asterisk mit `res_fax_spandsp`; mail2fax steuert ihn über das Asterisk Manager
Interface.

```
E-Mail  ──▶  mail2fax  ──▶  PDF→TIFF  ──▶  Asterisk (spandsp)  ──SIP──▶  FRITZ!Box  ──▶  Fax
```

### 1. Asterisk installieren

Im Container:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Internerd/mail2fax/main/install/sip-setup.sh)"
```

Das Skript installiert Asterisk und Ghostscript, schaltet das veraltete
`chan_sip` ab (es belegt sonst Port 5060), bindet das Konfigurations-
verzeichnis von mail2fax ein und aktiviert die lokale AMI-Schnittstelle.

Bei der Installation über `mail2fax.sh` auf dem Proxmox-Host können Sie das
im Dialog „Erweitert“ direkt mitauswählen.

### 2. IP-Telefon in der Anlage anlegen

**In der FRITZ!Box:**

1. **Telefonie → Telefoniegeräte → Neues Gerät einrichten**
2. **Telefon (mit und ohne Anrufbeantworter)** wählen → **LAN/WLAN (IP-Telefon)**
3. Namen vergeben, z. B. `mail2fax`
4. **Benutzername und Kennwort** notieren – die FRITZ!Box schlägt beides vor
5. Unter **Ausgehende Anrufe** die Rufnummer auswählen, über die gefaxt wird
6. Eingehende Anrufe können Sie abschalten – mail2fax nimmt keine an

**An anderen TK-Anlagen** legen Sie eine gewöhnliche SIP-Nebenstelle an. Wird
für ausgehende Gespräche eine Amtsholung benötigt (häufig `0`), tragen Sie
diese in mail2fax unter *Amtsholung* ein.

### 3. In mail2fax eintragen

Weboberfläche → **Fax** → Versandweg **SIP (FRITZ!Box / Telefonanlage)**:

| Feld | Beispiel | Hinweis |
|---|---|---|
| Anlage | `fritz.box` | Adresse der FRITZ!Box bzw. der Anlage |
| Benutzername | `620` | aus Schritt 2 |
| Passwort | – | aus Schritt 2 |
| Eigene Faxnummer | `+49301234567` | Absenderkennung; ohne sie weisen viele Gegenstellen das Fax ab |
| Amtsholung | leer | an TK-Anlagen oft `0` |
| National wählen | an | an der FRITZ!Box üblich |

Dann **„Speichern und Asterisk-Konfiguration anwenden“** drücken. Anschließend
muss **„Backend prüfen“** `Registered` melden.

Auf der Kommandozeile geht dasselbe mit:

```bash
mail2fax sip-apply      # Konfiguration schreiben und Asterisk neu laden
mail2fax sip-status     # Registrierung, Endpunkt und Kanäle anzeigen
mail2fax test-fax +49301234567
```

### 4. T.38 oder G.711?

| Einstellung | Wirkung |
|---|---|
| **T.38 aus** (Vorgabe) | Fax als Software-Modem über G.711. Über eine FRITZ!Box meist die zuverlässigere Wahl. |
| **T.38 an** | mail2fax fordert die Umschaltung auf T.38 an, mit Rückfall auf G.711. Sinnvoll bei SIP-Trunks, die T.38 sauber unterstützen. |

Ebenso ist **ECM** (Fehlerkorrektur) standardmäßig aus: Über eine FRITZ!Box
führt ECM häufiger zu Abbrüchen, als es hilft. Bei einem stabilen Trunk dürfen
Sie es einschalten.

### 5. Was mail2fax an Asterisk schreibt

Ausschließlich Dateien in `/etc/asterisk/mail2fax/`; die mitgelieferten
Dateien von Asterisk werden nur um je eine `#include`-Zeile ergänzt.

| Datei | Inhalt |
|---|---|
| `pjsip.conf` | Transport, Auth, Registrierung, AOR und Endpunkt (nur `alaw`/`ulaw`, `direct_media=no`) |
| `extensions.conf` | Kontext `mail2fax-send`: setzt `FAXOPT`, ruft `SendFAX` auf und meldet das Ergebnis per `UserEvent` zurück |
| `manager.conf` | AMI-Benutzer, nur von `127.0.0.1` erreichbar, mit eng gefassten Rechten |

Von Hand geänderte Werte in diesen Dateien gehen beim nächsten `sip-apply`
verloren – ändern Sie stattdessen die Einstellungen in mail2fax.

### 6. Faxweg ohne Telefonleitung prüfen

Mit `--selftest` legt das Einrichtungsskript einen Empfangskontext an. Damit
lässt sich der gesamte Weg (TIFF, Dialplan, spandsp, Rückmeldung) prüfen,
ohne dass ein echter Anruf zustande kommt:

```bash
bash install/sip-setup.sh --selftest
pytest -m integration            # aus dem Quellverzeichnis
```

Der Test sendet ein Fax von `SendFAX` an `ReceiveFAX` und prüft die empfangene
Seite. Er wird übersprungen, wenn Asterisk nicht eingerichtet ist.

### 7. Fehlersuche

```bash
mail2fax sip-status
asterisk -rx "pjsip show registrations"
asterisk -rx "core show channels"
journalctl -u asterisk -f
```

| Meldung / Symptom | Ursache und Abhilfe |
|---|---|
| `Registrierung an …: Rejected` | Benutzername oder Passwort stimmen nicht. In der FRITZ!Box unter *Telefoniegeräte* das IP-Telefon bearbeiten und die Zugangsdaten neu setzen. |
| `Registrierung an …: Unregistered` | Die Anlage ist nicht erreichbar. Adresse prüfen, aus dem Container testen: `ping fritz.box`. |
| `Registrierung …: nicht gefunden` | `mail2fax sip-apply` wurde noch nicht ausgeführt. |
| `Asterisk ist nicht erreichbar` | `systemctl status asterisk`; AMI aktiviert? (`install/sip-setup.sh` erledigt das) |
| `Anruf kam nicht zustande: Besetzt` | Die Zielnummer ist belegt – mail2fax wiederholt den Versuch automatisch. |
| `Verbindung endete ohne Faxübertragung` | Die Gegenstelle hat abgehoben, aber kein Faxsignal geliefert. Stimmt die Rufnummer? Ist es wirklich ein Faxanschluss? |
| Übertragung bricht mitten in der Seite ab | Höchste Übertragungsrate auf 9600 oder 4800 senken, ECM und T.38 aus lassen. |
| `Address already in use` im Asterisk-Protokoll | `chan_sip` belegt Port 5060. `install/sip-setup.sh` schaltet es ab; sonst in `/etc/asterisk/modules.conf` ergänzen: `noload => chan_sip.so` |
| Asterisk findet die TIFF-Datei nicht | Das Spool-Verzeichnis muss für die Gruppe `asterisk` lesbar sein. `install/sip-setup.sh` setzt das; prüfen mit `ls -ld /var/lib/mail2fax/spool` (erwartet: `drwxr-s--- mail2fax asterisk`). |

### 8. Grenzen

* **Nur ein Fax gleichzeitig** – mail2fax arbeitet die Warteschlange der Reihe
  nach ab. Das ist für den vorgesehenen Einsatzzweck ausreichend.
* **Asterisk braucht Platz und Arbeitsspeicher** – rund 200 MiB auf der Platte
  und etwa 100 MiB im Betrieb. Planen Sie den Container entsprechend.
* **Fax über VoIP bleibt empfindlich.** Paketverluste führen zu Abbrüchen. Das
  ist keine Eigenheit von mail2fax, sondern gilt für jeden Faxversand über
  VoIP-Anschlüsse.
* mail2fax **nimmt keine Faxe entgegen.** Eingehende Anrufe auf dem
  SIP-Konto werden abgewiesen.

---

## Fax per E-Mail

Die Zielrufnummer steht in der Empfängeradresse, das Dokument im Anhang.
Viele Anbieter und Telefonanlagen unterstützen das.

**Einstellungen** (*Fax → Fax per E-Mail*):

| Feld | Beispiel |
|---|---|
| Vorlage der Empfängeradresse | `{number_digits}@fax.example.net` |
| SMTP-Server | leer = Postausgang aus den E-Mail-Einstellungen |

Platzhalter:

| Platzhalter | Beispielwert |
|---|---|
| `{number}` | `+49301234567` |
| `{number_digits}` | `49301234567` |
| `{number_national}` | `0301234567` |

Die genaue Schreibweise gibt Ihr Anbieter vor. Verbreitete Muster:

```
{number_digits}@fax.example.net
fax.{number_national}@example.net
{number}@fax.example.net
```

> **Datenschutz:** Bei externen Anbietern verlassen die Faxinhalte Ihr Netz.
> Ein Auftragsverarbeitungsvertrag nach Art. 28 DSGVO ist dann in der Regel
> erforderlich – siehe [DATENSCHUTZ.md](DATENSCHUTZ.md).

---

## HylaFAX

Klassischer Faxserver unter Linux. mail2fax ruft `sendfax` auf.

```bash
apt install hylafax-client
```

**Einstellungen** (*Fax → HylaFAX*):

| Feld | Vorgabe |
|---|---|
| Pfad zu `sendfax` | `/usr/bin/sendfax` |
| Server | `localhost` |
| Port | `4559` |
| Benutzer | Konto auf dem HylaFAX-Server |
| Absenderkennung (TSI) | eigene Faxnummer |

Prüfen:

```bash
/opt/mail2fax/venv/bin/mail2fax test-backend
faxstat -h <server>        # Zustand des Servers
```

---

## Externes Kommando

Der flexibelste Weg: mail2fax ruft ein Programm Ihrer Wahl auf. Damit lässt
sich praktisch jede Telefonanlage anbinden.

**Einstellungen** (*Fax → Externes Kommando*), ein Argument je Zeile:

```
/usr/local/bin/faxsend.sh
{number}
{file}
```

Platzhalter: `{number}`, `{number_digits}`, `{number_national}`, `{file}`
(Pfad zum PDF), `{subject}`.

Das Kommando wird **ohne Shell** ausgeführt – Sonderzeichen werden nicht
interpretiert. Ein Rückgabewert von `0` gilt als Erfolg, alles andere als
Fehler; die Ausgabe landet im Protokoll.

Beispielskript:

```bash
#!/usr/bin/env bash
# /usr/local/bin/faxsend.sh <rufnummer> <pdf>
set -euo pipefail
NUMMER="$1"
DATEI="$2"

# Hier die eigene Anlage ansprechen, z. B.:
#   sendfax -d "$NUMMER" "$DATEI"
#   curl -sf -u user:pass -F "to=$NUMMER" -F "file=@$DATEI" https://anlage.local/api/fax

logger -t faxsend "Fax an ${NUMMER}: ${DATEI}"
```

Nicht vergessen: `chmod +x /usr/local/bin/faxsend.sh`. Das Skript läuft als
Benutzer `mail2fax`.

### Asterisk / FreePBX / 3CX

Diese Anlagen bieten meist eine der folgenden Möglichkeiten:

* eine **E-Mail-Schnittstelle** → besser das Backend *Fax per E-Mail* nutzen,
* ein **CLI-Werkzeug** oder eine **HTTP-API** → Backend *Externes Kommando*
  mit einem kleinen Wrapper-Skript wie oben.

---

## FRITZ!Box über die Weboberfläche

> **Erst prüfen, ob [SIP](#sip--fritzbox-oder-telefonanlage) infrage kommt.**
> Dieser Weg hier steuert die Weboberfläche der FRITZ!Box fern und kann
> durch ein FRITZ!OS-Update brechen. Er bleibt als Rückfallebene, wenn
> sich kein IP-Telefon einrichten lässt.

### Voraussetzungen

1. In der FRITZ!Box unter **Telefonie → Telefoniegeräte** eine
   **Faxfunktion** einrichten und ihr eine Rufnummer zuweisen.
2. Unter **System → FRITZ!Box-Benutzer** einen Benutzer mit der Berechtigung
   **„VoIP-Telefonie/Fax"** anlegen. Verwenden Sie nicht das
   Administratorkonto.
3. Diese Zugangsdaten in mail2fax unter *Fax → AVM FRITZ!Box* eintragen,
   zusammen mit der **eigenen Faxnummer** als Absenderkennung
   (z. B. `+49301234567`).

### Wie die Anbindung funktioniert

mail2fax meldet sich mit dem von AVM dokumentierten
Challenge-Response-Verfahren an (PBKDF2-SHA256 ab FRITZ!OS 7.24, davor MD5)
und übergibt das PDF anschließend über **dieselbe Schnittstelle, die auch die
Weboberfläche der FRITZ!Box benutzt**.

### Einschränkung – bitte lesen

**AVM bietet für den Faxversand keine dokumentierte, zugesicherte
Schnittstelle.** Ein FRITZ!OS-Update kann den Aufbau der Weboberfläche
verändern und den Versand dadurch unterbrechen. mail2fax hält Endpunkt und
Formularfelder deshalb in der Konfiguration – sie lassen sich ohne
Codeänderung anpassen:

```yaml
fax:
  fritzbox:
    endpoint: /cgi-bin/luacgi_notimeout
    form_fields:
      sid: sid
      page: page
      page_value: fx_send
      apply: apply
      recipient: 'SendFax:settings/recipient'
      sender_number: 'SendFax:settings/sender_number'
      sender_name: 'SendFax:settings/sender_name'
      subject: 'SendFax:settings/subject'
      file: UploadFax
```

So ermitteln Sie die passenden Werte bei einem Bruch:

1. Weboberfläche der FRITZ!Box im Browser öffnen, *Telefonie → Fax*.
2. Entwicklerwerkzeuge öffnen (F12), Reiter **Netzwerkanalyse**.
3. Ein Fax von Hand senden.
4. Die abgeschickte `POST`-Anfrage ansehen: Der **Pfad** gehört nach
   `endpoint`, die **Formularfeldnamen** nach `form_fields`.
5. `systemctl restart mail2fax`, danach ein Testfax senden.

Wenn Sie den Faxversand ohne solche Anpassungen dauerhaft stabil brauchen,
sind *Fax per E-Mail*, *HylaFAX* oder *Externes Kommando* die bessere Wahl.

### Fehlersuche

| Meldung | Ursache |
|---|---|
| `Anmeldung an der FRITZ!Box fehlgeschlagen` | Benutzername/Passwort falsch oder Berechtigung „VoIP-Telefonie/Fax" fehlt |
| `FRITZ!Box sperrt die Anmeldung noch für N Sekunden` | Zu viele Fehlversuche – abwarten |
| `FRITZ!Box unter … nicht erreichbar` | Adresse prüfen; aus dem Container heraus testen: `pct exec <CTID> -- curl -sI http://fritz.box` |
| `FRITZ!Box meldet einen Fehler` | Faxfunktion nicht eingerichtet oder Formularfelder passen nicht mehr (siehe oben) |
| `Für die FRITZ!Box ist keine eigene Faxnummer hinterlegt` | Absenderkennung eintragen |

Bei HTTPS mit selbstsigniertem Zertifikat die Zertifikatsprüfung abschalten
(Schalter im Formular).

---

## Testbetrieb

Das Backend **Testbetrieb** nimmt Aufträge an und protokolliert sie, sendet
aber nichts. Unabhängig davon gibt es den Schalter *Testbetrieb (dry-run)*,
der jeden anderen Versandweg stilllegt.

Nützlich, um zu prüfen, welche Nachrichten angenommen und welche Rufnummern
erkannt würden – ohne Kosten und ohne Fehlversand.

---

## Allgemeine Fehlersuche

```bash
# Backend prüfen
/opt/mail2fax/venv/bin/mail2fax test-backend

# Testfax senden
/opt/mail2fax/venv/bin/mail2fax test-fax +49301234567

# Protokoll mitlesen
journalctl -u mail2fax -f
```

Fehlgeschlagene Aufträge werden nach `retry_delay` Sekunden wiederholt
(Wartezeit verdoppelt sich je Versuch), insgesamt `max_attempts` mal.
Dauerhafte Fehler – etwa falsche Zugangsdaten – werden sofort als
endgültig erkannt und nicht wiederholt.

Einzelne Aufträge lassen sich in der Oberfläche unter **Aufträge** erneut
einplanen, solange die Dokumente noch vorhanden sind.
