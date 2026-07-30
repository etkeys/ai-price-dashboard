"""Tests for token-based authentication core.

These tests cover the acceptance criteria in §10 of
_research/2607301109_api-key-auth-design.md.
"""

from __future__ import annotations

import datetime
from unittest.mock import patch

import pytest
from flask import Flask, request
from sqlalchemy import select

from app.extensions import db
from app.models.auth import ApiKey, AuthEvent, AuthSession, RecoveryKey
from app.services.auth_service import (
    API_KEY_LENGTH,
    ROLE_ADMINISTRATOR,
    ROLE_UPDATER,
    TOKEN_PREFIX_API_KEY,
    TOKEN_PREFIX_RECOVERY,
    TOKEN_PREFIX_SESSION,
    _hash_secret,
    _utcnow,
    build_token,
    claim_recovery_key,
    create_api_key,
    create_auth_session,
    create_recovery_key,
    generate_kid,
    generate_secret,
    generate_token,
    has_role,
    parse_token,
    resolve_principal,
    revoke_api_key,
    revoke_auth_session,
)


@pytest.fixture
def admin_key(client, app):
    """Create and yield an Administrator API key inside the app context."""
    with app.app_context():
        api_key, token = create_api_key(name="test-admin", role=ROLE_ADMINISTRATOR)
        yield api_key, token


@pytest.fixture
def updater_key(client, app):
    """Create and yield an Updater API key inside the app context."""
    with app.app_context():
        api_key, token = create_api_key(name="test-updater", role=ROLE_UPDATER)
        yield api_key, token


def make_auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def make_json_header() -> dict[str, str]:
    return {"Content-Type": "application/json"}


class TestTokenFormat:
    """AC #1-5: token construction, parsing, delimiter, and zero-query rejection."""

    def test_kid_and_secret_lengths(self):
        kid = generate_kid()
        secret = generate_secret()
        assert len(kid) == 12
        assert len(secret) == 43

    def test_generated_token_format(self):
        token, kid, secret = generate_token(TOKEN_PREFIX_API_KEY)
        assert token == f"{TOKEN_PREFIX_API_KEY}.{kid}.{secret}"
        assert len(token) == API_KEY_LENGTH

    def test_parse_token_splits_on_dot_not_underscore(self):
        # Hardcoded token whose 12-char kid and 43-char secret both contain '_' and '-'.
        token = "apdk.Gr-d1B_Jgs4E.NDgf9HNm-0AjOyAW5ugX_8YWvHhVlKYZ8okq7f0Swcw"
        assert len(token) == 61
        parsed = parse_token(token)
        assert parsed is not None
        prefix, kid, secret = parsed
        assert prefix == TOKEN_PREFIX_API_KEY
        assert kid == "Gr-d1B_Jgs4E"
        assert secret == "NDgf9HNm-0AjOyAW5ugX_8YWvHhVlKYZ8okq7f0Swcw"

    def test_parse_rejects_wrong_length(self):
        assert parse_token("apdk.kid.secret") is None
        assert parse_token("apdk" + "." * 60) is None

    def test_parse_rejects_bad_prefix(self):
        token = build_token("badprefix", generate_kid(), generate_secret())
        assert parse_token(token) is None

    def test_parse_rejects_too_many_parts(self):
        token = f"apdk.{generate_kid()}.{generate_secret()}.extra"
        assert parse_token(token) is None

    def test_hash_secret_is_sha256_hex(self):
        secret = generate_secret()
        assert len(_hash_secret(secret)) == 64
        assert _hash_secret(secret) == _hash_secret(secret)


class TestRoles:
    """AC #10: role ranking."""

    def test_administrator_outranks_updater(self):
        assert has_role(ROLE_ADMINISTRATOR, ROLE_UPDATER)
        assert has_role(ROLE_ADMINISTRATOR, ROLE_ADMINISTRATOR)
        assert has_role(ROLE_UPDATER, ROLE_UPDATER)
        assert not has_role(ROLE_UPDATER, ROLE_ADMINISTRATOR)


