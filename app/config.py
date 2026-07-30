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

    # Authentication / session settings (§3.4 of auth spec)
    AUTH_SESSION_ABSOLUTE_LIFETIME = int(
        os.environ.get("AUTH_SESSION_ABSOLUTE_LIFETIME", "43200")
    )  # 12 hours (seconds)
    AUTH_SESSION_IDLE_TIMEOUT = int(
        os.environ.get("AUTH_SESSION_IDLE_TIMEOUT", "3600")
    )  # 60 minutes (seconds)
    AUTH_SESSION_TOUCH_INTERVAL = int(
        os.environ.get("AUTH_SESSION_TOUCH_INTERVAL", "60")
    )  # seconds between last_seen_at updates
    AUTH_RECOVERY_KEY_LIFETIME = int(
        os.environ.get("AUTH_RECOVERY_KEY_LIFETIME", "900")
    )  # 15 minutes (seconds)

    # Simple in-process rate limit for the unauthenticated exchange endpoints.
    AUTH_EXCHANGE_MAX_ATTEMPTS = int(
        os.environ.get("AUTH_EXCHANGE_MAX_ATTEMPTS", "10")
    )
    AUTH_EXCHANGE_WINDOW_SECONDS = int(
        os.environ.get("AUTH_EXCHANGE_WINDOW_SECONDS", "300")
    )  # 5 minutes

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
