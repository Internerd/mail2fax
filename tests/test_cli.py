"""Tests der Kommandozeile."""

from __future__ import annotations

import pytest

from mail2fax.cli import main
from mail2fax.config import load_config


def test_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert "mail2fax" in capsys.readouterr().out


def test_init_config(tmp_path, capsys):
    path = tmp_path / "config.yaml"
    assert main(["-c", str(path), "init-config"]) == 0
    assert path.exists()
    assert load_config(path).web.secret_key != ""
    assert "angelegt" in capsys.readouterr().out


def test_init_config_refuses_overwrite(tmp_path):
    path = tmp_path / "config.yaml"
    main(["-c", str(path), "init-config"])
    assert main(["-c", str(path), "init-config"]) == 1
    assert main(["-c", str(path), "init-config", "--force"]) == 0


def test_passwd_sets_hash(tmp_path):
    from mail2fax.web.auth import verify_password

    path = tmp_path / "config.yaml"
    main(["-c", str(path), "init-config"])
    assert main(["-c", str(path), "passwd", "--password", "Gutes-Passwort-42!"]) == 0
    assert verify_password("Gutes-Passwort-42!", load_config(path).web.password_hash)


def test_passwd_rejects_weak_password(tmp_path):
    path = tmp_path / "config.yaml"
    main(["-c", str(path), "init-config"])
    assert main(["-c", str(path), "passwd", "--password", "kurz"]) == 2


def test_passwd_force_allows_weak_password(tmp_path):
    path = tmp_path / "config.yaml"
    main(["-c", str(path), "init-config"])
    assert main(["-c", str(path), "passwd", "--password", "kurz", "--force"]) == 0


def test_show_config_redacts_secrets(tmp_path, capsys):
    path = tmp_path / "config.yaml"
    main(["-c", str(path), "init-config"])
    main(["-c", str(path), "passwd", "--password", "Gutes-Passwort-42!"])
    config = load_config(path)
    config.imap.password = "streng-geheim"
    from mail2fax.config import save_config

    save_config(config, path)

    assert main(["-c", str(path), "show-config"]) == 0
    output = capsys.readouterr().out
    assert "streng-geheim" not in output
    assert "***" in output


def test_test_fax_rejects_invalid_number(tmp_path, capsys):
    path = tmp_path / "config.yaml"
    main(["-c", str(path), "init-config"])
    assert main(["-c", str(path), "test-fax", "keine-nummer"]) == 2
    assert "Fehler" in capsys.readouterr().err


def test_test_fax_with_dummy_backend(tmp_path, capsys):
    path = tmp_path / "config.yaml"
    main(["-c", str(path), "init-config"])
    assert main(["-c", str(path), "test-fax", "+49301234567"]) == 0
    assert "Erfolgreich" in capsys.readouterr().out


def test_test_backend(tmp_path, capsys):
    path = tmp_path / "config.yaml"
    main(["-c", str(path), "init-config"])
    assert main(["-c", str(path), "test-backend"]) == 0
    assert "Testbackend" in capsys.readouterr().out


def test_unknown_command_exits(capsys):
    with pytest.raises(SystemExit):
        main(["gibtsnicht"])
