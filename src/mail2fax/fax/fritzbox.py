"""Faxversand ueber eine AVM FRITZ!Box.

Die FRITZ!Box bietet keine oeffentlich dokumentierte API fuer den Faxversand.
Genutzt wird deshalb dieselbe Schnittstelle wie die Weboberflaeche unter
"Telefonie -> Fax". Die Anmeldung erfolgt ueber das von AVM dokumentierte
Challenge-Response-Verfahren (PBKDF2 ab FRITZ!OS 7.24, sonst MD5).

Wichtig: AVM kann Endpunkt und Formularfelder mit jeder FRITZ!OS-Version
aendern. Beides ist deshalb in der Konfiguration hinterlegt und kann ohne
Codeaenderung angepasst werden (siehe docs/FAX-BACKENDS.md). Schlaegt der
Versand dauerhaft fehl, sind die Backends "mailgateway", "hylafax" oder
"command" die robusteren Alternativen.

Voraussetzungen in der FRITZ!Box:
  * Es ist eine Faxfunktion eingerichtet ("Telefoniegeraete -> Faxfunktion").
  * Der verwendete Benutzer besitzt die Berechtigung "VoIP-Telefonie/Fax".
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from xml.etree import ElementTree

import httpx

from ..config import AppConfig
from ..rules import Number
from .base import FaxBackend, FaxError, FaxResult

LOGGER = logging.getLogger(__name__)

INVALID_SID = "0000000000000000"


class FritzboxSession:
    """Anmeldung an der FRITZ!Box und Verwaltung der Session-ID."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        verify_tls: bool = False,
        timeout: int = 60,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self.sid: str | None = None
        self._client = httpx.Client(
            verify=verify_tls,
            timeout=httpx.Timeout(timeout, connect=15.0),
            follow_redirects=True,
            headers={"User-Agent": "mail2fax"},
        )

    def __enter__(self) -> FritzboxSession:
        self.login()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.logout()
        self._client.close()

    # -- Challenge-Response ------------------------------------------------

    @staticmethod
    def _response_pbkdf2(challenge: str, password: str) -> str:
        """PBKDF2-Verfahren ab FRITZ!OS 7.24 (Challenge beginnt mit "2$")."""
        parts = challenge.split("$")
        if len(parts) != 5:
            raise FaxError(f"Unerwartete FRITZ!Box-Challenge: {challenge}", permanent=True)
        _, iter1, salt1, iter2, salt2 = parts
        try:
            first = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), bytes.fromhex(salt1), int(iter1)
            )
            second = hashlib.pbkdf2_hmac("sha256", first, bytes.fromhex(salt2), int(iter2))
        except ValueError as error:
            raise FaxError(
                f"FRITZ!Box-Challenge konnte nicht verarbeitet werden: {error}", permanent=True
            ) from error
        return f"{salt2}${second.hex()}"

    @staticmethod
    def _response_md5(challenge: str, password: str) -> str:
        """Aelteres MD5-Verfahren (vor FRITZ!OS 7.24)."""
        digest = hashlib.md5(  # noqa: S324 - von AVM so vorgegeben
            f"{challenge}-{password}".encode("utf-16-le")
        ).hexdigest()
        return f"{challenge}-{digest}"

    def _request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        url = f"{self.base_url}{path}"
        try:
            response = self._client.request(method, url, **kwargs)  # type: ignore[arg-type]
        except httpx.HTTPError as error:
            raise FaxError(f"FRITZ!Box unter {self.base_url} nicht erreichbar: {error}") from error
        if response.status_code >= 400:
            raise FaxError(
                f"FRITZ!Box antwortet mit HTTP {response.status_code} auf {path}"
            )
        return response

    def login(self) -> str:
        """Meldet sich an und liefert die Session-ID."""
        if not self.password:
            raise FaxError("Fuer die FRITZ!Box ist kein Passwort hinterlegt", permanent=True)

        response = self._request("GET", "/login_sid.lua?version=2")
        try:
            root = ElementTree.fromstring(response.text)  # noqa: S314 - Antwort der FRITZ!Box
        except ElementTree.ParseError as error:
            raise FaxError(
                f"Antwort der FRITZ!Box ist kein gueltiges XML: {error}", permanent=True
            ) from error

        challenge = (root.findtext("Challenge") or "").strip()
        block_time = int((root.findtext("BlockTime") or "0").strip() or 0)
        if block_time > 0:
            raise FaxError(
                f"FRITZ!Box sperrt die Anmeldung noch fuer {block_time} Sekunden "
                "(zu viele Fehlversuche)"
            )
        if not challenge:
            raise FaxError("FRITZ!Box hat keine Challenge geliefert", permanent=True)

        if challenge.startswith("2$"):
            answer = self._response_pbkdf2(challenge, self.password)
        else:
            answer = self._response_md5(challenge, self.password)

        response = self._request(
            "POST",
            "/login_sid.lua?version=2",
            data={"username": self.username, "response": answer},
        )
        try:
            root = ElementTree.fromstring(response.text)  # noqa: S314
        except ElementTree.ParseError as error:
            raise FaxError(f"Anmeldeantwort unlesbar: {error}") from error

        sid = (root.findtext("SID") or "").strip()
        if not sid or sid == INVALID_SID:
            raise FaxError(
                "Anmeldung an der FRITZ!Box fehlgeschlagen - Benutzername oder "
                "Passwort falsch, oder dem Benutzer fehlt die Berechtigung",
                permanent=True,
            )
        self.sid = sid
        LOGGER.debug("An FRITZ!Box angemeldet (SID %s…)", sid[:4])
        return sid

    def logout(self) -> None:
        if not self.sid:
            return
        try:
            self._client.get(
                f"{self.base_url}/login_sid.lua?version=2&logout=1&sid={self.sid}",
                timeout=10,
            )
        except httpx.HTTPError:  # pragma: no cover - Abmeldung ist unkritisch
            LOGGER.debug("Abmeldung von der FRITZ!Box fehlgeschlagen")
        finally:
            self.sid = None

    def post_multipart(self, endpoint: str, fields: dict[str, str], files: dict) -> str:
        response = self._request("POST", endpoint, data=fields, files=files)
        return response.text


