"""Tests for the public modalities discovery endpoint (D-025..D-029)."""

from app.extensions import db
from app.models import Modality
from app.models.auth import ROLE_ADMINISTRATOR
from app.services.auth_service import create_api_key

EXPECTED_PAYLOAD = {
    "modalities": [
        {"name": "Audio"},
        {"name": "Files"},
        {"name": "Images"},
        {"name": "Text"},
        {"name": "Videos"},
    ]
}


def test_returns_all_modalities(seeded_client):
    """The endpoint returns the full vocabulary, exactly, in name order."""
    resp = seeded_client.get("/api/v1/modalities")
    assert resp.status_code == 200
    assert resp.get_json() == EXPECTED_PAYLOAD


def test_response_is_json_and_ordered_alphabetically(seeded_client):
    """Responses are JSON with names sorted alphabetically."""
    resp = seeded_client.get("/api/v1/modalities")
    assert resp.status_code == 200
    assert resp.content_type == "application/json"
    names = [m["name"] for m in resp.get_json()["modalities"]]
    assert names == sorted(names)


def test_empty_vocabulary_returns_empty_list(client):
    """A migrated-but-unseeded database yields 200 with an empty array (D-029)."""
    resp = client.get("/api/v1/modalities")
    assert resp.status_code == 200
    assert resp.get_json() == {"modalities": []}


def test_requires_no_authentication(client):
    """The endpoint is public; no Authorization header is required."""
    resp = client.get("/api/v1/modalities")
    assert resp.status_code == 200


def test_invalid_token_still_returns_200(client):
    """A garbage bearer token must not 401; body matches the bare request."""
    bare = client.get("/api/v1/modalities")
    resp = client.get(
        "/api/v1/modalities", headers={"Authorization": "Bearer ***"}
    )
    assert resp.status_code == 200
    assert resp.get_json() == bare.get_json()


def test_authenticated_response_is_identical(seeded_client, app):
    """A valid administrator token gets the same body as an anonymous client."""
    with app.app_context():
        _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
    authed = seeded_client.get(
        "/api/v1/modalities", headers={"Authorization": f"Bearer {token}"}
    )
    bare = seeded_client.get("/api/v1/modalities")
    assert authed.status_code == 200
    assert authed.get_json() == bare.get_json()


def test_rejects_post(client):
    """Mutating methods are rejected with 405 (Flask automatic)."""
    resp = client.post("/api/v1/modalities")
    assert resp.status_code == 405


def test_sets_cache_and_cors_headers(seeded_client):
    """The route is cacheable for 5 minutes and CORS-open on this route only."""
    resp = seeded_client.get("/api/v1/modalities")
    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "public, max-age=300"
    assert resp.headers["Access-Control-Allow-Origin"] == "*"


def test_admin_routes_remain_no_store(app, client):
    """No app-wide CORS hook: /admin/* JSON stays no-store and CORS-free."""
    with app.app_context():
        _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
    resp = client.get("/admin/keys", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "no-store"
    assert "Access-Control-Allow-Origin" not in resp.headers


def test_excludes_rows_outside_allow_list(app, seeded_client):
    """An orphan row not in the allow-list is not advertised (D-027)."""
    with app.app_context():
        db.session.add(Modality(name="Bogus"))
        db.session.commit()
    resp = seeded_client.get("/api/v1/modalities")
    assert resp.status_code == 200
    assert resp.get_json() == EXPECTED_PAYLOAD