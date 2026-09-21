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

## `smtp` – Statusmeldungen

| Schlüssel | Vorgabe | Bedeutung |
|---|---|---|
| `enabled` | `false` | Statusmeldungen versenden |
| `host` / `port` | – / `587` | SMTP-Server |
| `security` | `starttls` | `starttls`, `ssl`, `none` |
| `from_address` | – | Absenderadresse |
| `notify_sender` | `true` | Absender über Erfolg/Misserfolg informieren |
| `admin_address` | – | zusätzliche Adresse für Fehlermeldungen |

Statusmeldungen tragen `Auto-Submitted: auto-replied`, damit keine
Mailschleifen entstehen.

## `fax` – Versand

| Schlüssel | Vorgabe | Bedeutung |
|---|---|---|
| `backend` | `dummy` | `sip`, `fritzbox`, `hylafax`, `mailgateway`, `command`, `dummy` |
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
| `ami_*` | – | Steuerung des lokalen Asterisk; wird automatisch gesetzt |
| `endpoint_name` | `mail2fax-tk` | Name des erzeugten PJSIP-Endpunkts |
| `config_dir` | `/etc/asterisk/mail2fax` | Zielverzeichnis der erzeugten Asterisk-Dateien |

Nach jeder Änderung an diesen Werten muss die Asterisk-Konfiguration neu
geschrieben werden – über die Schaltfläche in der Weboberfläche oder mit
`mail2fax sip-apply`.

Die Unterabschnitte `fritzbox`, `hylafax`, `mailgateway` und `command` sind in
[FAX-BACKENDS.md](FAX-BACKENDS.md) beschrieben.

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

## `security` – Zugangs- und Missbrauchsschutz

| Schlüssel | Vorgabe | Bedeutung |
|---|---|---|
| `sender_whitelist` | `[]` | **Pflicht.** Nur diese Absender lösen Faxe aus |
| `allowed_number_prefixes` | `['+49']` | erlaubte Vorwahlen (leer = alle) |
| `blocked_number_prefixes` | 0900, 0137, 0180, … | gesperrte Vorwahlen |
| `accept_national_format` | `true` | `0301234567` zu `+49301234567` normalisieren |
| `default_country_code` | `+49` | Landesvorwahl für die Normalisierung |
| `rate_limit_per_hour` | `20` | Faxe pro Stunde insgesamt (`0` = unbegrenzt) |
| `rate_limit_per_sender_per_hour` | `10` | Faxe je Absender und Stunde |

Die Whitelist erlaubt vollständige Adressen und Platzhalter:

```yaml
sender_whitelist:
  - chef@example.com
  - '*@intern.example.com'
  - 'fax-*@example.com'
```

Ein fehlendes Pluszeichen bei den Vorwahlen wird automatisch ergänzt: `49`
wirkt wie `+49`.

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
