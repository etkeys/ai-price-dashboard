"""Application factory for the ai-price-dashboard Flask app."""

from flask import Flask


def create_app(config_name: str = "default") -> Flask:
    """Create and configure a Flask application instance."""
    app = Flask(__name__)

    # Load configuration from the matching config class.
    from app.config import config

    app.config.from_object(config[config_name]())

    # Initialize extensions against the app.
    from app.extensions import db, migrate

    db.init_app(app)
    migrate.init_app(app, db)

    # Register Jinja template helpers.
    from app.utils.helpers import format_context, format_price

    app.jinja_env.globals.update(format_context=format_context, format_price=format_price)

    # Register blueprints.
    from app.routes.main import main_bp

    app.register_blueprint(main_bp)

    return app
