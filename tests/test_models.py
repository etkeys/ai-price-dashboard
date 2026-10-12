"""Tests for the SQLAlchemy data models."""

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError

from app.commands import seed_database
from app.extensions import db
from app.models import AiModel, AiModelInputModality, AiModelOutputModality, Modality


class TestAiModelProperties:
    """The ORM entity must expose the attribute contract used by templates."""

    def test_input_output_content_are_ordered_lists(self, app):
        with app.app_context():
            text = Modality(name="Text")
            images = Modality(name="Images")
            db.session.add_all([text, images])
            db.session.flush()

            model = AiModel(
                name="vendor/model",
                price_in=1.0,
                price_out=2.0,
                context_tokens=100_000,
            )
            db.session.add(model)
            db.session.flush()

            db.session.add_all(
                [
                    AiModelInputModality(
                        ai_model_id=model.id, modality_id=images.id, position=0
                    ),
                    AiModelInputModality(
                        ai_model_id=model.id, modality_id=text.id, position=1
                    ),
                    AiModelOutputModality(
                        ai_model_id=model.id, modality_id=text.id, position=0
                    ),
                ]
            )
            db.session.commit()

            # Ordering is governed by the association position column.
            assert model.input_content == ["Images", "Text"]
            assert model.output_content == ["Text"]
            assert isinstance(model.input_content, list)
            assert isinstance(model.output_content, list)

    def test_name_uniqueness_raises(self, app):
        with app.app_context():
            first = AiModel(
                name="vendor/model", price_in=1.0, price_out=2.0, context_tokens=100_000
            )
            db.session.add(first)
            db.session.commit()

            duplicate = AiModel(
                name="vendor/model", price_in=3.0, price_out=4.0, context_tokens=200_000
            )
            db.session.add(duplicate)
            with pytest.raises(IntegrityError):
                db.session.commit()

    def test_is_hidden_reflects_hidden_at(self, app):
        """is_hidden is False when hidden_at is None, True otherwise (D-020).

        The hybrid is the canonical predicate; routes and templates must never
        re-derive the hidden state from the raw column.
        """
        with app.app_context():
            visible = AiModel(
                name="vendor/visible",
                price_in=1.0,
                price_out=2.0,
                context_tokens=100_000,
            )
            hidden = AiModel(
                name="vendor/hidden",
                price_in=1.0,
                price_out=2.0,
                context_tokens=100_000,
                hidden_at=db.func.now(),
            )
            db.session.add_all([visible, hidden])
            db.session.commit()

            assert visible.is_hidden is False
            assert hidden.is_hidden is True

    def test_is_hidden_usable_as_sql_expression(self, app):
        """is_hidden compiles in a WHERE clause as `hidden_at IS NOT NULL` (D-036).

        The endpoint's natural query filters with ``~AiModel.is_hidden``, the
        exact use that raised InvalidRequestError on the pre-fix tree because
        ``@is_hidden.expression`` did not replace the class-level attribute.
        This pins the *expression* form so a regression fails loudly.
        """
        with app.app_context():
            visible = AiModel(
                name="vendor/visible",
                price_in=1.0,
                price_out=2.0,
                context_tokens=100_000,
            )
            hidden = AiModel(
                name="vendor/hidden",
                price_in=1.0,
                price_out=2.0,
                context_tokens=100_000,
                hidden_at=db.func.now(),
            )
            db.session.add_all([visible, hidden])
            db.session.commit()

            hidden_rows = db.session.scalars(
                select(AiModel).where(AiModel.is_hidden)
            ).all()
            assert [r.name for r in hidden_rows] == ["vendor/hidden"]

            visible_rows = db.session.scalars(
                select(AiModel).where(~AiModel.is_hidden)
            ).all()
            assert [r.name for r in visible_rows] == ["vendor/visible"]


class TestSeedIdempotency:
    """Seeding must be safe to run repeatedly."""

    def test_seed_is_idempotent(self, app):
        with app.app_context():
            ok1, msg1 = seed_database()
            assert ok1 is True
            assert "Seeded" in msg1
            count1 = db.session.scalar(select(func.count()).select_from(AiModel))

            ok2, msg2 = seed_database()
            assert ok2 is True
            assert "already seeded" in msg2
            count2 = db.session.scalar(select(func.count()).select_from(AiModel))

            assert count1 == count2


