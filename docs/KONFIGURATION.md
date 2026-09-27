# Konfigurationsreferenz

Die Konfiguration liegt unter `/etc/mail2fax/config.yaml`. Alle Werte lassen
sich auch in der Weboberfläche pflegen – dort ist der Weg bequemer und die
Datei bleibt gültig.

Nach dem Bearbeiten von Hand: `systemctl restart mail2fax`

Eine vollständig kommentierte Vorlage liegt unter
[`config/config.example.yaml`](../config/config.example.yaml) bzw. nach der
Installation unter `/opt/mail2fax/doc/config.example.yaml`.

## Allgemein

| Schlüssel | Vorgabe | Bedeutung |
|---|---|---|
| `log_level` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `history_retention_days` | `90` | Auftragshistorie löschen nach n Tagen (`0` = nie) |
| `delete_documents_after_send` | `true` | Faxdateien nach Erfolg löschen |

## `imap` – überwachtes Postfach

| Schlüssel | Vorgabe | Bedeutung |
|---|---|---|
| `enabled` | `false` | Überwachung aktiv |
| `host` / `port` | – / `993` | IMAP-Server |
| `security` | `ssl` | `ssl`, `starttls`, `none` |
| `username` / `password` | – | Zugangsdaten |
| `folder` | `INBOX` | zu überwachender Ordner |
| `poll_interval` | `60` | Sekunden zwischen zwei Abfragen (10–3600) |
| `processed_action` | `seen` | `seen`, `move`, `delete` |
| `processed_folder` | `Fax/Versendet` | Ziel bei `move` |
| `rejected_folder` | `Fax/Abgelehnt` | Ziel für abgelehnte Nachrichten |
| `max_message_size_mb` | `25` | größere Nachrichten werden übersprungen |
| `verify_tls` | `true` | Zertifikatsprüfung (nur zum Testen abschalten) |

Verarbeitet werden ausschließlich **ungelesene** Nachrichten.

## `smtp` – Sende- und Fehlerberichte

| Schlüssel | Vorgabe | Bedeutung |
|---|---|---|
| `enabled` | `false` | Postausgang für Berichte aktivieren |
| `host` / `port` | – / `587` | SMTP-Server |
| `security` | `starttls` | `starttls`, `ssl`, `none` |
| `from_address` | – | Absenderadresse |
| `notify_sender` | `true` | Sende- und Fehlerberichte an den Absender (nur Whitelist) |
| `report_unconfirmed` | `true` | auch ohne Quittung der Gegenstelle berichten |
| `admin_address` | – | zusätzliche Adresse für Fehlermeldungen |

Berichte tragen `Auto-Submitted: auto-replied` und
`X-Auto-Response-Suppress: All`, damit keine Mailschleifen entstehen.

> Berichte gehen **ausschließlich** an Adressen der Absender-Whitelist.
> Ein *Sendebericht*, der die Übertragung behauptet, entsteht nur bei
> quittierter Übertragung – siehe [SENDEBERICHTE.md](SENDEBERICHTE.md).

## `fax` – Versand

| Schlüssel | Vorgabe | Bedeutung |
|---|---|---|
| `backend` | `dummy` | `sip`, `hylafax`, `mailgateway`, `command`, `dummy` |
| `max_attempts` | `3` | Zustellversuche insgesamt |
| `retry_delay` | `300` | Sekunden bis zur Wiederholung; verdoppelt sich je Versuch |
| `dry_run` | `false` | `true` = annehmen, aber nicht senden |

### `fax.sip` – FRITZ!Box oder Telefonanlage über SIP

| Schlüssel | Vorgabe | Bedeutung |
|---|---|---|
| `server` / `port` | `fritz.box` / `5060` | Adresse der Anlage |
| `transport` | `udp` | `udp` oder `tcp` |
| `username` / `password` | – | Zugangsdaten des IP-Telefons |
| `sender_number` | – | eigene Faxnummer (Absenderkennung/TSI) |
| `station_name` | `mail2fax` | Text der Faxkopfzeile |
| `dial_prefix` | – | Amtsholung, an TK-Anlagen oft `0` |
| `dial_national` | `true` | `0301234567` statt `+49301234567` wählen |
| `t38` | `false` | T.38 anbieten; an der FRITZ!Box meist besser aus |
| `ecm` | `false` | Fehlerkorrektur; an der FRITZ!Box meist besser aus |
| `minrate` / `maxrate` | `2400` / `14400` | Übertragungsrate; bei Abbrüchen senken |
| `timeout` | `900` | Sekunden Wartezeit auf die Übertragung |
| `dial_timeout` | `60` | Sekunden Wartezeit auf das Abheben |
| `ami_host` / `ami_port` | `127.0.0.1` / `5038` | Adresse der Asterisk-Steuerung (AMI) |
| `ami_user` / `ami_password` | `mail2fax` / – | Zugang zur AMI; das Passwort erzeugt `sip-apply` selbst |
| `endpoint_name` | `mail2fax-tk` | Name des erzeugten PJSIP-Endpunkts |
| `config_dir` | `/etc/asterisk/mail2fax` | Zielverzeichnis der erzeugten Asterisk-Dateien |

