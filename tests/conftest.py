"""pytest fixtures for the ai-price-dashboard test suite."""

import pytest

from app import create_app
from app.commands import seed_database
from app.extensions import db


@pytest.fixture
def app():
    """Create and configure a fresh app instance for tests."""
    app = create_app("testing")

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    """Return a test client for the app."""
    return app.test_client()


@pytest.fixture
def seeded_client(app):
    """Return a test client whose in-memory database has been seeded."""
    with app.app_context():
        seed_database()
    return app.test_client()


@pytest.fixture
def seeded_app(app):
    """Yield an app whose in-memory database has been seeded with default models.

    Useful for tests that need to create their own client but still want
    the default model fixtures present.
    """
    with app.app_context():
        seed_database()
    yield app