class TestApiKeyLifecycle:
    """AC #18-22: creation, uniqueness, revocation, self-revoke guard."""

    def test_create_api_key_returns_token_once(self, app, admin_key):
        api_key, token = admin_key
        assert token.startswith(f"{TOKEN_PREFIX_API_KEY}.")
        with app.app_context():
            row = db.session.get(ApiKey, api_key.id)
            assert row is not None
            assert row.kid in token
            assert row.secret_hash == _hash_secret(token.split(".")[2])

    def test_duplicate_active_name_returns_integrity_error(self, app):
        with app.app_context():
            create_api_key(name="same-name", role=ROLE_ADMINISTRATOR)
            with pytest.raises(Exception):  # IntegrityError subclass wrapped in DBAPI
                create_api_key(name="same-name", role=ROLE_ADMINISTRATOR)

    def test_create_api_key_rejects_past_expiry(self, app):
        with app.app_context():
            past = _utcnow() - datetime.timedelta(seconds=1)
            with pytest.raises(ValueError, match="expires_at must be in the future"):
                create_api_key(name="past-expiry", role=ROLE_ADMINISTRATOR, expires_at=past)

    def test_revoke_api_key_sets_revoked_at(self, app, admin_key):
        api_key, _token = admin_key
        with app.app_context():
            row = revoke_api_key(api_key.kid)
            assert row.revoked_at is not None

    def test_revoke_api_key_is_idempotent(self, app, admin_key):
        api_key, _token = admin_key
        with app.app_context():
            revoke_api_key(api_key.kid)
            row = revoke_api_key(api_key.kid)
            # Second call must not error and row remains revoked.
            assert row.revoked_at is not None

    def test_revoke_api_key_cascades_to_sessions(self, app, admin_key):
        api_key, token = admin_key
        with app.app_context():
            session_model, _session_token = create_auth_session(api_key)
            revoke_api_key(api_key.kid)
            row = db.session.get(AuthSession, session_model.id)
            assert row.revoked_at is not None


