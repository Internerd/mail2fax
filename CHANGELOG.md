# Änderungsverlauf

Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
die Versionierung an [Semantic Versioning](https://semver.org/lang/de/).

## [Unveröffentlicht]

### Behoben – Installation

- Beim Aufruf über `bash -c "$(curl …)"` brach `install.sh` mit
  `BASH_SOURCE[0]: unbound variable` ab und fiel beim Quellverzeichnis auf das
  aktuelle Arbeitsverzeichnis zurück – lag dort eine fremde `pyproject.toml`,
  wäre das falsche Projekt installiert worden. Lokal installiert wird jetzt
  nur noch aus einem echten mail2fax-Checkout.
- Locale-Warnungen von perl und apt im Container: Der Proxmox-Host reichte
  seine Locale durch, die im Container fehlt. Die Skripte verwenden jetzt
  `C.UTF-8`, das in jedem Debian vorhanden ist.

### Behoben – Ergebnisse des Logiktests

Die Kernlogik wurde mit realistischen Eingaben systematisch geprüft. Dabei
fielen Fehler auf, die zu einem **falschen Empfänger** oder **falschen
Inhalt** geführt hätten. Für jeden gibt es jetzt einen Regressionstest.

**Rufnummer im Betreff** – Grundsatz jetzt: *im Zweifel ablehnen statt raten*.

- `+49 (0)30 1234567` wurde zu `+490301234567` und an der Anlage als
  `00301234567` gewählt – ein Anruf nach Griechenland. Die Schreibweise `(0)`
  wird nun aufgelöst, ebenso der Tippfehler `+49030…`.
- Stand vor der Rufnummer ein Aktenzeichen mit führender 0
  (`Rechnung 0123456 an +49 30 1234567`), wurde an das Aktenzeichen gefaxt.
  Eine international geschriebene Nummer hat jetzt Vorrang; zu kurze
  Ziffernfolgen gelten nicht mehr als Rufnummer.
- Ziffern hinter der Rufnummer wurden angehängt: `+49 30 1234567 2 Seiten`
  wurde zu `+493012345672`. Lässt der Betreff offen, wo die Nummer endet,
  wird jetzt abgelehnt – mit beiden Lesarten im Fehlerbericht.
- Mehrere verschiedene Rufnummern im Betreff führen zur Ablehnung statt zur
  ersten Fundstelle.
- Auslandsnummern wurden bei nationaler Wahl mit `+` an die Anlage übergeben;
  jetzt mit `00`.
- Höchstlänge nach E.164 (15 Ziffern) statt 18.

**Inhalt des Faxes**

- Ein **Signatur-Logo wurde als Anhang gefaxt** – statt des Mailtextes und
  sogar statt eines beigefügten PDFs. Bilder, auf die der HTML-Text per
  `cid:` verweist, gelten jetzt als Teil des Textes. Echte Anhänge (auch
  Apple Mails „inline“-Anhänge) bleiben Anhänge.
- Text wurde nach Zeichenzahl umbrochen; breite Zeichen liefen über den
  rechten Rand und **fehlten auf dem Fax**. Umbrochen wird jetzt nach der
  gemessenen Breite.
- Zeichen wie ł, ř, ş und kyrillische Schrift kamen als **schwarze
  Kästchen** an. Die Textseite wird jetzt in DejaVu Sans gesetzt; der
  Installer richtet `fonts-dejavu-core` ein, das Update-Skript holt es nach.

**Absender-Whitelist**

- Ein Eintrag wie `*example.com` ließ auch `boese@nichtexample.com` durch.
  Platzhalter sind in der Domain nur noch als führendes `*.` erlaubt; die
  Domain wird exakt verglichen. Unsichere Einträge weist die Weboberfläche
  beim Speichern ab, eine von Hand bearbeitete Datei verwirft sie beim Laden.

**Betrieb**

- Zwei Testfaxe in derselben Sekunde teilten sich ein Arbeitsverzeichnis;
  das Aufräumen des ersten löschte die Dokumente des zweiten. Jeder Auftrag
  erhält nun ein eindeutiges Verzeichnis.

### Hinzugefügt

- [docs/RUFNUMMERN.md](docs/RUFNUMMERN.md): vollständige Regeln der
  Rufnummernerkennung mit Beispielen
- Ein Test liest die Beispieltabellen aus `docs/RUFNUMMERN.md` und dem README
  und prüft sie gegen den Code – die Dokumentation kann nicht mehr
  unbemerkt veralten


### Hinzugefügt

- **Sendebericht mit Übertragungsnachweis.** Beim Versandweg SIP wertet
  mail2fax die T.30-Quittung des empfangenden Faxgeräts aus. Der Bericht an
  den Absender nennt übertragene Seiten, Übertragungsrate, Auflösung, Dauer
  und die Stationskennung der Gegenstelle.
- **Fehlerbericht** an den Absender bei endgültigem Scheitern und bei
  abgelehnten Nachrichten, mit Grund, Versuchszahl und Hinweis zur
  richtigen Verwendung.
- Versandwege, die eine Übertragung nicht bestätigen können, erzeugen eine
  **Übergabebestätigung**, die den fehlenden Nachweis ausdrücklich benennt.
  Abschaltbar über `smtp.report_unconfirmed`.
- Einstellung `fax.command.confirms_delivery` für externe Kommandos, die die
  Übertragung abwarten
- Auftragsliste zeigt eine Spalte *Quittung*, das Auftragsdetail den
  vollständigen Sendebericht
- Hinweis auf der Übersicht, wenn der gewählte Versandweg keine Quittung
  liefern kann
- Die Auftragsdatenbank speichert die Angaben des Sendeberichts; bestehende
  Datenbanken werden beim Start um die neuen Spalten erweitert
- Dokumentation: [docs/SENDEBERICHTE.md](docs/SENDEBERICHTE.md)

### Behoben

- **Berichte gingen an beliebige Absender.** Eine abgelehnte Nachricht löste
  bisher auch dann eine Fehlermeldung aus, wenn der Absender *nicht* auf der
  Whitelist stand. Da der `From`-Header fälschbar ist, war mail2fax damit als
  Absender fremder Post missbrauchbar und verriet die Existenz der Adresse.
  Berichte gehen jetzt ausschließlich an Adressen der Absender-Whitelist.
- Der Erfolgsbericht behauptete keine Übertragung, belegte aber auch keine.
  Sendebericht und Übergabebestätigung sind nun getrennt und im Betreff
  unterscheidbar.
- Die von Asterisk gemeldete Auflösung (Punkte je Meter, z. B. `8031x7700`)
  wird in dpi umgerechnet: `204 x 196 dpi (fein)`

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

- `ensure_dirs` überschreibt die Rechte bestehender Verzeichnisse nicht mehr;
  der SIP-Versand braucht ein Spool-Verzeichnis mit der Gruppe `asterisk`
- Die Weboberfläche ist jetzt auch **vor** der Ersteinrichtung geschlossen:
  Solange kein Passwort gesetzt ist, führt jeder Aufruf zum
  Einrichtungsdialog. Zuvor waren in diesem Zustand alle Seiten und die
  Schnittstelle offen.
- GitHub Actions auf aktuelle Fassungen gehoben (Node-20-Abkündigung)

### Entfernt

- **Backend „FRITZ!Box über die Weboberfläche".** Es steuerte die
  Weboberfläche des Routers fern; AVM bietet dafür keine dokumentierte
  Schnittstelle, und jedes FRITZ!OS-Update konnte den Weg brechen. Für die
  FRITZ!Box ist stattdessen **SIP** vorgesehen.
  Bestehende Konfigurationen mit `backend: fritzbox` starten weiterhin,
  schalten aber auf den Testbetrieb um und weisen im Protokoll darauf hin,
  damit nichts unbeabsichtigt versendet wird.

### Behoben

- Tests schlugen unter Python 3.13 fehl: `threading.Thread` belegt dort
  selbst das Attribut `_handle`, was die gleichnamige Methode des
  Test-Servers verdeckte
- shellcheck beanstandete `A && B || C` in den Installationsskripten

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
