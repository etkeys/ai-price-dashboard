"""Tests for the run.py entry point."""

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.config import ConfigError


MODULE_NAME = "run"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _import_run(monkeypatch, **env):
    """Import ``run.py`` fresh with the supplied environment variables.

    Removing the module from ``sys.modules`` first guarantees that the WSGI
    import path is re-executed with the desired environment.
    """
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    sys.modules.pop(MODULE_NAME, None)
    return importlib.import_module(MODULE_NAME)


class TestRunConfigSelection:
    """run.py must select configs correctly for direct vs. WSGI execution."""

    def test_direct_execution_uses_development_config(self, tmp_path):
        """``python run.py`` always creates a DevelopmentConfig app."""
        # Avoid loading any .env so the test depends only on real env vars.
        # PATH is the only environment variable the subprocess strictly needs.
        env = {"PATH": os.environ.get("PATH", ""), "DOTENV_PATH": str(tmp_path / "no.env")}

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import flask, sys; "
                    "flask.Flask.run = lambda self, *a, **kw: sys.exit(0); "
                    f"run_path = {str(REPO_ROOT / 'run.py')!r}; "
                    "exec(compile(open(run_path).read(), run_path, 'exec'))"
                ),
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    def test_wsgi_import_defaults_to_production(self, monkeypatch):
        """A WSGI import without FLASK_CONFIG defaults to production."""
        run_module = _import_run(
            monkeypatch,
            FLASK_CONFIG=None,
            SECRET_KEY="valid-production-secret",
        )
        assert run_module.app.config["DEBUG"] is False
        assert run_module.app.config["SECRET_KEY"] == "valid-production-secret"

    def test_wsgi_import_honors_flask_config(self, monkeypatch):
        """A WSGI import uses FLASK_CONFIG when provided."""
        run_module = _import_run(
            monkeypatch,
            FLASK_CONFIG="development",
            SECRET_KEY=None,
        )
        assert run_module.app.config["DEBUG"] is True
        assert run_module.app.config["SECRET_KEY"] == "dev-secret-key"

    def test_wsgi_import_with_blank_flask_config_defaults_to_production(
        self, monkeypatch
    ):
        """Blank/whitespace FLASK_CONFIG resolves to production."""
        run_module = _import_run(
            monkeypatch,
            FLASK_CONFIG="   ",
            SECRET_KEY="valid-production-secret",
        )
        assert run_module.app.config["DEBUG"] is False

    def test_wsgi_import_missing_secret_key_fails(self, monkeypatch):
        """Production startup during import must fail without SECRET_KEY."""
        with pytest.raises(ConfigError, match="non-empty SECRET_KEY"):
            _import_run(
                monkeypatch,
                FLASK_CONFIG=None,
                SECRET_KEY=None,
            )

    def test_wsgi_import_whitespace_secret_key_fails(self, monkeypatch):
        """Production startup during import must fail with whitespace-only SECRET_KEY."""
        with pytest.raises(ConfigError, match="non-empty SECRET_KEY"):
            _import_run(
                monkeypatch,
                FLASK_CONFIG=None,
                SECRET_KEY="   ",
            )
