"""Public API blueprint — the agent-facing REST surface.

``/api/v1/`` denotes audience (the public, agent-facing REST API), not auth
class (D-025). Some endpoints here require authentication and some do not; a
protected endpoint returns ``401`` with ``WWW-Authenticate: Bearer`` when
called without a token, and the README table is the human signpost.
"""

from flask import Blueprint, jsonify, make_response
from sqlalchemy import select

from app.data.modalities import ALLOWED_MODALITIES
from app.extensions import db
from app.models import Modality

api_bp = Blueprint("api", __name__, url_prefix="/api/v1")


@api_bp.route("/modalities", methods=["GET"])
def list_modalities():
    """Return the assignable modality vocabulary, ordered by name.

    Public: no authentication. The response serves the ``modalities`` table
    intersected with the canonical allow-list, so every name advertised here
    is exactly a token the model write paths accept. Cacheable for five
    minutes and CORS-open on this route only.
    """
    names = db.session.scalars(
        select(Modality.name)
        .where(Modality.name.in_(ALLOWED_MODALITIES))
        .order_by(Modality.name)
    ).all()
    response = make_response(
        jsonify({"modalities": [{"name": name} for name in names]}), 200
    )
    response.headers["Cache-Control"] = "public, max-age=300"
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response