Nach jeder Änderung an diesen Werten muss die Asterisk-Konfiguration neu
geschrieben werden – über die Schaltfläche in der Weboberfläche oder mit
`mail2fax sip-apply`.

### `fax.hylafax`

| Schlüssel | Vorgabe | Bedeutung |
|---|---|---|
| `binary` | `/usr/bin/sendfax` | Pfad zum HylaFAX-Client |
| `host` / `port` | `localhost` / `4559` | HylaFAX-Server |
| `user` | – | Benutzer auf dem HylaFAX-Server |
| `sender_number` | – | Absenderkennung (TSI) |
| `extra_args` | `[]` | zusätzliche Argumente für `sendfax` |
| `timeout` | `600` | Sekunden |

HylaFAX nimmt den Auftrag nur in die Warteschlange; ein belegter
[Sendebericht](SENDEBERICHTE.md) ist damit nicht möglich.

### `fax.mailgateway` – Fax per E-Mail

| Schlüssel | Vorgabe | Bedeutung |
|---|---|---|
| `recipient_template` | `{number_digits}@fax.example.net` | Empfängeradresse; Platzhalter `{number}`, `{number_digits}`, `{number_national}` |
| `subject_template` | `Fax an {number}` | Betreff der Mail an das Gateway; Platzhalter `{number}`, `{subject}` |
| `body_template` | `Automatisch erzeugt durch mail2fax.` | Text der Mail an das Gateway |
| `host`, `port`, `security`, `username`, `password`, `from_address`, `verify_tls` | – | eigener SMTP-Server; leer = Postausgang aus `smtp` |

### `fax.command` – externes Kommando

| Schlüssel | Vorgabe | Bedeutung |
|---|---|---|
| `argv` | `[]` | Kommando, ein Argument je Listeneintrag; Platzhalter `{number}`, `{number_digits}`, `{number_national}`, `{file}`, `{subject}` |
| `timeout` | `600` | Sekunden |
| `env` | `{}` | zusätzliche Umgebungsvariablen |
| `confirms_delivery` | `false` | nur einschalten, wenn das Kommando erst nach der Quittung der Gegenstelle zurückkehrt – dann gilt die Übertragung als bestätigt |

Einrichtung und Beispiele der Versandwege: [FAX-BACKENDS.md](FAX-BACKENDS.md).

> Der Wert `fritzbox` aus älteren Fassungen wird beim Laden auf `dummy`
> (Testbetrieb) abgebildet, damit der Dienst startet und nichts
> unbeabsichtigt versendet wird. Ein etwaiger `fax.fritzbox`-Abschnitt in
> der Datei wird ignoriert und kann entfernt werden.

## `content` – was gefaxt wird

| Schlüssel | Vorgabe | Bedeutung |
|---|---|---|
| `attachment_mode` | `first` | `first` = erster passender Anhang, `all` = alle |
| `allowed_extensions` | pdf, png, jpg, … | zugelassene Dateiendungen |
| `convert_office` | `false` | Office-Dokumente über LibreOffice wandeln |
| `office_extensions` | doc, docx, odt, … | welche Endungen dabei gelten |
| `max_attachment_size_mb` | `20` | größere Anhänge werden übergangen |
| `max_pages` | `30` | Auftrag wird abgelehnt, wenn überschritten (`0` = unbegrenzt) |
| `include_mail_header` | `true` | Von/Betreff/Datum auf der Textseite ausgeben |

**Regel:** Gibt es einen verwertbaren Anhang, wird dieser gefaxt. Andernfalls
wird der Text der E-Mail gesetzt. Übergangene Anhänge werden am Ende der
Textseite aufgeführt, damit der Empfänger nichts stillschweigend verpasst.

