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
