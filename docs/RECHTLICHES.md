# Rechtliche Hinweise

> **Kein Rechtsrat.** Dieses Dokument fasst allgemeine Anforderungen zusammen,
> die beim Betrieb eines automatisierten Faxversands in Deutschland typischerweise
> eine Rolle spielen. Es ersetzt keine Rechtsberatung und erhebt keinen Anspruch
> auf Vollständigkeit oder Aktualität. Verbindliche Auskunft erteilt nur eine
> Rechtsanwältin oder ein Rechtsanwalt.

## 1. Verantwortlichkeit

mail2fax ist ein Werkzeug. **Verantwortlich für jedes versendete Fax ist die
Person oder Organisation, die das System betreibt** – nicht die Entwickler
der Software. Das gilt für Inhalt, Empfängerauswahl und Zulässigkeit des
Versands gleichermaßen.

Die Software wird unter der MIT-Lizenz **ohne jede Gewährleistung**
bereitgestellt. Insbesondere wird nicht zugesichert, dass ein Fax den
Empfänger erreicht, vollständig übertragen wird oder lesbar ankommt. Eine
Erfolgsmeldung von mail2fax bestätigt lediglich die **Übergabe** an das
Faxsystem, nicht die Zustellung beim Empfänger.

## 2. Werbung per Fax – § 7 UWG

Das ist die praktisch wichtigste Einschränkung.

* Werbung per Telefax gilt nach **§ 7 Abs. 2 Nr. 1 UWG** als unzumutbare
  Belästigung, **wenn keine vorherige ausdrückliche Einwilligung** des
  Empfängers vorliegt.
* Das gilt **gegenüber Verbrauchern und gegenüber Unternehmen** gleichermaßen.
  Die Ausnahme für Bestandskunden aus § 7 Abs. 3 UWG gilt nur für E-Mail –
  **nicht für Fax**.
* Eine Einwilligung muss **vorher**, **ausdrücklich**, **für den konkreten
  Zweck** und nachweisbar erteilt werden. Die Nachweispflicht trifft den
  Absender.
* Verstöße können Abmahnungen, Unterlassungsansprüche, Vertragsstrafen und
  Bußgelder nach sich ziehen.

**Praktische Folge:** Setzen Sie mail2fax nicht für Massen- oder Werbeversand
ein. Für Rechnungen, Bestellungen, Anfragen und sonstige
Individualkommunikation, die der Empfänger erwartet, ist der Einsatz
unproblematisch.

Die Absender-Whitelist und die Mengenbegrenzung in mail2fax sind auch dazu
gedacht, ungewollten Massenversand zu verhindern. Umgehen Sie diese
Schutzmechanismen nicht.

## 3. Fernmeldegeheimnis und Vertraulichkeit

* Inhalte von E-Mails und Faxen unterliegen der Vertraulichkeit. Wer als
  Diensteanbieter geschäftsmäßig Telekommunikationsdienste erbringt,
  unterliegt zusätzlich dem **Fernmeldegeheimnis (§ 3 TTDSG, §§ 3, 5 TDDDG
  bzw. den Nachfolgeregelungen)**.
* Protokolle, Auftragshistorie und zwischengespeicherte Dokumente können
  vertrauliche Inhalte enthalten. Beschränken Sie den Zugriff auf den
  Personenkreis, der ihn benötigt, und halten Sie die Löschfristen ein
  (siehe [DATENSCHUTZ.md](DATENSCHUTZ.md)).
* Der Zugriff auf die Weboberfläche ist deshalb passwortgeschützt und auf das
  lokale Netz begrenzt.

## 4. Aufbewahrungspflichten

Werden per Fax **Handels- oder Geschäftsbriefe** bzw. **steuerlich relevante
Unterlagen** versendet, gelten die Aufbewahrungspflichten nach
**§ 257 HGB** und **§ 147 AO** (regelmäßig 6 bzw. 8 oder 10 Jahre, je nach
Unterlagenart und Rechtslage) sowie die **GoBD**.

mail2fax ist **kein Archivsystem**. In der Standardeinstellung werden

* Faxdateien nach erfolgreichem Versand gelöscht
  (`delete_documents_after_send: true`) und
* die Auftragshistorie nach 90 Tagen entfernt
  (`history_retention_days: 90`).

