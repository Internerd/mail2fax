# Änderungsverlauf

Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
die Versionierung an [Semantic Versioning](https://semver.org/lang/de/).

## [Unveröffentlicht]

### Hinzugefügt

- **Faxversand über SIP** an FRITZ!Box und Telefonanlagen: mail2fax meldet
  sich als IP-Telefon an und überträgt das Fax selbst. Die Signalverarbeitung
  (T.30 bzw. T.38) übernimmt ein lokal installierter Asterisk mit
  `res_fax_spandsp`, gesteuert über das Asterisk Manager Interface.
  Damit entfällt die Abhängigkeit von der Weboberfläche der FRITZ!Box.
- Wandlung der Dokumente in Fax-TIFF (CCITT Gruppe 4, 1728 px, 204×196 dpi)
  mit Ghostscript
- mail2fax erzeugt die Asterisk-Konfiguration selbst (PJSIP-Registrierung,
  Fax-Dialplan, AMI-Benutzer) – über `mail2fax sip-apply` oder die
  Schaltfläche in der Weboberfläche
- Neue Befehle `mail2fax sip-apply` und `mail2fax sip-status`
- Einrichtungsskript `install/sip-setup.sh`; die SIP-Einrichtung lässt sich
  auch direkt bei der LXC-Installation mitauswählen
- Einstellbar: T.38, ECM, Übertragungsrate, Amtsholung, nationale Wahl
- Integrationstest, der ein echtes Fax von `SendFAX` an `ReceiveFAX` sendet
  und die empfangene Seite prüft (`pytest -m integration`)

### Geändert

- Das Backend „FRITZ!Box über die Weboberfläche" bleibt erhalten, ist aber
  nicht mehr der empfohlene Weg für eine FRITZ!Box
- `ensure_dirs` überschreibt die Rechte bestehender Verzeichnisse nicht mehr;
  der SIP-Versand braucht ein Spool-Verzeichnis mit der Gruppe `asterisk`

## [1.0.0] – 2026-09-21

Erste Veröffentlichung.

### Hinzugefügt

**Kern**
- Überwachung eines IMAP-Postfachs mit einstellbarem Abfrageintervall
- Zielrufnummer aus dem Betreff (`+49…`, `0049…`, `0…`, mit Trennzeichen)
- Faxinhalt: Anhang bevorzugt, sonst der Mailtext als PDF
- Unterstützte Anhänge: PDF, PNG, JPEG, GIF, BMP, TIFF, Text; optional
  Office-Dokumente über LibreOffice
- Auftragswarteschlange mit Wiederholversuchen und steigender Wartezeit
- Schutz vor Doppelversand über die Message-ID
- Optionale Statusmeldungen per SMTP an Absender und Administrator

**Versandwege**
- AVM FRITZ!Box (Anmeldung per PBKDF2 bzw. MD5, Endpunkt konfigurierbar)
- HylaFAX über `sendfax`
- Fax per E-Mail an ein Gateway oder einen Anbieter
- Beliebiges externes Kommando
- Testbetrieb ohne tatsächlichen Versand

**Sicherheit**
- Absender-Whitelist mit Platzhaltern; ohne Eintrag wird nichts verarbeitet
- Positiv- und Negativliste für Rufnummernvorwahlen, Sonderrufnummern
  standardmäßig gesperrt
- Mengenbegrenzung gesamt und je Absender
- Weboberfläche auf konfigurierbare Netze begrenzt
- Anmeldung mit PBKDF2-SHA256 (240 000 Iterationen) und Drosselung
- Sicherheitsheader ohne externe Ressourcen
- Abgesicherte systemd-Unit, eigener Systembenutzer
- Konfiguration stets mit Rechten `0640`

**Weboberfläche**
- Übersicht mit Kennzahlen, Dienststatus und Konfigurationshinweisen
- Auftragsliste und -detail mit Verlauf und manueller Wiederholung
- Einstellungsseiten für E-Mail, Fax und Sicherheit
- Verbindungstests für IMAP, SMTP und das Fax-Backend, Testfaxversand
- Protokollansicht
- Helles und dunkles Erscheinungsbild

**Installation und Betrieb**
- Installationsskript für Proxmox VE, das einen LXC anlegt und einrichtet
- Installationsskript für bestehende Debian-/Ubuntu-Systeme
- Update-Skript mit vorheriger Sicherung
- Kommandozeile für Passwort, Verbindungstests, Testfax und Diagnose
- Automatische Löschung der Auftragshistorie nach einstellbarer Frist

**Dokumentation**
- Installations-, Konfigurations-, Betriebs- und Backend-Anleitung
- Rechtliche Hinweise (u. a. § 7 UWG), Datenschutzunterlage (DSGVO),
  Sicherheitsleitfaden und Offenlegung des KI-Einsatzes

[Unveröffentlicht]: https://github.com/Internerd/mail2fax/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Internerd/mail2fax/releases/tag/v1.0.0
