"""Regression tests for SQLAlchemy model registration."""

from app import create_app
from app.extensions import db
from app.models.price import Price


def test_price_model_registered_after_factory_creation():
    """Creating the app should populate SQLAlchemy metadata with the Price table."""
    app = create_app("testing")
    with app.app_context():
        assert "prices" in db.metadata.tables
        assert db.metadata.tables["prices"] is Price.__table__


def test_create_all_populates_price_table():
    """db.create_all() should create the prices table without explicit model import."""
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        assert "prices" in db.inspect(db.engine).get_table_names()