Sorgen Sie für eine revisionssichere Archivierung an anderer Stelle, wenn
Aufbewahrungspflichten bestehen. Die Historie von mail2fax genügt diesen
Anforderungen **nicht**.

## 5. Signatur und Beweiswert

Ein Fax ist **keine** elektronische Signatur im Sinne der eIDAS-Verordnung.
Wo Schriftform (§ 126 BGB) oder Textform mit besonderen Anforderungen
vorgeschrieben ist, prüfen Sie gesondert, ob ein Fax genügt. Die
Rechtsprechung zum Beweiswert von Telefaxen ist differenziert; ein
Sendeprotokoll allein beweist den Zugang in der Regel nicht.

## 6. Rufnummern und Netzbetreiber

* Übermitteln Sie als Absenderkennung nur eine Rufnummer, die Ihnen zusteht
  (**§ 120 TKG** – Verbot der Rufnummernunterdrückung bzw. -fälschung).
* Beachten Sie die Bedingungen Ihres Anbieters. Viele Anschlüsse und
  VoIP-Tarife untersagen automatisierten Massenversand.
* Faxe an Sonderrufnummern (0900, 0137, 0180 …) sind in mail2fax
  standardmäßig gesperrt. Heben Sie diese Sperren nur bewusst auf – sie
  schützen vor hohen Verbindungsentgelten.

## 7. Drittanbieter

Nutzen Sie das Backend „Fax per E-Mail“ mit einem externen Anbieter,
verlassen die Faxinhalte Ihr Netz. Dann sind zusätzlich zu beachten:

* **Auftragsverarbeitungsvertrag nach Art. 28 DSGVO** mit dem Anbieter,
* Ort der Verarbeitung (Drittlandtransfer, Art. 44 ff. DSGVO),
* die Geschäftsbedingungen des Anbieters.

Siehe [DATENSCHUTZ.md](DATENSCHUTZ.md), Abschnitt „Auftragsverarbeitung“.

## 8. Lizenz und Marken

* mail2fax steht unter der **MIT-Lizenz** (siehe [LICENSE](../LICENSE)).
  Verwendete Fremdbibliotheken und deren Lizenzen sind in
  [NOTICE](../NOTICE) aufgeführt.
* **FRITZ!Box** und **FRITZ!OS** sind Marken der AVM GmbH. **Proxmox** ist
  eine Marke der Proxmox Server Solutions GmbH. Dieses Projekt steht in
  keiner Verbindung zu diesen Unternehmen und wird von ihnen weder
  unterstützt noch geprüft. Die Nennung erfolgt ausschließlich beschreibend.
* Die Anbindung an die FRITZ!Box erfolgt über die Weboberfläche des Geräts.
  Prüfen Sie eigenverantwortlich, ob dies mit den Nutzungsbedingungen Ihres
  Geräts vereinbar ist.

## 9. Einsatz im Unternehmen

Zusätzlich können relevant werden:

* **Mitbestimmung des Betriebsrats** (§ 87 Abs. 1 Nr. 6 BetrVG), da die
  Auftragshistorie Rückschlüsse auf das Verhalten von Beschäftigten zulässt,
* interne Richtlinien zur E-Mail- und Telekommunikationsnutzung,
* das **Verzeichnis von Verarbeitungstätigkeiten** (Art. 30 DSGVO),
* branchenspezifische Vorgaben (z. B. ärztliche Schweigepflicht nach
  § 203 StGB, anwaltliche Verschwiegenheit, § 9 KWG).

## 10. Veröffentlichung auf GitHub und Impressum

Für ein rein privat oder innerbetrieblich betriebenes Systeme im lokalen Netz
besteht **keine Impressumspflicht** nach § 5 DDG (vormals § 5 TMG), da es sich
nicht um ein öffentlich zugängliches Telemedium handelt. Machen Sie die
Oberfläche öffentlich erreichbar – wovon dieses Projekt ausdrücklich abrät –,
ändert sich diese Bewertung.

Für das GitHub-Repository selbst gilt: Ein rein privat betriebenes
Open-Source-Repository ohne geschäftsmäßigen Charakter benötigt in der Regel
kein Impressum. Bei geschäftsmäßigem Angebot prüfen Sie die Pflichten nach
§ 5 DDG gesondert.
