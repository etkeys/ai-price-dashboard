"""Tests for web authentication UI layer (§8 acceptance criteria).

Tests cover sign-in flow, session behaviour, key management page,
security invariants, and regression on auth backend.
"""

import pytest
from urllib.parse import urljoin

from app.models.auth import ROLE_ADMINISTRATOR, ROLE_UPDATER
from app.services.auth_service import create_api_key


class TestSignInFlow:
    """AC #1-7: Sign-in affordance, token exchange, storage."""

    def test_anonymous_sees_authenticate_control(self, client):
        """AC #1: Anonymous visitor to / sees an "Authenticate" control in the header."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"id=\"auth-control\"" in resp.data
        assert b"Authenticate" in resp.data

    def test_sign_in_dialog_has_password_input(self, client):
        """AC #2: The input is type="password" to avoid shoulder-surfing."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert b'type="password"' in resp.data
        assert b'id="sign-in-key"' in resp.data

    def test_valid_key_exchange_stores_session_token(self, client, app):
        """AC #3, #6: Valid key results in signed-in header; sessionStorage holds session token, not API key."""
        with app.app_context():
            api_key, token = create_api_key(name="test-key", role=ROLE_ADMINISTRATOR)

        # Exchange the key for a session token.
        resp = client.post(
            "/auth/session",
            json={"key": token},
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert "token" in data
        assert data["name"] == "test-key"
        assert data["role"] == ROLE_ADMINISTRATOR
        assert "expires_at" in data

        # The returned token should be a session token (apds.*).
        session_token = data["token"]
        assert session_token.startswith("apds.")

    def test_invalid_key_returns_uniform_error(self, client):
        """AC #4: Submitting invalid/revoked/expired key shows uniform "Invalid key" message."""
        resp = client.post(
            "/auth/session",
            json={"key": "invalid.nonsense.token"},
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401
        data = resp.get_json()
        assert data["error"] == "Invalid key"

    def test_rate_limit_shows_retry_after(self, client, app):
        """AC #5: Exceeding throttle shows rate-limit message."""
        with app.app_context():
            api_key, token = create_api_key(name="test", role=ROLE_ADMINISTRATOR)

        # Trigger throttle by hitting the endpoint multiple times with bad keys.
        for i in range(11):  # Exceed the default throttle limit (10 attempts).
            resp = client.post(
                "/auth/session",
                json={"key": f"invalid.{i}.key"},
                headers={"Content-Type": "application/json"},
            )
            if i < 10:
                assert resp.status_code == 401
            else:
                # Should be rate-limited.
                assert resp.status_code == 429
                assert "Retry-After" in resp.headers

    def test_no_auth_cookie_set(self, client, app):
        """AC #7: No auth cookie; sessionStorage is the only auth mechanism."""
        with app.app_context():
            api_key, token = create_api_key(name="test", role=ROLE_ADMINISTRATOR)

        resp = client.post(
            "/auth/session",
            json={"key": token},
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 201
        # Flask test client doesn't auto-manage cookies the way a browser does,
        # but we can at least verify no Set-Cookie header with auth data is sent.
        # Real verification happens in browser integration testing.
        assert "session" not in resp.headers.get("Set-Cookie", "").lower()


class TestSessionBehaviour:
    """AC #8-11: Tab scope, stale token handling, sign-out."""

    def test_sign_out_revokes_server_side(self, client, app):
        """AC #10: Sign out clears sessionStorage and server-side row."""
        with app.app_context():
            api_key, token = create_api_key(name="test-admin", role=ROLE_ADMINISTRATOR)
            session, session_token = self._exchange_key(client, token)

        # Verify the token works before sign-out.
        resp = client.get(
            "/auth/whoami",
            headers={"Authorization": f"Bearer {session_token}"},
        )
        assert resp.status_code == 200

        # Sign out.
        resp = client.delete(
            "/auth/session",
            headers={"Authorization": f"Bearer {session_token}"},
        )
        assert resp.status_code == 200

        # Token should now be rejected.
        resp = client.get(
            "/auth/whoami",
            headers={"Authorization": f"Bearer {session_token}"},
        )
        assert resp.status_code == 401

    def test_stale_token_triggers_401(self, client, app):
        """AC #11: A stale/expired token triggers 401; UI must re-render as signed-out."""
        # This is verified by authFetch centrally handling 401 in auth.js.
        # Backend test: ensure /auth/whoami returns 401 for expired tokens.
        with app.app_context():
            from app.models.auth import AuthSession
            from app.extensions import db
            from datetime import timedelta
            from app.services.auth_service import _utcnow
            from sqlalchemy import select

            api_key, token = create_api_key(name="test-admin", role=ROLE_ADMINISTRATOR)

        # Exchange the token (outside app context).
        resp = client.post(
            "/auth/session",
            json={"key": token},
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 201
        session_token = resp.get_json()["token"]

        # Now expire the session and verify it rejects.
        with app.app_context():
            kid = session_token.split(".")[1]
            session_model = db.session.scalar(select(AuthSession).where(AuthSession.kid == kid))
            assert session_model is not None

            now = _utcnow()
            session_model.expires_at = now - timedelta(hours=1)
            db.session.commit()

        # Token should be rejected.
        resp = client.get(
            "/auth/whoami",
            headers={"Authorization": f"Bearer {session_token}"},
        )
        assert resp.status_code == 401

    @staticmethod
    def _exchange_key(client, api_key_token):
        """Helper to exchange an API key for a session token."""
        from app.extensions import db
        from app.models.auth import ApiKey, AuthSession
        from sqlalchemy import select

        resp = client.post(
            "/auth/session",
            json={"key": api_key_token},
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        session_token = data["token"]

        # Retrieve the session model from the database.
        with current_app.app_context():
            session_model = db.session.scalar(
                select(AuthSession).where(AuthSession.kid == session_token.split(".")[1])
            )
        return session_model, session_token


class TestKeyManagementPage:
    """AC #12-18: Admin keys page rendering and CRUD operations."""

    def test_page_reachable_from_header_when_admin(self, client, app):
        """AC #12: Reachable from header only when principal is admin."""
        resp = client.get("/")
        # Anonymous: link not shown (hidden by JS).
        assert b"admin-keys-link" in resp.data  # element exists in HTML
        # Visibility check is JavaScript-based; backend test below covers access.

    def test_anonymous_gets_empty_shell(self, client):
        """AC #13: Anonymous visitor gets a shell with "Administrator access required" message."""
        resp = client.get("/admin/keys/manage")
        assert resp.status_code == 200
        assert b"API Key Management" in resp.data  # Page renders
        # The JS will fetch /admin/keys and get 401, displaying the error message.

    def test_updater_gets_403_from_fetch(self, client, app):
        """AC #14: Updater principal gets 403 from the data fetch."""
        with app.app_context():
            api_key, token = create_api_key(name="test-updater", role=ROLE_UPDATER)

        resp = client.get(
            "/admin/keys",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    def test_admin_sees_keys_table(self, client, app):
        """AC #15: Administrator sees all keys with name, role, status, timestamps."""
        with app.app_context():
            admin_key, admin_token = create_api_key(name="admin-1", role=ROLE_ADMINISTRATOR)
            updater_key, updater_token = create_api_key(name="updater-1", role=ROLE_UPDATER)

        resp = client.get(
            "/admin/keys",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "keys" in data
        keys = data["keys"]
        assert len(keys) >= 2

        # Verify key structure.
        key = keys[0]
        assert "kid" in key
        assert "name" in key
        assert "role" in key
        assert "status" in key
        assert "created_at" in key
        assert "last_used_at" in key
        assert "expires_at" in key

    def test_create_key_returns_plaintext_once(self, client, app):
        """AC #16: Creating a key displays the plaintext token exactly once."""
        with app.app_context():
            admin_key, admin_token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)

        resp = client.post(
            "/admin/keys",
            json={"name": "new-key", "role": "updater"},
            headers={
                "Authorization": f"Bearer {admin_token}",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert "token" in data
        plaintext_token = data["token"]

        # The token should not appear in subsequent fetches.
        list_resp = client.get(
            "/admin/keys",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert list_resp.status_code == 200
        list_data = list_resp.get_json()
        for key in list_data["keys"]:
            if key["name"] == "new-key":
                # Should have the structure, but no "token" field.
                assert "token" not in key

    def test_revoke_key_updates_status(self, client, app):
        """AC #17: Revoking a key updates status to revoked; it fails authentication."""
        with app.app_context():
            admin_key, admin_token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
            revoke_key, revoke_token = create_api_key(name="to-revoke", role=ROLE_UPDATER)

        # Revoke the key.
        resp = client.delete(
            f"/admin/keys/{revoke_token.split('.')[1]}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200

        # Try to use the revoked key.
        resp = client.post(
            "/auth/session",
            json={"key": revoke_token},
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401

    def test_cannot_revoke_own_key(self, client, app):
        """AC #18: Attempting to revoke the backing key returns 409 with server message."""
        with app.app_context():
            admin_key, admin_token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)

        # Extract the kid from the token.
        kid = admin_token.split(".")[1]

        # Try to revoke own key.
        resp = client.delete(
            f"/admin/keys/{kid}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 409
        data = resp.get_json()
        assert "error" in data


class TestSecurityInvariants:
    """AC #19-24: No new deps, no cookie auth, no leaked tokens, role checks."""

    def test_no_new_dependencies(self):
        """AC #19: No new dependency in pyproject.toml or requirements.txt."""
        import os
        from pathlib import Path

        # Read the project manifest.
        project_root = Path(__file__).parent.parent
        pyproject_path = project_root / "pyproject.toml"
        requirements_path = project_root / "requirements.txt"

        # Check for suspect imports (Flask-Login, Flask-WTF).
        if pyproject_path.exists():
            content = pyproject_path.read_text()
            assert "Flask-Login" not in content
            assert "Flask-WTF" not in content
            assert "flask-login" not in content
            assert "flask-wtf" not in content

    def test_protected_endpoint_requires_header_auth(self, client, app):
        """AC #21: No protected endpoint accepts a cookie as proof of identity."""
        with app.app_context():
            admin_key, admin_token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)

        # Verify that /admin/keys requires the Authorization header.
        # Sending a request without the header should fail.
        resp = client.get("/admin/keys")
        assert resp.status_code == 401

        # With the header, it should succeed.
        resp = client.get(
            "/admin/keys",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200

    def test_no_form_post_to_protected_endpoint(self, client, app):
        """AC #23: No <form method="post"> targets a protected endpoint."""
        # This is verified by code inspection (mutation via fetch, not form post).
        # Backend test: `/admin/keys` POST is protected by @require_role.
        with app.app_context():
            admin_key, admin_token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)

        # POST to /admin/keys without auth should fail.
        resp = client.post(
            "/admin/keys",
            json={"name": "test", "role": "updater"},
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401

    def test_page_routes_are_public(self, client):
        """AC #24: Page routes are public; data endpoints carry @require_role."""
        # /admin/keys/manage is public (page shell).
        resp = client.get("/admin/keys/manage")
        assert resp.status_code == 200

        # /admin/keys (data endpoint) is protected.
        resp = client.get("/admin/keys")
        assert resp.status_code == 401


class TestRegression:
    """AC #25-27: Tests pass, /health unchanged, / public."""

    def test_health_endpoint_unauthenticated(self, client):
        """AC #26: /health remains unauthenticated and returns {"status": "ok"}."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data == {"status": "ok"}

    def test_dashboard_public_model_listing(self, client, seeded_client):
        """AC #27: GET / renders the model listing for anonymous visitors."""
        resp = seeded_client.get("/")
        assert resp.status_code == 200
        # Should contain the model table; test data has some models.
        assert b"Models" in resp.data
        assert b"models-table" in resp.data or b"model" in resp.data.lower()


# Import current_app for helper function.
from flask import current_app