class FritzboxBackend(FaxBackend):
    """Versand ueber die Weboberflaeche der FRITZ!Box."""

    name = "AVM FRITZ!Box"

    def __init__(self, config: AppConfig) -> None:
        super().__init__(config)
        self.settings = config.fax.fritzbox

    def _session(self) -> FritzboxSession:
        if not self.settings.url:
            raise FaxError("Fuer die FRITZ!Box ist keine Adresse hinterlegt", permanent=True)
        return FritzboxSession(
            self.settings.url,
            self.settings.username,
            self.settings.password,
            verify_tls=self.settings.verify_tls,
            timeout=self.settings.timeout,
        )

    def send(self, number: Number, documents: list[Path], *, subject: str = "") -> FaxResult:
        from ..render import merge_pdfs

        if not documents:
            raise FaxError("Es liegen keine Dokumente zum Versand vor", permanent=True)
        if not self.settings.sender_number:
            raise FaxError(
                "Fuer die FRITZ!Box ist keine eigene Faxnummer (Absenderkennung) "
                "hinterlegt",
                permanent=True,
            )

        document = documents[0] if len(documents) == 1 else merge_pdfs(
            documents, documents[0].parent / "fax-gesamt.pdf"
        )

        fields = self.settings.form_fields
        with self._session() as session:
            assert session.sid is not None
            form = {
                fields.get("sid", "sid"): session.sid,
                fields.get("page", "page"): fields.get("page_value", "fx_send"),
                fields.get("apply", "apply"): "",
                fields.get("recipient", "recipient"): number.e164,
                fields.get("sender_number", "sender_number"): self.settings.sender_number,
                fields.get("sender_name", "sender_name"): self.settings.sender_name,
                fields.get("subject", "subject"): (subject or "Fax")[:120],
            }
            with document.open("rb") as handle:
                files = {
                    fields.get("file", "UploadFax"): (
                        document.name,
                        handle,
                        "application/pdf",
                    )
                }
                body = session.post_multipart(self.settings.endpoint, form, files)

        lowered = body.lower()
        for marker in ("fehler", "error", "nicht gesendet", "fehlgeschlagen"):
            if marker in lowered:
                excerpt = re.sub(r"<[^>]+>", " ", body)
                excerpt = re.sub(r"\s+", " ", excerpt).strip()[:300]
                raise FaxError(f"FRITZ!Box meldet einen Fehler: {excerpt}")

        return FaxResult(
            success=True,
            detail=f"Fax ueber FRITZ!Box an {number.e164} uebergeben",
        )

    def test(self) -> str:
        with self._session() as session:
            sid = session.sid or ""
        return (
            "Anmeldung an der FRITZ!Box erfolgreich "
            f"(Session {sid[:4]}…). Hinweis: Ob der Faxversand funktioniert, "
            "zeigt erst ein echter Testversand."
        )
