"""Unit tests for configuration loading, merging, and validation."""

import os
import pytest
from pathlib import Path

from ctxguard.config.schema import AppConfig
from ctxguard.config.loader import ConfigLoader
from ctxguard.config.validator import validate_config, ConfigValidationError


def test_default_config_is_valid():
    config = AppConfig()
    warnings = validate_config(config)
    assert isinstance(warnings, list)
    assert config.server.port == 8787
    assert config.server.host == "127.0.0.1"
    assert config.upstream.default_provider == "anthropic"


def test_config_validation_invalid_port():
    config = AppConfig()
    config.server.port = 99999
    with pytest.raises(ConfigValidationError) as excinfo:
        validate_config(config)
    assert "Invalid server port" in str(excinfo.value)


def test_config_validation_invalid_provider():
    config = AppConfig()
    config.upstream.default_provider = "non_existent_provider"
    with pytest.raises(ConfigValidationError) as excinfo:
        validate_config(config)
    assert "not defined in upstream.providers" in str(excinfo.value)


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("CTXGUARD_SERVER_PORT", "9090")
    monkeypatch.setenv("CTXGUARD_SERVER_HOST", "0.0.0.0")
    monkeypatch.setenv("CTXGUARD_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("CTXGUARD_DEFAULT_PROVIDER", "openai")

    config = ConfigLoader.load_config()
    assert config.server.port == 9090
    assert config.server.host == "0.0.0.0"
    assert config.server.log_level == "DEBUG"
    assert config.upstream.default_provider == "openai"


def test_cli_overrides():
    cli_overrides = {
        "port": 7777,
        "host": "127.0.0.2",
        "log_level": "WARNING",
    }
    config = ConfigLoader.load_config(cli_overrides=cli_overrides)
    assert config.server.port == 7777
    assert config.server.host == "127.0.0.2"
    assert config.server.log_level == "WARNING"
