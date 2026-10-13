"""Tests for the public model-update API — PATCH /api/v1/models/<id>.

Coverage follows the plan `_research/2610121946_public-model-update-api-plan-and-decisions.md`
and the confirmed rulings D-040 (strict public JSON numeric types plus the shared
admin boolean-coercion rejection) and D-041 (public transition-only context pairing).

Acceptance areas:
  (1) an updater-role caller can update input/output prices and other editable fields;
  (2) an administrator-role caller can do the same;
  (3) unauthenticated callers are rejected 401; a principal denied the gate is
      rejected 403 — synthesised by mocking ``has_role`` for a known valid
      updater principal, since the schema admits no real lower role;
  (4) 'name' and 'hidden' (plus identity/timestamps) are immutable here: rejected
      400 with the persisted value untouched;
  (5) invalid payloads (wrong types, negative prices, unknown/protected fields,
      incoherent context) return 400 without any partial write;
  (6) a successful update persists and is reflected in a fresh-session reread and
      the subsequent public GET.

Auth paths covered with real keys/sessions: direct API keys (updater and admin),
the short-lived session token, invalid/garbage, revoked, expired, and recovery-as-
bearer rejection. The atomicity tests snapshot scalars, association rows, name,
hidden_at and updated_at and assert all stay unchanged on a failed request.
"""

import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import AiModel
from app.models.auth import ROLE_ADMINISTRATOR, ROLE_UPDATER
from app.services.auth_service import (
    _utcnow,
    create_api_key,
    create_auth_session,
    create_recovery_key,
    revoke_api_key,
)

EXPECTED_MODEL_FIELDS = {
    "id",
    "name",
    "price_in",
    "price_out",
    "context_type",
    "context_tokens",
    "pricing_unit",
    "input_content",
    "output_content",
    "hidden",
    "hidden_at",
    "created_at",
    "updated_at",
}

TOKEN_MODEL = "anthropic/claude-haiku-4.5"  # token context, price_in=1.0
IMAGE_MODEL = "bytedance-seed/seedream-5-0-lite"  # image context, price_in=null


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _make_token(app, role: str, name: str = "caller") -> str:
    with app.app_context():
        _, token = create_api_key(name=name, role=role)
    return token


def _model_id(app, name: str = TOKEN_MODEL) -> int:
    with app.app_context():
        row = db.session.scalar(select(AiModel).where(AiModel.name == name))
        assert row is not None, f"seeded model {name!r} not found"
        return row.id


def _snapshot(app, model_id: int) -> dict:
    """Capture every write-sensitive attribute for atomicity assertions."""
    with app.app_context():
        row = db.session.get(AiModel, model_id)
        assert row is not None
        return {
            "name": row.name,
            "price_in": row.price_in,
            "price_out": row.price_out,
            "context_type": row.context_type,
            "context_tokens": row.context_tokens,
            "pricing_unit": row.pricing_unit,
            "input_content": list(row.input_content),
            "output_content": list(row.output_content),
            "hidden_at": row.hidden_at,
            "updated_at": row.updated_at,
        }


