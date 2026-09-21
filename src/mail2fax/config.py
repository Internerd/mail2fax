"""Konfigurationsmodell und Laden/Speichern der YAML-Konfiguration.

Die Konfiguration liegt standardmaessig unter /etc/mail2fax/config.yaml und
enthaelt Zugangsdaten. Sie wird daher immer mit den Rechten 0640 geschrieben.
"""

from __future__ import annotations

import contextlib
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from .paths import CONFIG_PATH


def _as_e164_prefix(value: Any) -> str:
    """Bringt eine Vorwahlangabe in die Form "+49".

    Akzeptiert "49", "0049", "+49" sowie Schreibweisen mit Trennzeichen und
    liefert "" fuer leere Eingaben. So fuehrt ein vergessenes Pluszeichen in
    der Weboberflaeche nicht zu unverstaendlichen Fehlermeldungen.
    """
    text = "".join(char for char in str(value or "") if char.isdigit() or char == "+")
    if not text:
        return ""
    if text.startswith("+"):
        return "+" + text.lstrip("+")
    if text.startswith("00"):
        return "+" + text[2:]
    return "+" + text


class ImapConfig(BaseModel):
    """Postfach, das auf neue Nachrichten ueberwacht wird."""

    enabled: bool = False
    host: str = ""
    port: int = 993
    security: Literal["ssl", "starttls", "none"] = "ssl"
    username: str = ""
    password: str = ""
    folder: str = "INBOX"
    poll_interval: int = Field(default=60, ge=10, le=3600)
    #: Wie mit verarbeiteten Nachrichten umgegangen wird.
    processed_action: Literal["seen", "move", "delete"] = "seen"
    processed_folder: str = "Fax/Versendet"
    rejected_folder: str = "Fax/Abgelehnt"
    #: Nachrichten oberhalb dieser Groesse werden nicht geladen (MiB).
    max_message_size_mb: int = Field(default=25, ge=1, le=200)
    #: TLS-Zertifikat der Gegenstelle pruefen. Nur fuer Testsysteme abschalten.
    verify_tls: bool = True


class SmtpConfig(BaseModel):
    """Postausgang fuer Statusmeldungen (Quittungen)."""

    enabled: bool = False
    host: str = ""
    port: int = 587
    security: Literal["starttls", "ssl", "none"] = "starttls"
    username: str = ""
    password: str = ""
    from_address: str = ""
    #: Absender der Ursprungsmail ueber Erfolg/Misserfolg informieren.
    notify_sender: bool = True
    #: Zusaetzliche Adresse fuer Fehlermeldungen (optional).
    admin_address: str = ""
    verify_tls: bool = True


class FritzboxConfig(BaseModel):
    """Zugangsdaten fuer eine AVM FRITZ!Box.

    Der Versand erfolgt ueber die Weboberflaeche der FRITZ!Box (dieselbe
    Schnittstelle, die auch "Telefonie -> Fax" im Browser benutzt). AVM
    aendert diese Oberflaeche zwischen FRITZ!OS-Versionen, deshalb sind
    Endpunkt und Formularfelder konfigurierbar.
    """

    url: str = "http://fritz.box"
    username: str = ""
    password: str = ""
    #: Eigene Faxnummer (Absenderkennung), z. B. "+4930123456".
    sender_number: str = ""
    #: Absendername in der Faxkopfzeile.
    sender_name: str = "mail2fax"
    verify_tls: bool = False
    timeout: int = Field(default=180, ge=10, le=900)
    #: Pfad des Upload-Endpunkts relativ zur Basis-URL.
    endpoint: str = "/cgi-bin/luacgi_notimeout"
    #: Abbildung der Formularfelder; bei abweichendem FRITZ!OS anpassbar.
    form_fields: dict[str, str] = Field(
        default_factory=lambda: {
            "sid": "sid",
            "page": "page",
            "page_value": "fx_send",
            "apply": "apply",
            "recipient": "SendFax:settings/recipient",
            "sender_number": "SendFax:settings/sender_number",
            "sender_name": "SendFax:settings/sender_name",
            "subject": "SendFax:settings/subject",
            "file": "UploadFax",
        }
    )


