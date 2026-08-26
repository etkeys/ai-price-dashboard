"""Populated-database Alembic migration round-trip for output-only pricing.

D-037..D-039 mandate a lossless migration: every pre-revision row must come
through upgrade with its original ``price_in``/``context_tokens`` values
unchanged and be backfilled to legacy token semantics (``context_type='tokens'``,
``pricing_unit='million_tokens'``). Downgrade must refuse loudly while any row
uses the new output-only/image features, and re-upgrade must reproduce the new
schema. These tests drive Alembic against a temp file-backed SQLite database
through the real migration scripts.
"""

import os

import pytest
from alembic import command
from alembic.config import Config

from app import create_app
from app.extensions import db

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREV_REV = "453c7603f37a"

ALEMBIC_CFG = os.path.join(ROOT, "migrations", "alembic.ini")
SCRIPT_LOCATION = os.path.join(ROOT, "migrations")


def _alembic_config():
    cfg = Config(ALEMBIC_CFG)
    cfg.set_main_option("script_location", SCRIPT_LOCATION)
    return cfg


@pytest.fixture
def migrated_app(tmp_path):
    """An app pointed at a temp file SQLite DB, migrated to the previous head."""
    uri = f"sqlite:///{tmp_path / 'test.db'}"
    app = create_app("testing")
    app.config["SQLALCHEMY_DATABASE_URI"] = uri
    with app.app_context():
        command.upgrade(_alembic_config(), PREV_REV)
    yield app


def _upgrade_head(app):
    with app.app_context():
        command.upgrade(_alembic_config(), "head")


def _downgrade_prev(app):
    with app.app_context():
        command.downgrade(_alembic_config(), PREV_REV)


def _insert_legacy(app, name, price_in, price_out, context_tokens):
    with app.app_context():
        conn = db.session.connection()
        conn.exec_driver_sql(
            "INSERT INTO ai_models (name, price_in, price_out, context_tokens) "
            "VALUES (?, ?, ?, ?)",
            (name, price_in, price_out, context_tokens),
        )
        db.session.commit()


def _rows(app, cols, where=""):
    sql = f"SELECT {cols} FROM ai_models {where} ORDER BY name"
    with app.app_context():
        return db.session.execute(db.text(sql)).mappings().all()


def test_upgrade_preserves_legacy_rows_and_backfills_defaults(migrated_app):
    _insert_legacy(migrated_app, "legacy/one", 1.0, 5.0, 200000)
    _insert_legacy(migrated_app, "legacy/zero-input", 0.0, 0.035, 66000)

    _upgrade_head(migrated_app)

    rows = _rows(
        migrated_app,
        "name, price_in, price_out, context_tokens, context_type, pricing_unit",
    )
    assert rows[0]["name"] == "legacy/one"
    assert rows[0]["price_in"] == 1.0
    assert rows[0]["price_out"] == 5.0
    assert rows[0]["context_tokens"] == 200000
    assert rows[0]["context_type"] == "tokens"
    assert rows[0]["pricing_unit"] == "million_tokens"

    # Numeric 0 stays a distinct free-input price, not nulled.
    assert rows[1]["name"] == "legacy/zero-input"
    assert rows[1]["price_in"] == 0.0
    assert rows[1]["context_tokens"] == 66000
    assert rows[1]["context_type"] == "tokens"
    assert rows[1]["pricing_unit"] == "million_tokens"


def test_new_schema_accepts_output_only_image_row(migrated_app):
    _upgrade_head(migrated_app)
    with migrated_app.app_context():
        db.session.execute(
            db.text(
                "INSERT INTO ai_models (name, price_in, price_out, context_tokens,"
                " context_type, pricing_unit) VALUES (:name, NULL, :price_out, NULL,"
                " 'image', 'image')"
            ),
            {"name": "seedream/lite", "price_out": 0.035},
        )
        db.session.commit()
    rows = _rows(migrated_app, "price_in, price_out, context_tokens", "WHERE name='seedream/lite'")
    assert rows[0]["price_in"] is None
    assert rows[0]["price_out"] == 0.035
    assert rows[0]["context_tokens"] is None


def test_downgrade_refuses_output_only_rows(migrated_app):
    _upgrade_head(migrated_app)
    with migrated_app.app_context():
        db.session.execute(
            db.text(
                "INSERT INTO ai_models (name, price_in, price_out, context_tokens,"
                " context_type, pricing_unit) VALUES ('seedream/lite', NULL, 0.035, NULL,"
                " 'image', 'image')"
            )
        )
        db.session.commit()
    with pytest.raises(RuntimeError, match="Cannot downgrade"):
        _downgrade_prev(migrated_app)


def test_downgrade_upgrade_round_trip_on_legacy_data(migrated_app):
    _insert_legacy(migrated_app, "legacy/one", 1.0, 5.0, 200000)
    _upgrade_head(migrated_app)
    _downgrade_prev(migrated_app)
    # Legacy columns are back to non-null; data unchanged.
    rows = _rows(migrated_app, "name, price_in, price_out, context_tokens")
    assert rows[0]["price_in"] == 1.0
    assert rows[0]["context_tokens"] == 200000
    # Re-upgrade reproduces the new schema and defaults.
    _upgrade_head(migrated_app)
    rows = _rows(migrated_app, "name, context_type, pricing_unit")
    assert rows[0]["context_type"] == "tokens"
    assert rows[0]["pricing_unit"] == "million_tokens"
