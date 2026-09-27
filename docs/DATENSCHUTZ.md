# Datenschutz (DSGVO)

> **Kein Rechtsrat.** Diese Unterlage unterstützt Sie dabei, den Betrieb von
> mail2fax datenschutzkonform aufzusetzen. Verantwortlich im Sinne der DSGVO
> ist die Stelle, die mail2fax betreibt – nicht die Entwickler der Software.

## 1. Welche Daten verarbeitet mail2fax?

| Datenart | Herkunft | Wo gespeichert | Aufbewahrung |
|---|---|---|---|
| E-Mail-Adresse des Absenders | eingehende Mail | Auftragsdatenbank | `history_retention_days` (Vorgabe 90 Tage) |
| Betreff der E-Mail | eingehende Mail | Auftragsdatenbank | wie oben |
| Zielrufnummer | Betreff der Mail | Auftragsdatenbank | wie oben |
| Inhalt der Mail bzw. des Anhangs | eingehende Mail | `/var/lib/mail2fax/spool` | bis zum Versand, dann gelöscht¹ |
| Zeitpunkte, Status, Fehlermeldungen | Betrieb | Auftragsdatenbank | wie oben |
| Zugangsdaten (IMAP, SMTP, Fax) | Konfiguration | `/etc/mail2fax/config.yaml` | bis zur Änderung |
| IP-Adressen von Anmeldeversuchen | Weboberfläche | nur Systemprotokoll (journald) | Aufbewahrung des Journals |

¹ Sofern `delete_documents_after_send: true` gesetzt ist (Standard).

**Nicht verarbeitet werden:** Es findet keine Übermittlung an die Entwickler,
keine Telemetrie und keine Nutzungsanalyse statt. mail2fax baut ausschließlich
Verbindungen zu den von Ihnen konfigurierten Systemen auf (IMAP-Server,
SMTP-Server, Faxgegenstelle).

## 2. Rechtsgrundlage

Die zutreffende Rechtsgrundlage hängt vom Einsatzzweck ab. In Betracht kommen
insbesondere:

* **Art. 6 Abs. 1 lit. b DSGVO** – Verarbeitung zur Erfüllung eines Vertrags
  (z. B. Versand von Rechnungen oder Bestellungen),
* **Art. 6 Abs. 1 lit. c DSGVO** – rechtliche Verpflichtung (z. B.
  Aufbewahrungs- oder Meldepflichten),
* **Art. 6 Abs. 1 lit. f DSGVO** – berechtigtes Interesse an einer
  funktionierenden Geschäftskommunikation, nach Interessenabwägung.

Werden **besondere Kategorien personenbezogener Daten** (Art. 9 DSGVO) gefaxt
– etwa Gesundheitsdaten – gelten strengere Anforderungen. Prüfen Sie in diesem
Fall gesondert und ziehen Sie eine Datenschutz-Folgenabschätzung nach
Art. 35 DSGVO in Betracht.

## 3. Verzeichnis von Verarbeitungstätigkeiten (Art. 30 DSGVO)

Bausteine für Ihren Eintrag:

* **Zweck:** automatisierter Versand von Dokumenten per Telefax aus einem
  überwachten E-Mail-Postfach
* **Betroffene Personen:** Absender der E-Mails (meist eigene Beschäftigte),
  Empfänger der Faxe, in den Dokumenten genannte Personen
* **Datenkategorien:** Kontaktdaten, Kommunikationsinhalte, Rufnummern,
  Protokolldaten
* **Empfänger:** Telefonanlage bzw. Fax-Dienstleister, Netzbetreiber
* **Löschfristen:** siehe Tabelle in Abschnitt 1
* **TOM:** siehe Abschnitt 5

## 4. Auftragsverarbeitung (Art. 28 DSGVO)

* **SIP, HylaFAX, eigenes Kommando (lokal):** Die Verarbeitung bleibt in
  Ihrer Infrastruktur. Ein Auftragsverarbeitungsvertrag ist insoweit nicht
  erforderlich – wohl aber gegenüber einem etwaigen externen IT-Dienstleister.
* **Fax per E-Mail über einen externen Anbieter:** Die Faxinhalte verlassen
  Ihr Netz. Erforderlich sind in der Regel
  * ein **Auftragsverarbeitungsvertrag nach Art. 28 DSGVO**,
  * die Prüfung des **Verarbeitungsorts** (bei Drittlandtransfer zusätzlich
    Art. 44 ff. DSGVO, z. B. Standardvertragsklauseln),
  * eine Aufnahme des Anbieters in Ihr Verarbeitungsverzeichnis.
* **E-Mail-Provider:** Auch der Betreiber des überwachten Postfachs verarbeitet
  Inhalte. Für externe Anbieter gilt das Gleiche.

**Hinweis:** Die Faxübertragung selbst ist unverschlüsselt. Für besonders
schutzbedürftige Inhalte ist Fax kein geeigneter Übertragungsweg.

## 5. Technische und organisatorische Maßnahmen (Art. 32 DSGVO)

Was mail2fax mitbringt:

* **Zugriffsbeschränkung:** Die Weboberfläche ist auf konfigurierte Netze
  begrenzt (Vorgabe: private Netze) und passwortgeschützt.