**Eingebettete Bilder sind kein Anhang.** Bilder, auf die der HTML-Text der
Mail verweist (`cid:`) – typischerweise das Logo in der Signatur –, gehören
zum Nachrichtentext und werden nicht gefaxt. Sonst würde bei jeder Mail mit
Signatur-Logo das Logo statt des Textes oder sogar statt des PDF-Anhangs
übertragen. Das gilt auch, wenn der Absender das Bild als Anhang markiert hat.
Echte Anhänge – auch solche, die Apple Mail als „inline“ kennzeichnet –
werden nicht per `cid:` eingebunden und bleiben Anhänge. Im Auftragsverlauf
steht, welche eingebetteten Bilder übergangen wurden.

**Schrift.** Die Textseite wird in DejaVu Sans gesetzt, damit auch Zeichen
wie ł, ř, ş oder kyrillische Schrift lesbar ankommen (Paket
`fonts-dejavu-core`, vom Installer eingerichtet). Fehlt die Schrift, greift
mail2fax auf Helvetica zurück – dann erscheinen solche Zeichen als Kästchen,
und das Protokoll weist darauf hin. Umbrochen wird nach der tatsächlichen
Textbreite, sodass nichts über den Rand hinausläuft.

## `security` – Zugangs- und Missbrauchsschutz

| Schlüssel | Vorgabe | Bedeutung |
|---|---|---|
| `sender_whitelist` | `[]` | **Pflicht.** Nur diese Absender lösen Faxe aus |
| `allowed_number_prefixes` | `['+49']` | erlaubte Vorwahlen (leer = alle) |
| `blocked_number_prefixes` | 0900, 0137, 0180, … | gesperrte Vorwahlen |
| `accept_national_format` | `true` | `0301234567` zu `+49301234567` normalisieren; abgeschaltet zählt nur `+…`/`00…` |
| `default_country_code` | `+49` | Landesvorwahl für die Normalisierung |
| `rate_limit_per_hour` | `20` | Faxe pro Stunde insgesamt (`0` = unbegrenzt) |
| `rate_limit_per_sender_per_hour` | `10` | Faxe je Absender und Stunde |

Die Whitelist erlaubt vollständige Adressen und Platzhalter:

```yaml
sender_whitelist:
  - chef@example.com
  - '*@intern.example.com'     # alle Adressen dieser Domain
  - 'fax-*@example.com'        # Platzhalter vor dem @
  - '*@*.example.com'          # alle Subdomains, nicht example.com selbst
```

**Platzhalter in der Domain sind nur als führendes `*.` erlaubt.** Einträge
wie `*example.com` oder `*@*example.com` würden auch
`boese@nichtexample.com` durchlassen und werden deshalb abgewiesen – in der
Weboberfläche beim Speichern, in einer von Hand bearbeiteten Datei beim
Laden (mit Hinweis im Protokoll). Ebenso zu weit gefasst und unzulässig:
`*`, `*@*` und `*@*.com`.

Ein fehlendes Pluszeichen bei den Vorwahlen wird automatisch ergänzt: `49`
wirkt wie `+49`.

Wie die Rufnummer im Betreff erkannt wird und wann mail2fax ablehnt, steht
in [RUFNUMMERN.md](RUFNUMMERN.md).

## `web` – Weboberfläche

| Schlüssel | Vorgabe | Bedeutung |
|---|---|---|
| `host` | `0.0.0.0` | Bindeadresse (Zugriff regelt `allowed_networks`) |
| `port` | `8080` | Port |
| `allowed_networks` | private Netze | nur aus diesen Netzen erreichbar (CIDR) |
| `password_hash` | – | PBKDF2-Hash; über `mail2fax passwd` setzen |
| `secret_key` | – | wird automatisch erzeugt |
| `session_timeout_minutes` | `120` | Sitzungsdauer |
| `login_attempts` | `10` | Fehlversuche je IP und 15 Minuten |

## Umgebungsvariablen

| Variable | Vorgabe | Zweck |
|---|---|---|
| `MAIL2FAX_CONFIG` | `/etc/mail2fax/config.yaml` | Pfad der Konfiguration |
| `MAIL2FAX_DATA_DIR` | `/var/lib/mail2fax` | Datenverzeichnis |

Nützlich für Testinstallationen neben dem Produktivbetrieb.
