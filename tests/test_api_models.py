"""Tests for the public models listing endpoint (D-030..D-036).

The route returns ``{"models": [...]}`` — an envelope, not a bare array (D-031)
— where each model object carries exactly the eleven fields of the spec §4.3.
Filtering is governed by ``?include_hidden=true|false`` (strict, D-030). All
helpers here use direct ORM manipulation to hide models because the hide
write path requires an administrator token.
"""

import datetime

import pytest
from sqlalchemy import event, select

from app.data.sample_models import SAMPLE_MODELS
from app.extensions import db
from app.models import AiModel
from app.models.auth import ROLE_ADMINISTRATOR
from app.services.auth_service import create_api_key

EXPECTED_MODEL_FIELDS = {
    "id",
    "name",
    "price_in",
    "price_out",
    "context_tokens",
    "input_content",
    "output_content",
    "hidden",
    "hidden_at",
    "created_at",
    "updated_at",
}


def _hide_model(app, name: str) -> None:
    """Persist hidden_at on the row(s) named ``name`` (direct ORM, no auth)."""
    with app.app_context():
        rows = db.session.scalars(select(AiModel).where(AiModel.name == name)).all()
        for row in rows:
            row.hidden_at = db.func.now()
        db.session.commit()


def _pick_visible_names(app, count: int) -> list[str]:
    """Return ``count`` distinct model names that are present and visible."""
    with app.app_context():
        rows = db.session.scalars(
            select(AiModel).where(~AiModel.is_hidden).order_by(AiModel.name)
        ).all()
        assert len(rows) >= count
        return [r.name for r in rows[:count]]


def _model_names(payload: dict) -> list[str]:
    return [m["name"] for m in payload["models"]]


def test_returns_all_visible_models(seeded_client):
    """No params returns exactly the seeded rows, none hidden."""
    resp = seeded_client.get("/api/v1/models")
    assert resp.status_code == 200
    models = resp.get_json()["models"]
    assert len(models) == len(SAMPLE_MODELS)
    assert all(m["hidden"] is False for m in models)


def test_excludes_hidden_by_default(seeded_app):
    """Hiding one model keeps it out of the default listing (D-021)."""
    hidden_name = _pick_visible_names(seeded_app, 1)[0]
    _hide_model(seeded_app, hidden_name)

    resp = seeded_app.test_client().get("/api/v1/models")
    assert resp.status_code == 200
    names = _model_names(resp.get_json())
    assert len(names) == len(SAMPLE_MODELS) - 1
    assert hidden_name not in names


def test_include_hidden_true_returns_all(seeded_app):
    """Including hidden returns every model, with hidden state flagged."""
    hidden_name = _pick_visible_names(seeded_app, 1)[0]
    _hide_model(seeded_app, hidden_name)

    resp = seeded_app.test_client().get("/api/v1/models?include_hidden=true")
    assert resp.status_code == 200
    models = resp.get_json()["models"]
    assert len(models) == len(SAMPLE_MODELS)
    hidden_rows = [m for m in models if m["name"] == hidden_name]
    assert len(hidden_rows) == 1
    assert hidden_rows[0]["hidden"] is True
    assert hidden_rows[0]["hidden_at"] is not None


def test_include_hidden_false_matches_default(seeded_app):
    """?include_hidden=false is byte-identical to the no-parameter body."""
    client = seeded_app.test_client()
    default = client.get("/api/v1/models")
    explicit = client.get("/api/v1/models?include_hidden=false")
    assert default.status_code == 200
    assert explicit.status_code == 200
    assert explicit.data == default.data


def test_model_object_shape(seeded_client):
    """Each object has exactly the eleven fields of §4.3; tokens stay raw."""
    payload = seeded_client.get("/api/v1/models").get_json()
    obj = next(m for m in payload["models"] if m["name"] == "anthropic/claude-haiku-4.5")
    assert set(obj.keys()) == EXPECTED_MODEL_FIELDS
    assert isinstance(obj["context_tokens"], int)
    assert obj["context_tokens"] == 200_000


def test_modality_lists_preserve_persisted_order(seeded_client):
    """input_content comes back in position order, not alphabetical (D-032)."""
    payload = seeded_client.get("/api/v1/models").get_json()
    obj = next(m for m in payload["models"] if m["name"] == "anthropic/claude-haiku-4.5")
    assert obj["input_content"] == ["Text", "Images", "Files"]


def test_ordering_matches_dashboard(seeded_app):
    """Names are returned in sort_name, name order (D-016/D-017)."""
    with seeded_app.app_context():
        expected = db.session.scalars(
            select(AiModel).order_by(AiModel.sort_name, AiModel.name)
        ).all()
        expected_names = [m.name for m in expected]

    payload = seeded_app.test_client().get("/api/v1/models").get_json()
    assert _model_names(payload) == expected_names


def test_timestamps_are_utc_iso8601(seeded_app):
    """Timestamps end with Z and parse as UTC; hidden_at null when visible (D-033)."""
    hidden_name = _pick_visible_names(seeded_app, 1)[0]
    _hide_model(seeded_app, hidden_name)

    models = seeded_app.test_client().get("/api/v1/models?include_hidden=true").get_json()["models"]
    for m in models:
        for field in ("created_at", "updated_at"):
            assert m[field].endswith("Z")
            parsed = datetime.datetime.fromisoformat(m[field])
            # 'Z' parses as an explicit UTC offset in Python 3.11+ (RFC 3339).
            assert parsed.tzinfo == datetime.timezone.utc
        if m["hidden"]:
            assert isinstance(m["hidden_at"], str)
            assert m["hidden_at"].endswith("Z")
        else:
            assert m["hidden_at"] is None


