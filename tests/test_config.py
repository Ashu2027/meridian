"""
tests/test_config.py
Unit tests for config.py — load_config, save_config, ConfigMissingError.
All disk I/O patched via secrets_manager mocks.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from config import AppConfig, ConfigMissingError, load_config, save_config


def _full_cfg() -> AppConfig:
    return AppConfig(
        tidb_host="myhost",
        tidb_port=4000,
        tidb_user="admin",
        tidb_password="secret",
        tidb_database="meridian",
        tidb_use_tls=True,
        tidb_ssl_ca=None,
        resend_api_key="re_test_key",
        default_from_name="Test Desk",
        default_from_email="out@test.com",
        api_host="127.0.0.1",
        api_port=8765,
        api_secret_token="token123",
    )


class TestAppConfig:
    def test_default_values(self):
        cfg = AppConfig()
        assert cfg.tidb_host == ""
        assert cfg.tidb_port == 4000
        assert cfg.tidb_database == "meridian"
        assert cfg.tidb_use_tls is True
        assert cfg.default_from_name == "Meridian Desk"
        assert cfg.api_host == "127.0.0.1"
        assert cfg.api_port == 8765

    def test_custom_values(self):
        cfg = _full_cfg()
        assert cfg.tidb_host == "myhost"
        assert cfg.resend_api_key == "re_test_key"
        assert cfg.api_secret_token == "token123"

    def test_is_dataclass(self):
        cfg = _full_cfg()
        d = asdict(cfg)
        assert isinstance(d, dict)
        assert "tidb_host" in d


class TestLoadConfig:
    def test_loads_successfully(self):
        cfg = _full_cfg()
        with patch("services.secrets_manager.load_secrets", return_value=asdict(cfg)):
            loaded = load_config()
        assert loaded.tidb_host == "myhost"
        assert loaded.resend_api_key == "re_test_key"
        assert loaded.api_port == 8765

    def test_raises_config_missing_error_on_missing_file(self):
        with patch("services.secrets_manager.load_secrets",
                   side_effect=FileNotFoundError("key not found")):
            with pytest.raises(ConfigMissingError, match="key not found"):
                load_config()

    def test_ignores_unknown_keys_in_secrets(self):
        """Extra keys in the secrets file (from future versions) should be silently dropped."""
        data = asdict(_full_cfg())
        data["future_unknown_key"] = "some_value"

        with patch("services.secrets_manager.load_secrets", return_value=data):
            cfg = load_config()
        assert not hasattr(cfg, "future_unknown_key")

    def test_partial_secrets_use_defaults(self):
        """A secrets file with only some fields filled in should fill the rest with defaults."""
        with patch("services.secrets_manager.load_secrets",
                   return_value={"tidb_host": "partial_host"}):
            cfg = load_config()
        assert cfg.tidb_host == "partial_host"
        assert cfg.tidb_port == 4000      # default
        assert cfg.resend_api_key == ""   # default


class TestSaveConfig:
    def test_saves_all_fields(self):
        cfg = _full_cfg()

        saved_data = {}

        def capture_save(data):
            saved_data.update(data)

        with patch("services.secrets_manager.save_secrets", side_effect=capture_save), \
             patch("services.secrets_manager._key_path") as mock_kp:
            mock_kp.return_value = MagicMock(exists=MagicMock(return_value=True))
            save_config(cfg)

        assert saved_data["tidb_host"] == "myhost"
        assert saved_data["resend_api_key"] == "re_test_key"
        assert saved_data["api_secret_token"] == "token123"

    def test_generates_key_if_missing(self):
        cfg = _full_cfg()

        with patch("services.secrets_manager.save_secrets"), \
             patch("services.secrets_manager._key_path") as mock_kp, \
             patch("services.secrets_manager.generate_local_key") as mock_gen:
            mock_kp.return_value = MagicMock(exists=MagicMock(return_value=False))
            save_config(cfg)
            mock_gen.assert_called_once()

    def test_does_not_generate_key_if_exists(self):
        cfg = _full_cfg()

        with patch("services.secrets_manager.save_secrets"), \
             patch("services.secrets_manager._key_path") as mock_kp, \
             patch("services.secrets_manager.generate_local_key") as mock_gen:
            mock_kp.return_value = MagicMock(exists=MagicMock(return_value=True))
            save_config(cfg)
            mock_gen.assert_not_called()


class TestConfigMissingError:
    def test_is_exception_subclass(self):
        assert issubclass(ConfigMissingError, Exception)

    def test_raises_with_message(self):
        with pytest.raises(ConfigMissingError, match="setup wizard"):
            raise ConfigMissingError("Run the setup wizard first.")