class TestForeignKeys:
    """SQLite foreign key support must be enabled for cascading deletes."""

    def test_pragma_foreign_keys_enabled(self, app):
        with app.app_context():
            result = db.session.execute(db.text("PRAGMA foreign_keys"))
            assert result.scalar() == 1

    def test_delete_model_cascades_associations(self, app):
        with app.app_context():
            text = Modality(name="Text")
            db.session.add(text)
            db.session.flush()

            model = AiModel(
                name="vendor/model", price_in=1.0, price_out=2.0, context_tokens=100_000
            )
            db.session.add(model)
            db.session.flush()

            db.session.add(
                AiModelInputModality(
                    ai_model_id=model.id, modality_id=text.id, position=0
                )
            )
            db.session.commit()

            db.session.delete(model)
            db.session.commit()

            inspector = inspect(db.engine)
            assert inspector.get_table_names()
            assert (
                db.session.scalar(
                    select(func.count()).select_from(AiModelInputModality)
                )
                == 0
            )


class TestContextTypeAndNullPricing:
    """D-037..D-039: nullable price_in and token/image context semantics."""

    def test_legacy_orm_construction_is_token_based(self, app):
        """Direct legacy ORM construction defaults to token context / million tokens.

        Ruling 3A: an AiModel built without the new fields behaves exactly like
        the pre-feature model.
        """
        with app.app_context():
            model = AiModel(
                name="vendor/model", price_in=1.0, price_out=2.0, context_tokens=100_000
            )
            db.session.add(model)
            db.session.flush()
            assert model.context_type == "tokens"
            assert model.pricing_unit == "million_tokens"
            assert model.context_tokens == 100_000

    def test_nullable_input_price_and_image_context_row(self, app):
        """An output-only image row persists price_in NULL and image semantics."""
        with app.app_context():
            model = AiModel(
                name="bytedance-seed/seedream-5-0-lite",
                price_in=None,
                price_out=0.035,
                context_type="image",
                context_tokens=None,
                pricing_unit="image",
            )
            db.session.add(model)
            db.session.commit()

            fresh = db.session.scalar(select(AiModel).where(AiModel.name == model.name))
            assert fresh.price_in is None
            assert fresh.price_out == 0.035
            assert fresh.context_type == "image"
            assert fresh.context_tokens is None
            assert fresh.pricing_unit == "image"

    def test_zero_price_in_is_distinct_from_null(self, app):
        """Numeric 0 persists as a real free-input price, not NULL."""
        with app.app_context():
            free = AiModel(
                name="vendor/free", price_in=0.0, price_out=2.0, context_tokens=100_000
            )
            db.session.add(free)
            db.session.commit()
            fresh = db.session.scalar(select(AiModel).where(AiModel.name == free.name))
            assert fresh.price_in == 0.0
            assert fresh.price_in is not None

    @pytest.mark.parametrize(
        ("context_type", "context_tokens"),
        [
            ("bogus", 1000),
            ("tokens", None),
            ("tokens", 0),
            ("image", 1000),
        ],
    )
    def test_db_rejects_invalid_context_type_combinations(
        self, app, context_type, context_tokens
    ):
        """The conditional CHECK constraints reject incoherent rows at the DB level."""
        with app.app_context():
            model = AiModel(
                name=f"vendor/{context_type}-{context_tokens}",
                price_in=1.0,
                price_out=2.0,
                context_type=context_type,
                context_tokens=context_tokens,
            )
            db.session.add(model)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()

    def test_db_rejects_invalid_pricing_unit(self, app):
        """An unknown pricing_unit violates its CHECK constraint."""
        with app.app_context():
            model = AiModel(
                name="vendor/bad-unit",
                price_in=1.0,
                price_out=2.0,
                context_tokens=100_000,
                pricing_unit="per-chunk",
            )
            db.session.add(model)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()