@pytest.mark.parametrize(
    "value",
    ["1", "0", "yes", "no", "on", "", "TRUE1", "maybe"],
)
def test_invalid_include_hidden_returns_400(seeded_client, value):
    """Anything other than true/false is a 400, no-store, no error caching (D-030)."""
    resp = seeded_client.get(f"/api/v1/models?include_hidden={value}")
    assert resp.status_code == 400
    assert "error" in resp.get_json()
    assert resp.headers["Cache-Control"] == "no-store"
    assert "Access-Control-Allow-Origin" not in resp.headers


@pytest.mark.parametrize(
    "value",
    ["TRUE", "True", "FALSE", "False"],
)
def test_case_insensitive_boolean_accepted(seeded_client, value):
    """Mixed/mixed-case true and false are all accepted with correct filtering."""
    resp = seeded_client.get(f"/api/v1/models?include_hidden={value}")
    assert resp.status_code == 200
    models = resp.get_json()["models"]
    assert len(models) == len(SAMPLE_MODELS)  # none hidden in seed
    assert all(m["hidden"] is False for m in models)


def test_sets_cache_and_cors_headers_and_admin_unaffected(app, client, seeded_client):
    """Success carries the cache+CORS headers; /admin/* stays no-store and CORS-free."""
    resp = seeded_client.get("/api/v1/models")
    assert resp.headers["Cache-Control"] == "public, max-age=60"
    assert resp.headers["Access-Control-Allow-Origin"] == "*"

    with app.app_context():
        _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
    admin_resp = client.get(
        "/admin/keys", headers={"Authorization": f"Bearer {token}"}
    )
    assert admin_resp.status_code == 200
    assert admin_resp.headers["Cache-Control"] == "no-store"
    assert "Access-Control-Allow-Origin" not in admin_resp.headers


def test_empty_database_returns_empty_list(client):
    """A migrated-but-unseeded database yields 200 with an empty array (D-029)."""
    resp = client.get("/api/v1/models")
    assert resp.status_code == 200
    assert resp.get_json() == {"models": []}
    resp = client.get("/api/v1/models?include_hidden=true")
    assert resp.status_code == 200
    assert resp.get_json() == {"models": []}


def test_all_hidden_returns_empty_list(seeded_app):
    """Hiding every model yields an empty default listing and all rows when included."""
    with seeded_app.app_context():
        for row in db.session.scalars(select(AiModel)).all():
            row.hidden_at = db.func.now()
        db.session.commit()

    client = seeded_app.test_client()
    default = client.get("/api/v1/models")
    assert default.status_code == 200
    assert _model_names(default.get_json()) == []

    included = client.get("/api/v1/models?include_hidden=true")
    assert included.status_code == 200
    assert len(included.get_json()["models"]) == len(SAMPLE_MODELS)


def test_requires_no_authentication(seeded_client):
    """The endpoint is public; no Authorization header is required."""
    resp = seeded_client.get("/api/v1/models")
    assert resp.status_code == 200


def test_invalid_token_still_returns_200(seeded_client):
    """A garbage bearer token must not 401; body matches the bare request."""
    bare = seeded_client.get("/api/v1/models")
    resp = seeded_client.get("/api/v1/models", headers={"Authorization": "Bearer ***"})
    assert resp.status_code == 200
    assert resp.get_json() == bare.get_json()


def test_authenticated_response_is_identical(seeded_client, app):
    """A valid administrator token gets the same body as an anonymous client."""
    with app.app_context():
        _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
    authed = seeded_client.get(
        "/api/v1/models", headers={"Authorization": f"Bearer {token}"}
    )
    bare = seeded_client.get("/api/v1/models")
    assert authed.status_code == 200
    assert authed.get_json() == bare.get_json()


def test_rejects_post(seeded_client):
    """Mutating methods are rejected with 405 (Flask automatic)."""
    resp = seeded_client.post("/api/v1/models")
    assert resp.status_code == 405


def test_duplicate_parameter_uses_first_value(seeded_app):
    """?include_hidden=true&include_hidden=false behaves as true (first wins)."""
    hidden_name = _pick_visible_names(seeded_app, 1)[0]
    _hide_model(seeded_app, hidden_name)

    resp = seeded_app.test_client().get(
        "/api/v1/models?include_hidden=true&include_hidden=false"
    )
    assert resp.status_code == 200
    names = _model_names(resp.get_json())
    assert len(names) == len(SAMPLE_MODELS)
    assert hidden_name in names


def test_uses_bounded_query_count(seeded_app):
    """The listing uses exactly 3 queries for both filter values (no N+1)."""
    client = seeded_app.test_client()

    for query_string in ("", "?include_hidden=true"):
        query_count = 0

        def _count_queries(_conn, _cursor, _statement, _parameters, _context, _executemany):
            nonlocal query_count
            query_count += 1

        with seeded_app.app_context():
            event.listen(db.engine, "before_cursor_execute", _count_queries)
            try:
                client.get(f"/api/v1/models{query_string}")
            finally:
                event.remove(db.engine, "before_cursor_execute", _count_queries)

        # One select for models + two selectin loads for input/output modalities.
        assert query_count == 3
