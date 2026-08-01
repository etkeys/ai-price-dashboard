"""Tests for admin model-creation feature (administrator-only add model)."""

import re

import pytest
from app.models.auth import ROLE_ADMINISTRATOR, ROLE_UPDATER
from app.models import AiModel
from app.services.auth_service import create_api_key


class TestCreateModel:
    """Model creation endpoint tests."""

    def test_model_form_does_not_require_first_modality_checkbox(self, client):
        """The modality requirement is enforced by JavaScript at group level."""
        resp = client.get("/admin/models/manage")

        assert resp.status_code == 200
        assert not re.search(
            rb'<input\b(?=[^>]*type="checkbox")[^>]*\brequired\b[^>]*>',
            resp.data,
        )

    def test_unauthenticated_returns_401(self, client):
        """POST /admin/models without auth returns 401."""
        resp = client.post(
            "/admin/models",
            json={"name": "test/model"},
        )
        assert resp.status_code == 401

    def test_updater_returns_403(self, client, app):
        """Non-administrator gets 403."""
        # D-006 and D-007: structural model creation is administrator-only.
        with app.app_context():
            _, token = create_api_key(name="updater", role=ROLE_UPDATER)
        resp = client.post(
            "/admin/models",
            json={"name": "test/model"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    def test_missing_name_returns_400(self, client, app):
        """Missing name field returns 400."""
        with app.app_context():
            _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
        resp = client.post(
            "/admin/models",
            json={
                "price_in": 1.0,
                "price_out": 5.0,
                "context_tokens": 1000000,
                "input_content": ["Text"],
                "output_content": ["Text"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert "Missing 'name'" in resp.json["error"]

    def test_incomplete_optional_attributes_returns_400(self, client, app):
        """Supplying some but not all optional fields returns 400."""
        with app.app_context():
            _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
        resp = client.post(
            "/admin/models",
            json={
                "name": "test/model",
                "price_in": 1.0,
                "price_out": 5.0,
                # Missing context_tokens and modalities
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert "All model attributes" in resp.json["error"]

    def test_all_optional_missing_returns_400(self, client, app):
        """Supplying no optional fields returns 400."""
        # D-005: all model attributes are required by the schema.
        with app.app_context():
            _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
        resp = client.post(
            "/admin/models",
            json={"name": "test/model"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert "All model attributes" in resp.json["error"]

    def test_invalid_price_values_return_400(self, client, app):
        """Non-numeric prices return 400."""
        with app.app_context():
            _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
        resp = client.post(
            "/admin/models",
            json={
                "name": "test/model",
                "price_in": "invalid",
                "price_out": 5.0,
                "context_tokens": 1000000,
                "input_content": ["Text"],
                "output_content": ["Text"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert "Prices must be numbers" in resp.json["error"]

    def test_negative_prices_return_400(self, client, app):
        """Negative prices return 400."""
        with app.app_context():
            _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
        resp = client.post(
            "/admin/models",
            json={
                "name": "test/model",
                "price_in": -1.0,
                "price_out": 5.0,
                "context_tokens": 1000000,
                "input_content": ["Text"],
                "output_content": ["Text"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert ">= 0" in resp.json["error"]

    def test_zero_or_negative_context_tokens_return_400(self, client, app):
        """Non-positive context_tokens return 400."""
        with app.app_context():
            _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
        resp = client.post(
            "/admin/models",
            json={
                "name": "test/model",
                "price_in": 1.0,
                "price_out": 5.0,
                "context_tokens": 0,
                "input_content": ["Text"],
                "output_content": ["Text"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert "greater than zero" in resp.json["error"]

    def test_invalid_modality_returns_400(self, client, app):
        """Unknown modality name returns 400."""
        with app.app_context():
            _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
        resp = client.post(
            "/admin/models",
            json={
                "name": "test/model",
                "price_in": 1.0,
                "price_out": 5.0,
                "context_tokens": 1000000,
                "input_content": ["Text", "InvalidModality"],
                "output_content": ["Text"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert "invalid modality" in resp.json["error"]

    def test_duplicate_modality_returns_400(self, client, app):
        """Duplicate modality in the same field returns 400."""
        with app.app_context():
            _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
        resp = client.post(
            "/admin/models",
            json={
                "name": "test/model",
                "price_in": 1.0,
                "price_out": 5.0,
                "context_tokens": 1000000,
                "input_content": ["Text", "Text"],
                "output_content": ["Text"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert "duplicate" in resp.json["error"]

    def test_empty_modality_list_returns_400(self, client, app):
        """Empty modality list returns 400."""
        with app.app_context():
            _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
        resp = client.post(
            "/admin/models",
            json={
                "name": "test/model",
                "price_in": 1.0,
                "price_out": 5.0,
                "context_tokens": 1000000,
                "input_content": [],
                "output_content": ["Text"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert "non-empty list" in resp.json["error"]

    def test_duplicate_model_name_returns_409(self, client, app, seeded_client):
        """Creating a model with an existing name returns 409."""
        with app.app_context():
            _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
            # Get an existing model name from the seeded DB.
            existing = app.test_client()
            resp = existing.get("/")
        # Now try to create a duplicate via the seeded client.
        resp = seeded_client.post(
            "/admin/models",
            json={
                "name": "anthropic/claude-haiku-4.5",  # Already exists from seed.
                "price_in": 2.0,
                "price_out": 10.0,
                "context_tokens": 200000,
                "input_content": ["Text"],
                "output_content": ["Text"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 409
        assert "already exists" in resp.json["error"]

    def test_successful_create_returns_201(self, seeded_client, app):
        """Successful model creation returns 201 with model data."""
        with app.app_context():
            _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
        resp = seeded_client.post(
            "/admin/models",
            json={
                "name": "acme/llama-3.0",
                "price_in": 0.5,
                "price_out": 1.5,
                "context_tokens": 8192,
                "input_content": ["Text", "Images"],
                "output_content": ["Text"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        data = resp.json
        assert data["name"] == "acme/llama-3.0"
        assert "id" in data

    def test_created_model_persists_in_db(self, seeded_client, app):
        """Created model is stored in the database."""
        with app.app_context():
            _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)

        resp = seeded_client.post(
            "/admin/models",
            json={
                "name": "acme/brand-new",
                "price_in": 2.0,
                "price_out": 4.0,
                "context_tokens": 4096,
                "input_content": ["Text"],
                "output_content": ["Text"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        model_id = resp.json["id"]

        with app.app_context():
            from app.extensions import db
            from sqlalchemy import select

            model = db.session.get(AiModel, model_id)
            assert model is not None
            assert model.name == "acme/brand-new"
            assert model.price_in == 2.0
            assert model.price_out == 4.0
            assert model.context_tokens == 4096
            assert model.input_content == ["Text"]
            assert model.output_content == ["Text"]

    def test_modalities_ordered_correctly(self, seeded_client, app):
        """Modality ordering is preserved in the database."""
        with app.app_context():
            _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)

        resp = seeded_client.post(
            "/admin/models",
            json={
                "name": "order/test",
                "price_in": 1.0,
                "price_out": 1.0,
                "context_tokens": 1000,
                "input_content": ["Audio", "Text", "Images"],  # Different order
                "output_content": ["Images", "Text"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        model_id = resp.json["id"]

        with app.app_context():
            from app.extensions import db

            model = db.session.get(AiModel, model_id)
            assert model.input_content == ["Audio", "Text", "Images"]
            assert model.output_content == ["Images", "Text"]
