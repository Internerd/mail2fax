"""Tests der erzeugten Asterisk-Konfiguration.

Die Syntax dieser Dateien wird zusaetzlich in tests/test_sip_integration.py
gegen ein echtes Asterisk geprueft, sofern eines installiert ist.
"""

from __future__ import annotations

import stat

import pytest

from mail2fax.asterisk import (
    DIALPLAN_CONTEXT,
    DIALPLAN_EXTEN,
    RESULT_EVENT,
    generate_ami_secret,
    render_extensions,
    render_manager,
    render_pjsip,
    write_config,
)
from mail2fax.config import SipConfig


@pytest.fixture
def sip():
    return SipConfig(
        server="fritz.box",
        username="620",
        password="geheim",
        sender_number="+49301234567",
        ami_password="ami-geheim",
    )


# -- PJSIP -----------------------------------------------------------------


def test_pjsip_defines_all_required_objects(sip):
    text = render_pjsip(sip)
    for objekt in ("type=transport", "type=auth", "type=registration", "type=aor", "type=endpoint"):
        assert objekt in text, f"{objekt} fehlt"


def test_pjsip_uses_only_uncompressed_codecs(sip):
    """Fax vertraegt keine komprimierenden Codecs."""
    text = render_pjsip(sip)
    assert "disallow=all" in text
    assert "allow=alaw" in text
    assert "allow=ulaw" in text
    for codec in ("gsm", "g729", "opus", "g722", "speex"):
        assert f"allow={codec}" not in text


def test_pjsip_keeps_media_on_asterisk(sip):
    """Ohne direct_media=no sieht spandsp die Faxtoene nicht."""
    assert "direct_media=no" in render_pjsip(sip)


def test_pjsip_sets_no_invalid_endpoint_options(sip):
    """tone_detect gibt es als Endpunkt-Option nicht - Asterisk lehnt sonst ab."""
    assert "tone_detect" not in render_pjsip(sip)


def test_pjsip_t38_switchable(sip):
    assert "t38_udptl=no" in render_pjsip(sip)
    sip.t38 = True
    text = render_pjsip(sip)
    assert "t38_udptl=yes" in text
    assert "t38_udptl_ec=redundancy" in text


def test_pjsip_credentials_are_used(sip):
    text = render_pjsip(sip)
    assert "username=620" in text
    assert "password=geheim" in text
    assert "client_uri=sip:620@fritz.box" in text


def test_pjsip_non_standard_port(sip):
    sip.port = 5070
    assert "sip:fritz.box:5070" in render_pjsip(sip)


def test_pjsip_tcp_transport(sip):
    sip.transport = "tcp"
    text = render_pjsip(sip)
    assert "protocol=tcp" in text
    assert "transport=transport-tcp-mail2fax" in text


@pytest.mark.parametrize(
    ("feld", "wert", "eingeschleust"),
    [
        ("username", "620\ncontext=boeser-kontext", "context=boeser-kontext"),
        ("password", "geheim\r\nallow=g729", "allow=g729"),
        ("server", "fritz.box\ndeny=nichts", "deny=nichts"),
        ("endpoint_name", "tk\ncontext=fremder-kontext", "context=fremder-kontext"),
        ("station_name", "mail2fax\nexten => 1,1,System(rm -rf /)", "System(rm"),
    ],
)
def test_no_configuration_line_can_be_injected(sip, feld, wert, eingeschleust):
    """Zeilenumbrueche in Werten duerfen keine zusaetzliche Zeile erzeugen."""
    setattr(sip, feld, wert)
    zeilen = [zeile.strip() for zeile in render_pjsip(sip).splitlines()]
    assert not any(zeile.startswith(eingeschleust) for zeile in zeilen), (
        f"{feld} konnte eine Konfigurationszeile einschleusen"
    )


def test_section_header_cannot_be_injected(sip):
    """Ein Zeilenumbruch im Endpunktnamen darf keinen neuen Abschnitt oeffnen."""
    sip.endpoint_name = "tk]\n[boeser-abschnitt"
    zeilen = [zeile.strip() for zeile in render_pjsip(sip).splitlines()]
    assert "[boeser-abschnitt]" not in zeilen
    assert "[boeser-abschnitt" not in zeilen


def test_comment_character_is_removed(sip):
    """Ein ";" wuerde den Rest der Zeile zum Kommentar machen."""
    sip.password = "geheim;permit=all"
    text = render_pjsip(sip)
    assert "password=geheimpermit=all" in text
    assert ";permit" not in text


def test_dialplan_cannot_be_injected_via_station_name(sip):
    sip.station_name = "mail2fax\nexten => 999,1,System(id)"
    zeilen = [zeile.strip() for zeile in render_extensions(sip).splitlines()]
    assert not any(zeile.startswith("exten => 999") for zeile in zeilen)


# -- Dialplan --------------------------------------------------------------


def test_dialplan_sends_fax_and_reports_back(sip):
    text = render_extensions(sip)
    assert f"[{DIALPLAN_CONTEXT}]" in text
    assert f"exten => {DIALPLAN_EXTEN},1," in text
    assert "SendFAX(${M2F_FILE},${M2F_OPTIONS})" in text
    assert f"UserEvent({RESULT_EVENT}," in text


def test_dialplan_sets_station_id_and_header(sip):
    text = render_extensions(sip)
    assert "Set(FAXOPT(localstationid)=${M2F_STATIONID})" in text
    assert "Set(FAXOPT(headerinfo)=${M2F_HEADER})" in text
    assert "Set(FAXOPT(ecm)=${M2F_ECM})" in text


def test_dialplan_reports_on_hangup(sip):
    """Auch ein Abbruch muss gemeldet werden, sonst laeuft mail2fax in den Zeitablauf."""
    text = render_extensions(sip)
    assert "exten => h,1," in text
    assert text.count(f"UserEvent({RESULT_EVENT},") >= 2


def test_dialplan_rejects_incoming_calls(sip):
    text = render_extensions(sip)
    assert f"[{DIALPLAN_CONTEXT}-in]" in text
    assert "Hangup(21)" in text


# -- Manager ---------------------------------------------------------------


def test_manager_denies_before_permitting(sip):
    """Reihenfolge ist entscheidend: ein spaeteres deny sperrt sonst alles aus."""
    text = render_manager(sip)
    assert text.index("deny = 0.0.0.0/0.0.0.0") < text.index("permit = 127.0.0.1")


def test_manager_grants_only_needed_rights(sip):
    text = render_manager(sip)
    assert "write = originate,command,reload" in text
    assert "secret = ami-geheim" in text


def test_ami_secret_is_random():
    assert generate_ami_secret() != generate_ami_secret()
    assert len(generate_ami_secret()) >= 30


# -- Schreiben -------------------------------------------------------------


def test_write_config_creates_all_files(sip, tmp_path):
    written = write_config(sip, tmp_path)
    namen = {path.name for path in written}
    assert namen == {"pjsip.conf", "extensions.conf", "manager.conf"}
    assert all(path.exists() for path in written)


def test_written_files_are_not_world_readable(sip, tmp_path):
    """Die Dateien enthalten SIP- und AMI-Passwoerter."""
    for path in write_config(sip, tmp_path):
        assert stat.S_IMODE(path.stat().st_mode) == 0o640, path.name


def test_write_config_is_repeatable(sip, tmp_path):
    write_config(sip, tmp_path)
    write_config(sip, tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "extensions.conf", "manager.conf", "pjsip.conf"
    ]
