# Sicherheit im Betrieb

Diese Seite beschreibt, wie mail2fax abgesichert ist und was Sie beim Betrieb
zusätzlich tun sollten. Zum Melden von Schwachstellen siehe
[SECURITY.md](../SECURITY.md).

## Bedrohungsmodell in Kurzform

mail2fax verarbeitet **fremde Eingaben**: E-Mails samt Anhängen. Jeder, der
die Adresse des überwachten Postfachs kennt, kann Nachrichten dorthin senden.
Daraus ergeben sich drei Hauptrisiken:

1. **Unbefugter Faxversand** (Kosten, Missbrauch, Belästigung Dritter)
2. **Abfluss vertraulicher Inhalte** (Faxdateien, Zugangsdaten)
3. **Angriffe über die Weboberfläche**

## 1. Unbefugter Faxversand

| Schutzmaßnahme | Standard | Einstellung |
|---|---|---|
| Absender-Whitelist | **leer – nichts wird verarbeitet** | *Sicherheit* |
| Erlaubte Vorwahlen | `+49` | *Sicherheit* |
| Gesperrte Vorwahlen | 0900, 0137, 0180, 0181, 01900 | *Sicherheit* |
| Faxe pro Stunde | 20 | *Sicherheit* |
| Faxe je Absender und Stunde | 10 | *Sicherheit* |
| Seiten je Fax | 30 | *Fax* |

**Wichtig – Absenderadressen sind fälschbar.** mail2fax prüft den
`From`-Header. Dieser lässt sich ohne Weiteres fälschen. Härten Sie deshalb
zusätzlich ab:

* **SPF, DKIM und DMARC** auf dem Mailserver prüfen lassen und Nachrichten,
  die durchfallen, gar nicht erst zustellen.
* Oder ein Postfach verwenden, das **nur aus dem internen Netz** beliefert
  wird und von außen keine Mails annimmt.
* Serverseitige Filterregeln (z. B. Sieve) einsetzen, die nur Nachrichten
  zugelassener Absender in den überwachten Ordner legen.

Mit `dry_run: true` (*Fax → Testbetrieb*) können Sie gefahrlos beobachten,
welche Nachrichten angenommen würden.

## 2. Schutz vertraulicher Inhalte

* Die Konfiguration `/etc/mail2fax/config.yaml` enthält **Zugangsdaten im
  Klartext** und wird mit `0640` gespeichert, Eigentümer `mail2fax`.
  Ändern Sie diese Rechte nicht.
* Faxdateien liegen während der Verarbeitung unter
  `/var/lib/mail2fax/spool` (`0750`) und werden nach erfolgreichem Versand
  gelöscht, sofern `delete_documents_after_send` aktiv ist.
* **Sicherungen des Containers enthalten diese Daten ebenfalls.** Verschlüsseln
  Sie Backups und regeln Sie deren Aufbewahrung.
* Die **Faxübertragung selbst ist unverschlüsselt**. Für besonders
  schutzbedürftige Inhalte ist Fax kein geeigneter Weg.

## 3. Weboberfläche

Eingebaute Maßnahmen:

* **Netzbeschränkung:** Anfragen aus nicht zugelassenen Netzen werden mit
  HTTP 403 abgewiesen – vor jeder weiteren Verarbeitung.
  Ausgewertet wird dabei bewusst die echte Peer-Adresse, **nicht** der
  fälschbare `X-Forwarded-For`-Header.
* **Anmeldung** mit PBKDF2-SHA256 (240 000 Iterationen), zeitkonstanter
  Vergleich, Drosselung nach zu vielen Fehlversuchen (10 je 15 Minuten).
* **Sitzungen** im Arbeitsspeicher mit `HttpOnly`- und `SameSite=Strict`-Cookie;
  nach einem Passwortwechsel werden alle Sitzungen beendet.
* **Sicherheitsheader:** `Content-Security-Policy` ohne externe Quellen,
  `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer`. Es werden keinerlei externe Ressourcen
  (Schriften, Skripte, Analytics) geladen.
* Die automatische API-Dokumentation von FastAPI (`/docs`, `/openapi.json`)
  ist abgeschaltet.

**Nicht enthalten:** HTTPS. Im lokalen Netz ist HTTP vertretbar; wenn die
Oberfläche über Netzgrenzen hinweg erreichbar sein soll, setzen Sie einen
Reverse Proxy mit TLS davor (Beispiel in [BETRIEB.md](BETRIEB.md)) und
beschränken Sie `allowed_networks` entsprechend.

**Richten Sie keine Portweiterleitung aus dem Internet ein.**

## 4. Verarbeitung von Anhängen

* Es werden nur Dateitypen aus `allowed_extensions` verarbeitet; alles andere
  wird verworfen und stattdessen der Mailtext gefaxt.
* Dateinamen aus E-Mails werden von Pfadanteilen befreit und auf harmlose
  Zeichen reduziert, bevor sie im Spool-Verzeichnis landen.
* Größen- und Seitenbegrenzungen verhindern, dass ein einzelner Anhang den
  Container füllt oder stundenlange Übertragungen auslöst.
* **Die optionale LibreOffice-Wandlung vergrößert die Angriffsfläche**
  erheblich, da ein komplexes Office-Paket fremde Dokumente öffnet. Sie ist
  deshalb standardmäßig abgeschaltet. Aktivieren Sie sie nur, wenn Sie sie
  wirklich brauchen.

## 5. Dienstabsicherung

Die mitgelieferte systemd-Unit schränkt den Dienst ein:

```
NoNewPrivileges, PrivateTmp, PrivateDevices, ProtectSystem=strict,
ProtectHome, ProtectKernelTunables/Modules/Logs, ProtectControlGroups,
ProtectClock, ProtectHostname, ProtectProc=invisible, RestrictNamespaces,
RestrictRealtime, RestrictSUIDSGID, LockPersonality,
SystemCallFilter=@system-service, CapabilityBoundingSet= (leer), UMask=0027
```

Schreibrechte bestehen nur auf `/etc/mail2fax` und `/var/lib/mail2fax`.
Prüfen lässt sich das mit:

```bash
systemd-analyze security mail2fax
```

## 6. Empfohlene Ergänzungen

* Container-Firewall in Proxmox aktivieren und eingehend nur Port 8080 aus
  Ihrem Verwaltungsnetz zulassen.
* Unbeaufsichtigte Sicherheitsupdates im Container aktivieren:
  `apt install unattended-upgrades`.
* mail2fax regelmäßig aktualisieren (`install/update.sh`).
* `journalctl -u mail2fax` auf wiederholte Anmeldefehler und abgelehnte
  Absender prüfen.
* Ein eigenes Postfach ausschließlich für den Faxversand verwenden – nicht
  das persönliche.
