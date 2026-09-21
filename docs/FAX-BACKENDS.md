# Versandwege (Fax-Backends)

mail2fax kann Faxe auf vier Wegen versenden. Welcher passt, hängt davon ab,
was bei Ihnen vorhanden ist.

| Backend | Geeignet für | Zuverlässigkeit | Aufwand |
|---|---|---|---|
| [Fax per E-Mail](#fax-per-e-mail) | Anbieter und Telefonanlagen mit Mail-Schnittstelle | hoch | gering |
| [HylaFAX](#hylafax) | ISDN-/T.38-Gateways, eigene Faxserver | hoch | mittel |
| [Externes Kommando](#externes-kommando) | Asterisk, 3CX, CapiSuite, eigene Skripte | hoch | mittel |
| [FRITZ!Box](#fritzbox) | AVM-Router im Heim- und Kleinbüro | eingeschränkt¹ | gering |
| [Testbetrieb](#testbetrieb) | Inbetriebnahme, keine echte Zustellung | – | – |

¹ AVM bietet keine dokumentierte Schnittstelle für den Faxversand. Siehe unten.

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

## FRITZ!Box

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
