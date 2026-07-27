"""Entry point for the ai-price-dashboard Flask app.

When executed directly (``python run.py``), the app always runs in development
mode for local ergonomics regardless of environment variables.

When this module is imported by a WSGI server (e.g. ``gunicorn "run:app"``),
the application is built using the configuration selected by the
``FLASK_CONFIG`` environment variable, defaulting to ``production`` so that the
documented production deployment never silently falls back to development
settings.
"""

import os

from app import create_app


# The app object must be created in the correct path: direct execution uses
# development mode without reading FLASK_CONFIG, while a WSGI import uses
# FLASK_CONFIG and defaults to production.
if __name__ == "__main__":
    # Direct execution is always development mode.
    app = create_app("development")
    app.run(host="0.0.0.0", port=5000, debug=True)
else:
    # WSGI servers import this module without going through __main__, so pick
    # the configuration from FLASK_CONFIG. Any startup error (e.g. missing
    # SECRET_KEY for production) fails loudly at import time, which is the
    # safe failure mode for production deployments.
    _config_name = os.environ.get("FLASK_CONFIG", "production").strip() or "production"
    app = create_app(_config_name)
