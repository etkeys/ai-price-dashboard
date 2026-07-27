"""Configuration classes for the Flask application."""

import os

from dotenv import load_dotenv

load_dotenv()


class ConfigError(ValueError):
    """Raised when configuration validation fails."""


class Config:
    """Base configuration shared by all environments."""

    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///app.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    @property
    def SECRET_KEY(self) -> str:  # noqa: N802
        return os.environ.get("SECRET_KEY", "dev-secret-key").strip()


class DevelopmentConfig(Config):
    """Development configuration."""

    DEBUG = True


class ProductionConfig(Config):
    """Production configuration."""

    DEBUG = False

    @property
    def SECRET_KEY(self) -> str:  # noqa: N802
        value = os.environ.get("SECRET_KEY", "").strip()
        if not value:
            raise ConfigError(
                "A non-empty SECRET_KEY environment variable is required for production."
            )
        return value


class TestingConfig(Config):
    """Testing configuration."""

    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SECRET_KEY = "test-only-secret-key"


config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}