class HylafaxConfig(BaseModel):
    """Versand ueber HylaFAX bzw. HylaFAX+ (`sendfax`)."""

    binary: str = "/usr/bin/sendfax"
    host: str = "localhost"
    port: int = 4559
    user: str = ""
    #: Absenderkennung (TSI) fuer die Faxkopfzeile.
    sender_number: str = ""
    extra_args: list[str] = Field(default_factory=list)
    timeout: int = Field(default=600, ge=30, le=3600)


class MailGatewayConfig(BaseModel):
    """Versand ueber einen Fax-per-E-Mail-Dienst (z. B. Telefonanlage oder Provider).

    Die Zielrufnummer wird nach einem Muster in die Empfaengeradresse
    eingesetzt, z. B. ``{number}@fax.example.net``.
    """

    #: Muster der Empfaengeradresse. Platzhalter: {number}, {number_national},
    #: {number_digits}.
    recipient_template: str = "{number_digits}@fax.example.net"
    subject_template: str = "Fax an {number}"
    body_template: str = "Automatisch erzeugt durch mail2fax."
    #: Eigener SMTP-Server; wenn leer, wird die globale SMTP-Konfiguration genutzt.
    host: str = ""
    port: int = 587
    security: Literal["starttls", "ssl", "none"] = "starttls"
    username: str = ""
    password: str = ""
    from_address: str = ""
    verify_tls: bool = True


class CommandConfig(BaseModel):
    """Versand ueber ein beliebiges externes Kommando.

    Erlaubt die Anbindung beliebiger Telefonanlagen (Asterisk, 3CX, CapiSuite,
    T.38-Gateways ...). Das Kommando wird ohne Shell ausgefuehrt; Platzhalter
    werden je Argument ersetzt.
    """

    #: Argumentliste, z. B. ["/usr/local/bin/sendfax.sh", "{number}", "{file}"].
    argv: list[str] = Field(default_factory=list)
    timeout: int = Field(default=600, ge=10, le=3600)
    #: Zusaetzliche Umgebungsvariablen fuer das Kommando.
    env: dict[str, str] = Field(default_factory=dict)


class SipConfig(BaseModel):
    """Faxversand ueber eine SIP-Registrierung an FRITZ!Box oder Telefonanlage.

    mail2fax meldet sich als IP-Telefon an der Anlage an und uebertraegt das
    Fax selbst - entweder als T.38 oder als Software-Faxmodem ueber G.711.
    Die Medienverarbeitung uebernimmt ein lokaler Asterisk (res_fax_spandsp),
    den mail2fax ueber die Asterisk Manager Interface (AMI) steuert.

    Die Asterisk-Konfiguration erzeugt mail2fax selbst aus diesen Werten
    (``mail2fax sip-apply`` bzw. die Schaltflaeche in der Weboberflaeche).
    """

    # -- Anlage (SIP-Registrierung) ----------------------------------------
    #: Adresse der FRITZ!Box bzw. der Telefonanlage.
    server: str = "fritz.box"
    port: int = Field(default=5060, ge=1, le=65535)
    #: Interne Rufnummer bzw. SIP-Benutzername des angelegten IP-Telefons.
    username: str = ""
    password: str = ""
    #: Eigene Faxnummer als Absenderkennung (TSI), z. B. "+49301234567".
    sender_number: str = ""
    #: Text in der Faxkopfzeile.
    station_name: str = "mail2fax"
    #: Amtsholung, die der Rufnummer vorangestellt wird (z. B. "0" an einer TK-Anlage).
    dial_prefix: str = ""
    #: Rufnummern in nationaler Form waehlen (0301234567 statt +49301234567).
    dial_national: bool = True
    #: Transportprotokoll der SIP-Registrierung.
    transport: Literal["udp", "tcp"] = "udp"

    # -- Faxparameter -------------------------------------------------------
    #: T.38 anbieten. Viele FRITZ!Box-Modelle faxen zuverlaessiger ohne.
    t38: bool = False
    #: Fehlerkorrektur (ECM). Ueber eine FRITZ!Box oft besser abgeschaltet.
    ecm: bool = False
    minrate: int = Field(default=2400, ge=2400, le=14400)
    maxrate: int = Field(default=14400, ge=2400, le=14400)
    #: Sekunden, die auf den Abschluss der Uebertragung gewartet wird.
    timeout: int = Field(default=900, ge=60, le=3600)
    #: Sekunden, die auf das Abheben der Gegenstelle gewartet wird.
    dial_timeout: int = Field(default=60, ge=10, le=300)

    # -- Asterisk-Anbindung -------------------------------------------------
    ami_host: str = "127.0.0.1"
    ami_port: int = Field(default=5038, ge=1, le=65535)
    ami_user: str = "mail2fax"
    #: Wird beim ersten "sip-apply" automatisch erzeugt.
    ami_password: str = ""
    #: Name des erzeugten PJSIP-Endpunkts (nur aendern, wenn es kollidiert).
    endpoint_name: str = "mail2fax-tk"
    #: Verzeichnis, in das die erzeugte Asterisk-Konfiguration geschrieben wird.
    config_dir: str = "/etc/asterisk/mail2fax"

    @field_validator("sender_number", mode="before")
    @classmethod
    def _strip_sender(cls, value: Any) -> Any:
        return str(value or "").strip()


