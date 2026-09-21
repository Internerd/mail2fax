# Einsatz generativer KI in diesem Projekt

Dieses Dokument legt offen, in welchem Umfang bei der Entstehung von mail2fax
generative KI eingesetzt wurde, und ordnet die rechtlichen Folgen ein.

## 1. Offenlegung

**Der Quelltext und die Dokumentation dieses Projekts wurden überwiegend mit
Unterstützung eines generativen KI-Systems erstellt** (Claude von Anthropic,
eingesetzt über Claude Code). Das betrifft insbesondere:

* die Python-Anwendung unter `src/mail2fax/`,
* die Installations- und Betriebsskripte,
* die Tests unter `tests/`,
* diese Dokumentation einschließlich der rechtlichen Hinweise.

Die Erstellung erfolgte auf Grundlage einer menschlichen Anforderungs-
beschreibung. Konzeption, Auswahl der Lösungswege, Prüfung und Freigabe lagen
bei den menschlichen Projektbeteiligten.

Diese Offenlegung erfolgt freiwillig im Sinne der Transparenz. Eine allgemeine
gesetzliche Pflicht zur Kennzeichnung KI-gestützt erstellter Software besteht
in Deutschland derzeit nicht.

## 2. Was das für Nutzerinnen und Nutzer bedeutet

* **Prüfen Sie den Code, bevor Sie ihn produktiv einsetzen.** Das gilt für
  jede Software aus dem Internet, bei KI-gestützt erstelltem Code aber
  besonders: KI-Systeme erzeugen plausibel wirkenden, aber gelegentlich
  fehlerhaften Code.
* **Automatisierte Prüfungen sind vorhanden, aber kein Ersatz für Ihr
  Urteil.** Das Projekt bringt eine Testsuite (`pytest`), einen Linter
  (`ruff`) und Shell-Prüfungen (`shellcheck`) mit, die in der CI laufen.
  Diese decken nicht jeden Fehlerfall ab.
* **Keine Gewährleistung.** Siehe [LICENSE](../LICENSE) und
  [RECHTLICHES.md](RECHTLICHES.md).
* Sicherheitsrelevante Stellen – Authentifizierung, Netzbeschränkung,
  Rufnummernprüfung, Umgang mit Zugangsdaten – wurden bewusst konservativ
  ausgelegt und mit Tests abgesichert. Melden Sie Auffälligkeiten dennoch
  über [SECURITY.md](../SECURITY.md).

## 3. Urheberrecht

* Nach deutschem und europäischem Recht sind **rein maschinell erzeugte
  Inhalte nicht urheberrechtlich geschützt**, weil es an einer persönlichen
  geistigen Schöpfung im Sinne von § 2 Abs. 2 UrhG fehlt. Geschützt sein kann
  hingegen der menschliche Beitrag – Auswahl, Anordnung, Anpassung und
  Bearbeitung.
* Die Rechtslage zu KI-generiertem Code ist in Bewegung und im Einzelnen nicht
  abschließend geklärt.
* Das Projekt steht unabhängig davon unter der **MIT-Lizenz**
  (siehe [LICENSE](../LICENSE)). Die Lizenz erlaubt Nutzung, Veränderung und
  Weitergabe – auch kommerziell – unter Beibehaltung des Lizenztextes.
* Es wurde nicht bewusst Code aus fremden Projekten übernommen. Sollten Sie
  dennoch eine urheberrechtlich geschützte Passage aus einem anderen Projekt
  erkennen, melden Sie dies bitte über ein Issue; die Stelle wird dann
  entfernt oder korrekt lizenziert.

## 4. Verordnung (EU) 2024/1689 (KI-Verordnung, „AI Act“)

Einordnung dieses Projekts:

* **mail2fax ist selbst kein KI-System.** Die Anwendung enthält kein Modell
  und ruft zur Laufzeit keinen KI-Dienst auf. Sie verarbeitet E-Mails nach
  festen, nachvollziehbaren Regeln.
* Die KI-Verordnung regelt das Inverkehrbringen und den Betrieb von
  KI-Systemen. Für eine regelbasierte Anwendung, die lediglich **mit Hilfe**
  von KI entwickelt wurde, ergeben sich daraus **keine Pflichten als
  Anbieter eines KI-Systems**.
* Die Transparenzpflichten aus Art. 50 der Verordnung betreffen KI-Systeme im
  Einsatz (etwa Kennzeichnung synthetischer Inhalte gegenüber Nutzenden) und
  greifen hier nicht. Dieses Dokument dient der freiwilligen Transparenz.

Sollten Sie mail2fax erweitern und dabei KI-Funktionen zur Laufzeit ergänzen –
etwa eine automatische Erkennung von Rufnummern oder Inhalten durch ein
Sprachmodell – prüfen Sie die Pflichten aus der KI-Verordnung eigenständig neu.

## 5. Datenschutz bei der Entwicklung

Bei der Entwicklung wurden **keine personenbezogenen Daten aus dem
Produktivbetrieb** verwendet. Sämtliche Beispieldaten in Quelltext,
Dokumentation und Tests sind frei erfunden und nutzen die dafür vorgesehenen
Beispieldomänen (`example.com`, `example.org`, `example.net`) sowie
Beispielrufnummern.

## 6. Beiträge Dritter

Wenn Sie zu diesem Projekt beitragen, geben Sie bitte im Pull Request an, ob
und in welchem Umfang Sie generative KI eingesetzt haben – siehe
[CONTRIBUTING.md](../CONTRIBUTING.md). Sie bestätigen mit Ihrem Beitrag,
dass Sie die nötigen Rechte daran besitzen und ihn unter der MIT-Lizenz
beisteuern dürfen.
