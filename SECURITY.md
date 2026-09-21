# Sicherheitsrichtlinie

## Unterstützte Versionen

Sicherheitskorrekturen erscheinen für die jeweils aktuelle Version auf dem
`main`-Zweig. Ältere Stände werden nicht gepflegt.

## Schwachstellen melden

**Bitte melden Sie Sicherheitslücken nicht über ein öffentliches Issue.**

Nutzen Sie stattdessen eine der folgenden Möglichkeiten:

1. **GitHub Security Advisory** (bevorzugt):
   [Security → Report a vulnerability](https://github.com/Internerd/mail2fax/security/advisories/new)
2. Ersatzweise ein Issue **ohne technische Einzelheiten** mit der Bitte um
   einen vertraulichen Kontaktweg.

Hilfreich für die Bearbeitung:

* betroffene Version (`mail2fax --version`) und Einsatzumgebung,
* Beschreibung der Lücke und ihrer Auswirkung,
* Schritte zur Nachstellung,
* falls vorhanden: ein Vorschlag zur Behebung.

**Rückmeldung:** Wir bemühen uns um eine erste Antwort innerhalb von 14 Tagen.
Dies ist ein Freizeitprojekt ohne zugesicherte Reaktionszeiten (siehe
Gewährleistungsausschluss der MIT-Lizenz).

Wir bitten um **verantwortungsvolle Offenlegung**: Geben Sie uns angemessene
Zeit zur Behebung, bevor Sie Einzelheiten veröffentlichen. Auf Wunsch nennen
wir Sie in den Versionshinweisen.

## Geltungsbereich

**Im Geltungsbereich:**

* Umgehung der Netzbeschränkung oder der Anmeldung an der Weboberfläche
* Umgehung der Absender-Whitelist oder der Rufnummernsperren
* Offenlegung von Zugangsdaten oder Faxinhalten
* Codeausführung über verarbeitete E-Mails oder Anhänge
* Rechteausweitung innerhalb des Containers
* Schwächen in den Installationsskripten

**Außerhalb des Geltungsbereichs:**

* Fehlende HTTPS-Unterstützung – das ist eine bewusste Entscheidung für den
  Betrieb im lokalen Netz; siehe [docs/BETRIEB.md](docs/BETRIEB.md) für den
  Betrieb hinter einem Reverse Proxy.
* Fälschbare Absenderadressen in E-Mails. Das ist eine Eigenschaft des
  E-Mail-Systems; Gegenmaßnahmen sind in
  [docs/SICHERHEIT.md](docs/SICHERHEIT.md) beschrieben.
* Folgen einer bewussten Fehlkonfiguration, etwa abgeschaltete
  TLS-Zertifikatsprüfung oder `allowed_networks: ['0.0.0.0/0']`.
* Angriffe, die bereits root-Zugriff auf den Container voraussetzen.
* Schwachstellen in Fremdbibliotheken – melden Sie diese bitte beim jeweiligen
  Projekt; wir aktualisieren die Abhängigkeiten dann.

## Sicherer Betrieb

Eine ausführliche Darstellung der eingebauten Schutzmaßnahmen und der
empfohlenen Ergänzungen steht in
**[docs/SICHERHEIT.md](docs/SICHERHEIT.md)**.

Das Wichtigste in Kürze:

* Die Weboberfläche **nicht** aus dem Internet erreichbar machen.
* Die Absender-Whitelist eng halten.
* SPF/DKIM/DMARC auf dem Mailserver prüfen lassen.
* Sicherungen verschlüsseln – sie enthalten Zugangsdaten und Faxinhalte.
* Aktualisierungen einspielen.