class TestAuthorization:
    """Acceptance 3: authentication and role gating."""

    def test_unauthenticated_returns_401(self, seeded_app):
        model_id = _model_id(seeded_app)
        resp = seeded_app.test_client().patch(
            f"/api/v1/models/{model_id}", json={"price_in": 0.5}
        )
        assert resp.status_code == 401
        assert resp.json == {"error": "Authentication required"}
        assert resp.headers["WWW-Authenticate"] == "Bearer"
        assert resp.headers["Cache-Control"] == "no-store"
        assert "Access-Control-Allow-Origin" not in resp.headers

    def test_garbage_token_returns_401(self, seeded_app):
        model_id = _model_id(seeded_app)
        resp = seeded_app.test_client().patch(
            f"/api/v1/models/{model_id}",
            json={"price_in": 0.5},
            headers=_auth_header("apdk.garbage.garbage"),
        )
        assert resp.status_code == 401

    def test_revoked_key_returns_401(self, seeded_app):
        model_id = _model_id(seeded_app)
        with seeded_app.app_context():
            key, token = create_api_key(name="to-revoke", role=ROLE_ADMINISTRATOR)
            revoke_api_key(key.kid)
        resp = seeded_app.test_client().patch(
            f"/api/v1/models/{model_id}",
            json={"price_in": 0.5},
            headers=_auth_header(token),
        )
        assert resp.status_code == 401

    def test_expired_key_returns_401(self, seeded_app):
        model_id = _model_id(seeded_app)
        with seeded_app.app_context():
            future = _utcnow() + datetime.timedelta(days=1)
            _, token = create_api_key(
                name="expiring", role=ROLE_ADMINISTRATOR, expires_at=future
            )
        past = future + datetime.timedelta(seconds=1)
        with patch("app.services.auth_service._utcnow", return_value=past):
            resp = seeded_app.test_client().patch(
                f"/api/v1/models/{model_id}",
                json={"price_in": 0.5},
                headers=_auth_header(token),
            )
        assert resp.status_code == 401

    def test_recovery_key_as_bearer_returns_401(self, seeded_app):
        model_id = _model_id(seeded_app)
        with seeded_app.app_context():
            _, recovery_token = create_recovery_key()
        resp = seeded_app.test_client().patch(
            f"/api/v1/models/{model_id}",
            json={"price_in": 0.5},
            headers=_auth_header(recovery_token),
        )
        assert resp.status_code == 401

    def test_expired_session_returns_401(self, seeded_app):
        model_id = _model_id(seeded_app)
        client = seeded_app.test_client()
        with seeded_app.app_context():
            _, key_token = create_api_key(name="sess", role=ROLE_UPDATER)
        session_token = client.post("/auth/session", json={"key": key_token}).json["token"]
        future = _utcnow() + datetime.timedelta(seconds=1_000_000)
        with patch("app.services.auth_service._utcnow", return_value=future):
            resp = client.patch(
                f"/api/v1/models/{model_id}",
                json={"price_in": 0.5},
                headers=_auth_header(session_token),
            )
        assert resp.status_code == 401

    def test_denied_role_returns_403(self, seeded_app):
        """No real lower role exists (D-040/D-041, schema). A valid updater principal
        whose authorization decision is denied yields the synthetic 403."""
        model_id = _model_id(seeded_app)
        token = _make_token(seeded_app, ROLE_UPDATER)
        with patch("app.auth.decorators.has_role", return_value=False):
            resp = seeded_app.test_client().patch(
                f"/api/v1/models/{model_id}",
                json={"price_in": 0.5},
                headers=_auth_header(token),
            )
        assert resp.status_code == 403
        assert resp.json == {"error": "Insufficient role"}
        assert resp.headers["Cache-Control"] == "no-store"
        assert "Access-Control-Allow-Origin" not in resp.headers

    def test_unknown_model_id_returns_404(self, seeded_app):
        token = _make_token(seeded_app, ROLE_UPDATER)
        resp = seeded_app.test_client().patch(
            "/api/v1/models/9999999",
            json={"price_in": 0.5},
            headers=_auth_header(token),
        )
        assert resp.status_code == 404
        assert resp.json == {"error": "Model not found"}
        assert resp.headers["Cache-Control"] == "no-store"