class TestResolver:
    """AC #6-9, #12: resolver behaviour for keys, sessions, expiry, and revocation."""

    def test_resolve_api_key_authenticates(self, app, admin_key):
        api_key, token = admin_key
        with app.app_context():
            with app.test_request_context(
                "/", headers={"Authorization": f"Bearer {token}"}
            ):
                principal = resolve_principal(request)
                assert principal is not None
                assert principal.role == ROLE_ADMINISTRATOR
                assert principal.kind.value == "key"

    def test_resolve_rejects_revoked_key(self, app, admin_key):
        api_key, token = admin_key
        with app.app_context():
            revoke_api_key(api_key.kid)
            with app.test_request_context(
                "/", headers={"Authorization": f"Bearer {token}"}
            ):
                principal = resolve_principal(request)
                assert principal is None

    def test_resolve_session_authenticates(self, app, admin_key):
        api_key, token = admin_key
        with app.app_context():
            session_model, session_token = create_auth_session(api_key)
            with app.test_request_context(
                "/", headers={"Authorization": f"Bearer {session_token}"}
            ):
                principal = resolve_principal(request)
                assert principal is not None
                assert principal.role == ROLE_ADMINISTRATOR
                assert principal.kind.value == "session"

    def test_resolve_session_fails_when_parent_revoked(self, app, admin_key):
        api_key, token = admin_key
        with app.app_context():
            session_model, session_token = create_auth_session(api_key)
            # Manually un-revoke cascade so resolver must re-check parent itself.
            revoke_api_key(api_key.kid)
            session_model.revoked_at = None
            db.session.commit()
            with app.test_request_context(
                "/", headers={"Authorization": f"Bearer {session_token}"}
            ):
                principal = resolve_principal(request)
                assert principal is None

    def test_resolve_rejects_recovery_key_as_bearer(self, app, admin_key):
        api_key, token = admin_key
        with app.app_context():
            recovery_key, recovery_token = create_recovery_key()
            with app.test_request_context(
                "/", headers={"Authorization": f"Bearer {recovery_token}"}
            ):
                principal = resolve_principal(request)
                assert principal is None

    def test_resolve_rejects_expired_key(self, app):
        with app.app_context():
            future = _utcnow() + datetime.timedelta(days=1)
            api_key, token = create_api_key(
                name="expires-tomorrow", role=ROLE_ADMINISTRATOR, expires_at=future
            )
            past = future + datetime.timedelta(seconds=1)
            with patch("app.services.auth_service._utcnow", return_value=past):
                with app.test_request_context(
                    "/", headers={"Authorization": f"Bearer {token}"}
                ):
                    principal = resolve_principal(request)
                    assert principal is None

    def test_resolve_rejects_expired_session(self, app, admin_key, monkeypatch):
        api_key, key_token = admin_key
        with app.app_context():
            session_model, session_token = create_auth_session(api_key)
            # Force expiry by winding the clock past the absolute lifetime.
            future = _utcnow() + datetime.timedelta(seconds=1_000_000)
            with patch("app.services.auth_service._utcnow", return_value=future):
                with app.test_request_context(
                    "/", headers={"Authorization": f"Bearer {session_token}"}
                ):
                    principal = resolve_principal(request)
                    assert principal is None

    def test_resolve_rejects_idle_expired_session(self, app, admin_key):
        api_key, key_token = admin_key
        with app.app_context():
            session_model, session_token = create_auth_session(api_key)
            # last_seen_at is now; wind far into the future.
            far_future = _utcnow() + datetime.timedelta(days=2)
            with patch("app.services.auth_service._utcnow", return_value=far_future):
                with app.test_request_context(
                    "/", headers={"Authorization": f"Bearer {session_token}"}
                ):
                    principal = resolve_principal(request)
                    assert principal is None


