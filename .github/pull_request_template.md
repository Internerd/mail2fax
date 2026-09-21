## Worum geht es?

<!-- Kurze Beschreibung der Änderung und ihres Zwecks. -->

Behebt #

## Art der Änderung

- [ ] Fehlerbehebung
- [ ] Neue Funktion
- [ ] Änderung mit Auswirkung auf bestehende Installationen
- [ ] Dokumentation
- [ ] Wartung (Abhängigkeiten, Aufräumen, CI)

## Prüfungen

- [ ] `pytest` läuft fehlerfrei
- [ ] `ruff check src tests` ist sauber
- [ ] `shellcheck mail2fax.sh install/*.sh` ist sauber (falls Skripte betroffen)
- [ ] Tests für das neue Verhalten ergänzt
- [ ] Dokumentation angepasst (falls nötig)

## Wie wurde geprüft?

<!-- Womit haben Sie die Änderung ausprobiert? Welches Fax-Backend, welcher
     Mailserver, welche Proxmox-Version? -->

## Sicherheit

- [ ] Die Änderung betrifft Authentifizierung, Netzbeschränkung,
      Rufnummernprüfung oder den Umgang mit Zugangsdaten

<!-- Falls angekreuzt: Was ändert sich am Verhalten, und warum ist das sicher? -->

## Einsatz generativer KI

<!-- Siehe docs/KI-NUTZUNG.md. Bitte angeben, ob und wofür KI eingesetzt wurde. -->

- [ ] Ohne KI erstellt
- [ ] KI-gestützt erstellt und von mir geprüft
