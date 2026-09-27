# Mitwirken

Beiträge sind willkommen – ob Fehlerbericht, Verbesserungsvorschlag,
Dokumentation oder Code.

## Fehler melden

Bitte ein [Issue](https://github.com/Internerd/mail2fax/issues) anlegen mit:

* Version (`mail2fax --version`) und Umgebung (Proxmox-Version, Debian-Version),
* gewähltem Fax-Backend,
* was Sie erwartet haben und was stattdessen passiert ist,
* Schritten zur Nachstellung,
* relevanten Auszügen aus `journalctl -u mail2fax`.

> **Vor dem Absenden:** Entfernen Sie Zugangsdaten, echte E-Mail-Adressen und
> echte Rufnummern aus Protokollauszügen.

**Sicherheitslücken gehören nicht in ein öffentliches Issue** –
siehe [SECURITY.md](SECURITY.md).

## Entwicklungsumgebung

```bash
git clone https://github.com/Internerd/mail2fax.git
cd mail2fax
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Anwendung lokal starten, ohne die Systempfade zu berühren:

```bash
export MAIL2FAX_CONFIG=./dev-config.yaml
export MAIL2FAX_DATA_DIR=./dev-data
mail2fax init-config
mail2fax passwd
mail2fax web --host 127.0.0.1 --port 8080
```

## Prüfungen vor dem Pull Request

Alle drei müssen fehlerfrei durchlaufen – die CI prüft dasselbe:

```bash
pytest                                      # Tests
ruff check src tests                        # Linter
shellcheck mail2fax.sh install/*.sh         # Shell-Skripte
```

## Richtlinien für Code

* **Python 3.11 oder neuer**, Typannotationen wo sie den Code klarer machen.
* **Deutsche Texte** für alles, was Nutzende sehen: Oberfläche,
  Fehlermeldungen, Protokollausgaben, Dokumentation.
* **Docstrings und Kommentare auf Deutsch**, ohne Umlaute im Quelltext
  (`ue`, `oe`, `ae`, `ss`) – so bleibt der Code unabhängig von der
  Zeichensatzeinstellung des Terminals lesbar. In Templates, Markdown und
  Nutzertexten sind Umlaute erwünscht.
* **Kommentare erklären das Warum**, nicht das Was.
* **Tests für neues Verhalten.** Besonders bei Regeln rund um
  Rufnummern, Whitelist und Zugriffsschutz.
* **Keine neuen Abhängigkeiten ohne Not.** Das Projekt soll in einem
  4-GiB-Container laufen.
* Zeilenlänge bis 110 Zeichen (siehe `pyproject.toml`).

## Sicherheitsrelevante Änderungen

Bei Änderungen an Authentifizierung, Netzbeschränkung, Rufnummernprüfung oder
dem Umgang mit Zugangsdaten bitte im Pull Request ausdrücklich beschreiben,
was sich am Verhalten ändert.

Für die Rufnummernerkennung gilt: **im Zweifel ablehnen statt raten.** Neue
Schreibweisen dürfen nur dann akzeptiert werden, wenn sie keine zweite
Lesart zulassen. Die Beispiele in `docs/RUFNUMMERN.md` werden von
`tests/test_docs.py` gegen den Code geprüft – neue Fälle gehören dort in die
Tabelle. Diese Stellen sind bewusst restriktiv gehalten –
Lockerungen brauchen eine Begründung.

## Ein neues Fax-Backend beisteuern

1. Neue Datei unter `src/mail2fax/fax/`, Klasse von `FaxBackend` ableiten.
2. `send()` umsetzen; `FaxError(..., permanent=True)` für Fehler, bei denen
   ein weiterer Versuch zwecklos ist.
   **`FaxResult.confirmed` nur setzen, wenn die Gegenstelle den Empfang
   tatsächlich quittiert hat.** Davon hängt ab, ob der Absender einen
   Sendebericht mit Übertragungsnachweis erhält (siehe
   [docs/SENDEBERICHTE.md](docs/SENDEBERICHTE.md)). Ein Backend, das den
   Auftrag nur weiterreicht, darf das nicht behaupten.
3. `test()` für den Verbindungstest in der Oberfläche umsetzen.
4. Konfigurationsmodell in `config.py` ergänzen.
5. In `fax/__init__.py` registrieren und in `settings_fax.html` ein
   Formularfeld ergänzen.
6. Tests in `tests/test_fax_backends.py` und einen Abschnitt in
   `docs/FAX-BACKENDS.md` beisteuern.

## Einsatz generativer KI

Dieses Projekt wurde selbst KI-gestützt entwickelt (siehe
[docs/KI-NUTZUNG.md](docs/KI-NUTZUNG.md)) – KI-gestützte Beiträge sind daher
ausdrücklich willkommen. Bitte geben Sie im Pull Request an, ob und wofür Sie
generative KI eingesetzt haben, und **prüfen Sie den erzeugten Code, bevor Sie
ihn einreichen**. Sie verantworten Ihren Beitrag unabhängig davon, womit er
entstanden ist.

## Lizenz der Beiträge

Mit dem Einreichen eines Beitrags bestätigen Sie, dass Sie die erforderlichen
Rechte daran besitzen und ihn unter der [MIT-Lizenz](LICENSE) beisteuern.