class TestAuthHttpEndpoints:
    """HTTP-level tests for /auth/* and /admin/* routes."""

    def test_create_session_exchanges_key_for_token(self, client, admin_key, app):
        api_key, token = admin_key
        response = client.post("/auth/session", json={"key": token})
        assert response.status_code == 201
        assert response.json["role"] == ROLE_ADMINISTRATOR
        assert response.json["name"] == api_key.name
        assert response.json["token"].startswith(f"{TOKEN_PREFIX_SESSION}.")

    def test_create_session_rejects_bad_key(self, client):
        response = client.post("/auth/session", json={"key": "apdk.invalid.invalid"})
        assert response.status_code == 401

    def test_delete_session_revokes_session(self, client, admin_key, app):
        api_key, token = admin_key
        session_response = client.post("/auth/session", json={"key": token})
        session_token = session_response.json["token"]
        # Whoami should work before sign-out.
        assert client.get("/auth/whoami", headers=make_auth_header(session_token)).status_code == 200
        delete_response = client.delete(
            "/auth/session", headers=make_auth_header(session_token)
        )
        assert delete_response.status_code == 200
        assert client.get("/auth/whoami", headers=make_auth_header(session_token)).status_code == 401

    def test_whoami_for_api_key(self, client, updater_key):
        _api_key, token = updater_key
        response = client.get("/auth/whoami", headers=make_auth_header(token))
        assert response.status_code == 200
        assert response.json["role"] == ROLE_UPDATER
        assert response.json["kind"] == "key"

    def test_unauthenticated_admin_routes_return_401(self, client):
        """All admin key routes require administrator authentication."""
        assert client.get("/admin/keys").status_code == 401
        assert client.get("/admin/keys/anykid").status_code == 401
        assert client.post("/admin/keys").status_code == 401
        assert client.delete("/admin/keys/anykid").status_code == 401
        assert client.post("/admin/keys/anykid/revoke").status_code == 401

    def test_admin_role_only_can_manage_keys(self, client, updater_key):
        """Updater (and any non-admin role) is denied on all admin routes."""
        _api_key, token = updater_key
        headers = {**make_auth_header(token), **make_json_header()}
        assert client.get("/admin/keys", headers=make_auth_header(token)).status_code == 403
        assert client.get("/admin/keys/anykid", headers=make_auth_header(token)).status_code == 403
        assert (
            client.post("/admin/keys", headers=headers, json={"name": "no", "role": ROLE_UPDATER}).status_code
            == 403
        )
        assert (
            client.delete("/admin/keys/anykid", headers=make_auth_header(token)).status_code
            == 403
        )
        assert (
            client.post("/admin/keys/anykid/revoke", headers=make_auth_header(token)).status_code
            == 403
        )

    def test_admin_list_requires_admin(self, client, updater_key):
        _api_key, token = updater_key
        response = client.get("/admin/keys", headers=make_auth_header(token))
        assert response.status_code == 403

    def test_admin_create_key_requires_admin(self, client, updater_key):
        _api_key, token = updater_key
        response = client.post(
            "/admin/keys",
            headers={**make_auth_header(token), **make_json_header()},
            json={"name": "hacker", "role": ROLE_ADMINISTRATOR},
        )
        assert response.status_code == 403

    def test_admin_create_key_returns_token_once(self, client, admin_key):
        _api_key, token = admin_key
        response = client.post(
            "/admin/keys",
            headers={**make_auth_header(token), **make_json_header()},
            json={"name": "new-bot", "role": ROLE_UPDATER},
        )
        assert response.status_code == 201
        assert response.json["token"].startswith(f"{TOKEN_PREFIX_API_KEY}.")
        # Listing must not include secret_hash or token.
        list_response = client.get("/admin/keys", headers=make_auth_header(token))
        assert list_response.status_code == 200
        for key in list_response.json["keys"]:
            assert "secret_hash" not in key
            assert "token" not in key

    def test_admin_create_key_with_expiry(self, client, admin_key, app):
        _api_key, token = admin_key
        future = (_utcnow() + datetime.timedelta(days=7)).isoformat()
        response = client.post(
            "/admin/keys",
            headers={**make_auth_header(token), **make_json_header()},
            json={"name": "expiring-bot", "role": ROLE_UPDATER, "expires_at": future},
        )
        assert response.status_code == 201
        assert response.json["expires_at"] == future

    def test_admin_create_key_rejects_past_expiry(self, client, admin_key):
        _api_key, token = admin_key
        past = (_utcnow() - datetime.timedelta(seconds=1)).isoformat()
        response = client.post(
            "/admin/keys",
            headers={**make_auth_header(token), **make_json_header()},
            json={"name": "bad", "role": ROLE_UPDATER, "expires_at": past},
        )
        assert response.status_code == 400

    def test_admin_create_key_rejects_invalid_role(self, client, admin_key):
        _api_key, token = admin_key
        response = client.post(
            "/admin/keys",
            headers={**make_auth_header(token), **make_json_header()},
            json={"name": "trick", "role": "superuser"},
        )
        assert response.status_code == 400

    def test_admin_create_key_rejects_missing_name(self, client, admin_key):
        _api_key, token = admin_key
        response = client.post(
            "/admin/keys",
            headers={**make_auth_header(token), **make_json_header()},
            json={"role": ROLE_UPDATER},
        )
        assert response.status_code == 400

    def test_admin_get_key(self, client, admin_key, app):
        _api_key, token = admin_key
        create_resp = client.post(
            "/admin/keys",
            headers={**make_auth_header(token), **make_json_header()},
            json={"name": "detail-bot", "role": ROLE_UPDATER},
        )
        assert create_resp.status_code == 201
        kid = create_resp.json["kid"]
        detail_resp = client.get(f"/admin/keys/{kid}", headers=make_auth_header(token))
        assert detail_resp.status_code == 200
        assert "secret_hash" not in detail_resp.json
        assert detail_resp.json["kid"] == kid
        assert detail_resp.json["status"] in {"active", "expired"}

    def test_admin_get_key_missing_returns_404(self, client, admin_key):
        _api_key, token = admin_key
        response = client.get("/admin/keys/nosuchkid", headers=make_auth_header(token))
        assert response.status_code == 404

    def test_admin_revoke_key_via_post(self, client, admin_key):
        api_key, token = admin_key
        # Create another admin key so we can revoke without self-revoke guard.
        create_resp = client.post(
            "/admin/keys",
            headers={**make_auth_header(token), **make_json_header()},
            json={"name": "victim", "role": ROLE_ADMINISTRATOR},
        )
        victim_kid = create_resp.json["kid"]
        revoke_resp = client.post(
            f"/admin/keys/{victim_kid}/revoke",
            headers=make_auth_header(token),
        )
        assert revoke_resp.status_code == 200
        detail = client.get(f"/admin/keys/{victim_kid}", headers=make_auth_header(token))
        assert detail.json["status"] == "revoked"

    def test_admin_revoke_key_via_delete(self, client, admin_key):
        api_key, token = admin_key
        create_resp = client.post(
            "/admin/keys",
            headers={**make_auth_header(token), **make_json_header()},
            json={"name": "delete-victim", "role": ROLE_ADMINISTRATOR},
        )
        victim_kid = create_resp.json["kid"]
        revoke_resp = client.delete(
            f"/admin/keys/{victim_kid}",
            headers=make_auth_header(token),
        )
        assert revoke_resp.status_code == 200

    def test_admin_revoke_marks_key_unusable_immediately(self, client, admin_key):
        """Revocation immediately invalidates the token's bearer access."""
        _admin_api_key, admin_token = admin_key
        create_resp = client.post(
            "/admin/keys",
            headers={**make_auth_header(admin_token), **make_json_header()},
            json={"name": "short-lived", "role": ROLE_ADMINISTRATOR},
        )
        assert create_resp.status_code == 201
        victim_token = create_resp.json["token"]
        victim_kid = create_resp.json["kid"]

        # Victim token is usable before revocation.
        assert client.get("/admin/keys", headers=make_auth_header(victim_token)).status_code == 200

        # Revoke using the admin token.
        revoke_resp = client.post(
            f"/admin/keys/{victim_kid}/revoke",
            headers=make_auth_header(admin_token),
        )
        assert revoke_resp.status_code == 200

        # Victim token must be rejected immediately.
        assert client.get("/admin/keys", headers=make_auth_header(victim_token)).status_code == 401
        assert client.get("/auth/whoami", headers=make_auth_header(victim_token)).status_code == 401

    def test_admin_revoke_cascades_to_active_sessions(self, client, admin_key):
        _api_key, token = admin_key
        create_resp = client.post(
            "/admin/keys",
            headers={**make_auth_header(token), **make_json_header()},
            json={"name": "session-victim", "role": ROLE_UPDATER},
        )
        victim_token = create_resp.json["token"]
        victim_kid = create_resp.json["kid"]
        session_resp = client.post("/auth/session", json={"key": victim_token})
        assert session_resp.status_code == 201
        session_token = session_resp.json["token"]

        # Session works before cascading revocation.
        assert client.get("/auth/whoami", headers=make_auth_header(session_token)).status_code == 200

        client.post(f"/admin/keys/{victim_kid}/revoke", headers=make_auth_header(token))

        # Session derived from revoked key must be invalid.
        assert client.get("/auth/whoami", headers=make_auth_header(session_token)).status_code == 401

    def test_admin_self_revoke_guard(self, client, admin_key):
        _api_key, token = admin_key
        list_resp = client.get("/admin/keys", headers=make_auth_header(token))
        own_kid = list_resp.json["keys"][0]["kid"]
        revoke_resp = client.post(
            f"/admin/keys/{own_kid}/revoke", headers=make_auth_header(token)
        )
        assert revoke_resp.status_code == 409

    def test_role_not_read_from_request_body(self, client, updater_key):
        _api_key, token = updater_key
        response = client.post(
            "/admin/keys",
            headers={**make_auth_header(token), **make_json_header()},
            json={"name": "trick", "role": ROLE_ADMINISTRATOR},
        )
        assert response.status_code == 403

    def test_index_and_health_stay_unauthenticated(self, client, seeded_client):
        assert client.get("/").status_code == 200
        assert client.get("/health").status_code == 200

    def test_admin_list_payload_keys(self, client, admin_key):
        _api_key, token = admin_key
        response = client.get("/admin/keys", headers=make_auth_header(token))
        assert response.status_code == 200
        assert "keys" in response.json
        for key in response.json["keys"]:
            assert set(key.keys()) >= {"kid", "name", "role", "status", "created_at"}


