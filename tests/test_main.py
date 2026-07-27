"""Tests for main blueprint routes."""


def test_health_endpoint(client):
    """The health endpoint should return a shallow liveness response."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.content_type == "application/json"
    assert response.json == {"status": "ok"}


def test_health_endpoint_rejects_post(client):
    """Mutating methods should not be allowed on the health endpoint."""
    response = client.post("/health")
    assert response.status_code == 405


def test_index_page(client):
    """The index page should render successfully."""
    response = client.get("/")
    assert response.status_code == 200
    assert b"AI Price Dashboard" in response.data
