"""Public API blueprint — the agent-facing REST surface.

``/api/v1/`` denotes audience (the public, agent-facing REST API), not auth
class (D-025). Some endpoints here require authentication and some do not; a
protected endpoint returns ``401`` with ``WWW-Authenticate: Bearer`` when
called without a token, and the README table is the human signpost.
"""

from flask import Blueprint, jsonify, make_response, request
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.data.modalities import ALLOWED_MODALITIES
from app.extensions import db
from app.models import AiModel, Modality

api_bp = Blueprint("api", __name__, url_prefix="/api/v1")


def _api_error(status: int, message: str):
    """JSON error response, matching the app's ``{\"error\": ...}`` envelope.

    Errors carry ``Cache-Control: no-store`` and must not carry the CORS or
    ``max-age`` headers — caching a 400 would serve a client its own stale
    error on the corrected retry.
    """
    response = make_response(jsonify({"error": message}), status)
    response.headers["Cache-Control"] = "no-store"
    return response


def _iso_utc(value) -> str | None:
    """Serialise a naive-UTC datetime as ISO 8601 with an explicit ``Z`` (D-033).

    The stored columns are naive but genuinely UTC; a bare ``isoformat()``
    would emit a zoneless timestamp a machine consumer cannot interpret.
    """
    if value is None:
        return None
    return value.isoformat() + "Z"


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


@api_bp.route("/models", methods=["GET"])
def list_models():
    """Return a machine-readable listing of all models with their details.

    Public: no authentication. ``?include_hidden=true`` (case-insensitive)
    includes hidden models; absent or ``false`` excludes them, agreeing with
    the ``/`` dashboard (D-021). Modality lists come back in persisted
    ``position`` order (D-032), and timestamps carry an explicit ``Z`` (D-033).
    Cacheable for 60 seconds and CORS-open on this route only. ``id`` is the
    token to send back in ``PATCH /admin/models/<id>``.
    """
    raw = request.args.get("include_hidden")
    if raw is not None:
        normalized = raw.lower()
        if normalized == "true":
            include_hidden = True
        elif normalized == "false":
            include_hidden = False
        else:
            return _api_error(
                400, "'include_hidden' must be 'true' or 'false'"
            )
    else:
        include_hidden = False

    stmt = (
        select(AiModel)
        .options(
            selectinload(AiModel.input_modalities),
            selectinload(AiModel.output_modalities),
        )
        .order_by(AiModel.sort_name, AiModel.name)
    )
    if not include_hidden:
        stmt = stmt.where(~AiModel.is_hidden)

    models = db.session.scalars(stmt).all()

    payload = {
        "models": [
            {
                "id": m.id,
                "name": m.name,
                "price_in": m.price_in,
                "price_out": m.price_out,
                "context_type": m.context_type,
                "context_tokens": m.context_tokens,
                "pricing_unit": m.pricing_unit,
                "input_content": m.input_content,
                "output_content": m.output_content,
                "hidden": m.is_hidden,
                "hidden_at": _iso_utc(m.hidden_at),
                "created_at": _iso_utc(m.created_at),
                "updated_at": _iso_utc(m.updated_at),
            }
            for m in models
        ]
    }
    response = make_response(jsonify(payload), 200)
    response.headers["Cache-Control"] = "public, max-age=60"
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response