# Betrieb

## Dienst steuern

```bash
systemctl status  mail2fax     # Zustand
systemctl restart mail2fax     # nach Änderungen an der Konfiguration von Hand
systemctl stop    mail2fax
journalctl -u mail2fax -f      # Protokoll mitlesen
journalctl -u mail2fax -p err  # nur Fehler
```

Änderungen über die Weboberfläche greifen sofort – ein Neustart ist nur nötig,
wenn Sie `config.yaml` von Hand bearbeiten.

## Kommandozeile

Alle Befehle liegen unter `/opt/mail2fax/venv/bin/mail2fax`.

| Befehl | Zweck |
|---|---|
| `mail2fax passwd` | Passwort der Weboberfläche neu setzen |
| `mail2fax check-mail` | Postfach einmalig abfragen und Warteschlange abarbeiten |
| `mail2fax test-imap` | IMAP-Verbindung prüfen |
| `mail2fax test-backend` | Fax-Backend prüfen |
| `mail2fax test-fax +49301234567` | Testfax senden |
| `mail2fax show-config` | Konfiguration anzeigen (Passwörter maskiert) |
| `mail2fax init-config` | Standardkonfiguration anlegen |
| `mail2fax run` | nur den Hintergrunddienst starten (ohne Weboberfläche) |

Praktisch als Abkürzung:

```bash
echo 'alias mail2fax=/opt/mail2fax/venv/bin/mail2fax' >> /root/.bashrc
```

## Dateien und Verzeichnisse

| Pfad | Inhalt | Rechte |
|---|---|---|
| `/etc/mail2fax/config.yaml` | Konfiguration samt Zugangsdaten | `0640 mail2fax:mail2fax` |
| `/var/lib/mail2fax/mail2fax.db` | Auftragsdatenbank (SQLite) | `0640` |
| `/var/lib/mail2fax/spool/` | Faxdateien während der Verarbeitung | `0750` |
| `/opt/mail2fax/venv/` | Python-Umgebung | |
| `/opt/mail2fax/doc/` | mitgelieferte Dokumentation | |

## Aktualisieren

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Internerd/mail2fax/main/install/update.sh)"
```

Das Skript legt zuvor selbsttätig eine Sicherung unter `/var/backups/` an,
stoppt den Dienst, aktualisiert die Pakete und startet wieder. Konfiguration
und Historie bleiben erhalten.

Vom Proxmox-Host aus:

```bash
pct exec <CTID> -- bash -c "$(curl -fsSL https://raw.githubusercontent.com/Internerd/mail2fax/main/install/update.sh)"
```

## Sicherung und Wiederherstellung

### Sichern

Am einfachsten über Proxmox: *Container → Backup → Jetzt sichern*.

Nur die Daten von mail2fax:

```bash
tar -czf mail2fax-backup-$(date +%F).tar.gz \
    -C / etc/mail2fax var/lib/mail2fax
```

> Diese Sicherung enthält **Zugangsdaten und Faxinhalte**. Verschlüsseln Sie
> sie und regeln Sie die Aufbewahrung – siehe [DATENSCHUTZ.md](DATENSCHUTZ.md).

### Wiederherstellen

```bash
systemctl stop mail2fax
tar -xzf mail2fax-backup-2026-09-21.tar.gz -C /
chown -R mail2fax:mail2fax /etc/mail2fax /var/lib/mail2fax
chmod 0750 /etc/mail2fax /var/lib/mail2fax
chmod 0640 /etc/mail2fax/config.yaml
systemctl start mail2fax
```

## Auftragsdatenbank

```bash
apt install sqlite3
sqlite3 /var/lib/mail2fax/mail2fax.db

sqlite> SELECT id, datetime(created_at,'unixepoch','localtime'), sender, number, status
   ...> FROM jobs ORDER BY id DESC LIMIT 20;
