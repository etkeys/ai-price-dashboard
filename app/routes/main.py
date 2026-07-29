"""Main dashboard blueprint."""

from flask import Blueprint, render_template
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import AiModel

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    """Render the dashboard home page from the persisted model list."""
    models = db.session.scalars(
        select(AiModel)
        .options(
            selectinload(AiModel.input_modalities),
            selectinload(AiModel.output_modalities),
        )
        .order_by(AiModel.name)
    ).all()
    return render_template("index.html", models=models)


@main_bp.route("/health", methods=["GET"])
def health():
    """Lightweight liveness check endpoint."""
    return {"status": "ok"}, 200
