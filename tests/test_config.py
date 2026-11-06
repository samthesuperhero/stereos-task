import json
import logging
import os

import pytest

import back.config
from back.config import ConfigError, load_settings
from back.log import configure_logging


def test_defaults_are_complete(monkeypatch, tmp_path):
    for name in list(os.environ):
        if name.startswith("STEREOS_TASK_"):
            monkeypatch.delenv(name)
    monkeypatch.setattr(back.config, "DEFAULT_CONFIG_PATH", tmp_path / "missing.ini")
    settings = load_settings()
    assert settings.port == 61070
    assert settings.host == "127.0.0.1"


def test_ini_then_environment_precedence(monkeypatch, tmp_path):
    path = tmp_path / "service.ini"
    path.write_text("[service]\nport = 62000\nhost = 127.0.0.2\n", encoding="utf-8")
    monkeypatch.setenv("STEREOS_TASK_PORT", "63000")
    settings = load_settings(path)
    assert settings.port == 63000
    assert settings.host == "127.0.0.2"


@pytest.mark.parametrize("content", ["not ini", "[other]\nport = 1", "[service]\nport = nope"])
def test_invalid_configuration_is_rejected(tmp_path, content):
    path = tmp_path / "service.ini"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(path)


def test_unknown_log_level_falls_back_to_info(capsys):
    configure_logging("INVALID")
    logging.getLogger("test").info("ready", extra={"structured": {"key": "value"}})
    payload = json.loads(capsys.readouterr().out)
    assert logging.getLogger().level == logging.INFO
    assert payload["level"] == "INFO"
    assert payload["extra"] == {"key": "value"}
    assert payload["service"] == "stereos-task"


@pytest.mark.parametrize("field", ["request_timeout_seconds", "shutdown_timeout_seconds"])
@pytest.mark.parametrize("value", ["inf", "-inf", "nan"])
def test_non_finite_timeouts_are_rejected(tmp_path, field, value):
    path = tmp_path / "service.ini"
    path.write_text(f"[service]\n{field} = {value}\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(path)


@pytest.mark.parametrize("value", ["20.001", "60"])
def test_shutdown_timeout_preserves_systemd_margin(tmp_path, value):
    path = tmp_path / "service.ini"
    path.write_text(f"[service]\nshutdown_timeout_seconds = {value}\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(path)


def test_maximum_bounded_shutdown_timeout_is_accepted(tmp_path):
    path = tmp_path / "service.ini"
    path.write_text("[service]\nshutdown_timeout_seconds = 20\n", encoding="utf-8")
    assert load_settings(path).shutdown_timeout_seconds == 20