sqlite> SELECT status, COUNT(*) FROM jobs GROUP BY status;
```

Vor schreibenden Zugriffen den Dienst stoppen.

## Weboberfläche über Netzgrenzen hinweg (HTTPS)

mail2fax spricht bewusst nur HTTP – im lokalen Netz ist das vertretbar. Soll
die Oberfläche über Netzgrenzen hinweg erreichbar sein, stellen Sie einen
Reverse Proxy mit TLS davor. Beispiel mit nginx im selben Container:

```nginx
server {
    listen 443 ssl;
    server_name mail2fax.intern.example.com;

    ssl_certificate     /etc/ssl/certs/mail2fax.crt;
    ssl_certificate_key /etc/ssl/private/mail2fax.key;

    # Zugriff zusaetzlich auf das Verwaltungsnetz begrenzen
    allow 192.168.1.0/24;
    deny  all;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
    }
}
```

Dazu in `/etc/mail2fax/config.yaml`:

```yaml
web:
  host: 127.0.0.1           # nur noch lokal erreichbar
  allowed_networks:
    - 127.0.0.0/8           # Anfragen kommen jetzt vom Proxy
```

> mail2fax wertet bewusst **kein** `X-Forwarded-For` aus – ein gefälschter
> Header könnte sonst die Netzbeschränkung aushebeln. Die Zugangskontrolle
> übernimmt in dieser Aufstellung der Proxy.

**Machen Sie die Oberfläche nicht aus dem Internet erreichbar.** Für den
Zugriff von unterwegs ist ein VPN der richtige Weg.

## Fehlersuche

### Es werden keine Faxe versendet

1. **Aufträge** in der Oberfläche ansehen – steht dort etwas unter „Abgelehnt"?
2. Häufigste Ursache: **Absender steht nicht auf der Whitelist** oder die
   Whitelist ist leer.
3. Zweithäufigste: **Keine Rufnummer im Betreff** erkennbar.
4. `journalctl -u mail2fax -f` und parallel eine Testmail senden.

### Postfach wird nicht abgefragt

```bash
/opt/mail2fax/venv/bin/mail2fax test-imap
```

| Meldung | Abhilfe |
|---|---|
| `IMAP-Verbindung fehlgeschlagen: … AUTHENTICATIONFAILED` | Benutzername/Passwort prüfen; bei Anbietern mit Zwei-Faktor-Anmeldung ein anwendungsspezifisches Passwort verwenden |
| `certificate verify failed` | Zertifikat des Servers prüfen; nur auf Testsystemen die Prüfung abschalten |
| `Auswahl von … fehlgeschlagen` | Ordnername prüfen (Groß-/Kleinschreibung, z. B. `INBOX`) |
| Keine Fehlermeldung, aber nichts passiert | Sind die Nachrichten bereits als *gelesen* markiert? mail2fax verarbeitet nur ungelesene. |

### Auftrag bleibt in der Warteschlange

Der nächste Versuch steht an – die Wartezeit verdoppelt sich je Fehlversuch.
Grund und Zeitplan stehen im Auftragsdetail. Mit *Erneut versuchen* können Sie
den Auftrag sofort einplanen.

### „Zugriff nur aus dem lokalen Netz erlaubt"

Ihre IP liegt außerhalb von `allowed_networks`. Vom Container aus ergänzen:

```bash
nano /etc/mail2fax/config.yaml     # unter web.allowed_networks das eigene Netz eintragen
systemctl restart mail2fax
```

### Passwort vergessen

```bash
pct exec <CTID> -- /opt/mail2fax/venv/bin/mail2fax passwd
```

### Container voll

```bash
du -sh /var/lib/mail2fax/spool/
```

Liegen dort viele Dateien, wurde `delete_documents_after_send` abgeschaltet
oder es stapeln sich fehlgeschlagene Aufträge. Rückstände entfernen:

```bash
systemctl stop mail2fax
find /var/lib/mail2fax/spool -mindepth 1 -mtime +7 -delete
systemctl start mail2fax
```

## Überwachung

Für Monitoring-Systeme steht ein Endpunkt bereit:

```bash
curl -s http://<ip>:8080/healthz          # "ok", ohne Anmeldung
```

Für Kennzahlen (Anmeldung erforderlich):

```bash
curl -s -b cookies http://<ip>:8080/api/status
```

Liefert Version, Backend, Zustand des Hintergrunddienstes und die Anzahl der
Aufträge je Status.