* **Passwortschutz:** Das Admin-Passwort wird nur als PBKDF2-SHA256-Hash mit
  240 000 Iterationen gespeichert, nie im Klartext. Anmeldeversuche werden
  gedrosselt.
* **Berechtigungen:** Die Konfiguration mit den Zugangsdaten wird stets mit
  `0640` gespeichert; Datenverzeichnisse mit `0750`.
* **Dienstisolierung:** Der Dienst läuft als eigener Systembenutzer mit
  abgesicherter systemd-Unit (`ProtectSystem=strict`, `NoNewPrivileges`,
  leeres `CapabilityBoundingSet`, eingeschränkter Systemaufruffilter).
* **Transportverschlüsselung:** IMAP und SMTP nutzen TLS mit
  Zertifikatsprüfung (abschaltbar, aber nicht empfohlen).
* **Datenminimierung:** Faxdateien werden nach erfolgreichem Versand gelöscht,
  die Historie nach Ablauf der eingestellten Frist.
* **Missbrauchsschutz:** Absender-Whitelist, Rufnummernsperren und
  Mengenbegrenzung.

Was Sie zusätzlich veranlassen sollten:

* **Verschlüsselung der Festplatte** des Containers bzw. des Hosts.
* **Sicherungen** des Containers – und deren Löschkonzept, denn Backups
  enthalten Faxinhalte und Zugangsdaten.
* **Netztrennung:** mail2fax gehört nicht ins Gäste- oder Internet-Segment.
* **Reverse Proxy mit HTTPS**, falls die Oberfläche über mehrere
  Netzsegmente hinweg genutzt wird (siehe [BETRIEB.md](BETRIEB.md)).
* **Protokollprüfung:** regelmäßiger Blick in `journalctl -u mail2fax`.
* **Zugriffskonzept:** Wer kennt das Admin-Passwort? Was passiert beim
  Ausscheiden dieser Person?

## 6. Löschung und Betroffenenrechte

* Die Auftragshistorie wird automatisch nach `history_retention_days` gelöscht
  (Vorgabe 90 Tage, `0` schaltet die automatische Löschung ab).
* Setzen Sie die Frist so kurz wie möglich und so lang wie nötig. Beachten Sie
  dabei mögliche **Aufbewahrungspflichten** (siehe
  [RECHTLICHES.md](RECHTLICHES.md), Abschnitt 4), die einer Löschung
  entgegenstehen können.
* Einzelne Einträge lassen sich über die Datenbank entfernen:

  ```bash
  systemctl stop mail2fax
  sqlite3 /var/lib/mail2fax/mail2fax.db "DELETE FROM jobs WHERE id = 42;"
  sqlite3 /var/lib/mail2fax/mail2fax.db "DELETE FROM events WHERE job_id = 42;"
  systemctl start mail2fax
  ```

* **Auskunftsersuchen (Art. 15 DSGVO):** Relevante Daten stehen in der
  Auftragsdatenbank und im Systemjournal. Denken Sie auch an Sicherungen.

## 7. Meldepflicht bei Datenpannen

Bei einer Verletzung des Schutzes personenbezogener Daten – etwa einem Fax an
die falsche Rufnummer mit sensiblen Inhalten oder einem Abfluss der
Konfigurationsdatei – gelten die Fristen nach **Art. 33 DSGVO**
(Meldung an die Aufsichtsbehörde binnen 72 Stunden) und gegebenenfalls
**Art. 34 DSGVO** (Benachrichtigung der Betroffenen).

Die Auftragshistorie in mail2fax hilft bei der Aufklärung: Sie zeigt, welche
Nachricht wann an welche Rufnummer übergeben wurde.

## 8. Besonderer Hinweis zu Fehlversand

Eine Ziffer im Betreff genügt, um ein Fax an den falschen Empfänger zu
schicken. mail2fax ist deshalb darauf ausgelegt, **im Zweifel abzulehnen
statt zu raten** (Einzelheiten in [RUFNUMMERN.md](RUFNUMMERN.md)):

* Lässt der Betreff offen, wo die Rufnummer endet
  (`+49 30 1234567 2 Seiten`), wird abgelehnt.
* Enthält er mehrere verschiedene Rufnummern, wird abgelehnt.
* Eine international geschriebene Nummer hat Vorrang vor Ziffernfolgen mit
  führender 0, damit Aktenzeichen nicht zur Zielrufnummer werden.
* Die Schreibweise `+49 (0)30 …` wird korrekt aufgelöst und nicht als
  Auslandsgespräch gewählt.

Der Absender erfährt jede Ablehnung per Fehlerbericht, sofern er auf der
Whitelist steht.

Zusätzliche Empfehlungen:

* Die Liste `allowed_number_prefixes` eng fassen (z. B. nur `+49`).
* `accept_national_format` abschalten, wenn nur international geschriebene
  Nummern zählen sollen.
* Wo möglich, mit einem festen Empfängerkreis arbeiten und die
  Mengenbegrenzung niedrig halten.
* Vor dem Produktivbetrieb mit dem **Testbetrieb** (`dry_run`) prüfen, welche
  Rufnummern erkannt werden.
