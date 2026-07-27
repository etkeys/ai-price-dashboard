"""Main dashboard blueprint."""

from flask import Blueprint, render_template

from app.data.sample_models import SAMPLE_MODELS

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    """Render the dashboard home page."""
    return render_template("index.html", models=SAMPLE_MODELS)


@main_bp.route("/health", methods=["GET"])
def health():
    """Lightweight liveness check endpoint."""
    return {"status": "ok"}, 200
