"""pytest fixtures for the ai-price-dashboard test suite."""

import pytest

from app import create_app
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
