# Sende- und Fehlerberichte

mail2fax kann dem Absender einer E-Mail zurückmelden, was aus seinem Fax
geworden ist. Dabei gelten zwei Regeln, die sich nicht abschalten lassen.

## Regel 1: Berichte gehen nur an die Absender-Whitelist

Der `From`-Header einer E-Mail ist fälschbar. Würde mail2fax auf jede
eingehende Nachricht antworten, wäre der Dienst als Absender fremder Post
missbrauchbar (Rückstreuung), und ein Fremder erfährte, dass die Adresse
existiert.

Deshalb: **Wer nicht auf der Absender-Whitelist steht, erhält keine Antwort** –
auch keine Fehlermeldung. Eine Nachricht von außen wird still abgelehnt und
erscheint nur in der Auftragsliste und im Protokoll.

Der Administrator (`smtp.admin_address`) erhält Fehlerberichte dagegen immer,
auch zu Aufträgen fremder Absender – er hat die Anlage zu betreuen.

## Regel 2: Ein Sendebericht behauptet nichts Unbelegtes

Es gibt einen Unterschied zwischen „übergeben" und „übertragen":

| | Bedeutung |
|---|---|
| **übergeben** | mail2fax hat den Auftrag an das Faxsystem weitergereicht. Ob er ankam, ist offen. |
| **übertragen** | Das **empfangende Faxgerät hat quittiert**: Am Ende der T.30-Übertragung bestätigt es den vollständigen Empfang aller Seiten. |

Nur der zweite Fall ergibt einen Sendebericht, der etwas belegt.

### Welcher Versandweg kann quittieren?

| Versandweg | Quittung | Grund |
|---|---|---|
| **SIP** | **ja** | mail2fax überträgt das Fax selbst und sieht die T.30-Quittung |
| HylaFAX | nein | `sendfax` stellt den Auftrag nur in die Warteschlange |
| Fax per E-Mail | nein | der Anbieter bestätigt – wenn überhaupt – mit eigener Post |
| Externes Kommando | einstellbar | siehe unten |
| Testbetrieb | nein | es wird nichts gesendet |

Für einen belastbaren Sendebericht ist also der Versandweg **SIP** nötig.

Beim **externen Kommando** weiß nur der Betreiber, ob sein Skript die
Übertragung abwartet. Kehrt es erst zurück, nachdem die Gegenstelle quittiert
hat, darf `fax.command.confirms_delivery: true` gesetzt werden – dann weist
mail2fax die Übertragung als bestätigt aus. Im Zweifel abgeschaltet lassen.

## Die drei Berichtsarten

### Sendebericht (bestätigt)

```
Betreff: Sendebericht: Fax an +49301234567 uebertragen (3 Seiten)

SENDEBERICHT

Das Fax wurde uebertragen und von der Gegenstelle quittiert.

Uebertragung
  Empfaenger            : +49301234567
  Gegenstelle           : +4930999888
  Seiten                : 3
  Aufloesung            : 204 x 196 dpi (fein)
  Uebertragungsrate     : 14400 bit/s
  Dauer                 : 48 s
  Abgeschlossen         : 27.09.2026 um 10:12:33
  Versandweg            : SIP (FRITZ!Box / Telefonanlage)

Ihre Nachricht
  Betreff               : Rechnung 2026-001
  Eingegangen           : 27.09.2026 um 10:11:40
  Auftragsnummer        : #42
```

Die Angaben stammen unmittelbar aus der Faxübertragung: Seitenzahl,
Übertragungsrate, Auflösung und die Stationskennung, mit der sich das
empfangende Gerät gemeldet hat.

### Übergabebestätigung (ohne Nachweis)

Kann der Versandweg nicht quittieren, sagt der Bericht das unmissverständlich –
schon im Betreff:

```
Betreff: Fax an +49301234567 uebergeben - ohne Uebertragungsnachweis
```

Wer solche Post nicht möchte, schaltet `smtp.report_unconfirmed` ab. Dann
erhält der Absender nur bei bestätigter Übertragung einen Bericht.

### Fehlerbericht

Geht bei endgültigem Scheitern hinaus – nicht bei jedem Zwischenversuch:

```
Betreff: Fehlerbericht: Fax an +49301234567 fehlgeschlagen

FEHLERBERICHT

Das Fax konnte NICHT versendet werden. Es werden keine weiteren
Versuche unternommen.

Fehler
  Empfaenger            : +49301234567
  Grund                 : Faxuebertragung fehlgeschlagen: Keine Antwort
  Versuche              : 3 von 3
  ...
```

Auch eine **abgelehnte** Nachricht erzeugt einen Fehlerbericht, sofern der
Absender auf der Whitelist steht – etwa wenn im Betreff keine Rufnummer stand
oder die Seitenzahl überschritten war. Der Bericht erklärt dann, wie es richtig
geht.

## Nach einer Aktualisierung

Der Asterisk-Dialplan meldet die Stationskennung der Gegenstelle neu mit.
Bestehende SIP-Installationen schreiben ihn deshalb einmal neu:

```bash
mail2fax sip-apply
```

Ohne diesen Schritt funktioniert alles weiter, im Sendebericht bleibt das Feld
*Gegenstelle* aber leer.

## Einstellungen

Weboberfläche → **E-Mail → Postausgang**:

| Einstellung | Wirkung |
|---|---|
| Statusmeldungen versenden (`smtp.enabled`) | Grundschalter für allen Postausgang |
| Berichte an den Absender (`smtp.notify_sender`) | Sende- und Fehlerberichte an gelistete Absender |
| Auch ohne Nachweis berichten (`smtp.report_unconfirmed`) | Übergabebestätigungen zulassen |
| Adresse für Fehlermeldungen (`smtp.admin_address`) | Kopie aller endgültigen Fehler |

## In der Oberfläche

Die Auftragsliste zeigt eine Spalte **Quittung** (`bestätigt` / `ohne`), das
Auftragsdetail den vollständigen Sendebericht samt Gegenstelle, Rate, Auflösung
und Dauer sowie den Zeitpunkt, zu dem der Bericht hinausging.

## Rechtlicher Hinweis

Ein Sendebericht belegt die **Übertragung**, nicht die Kenntnisnahme durch den
Empfänger. Die Rechtsprechung zum Beweiswert von Sendeprotokollen ist
differenziert; ein Protokoll allein beweist den Zugang in der Regel nicht.
Siehe [RECHTLICHES.md](RECHTLICHES.md), Abschnitt 5.
