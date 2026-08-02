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


class TestUpdateModel:
    """PATCH /admin/models/<id> endpoint tests.

    Binding constraints:
      - Gate: `@require_role("updater")` admits both updater and administrator by
        rank (D-012 CONFIRMED). Updaters may edit every field except `name`.
      - `name`, `id`, `created_at`, `updated_at` in the body → 400.
      - Empty body / non-dict body → 400.
      - Unknown id → 404.
      - Unknown field → 400.
      - Modality edits are full replacement; `position` is reassigned from
        submission order. Display on `/` is alphabetical (D-008).
      - `Cache-Control: no-store` on the response.
      - `updated_at` is explicitly bumped even when only association rows change.
    """

    def test_edit_form_does_not_require_first_modality_checkbox(self, client, seeded_client):
        """The edit dialog's modality checkboxes carry no element-level required.

        Regression test for the same class of bug as t_e8df9b08 / t_4f256428
        on the create form. Scans the entire rendered page so it covers both
        the create and edit fieldset groups.
        """
        resp = client.get("/admin/models/manage")
        assert resp.status_code == 200
        assert not re.search(
            rb'<input\b(?=[^>]*type="checkbox")[^>]*\brequired\b[^>]*>',
            resp.data,
        )

    def test_unauthenticated_returns_401(self, client, seeded_app):
        """PATCH without auth returns 401."""
        with seeded_app.app_context():
            from app.extensions import db
            model = db.session.scalar(db.select(AiModel))
            assert model is not None
            resp = client.patch(f"/admin/models/{model.id}", json={"price_in": 9.0})
        assert resp.status_code == 401

    def test_updater_can_update_prices(self, seeded_app):
        """An updater may update price/context fields (D-012).

        The exact inverse of TestCreateModel.test_updater_returns_403: this
        endpoint admits updaters by rank; that one rejects them because
        create is administrator-only.
        """
        with seeded_app.app_context():
            _, token = create_api_key(name="updater", role=ROLE_UPDATER)
            client = seeded_app.test_client()
            from app.extensions import db
            from sqlalchemy import select
            model = db.session.scalar(select(AiModel).order_by(AiModel.name))
            assert model is not None
            original_price_in = model.price_in
            resp = client.patch(
                f"/admin/models/{model.id}",
                json={"price_in": 9.99},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        assert resp.json["id"] == model.id
        assert resp.json["name"] == model.name
        with seeded_app.app_context():
            from app.extensions import db
            from sqlalchemy import select
            refreshed = db.session.scalar(select(AiModel).where(AiModel.id == model.id))
            assert refreshed.price_in == 9.99
            assert refreshed.price_in != original_price_in

    def test_updater_can_update_modalities(self, seeded_app):
        """D-012: an updater may replace a model's modality lists.

        This is the test that pins D-012; without it, the ruled behaviour is
        indistinguishable from the rejected option (b).
        """
        with seeded_app.app_context():
            from app.extensions import db
            from sqlalchemy import select
            model = db.session.scalar(select(AiModel).order_by(AiModel.name))
            assert model is not None
            original_id = model.id
            original_input = list(model.input_content)
            _, token = create_api_key(name="updater", role=ROLE_UPDATER)
            client = seeded_app.test_client()
            new_input = ["Text", "Images", "Files", "Videos", "Audio"]
            new_output = ["Text", "Audio"]
            resp = client.patch(
                f"/admin/models/{original_id}",
                json={"input_content": new_input, "output_content": new_output},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        # Confirm the rows were actually rewritten (not just the response).
        with seeded_app.app_context():
            from app.extensions import db
            from sqlalchemy import select
            refreshed = db.session.scalar(select(AiModel).where(AiModel.id == original_id))
            assert refreshed.input_content == new_input
            assert refreshed.output_content == new_output
            assert refreshed.input_content != original_input

    def test_administrator_can_update(self, seeded_app):
        """An administrator may also PATCH models."""
        with seeded_app.app_context():
            from app.extensions import db
            from sqlalchemy import select
            model = db.session.scalar(select(AiModel).order_by(AiModel.name))
            assert model is not None
            target_id = model.id
            _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
            client = seeded_app.test_client()
            resp = client.patch(
                f"/admin/models/{target_id}",
                json={"context_tokens": 123456},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        with seeded_app.app_context():
            from app.extensions import db
            from sqlalchemy import select
            refreshed = db.session.scalar(select(AiModel).where(AiModel.id == target_id))
            assert refreshed.context_tokens == 123456

    def test_name_in_body_returns_400(self, seeded_app):
        """Renames must fail loudly with 400; the persisted name is unchanged."""
        with seeded_app.app_context():
            from app.extensions import db
            from sqlalchemy import select
            model = db.session.scalar(select(AiModel).order_by(AiModel.name))
            assert model is not None
            original_name = model.name
            target_id = model.id
            _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
            client = seeded_app.test_client()
            resp = client.patch(
                f"/admin/models/{target_id}",
                json={"name": "renamed/model"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 400
        assert "Cannot update field" in resp.json["error"]
        with seeded_app.app_context():
            from app.extensions import db
            from sqlalchemy import select
            refreshed = db.session.scalar(select(AiModel).where(AiModel.id == target_id))
            assert refreshed.name == original_name

    def test_id_or_timestamp_in_body_returns_400(self, seeded_app):
        """Identity and timestamp fields in the body are rejected."""
        with seeded_app.app_context():
            from app.extensions import db
            from sqlalchemy import select
            model = db.session.scalar(select(AiModel).order_by(AiModel.name))
            assert model is not None
            target_id = model.id
            _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
            client = seeded_app.test_client()
            for body in (
                {"id": 9999},
                {"created_at": "2026-01-01T00:00:00"},
                {"updated_at": "2026-01-01T00:00:00"},
            ):
                resp = client.patch(
                    f"/admin/models/{target_id}",
                    json=body,
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert resp.status_code == 400, body
                assert "Cannot update field" in resp.json["error"]

    def test_unknown_id_returns_404(self, seeded_app):
        """PATCH against a non-existent id returns 404."""
        with seeded_app.app_context():
            _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
            client = seeded_app.test_client()
            resp = client.patch(
                "/admin/models/9999999",
                json={"price_in": 1.0},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 404
        assert "not found" in resp.json["error"].lower()

    def test_empty_body_returns_400(self, seeded_app):
        """An empty JSON object returns 400."""
        with seeded_app.app_context():
            from app.extensions import db
            from sqlalchemy import select
            model = db.session.scalar(select(AiModel).order_by(AiModel.name))
            assert model is not None
            _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
            client = seeded_app.test_client()
            resp = client.patch(
                f"/admin/models/{model.id}",
                json={},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 400

    def test_non_object_body_returns_400(self, seeded_app):
        """A non-object body (e.g. list, scalar) returns 400."""
        with seeded_app.app_context():
            from app.extensions import db
            from sqlalchemy import select
            model = db.session.scalar(select(AiModel).order_by(AiModel.name))
            assert model is not None
            _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
            client = seeded_app.test_client()
            for body in ([], "scalar", 42):
                resp = client.patch(
                    f"/admin/models/{model.id}",
                    json=body,
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert resp.status_code == 400, body

    def test_unknown_field_returns_400(self, seeded_app):
        """An unknown field in the body returns 400."""
        with seeded_app.app_context():
            from app.extensions import db
            from sqlalchemy import select
            model = db.session.scalar(select(AiModel).order_by(AiModel.name))
            assert model is not None
            _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
            client = seeded_app.test_client()
            resp = client.patch(
                f"/admin/models/{model.id}",
                json={"not_a_field": 1},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 400

    def test_negative_price_returns_400(self, seeded_app):
        """A negative price is rejected."""
        with seeded_app.app_context():
            from app.extensions import db
            from sqlalchemy import select
            model = db.session.scalar(select(AiModel).order_by(AiModel.name))
            assert model is not None
            _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
            client = seeded_app.test_client()
            resp = client.patch(
                f"/admin/models/{model.id}",
                json={"price_in": -1.0},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 400

    def test_zero_context_tokens_returns_400(self, seeded_app):
        """Zero / negative context_tokens is rejected."""
        with seeded_app.app_context():
            from app.extensions import db
            from sqlalchemy import select
            model = db.session.scalar(select(AiModel).order_by(AiModel.name))
            assert model is not None
            _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
            client = seeded_app.test_client()
            resp = client.patch(
                f"/admin/models/{model.id}",
                json={"context_tokens": 0},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 400

    def test_unknown_modality_returns_400(self, seeded_app):
        """An invalid modality name is rejected."""
        with seeded_app.app_context():
            from app.extensions import db
            from sqlalchemy import select
            model = db.session.scalar(select(AiModel).order_by(AiModel.name))
            assert model is not None
            _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
            client = seeded_app.test_client()
            resp = client.patch(
                f"/admin/models/{model.id}",
                json={"input_content": ["Text", "NotAModality"]},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 400
        assert "invalid modality" in resp.json["error"]

    def test_duplicate_modality_returns_400(self, seeded_app):
        """Duplicate modality entries within a list are rejected."""
        with seeded_app.app_context():
            from app.extensions import db
            from sqlalchemy import select
            model = db.session.scalar(select(AiModel).order_by(AiModel.name))
            assert model is not None
            _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
            client = seeded_app.test_client()
            resp = client.patch(
                f"/admin/models/{model.id}",
                json={"input_content": ["Text", "Text"]},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 400
        assert "duplicates" in resp.json["error"]

    def test_empty_modality_list_returns_400(self, seeded_app):
        """An empty modality list is rejected."""
        with seeded_app.app_context():
            from app.extensions import db
            from sqlalchemy import select
            model = db.session.scalar(select(AiModel).order_by(AiModel.name))
            assert model is not None
            _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
            client = seeded_app.test_client()
            resp = client.patch(
                f"/admin/models/{model.id}",
                json={"input_content": []},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 400

    def test_partial_update_leaves_other_fields_untouched(self, seeded_app):
        """Sending only one field leaves the others untouched."""
        with seeded_app.app_context():
            from app.extensions import db
            from sqlalchemy import select
            model = db.session.scalar(select(AiModel).order_by(AiModel.name))
            assert model is not None
            target_id = model.id
            original = {
                "price_in": model.price_in,
                "price_out": model.price_out,
                "context_tokens": model.context_tokens,
                "input_content": list(model.input_content),
                "output_content": list(model.output_content),
            }
            _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
            client = seeded_app.test_client()
            resp = client.patch(
                f"/admin/models/{target_id}",
                json={"price_in": 0.01},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        with seeded_app.app_context():
            from app.extensions import db
            from sqlalchemy import select
            refreshed = db.session.scalar(select(AiModel).where(AiModel.id == target_id))
            assert refreshed.price_in == 0.01
            assert refreshed.price_out == original["price_out"]
            assert refreshed.context_tokens == original["context_tokens"]
            assert refreshed.input_content == original["input_content"]
            assert refreshed.output_content == original["output_content"]

    def test_modality_update_replaces_association_rows_with_position(self, seeded_app):
        """Modality update is full replacement; position is reassigned by submission order.

        Note: this assertion pins `position`-governed persistence (mirrors
        test_modalities_ordered_correctly). The display on `/` is alphabetical
        per D-008, but persistence preserves submission order.
        """
        with seeded_app.app_context():
            from app.extensions import db
            from sqlalchemy import select
            model = db.session.scalar(select(AiModel).order_by(AiModel.name))
            assert model is not None
            target_id = model.id
            _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
            client = seeded_app.test_client()
            resp = client.patch(
                f"/admin/models/{target_id}",
                json={
                    "input_content": ["Audio", "Text", "Images"],  # not alphabetical
                    "output_content": ["Images", "Text"],
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        with seeded_app.app_context():
            from app.extensions import db
            from sqlalchemy import select
            from app.models import AiModelInputModality, AiModelOutputModality
            refreshed = db.session.scalar(select(AiModel).where(AiModel.id == target_id))
            assert refreshed.input_content == ["Audio", "Text", "Images"]
            assert refreshed.output_content == ["Images", "Text"]
            # And the rows' `position` column matches the submitted order.
            input_rows = db.session.scalars(
                select(AiModelInputModality)
                .where(AiModelInputModality.ai_model_id == target_id)
                .order_by(AiModelInputModality.position.asc())
            ).all()
            assert [r.position for r in input_rows] == [0, 1, 2]

    def test_modality_only_edit_bumps_updated_at(self, seeded_app):
        """Modality-only edits must still bump updated_at."""
        with seeded_app.app_context():
            from app.extensions import db
            from sqlalchemy import select
            model = db.session.scalar(select(AiModel).order_by(AiModel.name))
            assert model is not None
            target_id = model.id
            original_updated_at = model.updated_at
            _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
            client = seeded_app.test_client()
            resp = client.patch(
                f"/admin/models/{target_id}",
                json={"input_content": ["Text", "Images", "Videos"]},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        with seeded_app.app_context():
            from app.extensions import db
            from sqlalchemy import select
            refreshed = db.session.scalar(select(AiModel).where(AiModel.id == target_id))
            assert refreshed.updated_at > original_updated_at

    def test_response_has_cache_control_no_store(self, seeded_app):
        """The PATCH response carries `Cache-Control: no-store`."""
        with seeded_app.app_context():
            from app.extensions import db
            from sqlalchemy import select
            model = db.session.scalar(select(AiModel).order_by(AiModel.name))
            assert model is not None
            _, token = create_api_key(name="admin", role=ROLE_ADMINISTRATOR)
            client = seeded_app.test_client()
            resp = client.patch(
                f"/admin/models/{model.id}",
                json={"price_in": 1.5},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        assert resp.headers.get("Cache-Control") == "no-store"
