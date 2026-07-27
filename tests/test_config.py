"""Tests for application configuration."""

import pytest

from app import create_app
from app.config import ConfigError, config


class TestProductionConfig:
    """Production configuration must reject a missing or empty SECRET_KEY."""

    def test_secret_key_missing_raises(self, monkeypatch):
        monkeypatch.delenv("SECRET_KEY", raising=False)
        cfg = config["production"]()
        with pytest.raises(ConfigError, match="non-empty SECRET_KEY"):
            _ = cfg.SECRET_KEY

    def test_secret_key_empty_raises(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "")
        cfg = config["production"]()
        with pytest.raises(ConfigError, match="non-empty SECRET_KEY"):
            _ = cfg.SECRET_KEY

    def test_secret_key_whitespace_raises(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "   ")
        cfg = config["production"]()
        with pytest.raises(ConfigError, match="non-empty SECRET_KEY"):
            _ = cfg.SECRET_KEY

    def test_secret_key_valid_allowed(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "a-secure-production-secret")
        cfg = config["production"]()
        assert cfg.SECRET_KEY == "a-secure-production-secret"

    def test_create_app_production_requires_secret_key(self, monkeypatch):
        """Loading the production config at startup must fail without SECRET_KEY."""
        monkeypatch.delenv("SECRET_KEY", raising=False)
        with pytest.raises(ConfigError, match="non-empty SECRET_KEY"):
            create_app("production")


class TestDevelopmentConfig:
    """Development config falls back to a predictable test/dev key."""

    def test_default_secret_key(self, monkeypatch):
        monkeypatch.delenv("SECRET_KEY", raising=False)
        cfg = config["development"]()
        assert cfg.SECRET_KEY == "dev-secret-key"

    def test_env_secret_key_overrides_default(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "custom-dev-key")
        cfg = config["development"]()
        assert cfg.SECRET_KEY == "custom-dev-key"
