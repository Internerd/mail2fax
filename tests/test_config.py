"""Tests fuer Laden und Speichern der Konfiguration."""

from __future__ import annotations

import stat

import pytest
import yaml

from mail2fax.config import AppConfig, generate_secret_key, load_config, save_config


def test_defaults_are_safe():
    config = AppConfig()
    assert config.security.sender_whitelist == []      # ohne Whitelist wird nichts verarbeitet
    assert config.fax.backend == "dummy"               # kein versehentlicher Versand
    assert config.imap.enabled is False
    assert config.imap.verify_tls is True
    assert "+49900" in config.security.blocked_number_prefixes


def test_roundtrip(tmp_path):
    path = tmp_path / "config.yaml"
    config = AppConfig()
    config.imap.host = "imap.example.com"
    config.security.sender_whitelist = ["chef@example.com"]
    save_config(config, path)
    loaded = load_config(path)
    assert loaded.imap.host == "imap.example.com"
    assert loaded.security.sender_whitelist == ["chef@example.com"]


def test_file_permissions_are_restrictive(tmp_path):
    path = tmp_path / "config.yaml"
    save_config(AppConfig(), path)
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o640, f"Konfiguration darf nicht fuer alle lesbar sein (ist {oct(mode)})"


def test_missing_file_yields_defaults(tmp_path):
    assert load_config(tmp_path / "gibtsnicht.yaml").fax.backend == "dummy"


def test_invalid_yaml_raises(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("- nur eine Liste", encoding="utf-8")
    with pytest.raises(ValueError, match="Mapping"):
        load_config(path)


def test_save_is_atomic_and_leaves_no_temp_files(tmp_path):
    path = tmp_path / "config.yaml"
    save_config(AppConfig(), path)
    save_config(AppConfig(), path)
    assert [entry.name for entry in tmp_path.iterdir()] == ["config.yaml"]


def test_extensions_are_normalised():
    config = AppConfig.model_validate({"content": {"allowed_extensions": [".PDF", "PNG ", ".Txt"]}})
    assert config.content.allowed_extensions == ["pdf", "png", "txt"]


def test_whitelist_is_lowercased():
    config = AppConfig.model_validate({"security": {"sender_whitelist": ["Chef@Example.COM"]}})
    assert config.security.sender_whitelist == ["chef@example.com"]


def test_secret_key_is_random():
    assert generate_secret_key() != generate_secret_key()


def test_example_config_matches_model():
    """Die mitgelieferte Beispielkonfiguration muss gueltig sein."""
    from pathlib import Path

    example = Path(__file__).resolve().parents[1] / "config" / "config.example.yaml"
    if not example.exists():
        pytest.skip("Beispielkonfiguration nicht vorhanden")
    data = yaml.safe_load(example.read_text(encoding="utf-8"))
    AppConfig.model_validate(data)


def test_save_tightens_permissions_of_existing_file(tmp_path):
    """Eine zu offen stehende Konfiguration wird beim Speichern verschaerft."""
    import os

    path = tmp_path / "config.yaml"
    save_config(AppConfig(), path)
    os.chmod(path, 0o666)
    save_config(AppConfig(), path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_save_creates_parent_directory(tmp_path):
    path = tmp_path / "tief" / "verschachtelt" / "config.yaml"
    save_config(AppConfig(), path)
    assert path.exists()


@pytest.mark.parametrize(
    ("eingabe", "erwartet"),
    [
        ("+49", "+49"),
        ("49", "+49"),
        ("0049", "+49"),
        ("+49 900", "+49900"),
        ("", "+49"),
    ],
)
def test_country_code_is_normalised(eingabe, erwartet):
    """Ein vergessenes Pluszeichen darf nicht zu kryptischen Fehlern fuehren."""
    config = AppConfig.model_validate({"security": {"default_country_code": eingabe}})
    assert config.security.default_country_code == erwartet


def test_number_prefixes_are_normalised():
    config = AppConfig.model_validate(
        {"security": {"allowed_number_prefixes": ["49", "+43"], "blocked_number_prefixes": ["0049900", ""]}}
    )
    assert config.security.allowed_number_prefixes == ["+49", "+43"]
    assert config.security.blocked_number_prefixes == ["+49900"]


def test_normalised_prefix_blocks_premium_number():
    """Auch ohne Pluszeichen eingetragene Sperren muessen greifen."""
    from mail2fax.rules import RuleError, check_number_allowed, normalise_number

    config = AppConfig.model_validate(
        {"security": {"default_country_code": "49", "blocked_number_prefixes": ["49900"]}}
    )
    number = normalise_number("0900123456", config.security)
    assert number.e164 == "+49900123456"
    with pytest.raises(RuleError, match="gesperrt"):
        check_number_allowed(number, config.security)


def test_removed_fritzbox_backend_falls_back_to_testbetrieb():
    """Eine alte Konfiguration darf den Dienststart nicht verhindern.

    Das Backend "fritzbox" steuerte die Weboberflaeche des Routers fern und
    wurde durch "sip" ersetzt. Bestehende Konfigurationen landen im
    Testbetrieb, damit nichts unbeabsichtigt versendet wird.
    """
    config = AppConfig.model_validate(
        {"fax": {"backend": "fritzbox", "fritzbox": {"url": "http://fritz.box"}}}
    )
    assert config.fax.backend == "dummy"
    assert not hasattr(config.fax, "fritzbox")


def test_removed_backend_is_matched_case_insensitively():
    assert AppConfig.model_validate({"fax": {"backend": "FritzBox"}}).fax.backend == "dummy"


def test_unknown_backend_still_raises():
    """Ein Tippfehler soll weiterhin auffallen und nicht stillschweigend wirken."""
    with pytest.raises(Exception, match="backend"):
        AppConfig.model_validate({"fax": {"backend": "gibtsnicht"}})