class FaxConfig(BaseModel):
    """Auswahl und Parameter des Faxversands."""

    backend: Literal[
        "sip", "fritzbox", "hylafax", "mailgateway", "command", "dummy"
    ] = "dummy"
    #: Anzahl der Zustellversuche insgesamt (inkl. Erstversuch).
    max_attempts: int = Field(default=3, ge=1, le=10)
    #: Wartezeit zwischen den Versuchen in Sekunden (wird verdoppelt).
    retry_delay: int = Field(default=300, ge=10, le=86400)
    #: Testbetrieb: Es wird nichts gesendet, der Auftrag gilt als erfolgreich.
    dry_run: bool = False

    sip: SipConfig = Field(default_factory=SipConfig)
    fritzbox: FritzboxConfig = Field(default_factory=FritzboxConfig)
    hylafax: HylafaxConfig = Field(default_factory=HylafaxConfig)
    mailgateway: MailGatewayConfig = Field(default_factory=MailGatewayConfig)
    command: CommandConfig = Field(default_factory=CommandConfig)


class ContentConfig(BaseModel):
    """Was gefaxt wird: Anhang oder Mailtext."""

    #: "first" = nur der erste passende Anhang, "all" = alle passenden Anhaenge.
    attachment_mode: Literal["first", "all"] = "first"
    #: Zugelassene Dateiendungen fuer Anhaenge.
    allowed_extensions: list[str] = Field(
        default_factory=lambda: [
            "pdf", "png", "jpg", "jpeg", "gif", "bmp", "tif", "tiff", "txt",
        ]
    )
    #: Office-Dokumente ueber LibreOffice wandeln (benoetigt libreoffice-core).
    convert_office: bool = False
    office_extensions: list[str] = Field(
        default_factory=lambda: ["doc", "docx", "odt", "rtf", "xls", "xlsx", "ods"]
    )
    #: Maximale Groesse eines Anhangs in MiB.
    max_attachment_size_mb: int = Field(default=20, ge=1, le=100)
    #: Maximale Seitenzahl pro Fax (0 = unbegrenzt).
    max_pages: int = Field(default=30, ge=0, le=500)
    #: Kopfzeile auf der aus dem Mailtext erzeugten Seite ausgeben.
    include_mail_header: bool = True

    @field_validator("allowed_extensions", "office_extensions", mode="before")
    @classmethod
    def _normalise_extensions(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [str(item).lower().lstrip(".").strip() for item in value if str(item).strip()]
        return value


class SecurityConfig(BaseModel):
    """Zugriffsschutz und Missbrauchsschutz."""

    #: Nur diese Absenderadressen duerfen Faxe ausloesen.
    #: Erlaubt sind vollstaendige Adressen und Platzhalter wie "*@example.com".
    sender_whitelist: list[str] = Field(default_factory=list)
    #: Erlaubte Rufnummernpraefixe in E.164-Schreibweise.
    allowed_number_prefixes: list[str] = Field(default_factory=lambda: ["+49"])
    #: Gesperrte Praefixe (Sonderrufnummern, teure Dienste).
    blocked_number_prefixes: list[str] = Field(
        default_factory=lambda: ["+49900", "+49137", "+49180", "+49181", "+491900"]
    )
    #: Nationale Schreibweise (0…) akzeptieren und zu +49 normalisieren.
    accept_national_format: bool = True
    #: Landesvorwahl fuer die Normalisierung nationaler Nummern.
    default_country_code: str = "+49"
    #: Maximale Anzahl Faxe pro Stunde (0 = unbegrenzt).
    rate_limit_per_hour: int = Field(default=20, ge=0, le=1000)
    #: Maximale Anzahl Faxe pro Absender und Stunde (0 = unbegrenzt).
    rate_limit_per_sender_per_hour: int = Field(default=10, ge=0, le=1000)

    @field_validator("sender_whitelist", mode="before")
    @classmethod
    def _normalise_whitelist(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [str(item).strip().lower() for item in value if str(item).strip()]
        return value

    @field_validator("allowed_number_prefixes", "blocked_number_prefixes", mode="before")
    @classmethod
    def _normalise_prefixes(cls, value: Any) -> Any:
        """Ergaenzt fehlende Pluszeichen, damit "49" wie "+49" wirkt."""
        if isinstance(value, list):
            return [
                prefix
                for prefix in (_as_e164_prefix(item) for item in value)
                if prefix
            ]
        return value

    @field_validator("default_country_code", mode="before")
    @classmethod
    def _normalise_country_code(cls, value: Any) -> Any:
        return _as_e164_prefix(value) or "+49"


class WebConfig(BaseModel):
    """Weboberflaeche - ausschliesslich fuer das lokale Netz gedacht."""

    host: str = "0.0.0.0"  # noqa: S104 - Zugriff wird ueber allowed_networks begrenzt
    port: int = Field(default=8080, ge=1, le=65535)
    #: Netze, aus denen die Oberflaeche erreichbar ist (CIDR).
    allowed_networks: list[str] = Field(
        default_factory=lambda: [
            "127.0.0.0/8",
            "::1/128",
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
            "fc00::/7",
            "fe80::/10",
        ]
    )
    #: PBKDF2-Hash des Admin-Passworts (siehe mail2fax passwd).
    password_hash: str = ""
    #: Schluessel fuer die Signatur der Sitzungscookies.
    secret_key: str = ""
    #: Sitzungsdauer in Minuten.
    session_timeout_minutes: int = Field(default=120, ge=5, le=10080)
    #: Anmeldeversuche pro IP und 15 Minuten.
    login_attempts: int = Field(default=10, ge=1, le=100)


class AppConfig(BaseModel):
    """Gesamtkonfiguration."""

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    #: Aufbewahrungsdauer der Auftragshistorie in Tagen (0 = unbegrenzt).
    history_retention_days: int = Field(default=90, ge=0, le=3650)
    #: Faxdateien nach erfolgreichem Versand loeschen (Datenminimierung).
    delete_documents_after_send: bool = True

    imap: ImapConfig = Field(default_factory=ImapConfig)
    smtp: SmtpConfig = Field(default_factory=SmtpConfig)
    fax: FaxConfig = Field(default_factory=FaxConfig)
    content: ContentConfig = Field(default_factory=ContentConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    web: WebConfig = Field(default_factory=WebConfig)


def load_config(path: Path | None = None) -> AppConfig:
    """Laedt die Konfiguration; fehlende Datei ergibt Standardwerte."""
    target = path or CONFIG_PATH
    if not target.exists():
        return AppConfig()
    with target.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Konfiguration {target} ist kein YAML-Mapping")
    return AppConfig.model_validate(raw)


def save_config(config: AppConfig, path: Path | None = None) -> None:
    """Schreibt die Konfiguration atomar mit restriktiven Rechten.

    Die Datei enthaelt Zugangsdaten im Klartext. Sie wird deshalb immer mit
    0640 abgelegt - auch dann, wenn die vorhandene Datei offener stand.
    Eigentuemer und Gruppe der bestehenden Datei bleiben erhalten, damit der
    Dienstbenutzer weiterhin lesen kann.
    """
    target = path or CONFIG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    data = config.model_dump(mode="json")

    descriptor, temp_name = tempfile.mkstemp(dir=target.parent, prefix=".config-", suffix=".tmp")
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            yaml.safe_dump(
                data, handle, allow_unicode=True, sort_keys=False, default_flow_style=False
            )
            handle.flush()
            os.fsync(handle.fileno())
        if target.exists():
            with contextlib.suppress(PermissionError, AttributeError, OSError):
                existing = target.stat()
                os.chown(temp_name, existing.st_uid, existing.st_gid)
        os.chmod(temp_name, 0o640)
        os.replace(temp_name, target)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def generate_secret_key() -> str:
    """Erzeugt einen Schluessel fuer Sitzungscookies."""
    return secrets.token_urlsafe(48)
