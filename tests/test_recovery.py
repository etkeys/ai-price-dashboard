"""Tests for container-only recovery and bootstrap CLI commands.

These complement tests/test_auth.py by covering the CLI issuance paths that
require shell access to the running container (or equivalent CLI access).
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner
from sqlalchemy import func, select

from app.commands import auth_command
from app.extensions import db
from app.models.auth import ApiKey, RecoveryKey
from app.services.auth_service import (
    ROLE_ADMINISTRATOR,
    TOKEN_PREFIX_API_KEY,
    TOKEN_PREFIX_RECOVERY,
    _utcnow,
    create_api_key,
    create_recovery_key,
)


@pytest.fixture
def runner():
    """Provide a fresh Click test runner."""
    return CliRunner()


class TestRecoveryCli:
    """CLI issuance of recovery/break-glass keys is container-only."""

    def test_cli_recovery_key_issues_apdr_token(self, app, runner):
        result = runner.invoke(auth_command, ["recovery-key"])
        assert result.exit_code == 0, result.output
        token = next(
            line
            for line in result.output.splitlines()
            if line.startswith(TOKEN_PREFIX_RECOVERY)
        )
        with app.app_context():
            row = db.session.scalar(
                select(RecoveryKey).where(RecoveryKey.kid == token.split(".")[1])
            )
            assert row is not None
            assert row.consumed_at is None
            assert row.expires_at > _utcnow()

    def test_cli_recovery_key_invalidates_prior_live_key(self, app, runner):
        first = runner.invoke(auth_command, ["recovery-key"])
        assert first.exit_code == 0
        first_token = next(
            line
            for line in first.output.splitlines()
            if line.startswith(TOKEN_PREFIX_RECOVERY)
        )

        second = runner.invoke(auth_command, ["recovery-key"])
        assert second.exit_code == 0
        second_token = next(
            line
            for line in second.output.splitlines()
            if line.startswith(TOKEN_PREFIX_RECOVERY)
        )

        with app.app_context():
            first_row = db.session.scalar(
                select(RecoveryKey).where(RecoveryKey.kid == first_token.split(".")[1])
            )
            second_row = db.session.scalar(
                select(RecoveryKey).where(RecoveryKey.kid == second_token.split(".")[1])
            )
            assert first_row is not None
            assert second_row is not None
            assert first_row.consumed_at is not None
            assert second_row.consumed_at is None

    def test_cli_recovery_key_claim_creates_admin_key(self, app, runner):
        result = runner.invoke(auth_command, ["recovery-key"])
        assert result.exit_code == 0
        token = next(
            line
            for line in result.output.splitlines()
            if line.startswith(TOKEN_PREFIX_RECOVERY)
        )

        with app.test_client() as client:
            resp = client.post(
                "/auth/recovery/claim",
                json={"recovery_key": token, "name": "cli-recovered"},
            )
            assert resp.status_code == 201
            assert resp.json["role"] == ROLE_ADMINISTRATOR
            assert resp.json["token"].startswith(TOKEN_PREFIX_API_KEY)

    def test_recovery_key_expires(self, app, runner):
        """A recovery key past its 15-minute lifetime cannot be claimed."""
        from datetime import timedelta

        with app.app_context():
            rk, token = create_recovery_key()
            # Force expiry by moving created_at and expires_at backwards.
            rk.expires_at = _utcnow() - timedelta(seconds=1)
            rk.created_at = rk.expires_at - timedelta(seconds=1)
            db.session.commit()

        with app.test_client() as client:
            resp = client.post(
                "/auth/recovery/claim",
                json={"recovery_key": token, "name": "too-late"},
            )
            assert resp.status_code == 401


class TestBootstrapCli:
    """Bootstrap CLI creates an Administrator key only when none exists."""

    def test_bootstrap_creates_admin_key_when_empty(self, app, runner):
        result = runner.invoke(auth_command, ["bootstrap"])
        assert result.exit_code == 0, result.output
        token = next(
            line
            for line in result.output.splitlines()
            if line.startswith(TOKEN_PREFIX_API_KEY)
        )
        with app.app_context():
            row = db.session.scalar(
                select(ApiKey).where(ApiKey.kid == token.split(".")[1])
            )
            assert row is not None
            assert row.role == ROLE_ADMINISTRATOR
            assert row.name == "bootstrap"

    def test_bootstrap_is_idempotent(self, app, runner):
        runner.invoke(auth_command, ["bootstrap"])
        result = runner.invoke(auth_command, ["bootstrap"])
        assert result.exit_code == 0
        assert "already exists" in result.output
        with app.app_context():
            assert db.session.scalar(select(func.count()).select_from(ApiKey)) == 1

    def test_bootstrap_creates_new_key_when_only_revoked_admin_exists(
        self, app, runner
    ):
        create_result = runner.invoke(auth_command, ["bootstrap"])
        assert create_result.exit_code == 0, create_result.output
        token = next(
            line
            for line in create_result.output.splitlines()
            if line.startswith(TOKEN_PREFIX_API_KEY)
        )
        kid = token.split(".")[1]
        with app.app_context():
            row = db.session.scalar(select(ApiKey).where(ApiKey.kid == kid))
            assert row is not None
            row.revoked_at = _utcnow()
            db.session.commit()

        result = runner.invoke(auth_command, ["bootstrap"])
        assert result.exit_code == 0, result.output
        new_token = next(
            (
                line
                for line in result.output.splitlines()
                if line.startswith(TOKEN_PREFIX_API_KEY)
            ),
            None,
        )
        assert new_token is not None

    def test_bootstrap_idempotent_after_manual_admin_creation(self, app, runner):
        with app.app_context():
            create_api_key(name="manual", role=ROLE_ADMINISTRATOR)
        result = runner.invoke(auth_command, ["bootstrap"])
        assert result.exit_code == 0
        assert "already exists" in result.output
