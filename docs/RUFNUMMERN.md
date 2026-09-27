# Rufnummer im Betreff

Die Zielrufnummer steht im Betreff der E-Mail. Diese Seite beschreibt genau,
wie mail2fax sie erkennt – und wann es ablehnt.

## Grundsatz: Im Zweifel ablehnen statt raten

Ein Fax an die falsche Nummer ist eine Datenpanne (siehe
[DATENSCHUTZ.md](DATENSCHUTZ.md), Abschnitt 8). Eine abgelehnte Nachricht
dagegen ist nur ein Hinweis: Der Absender erhält einen
[Fehlerbericht](SENDEBERICHTE.md), der den Grund nennt, und schickt die
Nachricht korrigiert erneut.

Deshalb rät mail2fax nie. Lässt der Betreff mehr als eine Lesart zu, wird
abgelehnt.

## Empfohlene Schreibweise

```
+49301234567
```

International, ohne Leerzeichen. Diese Form ist immer eindeutig – auch wenn
im Betreff weiterer Text steht.

## Was erkannt wird

| Betreff | Ergebnis | Warum |
|---|---|---|
| `+49301234567` | `+49301234567` | empfohlene Form |
| `Fax an +49 30 1234567` | `+49301234567` | Leerzeichen gliedern die Nummer |
| `+49 (0)30 1234567` | `+49301234567` | „(0)“ entfällt bei internationaler Wahl |
| `+49030 1234567` | `+49301234567` | nach +49 folgt nie eine 0 – Schreibfehler wird korrigiert |
| `0049 30 1234567` | `+49301234567` | 00 steht für + |
| `030 1234567` | `+49301234567` | national, wird um +49 ergänzt |
| `030/1234567` | `+49301234567` | Schrägstrich als Trenner |
| `+49 89 1234567-89` | `+4989123456789` | Durchwahl mit Bindestrich |
| `+49 30 1234567, 2 Seiten` | `+49301234567` | Komma trennt eindeutig |
| `+49 30 1234567 - Angebot` | `+49301234567` | Gedankenstrich trennt eindeutig |
| `+49 30 1234567 (2 Seiten)` | `+49301234567` | Klammer trennt eindeutig |
| `Rechnung 0123456 an +49 30 1234567` | `+49301234567` | internationale Nummer hat Vorrang |
| `Az. 047110, Fax 030 1234567` | `+49301234567` | zu kurz für eine Rufnummer – Aktenzeichen |

## Wann abgelehnt wird

| Betreff | Grund |
|---|---|
| `+49 30 1234567 2 Seiten` | **Nicht eindeutig, wo die Nummer endet:** gemeint sein kann `+49301234567` oder `+493012345672` |
| `+49 30 1234567 oder +49 40 7654321` | **Mehrere Rufnummern** im Betreff |
| `Vorgang 04711001 an 030 1234567` | Zwei Ziffernfolgen, die beide Rufnummern sein könnten |
| `Rechnung Nr. 12` | Keine Rufnummer gefunden |
| `+491900123456` | Gesperrte Vorwahl (Sonderrufnummer) |
| `+43 1 234567` | Außerhalb der erlaubten Vorwahlen (Vorgabe: nur `+49`) |

Der Fehlerbericht nennt in jedem Fall den Grund – bei Mehrdeutigkeit auch
beide möglichen Lesarten.

## Die Regeln im Einzelnen

1. **Internationale Schreibweise hat Vorrang.** Enthält der Betreff eine
   Nummer mit `+` oder `00`, werden national geschriebene Ziffernfolgen
   (`0…`) nicht als Rufnummer betrachtet. So stört ein Aktenzeichen mit
   führender 0 nicht.

2. **Mindestlänge.** Eine Ziffernfolge gilt erst ab 9 Ziffern (einschließlich
   Landesvorwahl) als eigenständige Rufnummer. Für Deutschland heißt das:
   mindestens 7 Stellen ohne die führende 0 – kürzer ist keine reale
   Faxnummer. Kürzere Folgen sind Aktenzeichen, Rechnungs- oder Seitenzahlen.

3. **Leerzeichen gliedern – oder trennen.** `+49 30 1234567` ist eine Nummer,
   in `+49 30 1234567 2 Seiten` gehört die 2 aber nicht dazu. Ergibt sich bei
   einem Schnitt an einem Leerzeichen eine weitere plausible Rufnummer, ist der
   Betreff mehrdeutig und wird abgelehnt.

4. **Satzzeichen trennen eindeutig.** Komma, Gedankenstrich mit Leerzeichen
   (` - `) und eine Klammer, die keine Ziffern umschließt, beenden die
   Rufnummer. Bindestrich ohne Leerzeichen (`1234567-89`) und Schrägstrich
   (`030 / 1234567`) gehören dagegen zur Nummer.

5. **Mehrere verschiedene Nummern werden abgelehnt.** Dieselbe Nummer zweimal
   ist erlaubt.

6. **Längenbegrenzung.** Höchstens 15 Ziffern einschließlich Landesvorwahl
   (E.164).

## Gewählt wird

An einer FRITZ!Box oder TK-Anlage (Versandweg SIP, „national wählen“):

| Rufnummer | wird gewählt als |
|---|---|
| `+49301234567` | `0301234567` |
| `+431234567` (Ausland) | `00431234567` |

Davor steht gegebenenfalls die eingestellte Amtsholung. Ein `+` wird nie an
die Anlage übergeben, da es an vielen Anlagen nicht wählbar ist.

## Einstellungen

| Einstellung | Wirkung |
|---|---|
| `security.allowed_number_prefixes` | Nur diese Vorwahlen sind erlaubt (Vorgabe `+49`) |
| `security.blocked_number_prefixes` | Gesperrte Vorwahlen (Sonderrufnummern) |
| `security.accept_national_format` | `0…` akzeptieren; abgeschaltet ist nur die internationale Form erlaubt |
| `security.default_country_code` | Landesvorwahl für national geschriebene Nummern |

Wer ganz sichergehen will, schaltet `accept_national_format` ab: Dann zählt
nur noch eine Nummer mit `+` oder `00`.
