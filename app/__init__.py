"""Application factory for the ai-price-dashboard Flask app."""

from flask import Flask
from sqlalchemy import event
from sqlalchemy.engine import Engine


def _set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable foreign key enforcement for every SQLite connection."""
    if type(dbapi_connection).__module__ == "sqlite3":
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


event.listens_for(Engine, "connect")(_set_sqlite_pragma)


def create_app(config_name: str = "default") -> Flask:
    """Create and configure a Flask application instance."""
    app = Flask(__name__)

    # Load configuration from the matching config class.
    from app.config import config

    app.config.from_object(config[config_name]())

    # Import models so db.metadata is populated before Alembic runs.
    from app import models

    # Initialize extensions against the app.
    from app.extensions import db, migrate

    db.init_app(app)
    migrate.init_app(app, db)

    # Register custom Flask CLI commands.
    from app.commands import register_commands

    register_commands(app)

    # Register Jinja template helpers.
    from app.utils.helpers import format_context, format_price, render_price

    app.jinja_env.globals.update(
        format_context=format_context, format_price=format_price, render_price=render_price
    )

    # Register blueprints.
    from app.auth import auth_bp
    from app.routes.admin import admin_bp
    from app.routes.api import api_bp
    from app.routes.main import main_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(admin_bp)

    return app