class TestAuthorizedRoles:
    """Acceptance 1 & 2: updater and administrator can update prices and editable fields."""

    def test_updater_can_update_prices(self, seeded_app):
        model_id = _model_id(seeded_app)
        token = _make_token(seeded_app, ROLE_UPDATER)
        resp = seeded_app.test_client().patch(
            f"/api/v1/models/{model_id}",
            json={"price_in": 0.1, "price_out": 0.4},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        with seeded_app.app_context():
            row = db.session.get(AiModel, model_id)
            assert row.price_in == 0.1
            assert row.price_out == 0.4

    def test_updater_can_edit_editable_attributes(self, seeded_app):
        model_id = _model_id(seeded_app)
        token = _make_token(seeded_app, ROLE_UPDATER)
        resp = seeded_app.test_client().patch(
            f"/api/v1/models/{model_id}",
            json={
                "pricing_unit": "image",
                "context_type": "image",
                "context_tokens": None,
                "price_in": None,
            },
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        with seeded_app.app_context():
            row = db.session.get(AiModel, model_id)
            assert row.pricing_unit == "image"
            assert row.context_type == "image"
            assert row.context_tokens is None
            assert row.price_in is None

    def test_administrator_can_update(self, seeded_app):
        model_id = _model_id(seeded_app)
        token = _make_token(seeded_app, ROLE_ADMINISTRATOR)
        resp = seeded_app.test_client().patch(
            f"/api/v1/models/{model_id}",
            json={"price_in": 0.25, "price_out": 0.75},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        with seeded_app.app_context():
            row = db.session.get(AiModel, model_id)
            assert row.price_in == 0.25
            assert row.price_out == 0.75

    def test_session_token_can_update(self, seeded_app):
        """The short-lived session exchange path admits an updater (D-012)."""
        model_id = _model_id(seeded_app)
        client = seeded_app.test_client()
        with seeded_app.app_context():
            _, key_token = create_api_key(name="session-updater", role=ROLE_UPDATER)
        session_token = client.post("/auth/session", json={"key": key_token}).json["token"]
        resp = client.patch(
            f"/api/v1/models/{model_id}",
            json={"price_out": 1.25},
            headers=_auth_header(session_token),
        )
        assert resp.status_code == 200
        with seeded_app.app_context():
            assert db.session.get(AiModel, model_id).price_out == 1.25

    def test_success_response_is_no_store_and_has_no_cors(self, seeded_app):
        model_id = _model_id(seeded_app)
        token = _make_token(seeded_app, ROLE_UPDATER)
        resp = seeded_app.test_client().patch(
            f"/api/v1/models/{model_id}",
            json={"price_in": 0.5},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.headers["Cache-Control"] == "no-store"
        assert "Access-Control-Allow-Origin" not in resp.headers


class TestProtectedFields:
    """Acceptance 4: name and hidden (plus identity/timestamps) are immutable."""

    @pytest.mark.parametrize(
        "field,value",
        [
            ("name", "renamed/model"),
            ("hidden", True),
            ("hidden", False),
            ("hidden_at", "2026-01-01T00:00:00Z"),
            ("is_hidden", True),
            ("id", 9999),
            ("created_at", "2026-01-01T00:00:00Z"),
            ("updated_at", "2026-01-01T00:00:00Z"),
        ],
    )
    def test_protected_field_rejected_and_state_unchanged(self, seeded_app, field, value):
        model_id = _model_id(seeded_app)
        before = _snapshot(seeded_app, model_id)
        token = _make_token(seeded_app, ROLE_ADMINISTRATOR)
        resp = seeded_app.test_client().patch(
            f"/api/v1/models/{model_id}",
            json={field: value},
            headers=_auth_header(token),
        )
        assert resp.status_code == 400, field
        assert "Cannot update field" in resp.json["error"], field
        assert resp.headers["Cache-Control"] == "no-store"
        after = _snapshot(seeded_app, model_id)
        assert after == before, f"{field} leaked into storage on a rejected request"


class TestPayloadValidation:
    """Acceptance 5: malformed bodies, wrong types, unknown fields → 400, no write."""

    def test_empty_body_returns_400(self, seeded_app):
        model_id = _model_id(seeded_app)
        token = _make_token(seeded_app, ROLE_UPDATER)
        resp = seeded_app.test_client().patch(
            f"/api/v1/models/{model_id}", json={}, headers=_auth_header(token)
        )
        assert resp.status_code == 400
        assert resp.json == {"error": "A non-empty JSON object is required"}

    def test_non_object_body_returns_400(self, seeded_app):
        model_id = _model_id(seeded_app)
        token = _make_token(seeded_app, ROLE_UPDATER)
        for body in ([], "scalar", 42):
            resp = seeded_app.test_client().patch(
                f"/api/v1/models/{model_id}",
                json=body,
                headers=_auth_header(token),
            )
            assert resp.status_code == 400, body
            assert "non-empty JSON object" in resp.json["error"]

    def test_unknown_field_returns_400(self, seeded_app):
        model_id = _model_id(seeded_app)
        before = _snapshot(seeded_app, model_id)
        token = _make_token(seeded_app, ROLE_UPDATER)
        resp = seeded_app.test_client().patch(
            f"/api/v1/models/{model_id}",
            json={"price_in": 0.5, "not_a_field": 1},
            headers=_auth_header(token),
        )
        assert resp.status_code == 400
        assert resp.json == {"error": "Unknown model field"}
        assert _snapshot(seeded_app, model_id) == before

    def test_negative_price_returns_400(self, seeded_app):
        model_id = _model_id(seeded_app)
        before = _snapshot(seeded_app, model_id)
        token = _make_token(seeded_app, ROLE_UPDATER)
        for body in ({"price_in": -1.0}, {"price_out": -0.5}):
            resp = seeded_app.test_client().patch(
                f"/api/v1/models/{model_id}", json=body, headers=_auth_header(token)
            )
            assert resp.status_code == 400, body
        assert _snapshot(seeded_app, model_id) == before

    def test_price_out_null_returns_400(self, seeded_app):
        model_id = _model_id(seeded_app)
        token = _make_token(seeded_app, ROLE_UPDATER)
        resp = seeded_app.test_client().patch(
            f"/api/v1/models/{model_id}",
            json={"price_out": None},
            headers=_auth_header(token),
        )
        assert resp.status_code == 400
        assert "price_out" in resp.json["error"]

    def test_incoherent_context_returns_400(self, seeded_app):
        model_id = _model_id(seeded_app)
        token = _make_token(seeded_app, ROLE_UPDATER)
        client = seeded_app.test_client()
        # image context cannot carry a numeric token count
        assert client.patch(
            f"/api/v1/models/{model_id}",
            json={"context_type": "image", "context_tokens": 1000},
            headers=_auth_header(token),
        ).status_code == 400
        # token context cannot be null or zero
        assert client.patch(
            f"/api/v1/models/{model_id}",
            json={"context_tokens": 0},
            headers=_auth_header(token),
        ).status_code == 400
        assert client.patch(
            f"/api/v1/models/{model_id}",
            json={"context_tokens": None},
            headers=_auth_header(token),
        ).status_code == 400
        # closed-vocabulary violations
        assert client.patch(
            f"/api/v1/models/{model_id}",
            json={"context_type": "bogus"},
            headers=_auth_header(token),
        ).status_code == 400
        assert client.patch(
            f"/api/v1/models/{model_id}",
            json={"pricing_unit": "per-model"},
            headers=_auth_header(token),
        ).status_code == 400

    def test_invalid_modality_lists_returns_400(self, seeded_app):
        model_id = _model_id(seeded_app)
        token = _make_token(seeded_app, ROLE_UPDATER)
        client = seeded_app.test_client()
        for body in (
            {"input_content": []},  # empty
            {"input_content": ["Text", "Text"]},  # duplicate
            {"input_content": ["Text", "NotAModality"]},  # invalid
            {"input_content": [1, "Text"]},  # non-string
        ):
            resp = client.patch(
                f"/api/v1/models/{model_id}", json=body, headers=_auth_header(token)
            )
            assert resp.status_code == 400, body

    @pytest.mark.parametrize(
        "field,value",
        [
            ("price_in", True),
            ("price_in", False),
            ("price_in", "1.5"),
            ("price_in", [1]),
            ("price_out", True),
            ("price_out", False),
            ("price_out", "5"),
            ("context_tokens", True),
            ("context_tokens", False),
            ("context_tokens", 3.0),
            ("context_tokens", 3.75),
            ("context_tokens", "100"),
        ],
    )
    def test_strict_numeric_types_rejected(self, seeded_app, field, value):
        """D-040: public route rejects booleans, numeric strings and fractional context."""
        model_id = _model_id(seeded_app)
        before = _snapshot(seeded_app, model_id)
        token = _make_token(seeded_app, ROLE_UPDATER)
        resp = seeded_app.test_client().patch(
            f"/api/v1/models/{model_id}",
            json={field: value},
            headers=_auth_header(token),
        )
        assert resp.status_code == 400, (field, value)
        assert _snapshot(seeded_app, model_id) == before, (field, value)

    def test_accepts_finite_prices_and_integer_context(self, seeded_app):
        model_id = _model_id(seeded_app)
        token = _make_token(seeded_app, ROLE_UPDATER)
        resp = seeded_app.test_client().patch(
            f"/api/v1/models/{model_id}",
            json={"price_in": 0, "price_out": 2.5, "context_tokens": 1000},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        with seeded_app.app_context():
            row = db.session.get(AiModel, model_id)
            # numeric zero stays 0.0 (never null) and is distinct from not-applicable
            assert row.price_in == 0.0
            assert row.price_in is not None
            assert row.price_out == 2.5
            assert row.context_tokens == 1000


class TestContextTransition:
    """D-041: public pairing is transition-only, not always-require-the-pair."""

    def test_unchanged_tokens_type_alone_succeeds(self, seeded_app):
        model_id = _model_id(seeded_app)
        before = _snapshot(seeded_app, model_id)
        token = _make_token(seeded_app, ROLE_UPDATER)
        resp = seeded_app.test_client().patch(
            f"/api/v1/models/{model_id}",
            json={"context_type": "tokens"},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.json["context_type"] == "tokens"
        assert resp.json["context_tokens"] == before["context_tokens"]

    def test_unchanged_image_type_alone_succeeds(self, seeded_app):
        model_id = _model_id(seeded_app, IMAGE_MODEL)
        before = _snapshot(seeded_app, model_id)
        token = _make_token(seeded_app, ROLE_UPDATER)
        resp = seeded_app.test_client().patch(
            f"/api/v1/models/{model_id}",
            json={"context_type": "image"},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.json["context_type"] == "image"
        assert resp.json["context_tokens"] is None
        assert resp.json["price_in"] == before["price_in"]

    def test_transition_tokens_to_image_without_pair_is_atomic(self, seeded_app):
        model_id = _model_id(seeded_app)
        before = _snapshot(seeded_app, model_id)
        token = _make_token(seeded_app, ROLE_UPDATER)
        resp = seeded_app.test_client().patch(
            f"/api/v1/models/{model_id}",
            json={"context_type": "image"},
            headers=_auth_header(token),
        )
        assert resp.status_code == 400
        assert "context_tokens" in resp.json["error"]
        assert _snapshot(seeded_app, model_id) == before

    def test_transition_image_to_tokens_without_pair_is_atomic(self, seeded_app):
        model_id = _model_id(seeded_app, IMAGE_MODEL)
        before = _snapshot(seeded_app, model_id)
        token = _make_token(seeded_app, ROLE_UPDATER)
        resp = seeded_app.test_client().patch(
            f"/api/v1/models/{model_id}",
            json={"context_type": "tokens"},
            headers=_auth_header(token),
        )
        assert resp.status_code == 400
        assert "context_tokens" in resp.json["error"]
        assert _snapshot(seeded_app, model_id) == before

    def test_paired_transition_tokens_to_image_succeeds(self, seeded_app):
        model_id = _model_id(seeded_app)
        token = _make_token(seeded_app, ROLE_UPDATER)
        resp = seeded_app.test_client().patch(
            f"/api/v1/models/{model_id}",
            json={
                "context_type": "image",
                "context_tokens": None,
                "price_in": None,
                "price_out": 0.035,
                "pricing_unit": "image",
            },
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        with seeded_app.app_context():
            row = db.session.get(AiModel, model_id)
            assert row.context_type == "image"
            assert row.context_tokens is None
            assert row.price_in is None

    def test_paired_transition_image_to_tokens_succeeds(self, seeded_app):
        model_id = _model_id(seeded_app, IMAGE_MODEL)
        token = _make_token(seeded_app, ROLE_UPDATER)
        resp = seeded_app.test_client().patch(
            f"/api/v1/models/{model_id}",
            json={
                "context_type": "tokens",
                "context_tokens": 8192,
                "price_in": 0.1,
                "pricing_unit": "million_tokens",
            },
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        with seeded_app.app_context():
            row = db.session.get(AiModel, model_id)
            assert row.context_type == "tokens"
            assert row.context_tokens == 8192
            assert row.price_in == 0.1

    def test_paired_transition_with_wrong_token_count_fails(self, seeded_app):
        model_id = _model_id(seeded_app, IMAGE_MODEL)
        before = _snapshot(seeded_app, model_id)
        token = _make_token(seeded_app, ROLE_UPDATER)
        # image -> tokens requires a positive integer token count
        resp = seeded_app.test_client().patch(
            f"/api/v1/models/{model_id}",
            json={"context_type": "tokens", "context_tokens": None},
            headers=_auth_header(token),
        )
        assert resp.status_code == 400
        assert _snapshot(seeded_app, model_id) == before


class TestPersistenceAndResponse:
    """Acceptance 6: a successful update persists and is reflected in subsequent reads."""

    def test_success_returns_full_object_matching_public_get(self, seeded_app):
        model_id = _model_id(seeded_app)
        token = _make_token(seeded_app, ROLE_UPDATER)
        resp = seeded_app.test_client().patch(
            f"/api/v1/models/{model_id}",
            json={"price_in": 0.1, "price_out": 0.4},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json
        assert set(body.keys()) == EXPECTED_MODEL_FIELDS
        assert body["price_in"] == 0.1
        assert body["price_out"] == 0.4
        assert body["name"] == TOKEN_MODEL

        listing = seeded_app.test_client().get("/api/v1/models").get_json()["models"]
        from_listing = next(m for m in listing if m["id"] == model_id)
        assert from_listing == body

    def test_update_persists_across_fresh_session_reread(self, seeded_app):
        """PATCH via one client, then read through a brand-new client to prove the
        write hit storage rather than an in-session object."""
        model_id = _model_id(seeded_app)
        token = _make_token(seeded_app, ROLE_UPDATER)
        resp = seeded_app.test_client().patch(
            f"/api/v1/models/{model_id}",
            json={"price_out": 3.33},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200

        fresh = seeded_app.test_client()
        model = next(
            m for m in fresh.get("/api/v1/models").get_json()["models"] if m["id"] == model_id
        )
        assert model["price_out"] == 3.33

    def test_modality_replacement_orders_and_reflects_in_response(self, seeded_app):
        model_id = _model_id(seeded_app)
        token = _make_token(seeded_app, ROLE_UPDATER)
        new_input = ["Audio", "Text", "Images", "Videos", "Files"]
        new_output = ["Images", "Text"]
        resp = seeded_app.test_client().patch(
            f"/api/v1/models/{model_id}",
            json={"input_content": new_input, "output_content": new_output},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        # The success body must reflect the fresh (post-write) association rows, not
        # a stale pre-write relationship.
        assert resp.json["input_content"] == new_input
        assert resp.json["output_content"] == new_output
        with seeded_app.app_context():
            row = db.session.get(AiModel, model_id)
            assert row.input_content == new_input
            assert row.output_content == new_output

    def test_update_bumps_updated_at(self, seeded_app):
        model_id = _model_id(seeded_app)
        before = _snapshot(seeded_app, model_id)
        token = _make_token(seeded_app, ROLE_UPDATER)
        resp = seeded_app.test_client().patch(
            f"/api/v1/models/{model_id}",
            json={"input_content": ["Text", "Images", "Videos"]},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        with seeded_app.app_context():
            row = db.session.get(AiModel, model_id)
            assert row.updated_at > before["updated_at"]

    def test_updater_can_patch_hidden_row_keeping_hidden(self, seeded_app):
        """D-023: hiding must never block a value sync; hidden state stays put."""
        model_id = _model_id(seeded_app)
        with seeded_app.app_context():
            row = db.session.get(AiModel, model_id)
            row.hidden_at = db.func.now()
            db.session.commit()
        with seeded_app.app_context():
            hidden_at = db.session.get(AiModel, model_id).hidden_at

        token = _make_token(seeded_app, ROLE_UPDATER)
        resp = seeded_app.test_client().patch(
            f"/api/v1/models/{model_id}",
            json={"price_in": 0.42},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.json["hidden"] is True
        with seeded_app.app_context():
            row = db.session.get(AiModel, model_id)
            assert row.price_in == 0.42
            assert row.hidden_at == hidden_at


class TestAtomicityAndRollback:
    """Mixed valid+invalid payloads must leave scalars, associations, name, hidden_at
    and updated_at untouched; a persist-time failure rolls the transaction back."""

    def test_mixed_valid_and_protected_payload_no_partial_write(self, seeded_app):
        model_id = _model_id(seeded_app)
        before = _snapshot(seeded_app, model_id)
        token = _make_token(seeded_app, ROLE_UPDATER)
        resp = seeded_app.test_client().patch(
            f"/api/v1/models/{model_id}",
            json={"price_in": 0.5, "price_out": 0.9, "name": "renamed/model"},
            headers=_auth_header(token),
        )
        assert resp.status_code == 400
        assert _snapshot(seeded_app, model_id) == before

    def test_mixed_valid_and_invalid_value_no_partial_write(self, seeded_app):
        model_id = _model_id(seeded_app)
        before = _snapshot(seeded_app, model_id)
        token = _make_token(seeded_app, ROLE_UPDATER)
        # price_out is valid but context_tokens is malformed → whole request rejected
        resp = seeded_app.test_client().patch(
            f"/api/v1/models/{model_id}",
            json={"price_out": 9.9, "context_tokens": "bad"},
            headers=_auth_header(token),
        )
        assert resp.status_code == 400
        assert _snapshot(seeded_app, model_id) == before

    def test_mixed_valid_and_invalid_modality_no_partial_write(self, seeded_app):
        model_id = _model_id(seeded_app)
        before = _snapshot(seeded_app, model_id)
        token = _make_token(seeded_app, ROLE_UPDATER)
        resp = seeded_app.test_client().patch(
            f"/api/v1/models/{model_id}",
            json={"price_in": 0.5, "input_content": ["Text", "Bogus"]},
            headers=_auth_header(token),
        )
        assert resp.status_code == 400
        assert _snapshot(seeded_app, model_id) == before

    def test_apply_model_update_rolls_back_on_integrity_error(self, seeded_app):
        """A persist-time IntegrityError must roll back so no partial write survives."""
        from app.services.model_service import apply_model_update

        model_id = _model_id(seeded_app)
        before = _snapshot(seeded_app, model_id)
        with seeded_app.app_context():
            model = db.session.get(AiModel, model_id)
            with patch(
                "app.services.model_service.db.session.commit",
                side_effect=IntegrityError("stmt", {}, Exception("boom")),
            ):
                error = apply_model_update(model, {"price_in": 0.5}, None)
            assert error == "Unable to update model"
            assert _snapshot(seeded_app, model_id) == before


class TestAdminBooleanCoercionRegression:
    """D-040: the admin surface must reject boolean numeric inputs on POST and PATCH,
    while keeping its legacy numeric-string / fractional-context coercion and its
    always-require-the-pair context rule (D-041 leaves admin pairing unchanged)."""

    def _admin_headers(self, app):
        return _auth_header(_make_token(app, ROLE_ADMINISTRATOR))

    def _pick_model(self, app):
        with app.app_context():
            return db.session.scalar(select(AiModel).order_by(AiModel.name))

    @pytest.mark.parametrize("field", ["price_in", "price_out", "context_tokens"])
    @pytest.mark.parametrize("value", [True, False])
    def test_admin_patch_rejects_boolean_and_leaves_state_unchanged(
        self, seeded_app, field, value
    ):
        model = self._pick_model(seeded_app)
        before = _snapshot(seeded_app, model.id)
        headers = self._admin_headers(seeded_app)
        resp = seeded_app.test_client().patch(
            f"/admin/models/{model.id}", json={field: value}, headers=headers
        )
        assert resp.status_code == 400, (field, value)
        assert "Prices must be numbers" in resp.json["error"]
        assert _snapshot(seeded_app, model.id) == before

    @pytest.mark.parametrize("field", ["price_in", "price_out", "context_tokens"])
    @pytest.mark.parametrize("value", [True, False])
    def test_admin_post_rejects_boolean_and_inserts_nothing(self, seeded_app, field, value):
        name = "bool-reject/no-insert"
        body = {
            "name": name,
            "price_in": 1.0,
            "price_out": 2.0,
            "context_tokens": 1000,
            "input_content": ["Text"],
            "output_content": ["Text"],
        }
        body[field] = value
        headers = self._admin_headers(seeded_app)
        resp = seeded_app.test_client().post("/admin/models", json=body, headers=headers)
        assert resp.status_code == 400, (field, value)
        # Neither the model row nor any association row may survive the rejection.
        with seeded_app.app_context():
            assert db.session.scalar(select(AiModel).where(AiModel.name == name)) is None

    def test_admin_numeric_string_coercion_preserved(self, seeded_app):
        model = self._pick_model(seeded_app)
        headers = self._admin_headers(seeded_app)
        resp = seeded_app.test_client().patch(
            f"/admin/models/{model.id}",
            json={"price_out": "1.25"},
            headers=headers,
        )
        assert resp.status_code == 200
        with seeded_app.app_context():
            assert db.session.get(AiModel, model.id).price_out == 1.25

    def test_admin_fractional_context_truncation_preserved(self, seeded_app):
        model = self._pick_model(seeded_app)
        headers = self._admin_headers(seeded_app)
        resp = seeded_app.test_client().patch(
            f"/admin/models/{model.id}",
            json={"context_tokens": 3.75},
            headers=headers,
        )
        assert resp.status_code == 200
        with seeded_app.app_context():
            assert db.session.get(AiModel, model.id).context_tokens == 3

    def test_admin_unchanged_context_type_still_requires_pair(self, seeded_app):
        """D-041: the internal admin route keeps its always-require-the-pair rule, so an
        unchanged context_type alone is still rejected there (unlike the public route)."""
        model = self._pick_model(seeded_app)
        headers = self._admin_headers(seeded_app)
        resp = seeded_app.test_client().patch(
            f"/admin/models/{model.id}",
            json={"context_type": "tokens"},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "context_tokens" in resp.json["error"]


class TestReadApiRegression:
    """The public GET surface stays unauthenticated and untouched by the write route."""

    def test_public_get_still_unauthenticated(self, seeded_app):
        resp = seeded_app.test_client().get("/api/v1/models")
        assert resp.status_code == 200
        assert resp.json["models"]

    def test_public_get_still_returns_full_object(self, seeded_app):
        model_id = _model_id(seeded_app)
        listing = seeded_app.test_client().get("/api/v1/models").get_json()["models"]
        obj = next(m for m in listing if m["id"] == model_id)
        assert set(obj.keys()) == EXPECTED_MODEL_FIELDS