class TestRecovery:
    """AC #25-29: recovery key issuance, claiming, and single-use guard."""

    def test_create_recovery_key(self, app):
        with app.app_context():
            recovery_key, token = create_recovery_key()
            assert token.startswith(f"{TOKEN_PREFIX_RECOVERY}.")
            assert recovery_key.consumed_at is None
            assert recovery_key.expires_at > _utcnow()

    def test_recovery_key_issues_only_one_live(self, app):
        with app.app_context():
            _old_key, old_token = create_recovery_key()
            new_key, new_token = create_recovery_key()
            old = db.session.scalar(select(RecoveryKey).where(RecoveryKey.kid == old_token.split(".")[1]))
            assert old.consumed_at is not None
            assert new_key.consumed_at is None

    def test_claim_recovery_key(self, app, client):
        with app.app_context():
            _recovery_key, token = create_recovery_key()
        response = client.post(
            "/auth/recovery/claim",
            json={"recovery_key": token, "name": "recovered-admin"},
        )
        assert response.status_code == 201
        assert response.json["role"] == ROLE_ADMINISTRATOR

    def test_claim_same_recovery_key_twice_fails(self, app, client):
        with app.app_context():
            _recovery_key, token = create_recovery_key()
        first = client.post(
            "/auth/recovery/claim",
            json={"recovery_key": token, "name": "admin-one"},
        )
        assert first.status_code == 201
        second = client.post(
            "/auth/recovery/claim",
            json={"recovery_key": token, "name": "admin-two"},
        )
        assert second.status_code == 401

    def test_failed_claim_does_not_consume(self, app, client):
        with app.app_context():
            _recovery_key, token = create_recovery_key()
        bad_secret = token.rsplit(".", 1)[0] + "." + generate_secret()
        response = client.post(
            "/auth/recovery/claim",
            json={"recovery_key": bad_secret, "name": "admin-wrong"},
        )
        assert response.status_code == 401
        with app.app_context():
            row = db.session.scalar(
                select(RecoveryKey).where(RecoveryKey.kid == token.split(".")[1])
            )
            assert row.consumed_at is None

    def test_recovery_key_as_bearer_returns_401(self, app, client):
        with app.app_context():
            _recovery_key, token = create_recovery_key()
        response = client.get("/admin/keys", headers=make_auth_header(token))
        assert response.status_code == 401


class TestStructural:
    """AC #11: every mutating route outside the two exchange endpoints is gated."""

    EXEMPT_ENDPOINTS = {
        "auth.create_session",
        "auth.claim_recovery",
        "main.health",
    }

    def test_all_mutating_routes_require_role(self, app: Flask):
        exempt_methods = {"GET", "HEAD", "OPTIONS"}
        for rule in app.url_map.iter_rules():
            methods = rule.methods - exempt_methods
            if not methods:
                continue
            if rule.endpoint in self.EXEMPT_ENDPOINTS:
                continue
            func = app.view_functions[rule.endpoint]
            assert getattr(func, "_auth_required_role", None) is not None, (
                f"Endpoint {rule.endpoint} ({methods}) is missing @require_role"
            )
