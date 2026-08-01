"""Administrator key-management and model-management API and pages."""

import math

from flask import Blueprint, Response, jsonify, make_response, render_template, request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth import require_role
from app.auth.decorators import get_principal
from app.extensions import db
from app.models import AiModel, AiModelInputModality, AiModelOutputModality, Modality
from app.models.auth import ROLE_ADMINISTRATOR, ApiKey, AuthEvent, AuthSession
from app.services.auth_service import (
    _utcnow,
    create_api_key,
    revoke_api_key,
    safe_name,
)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

ALLOWED_MODALITIES = frozenset({"Text", "Images", "Files", "Videos", "Audio"})


def _key_status(row: ApiKey) -> str:
    """Derived status string for a key row."""
    if row.revoked_at is not None:
        return "revoked"
    if row.expires_at is not None and row.expires_at <= _utcnow():
        return "expired"
    return "active"


def _admin_error(status: int, message: str) -> Response:
    response = make_response(jsonify({"error": message}), status)
    response.headers["Cache-Control"] = "no-store"
    return response


@admin_bp.route("/keys/manage", methods=["GET"])
def keys_page():
    """Render the key management page (public shell; data is protected via @require_role)."""
    return render_template("admin/keys.html")


@admin_bp.route("/keys", methods=["GET"])
@require_role(ROLE_ADMINISTRATOR)
def list_keys():
    """List all API keys with metadata; never include secret hashes or raw tokens."""
    rows = db.session.scalars(select(ApiKey).order_by(ApiKey.created_at.desc())).all()
    creator_names = {k.id: k.name for k in rows}

    payload = []
    for row in rows:
        payload.append(
            {
                "kid": row.kid,
                "name": row.name,
                "role": row.role,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "created_by": creator_names.get(row.created_by_key_id)
                if row.created_by_key_id
                else None,
                "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
                "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
                "status": _key_status(row),
            }
        )

    response = make_response({"keys": payload}, 200)
    response.headers["Cache-Control"] = "no-store"
    return response


@admin_bp.route("/keys", methods=["POST"])
@require_role(ROLE_ADMINISTRATOR)
def create_key():
    """Create a new named API key; the plaintext token is returned exactly once."""
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    role = (data.get("role") or "").strip().lower()
    expires_at_raw = data.get("expires_at")

    if not name:
        return _admin_error(400, "Missing 'name'")
    if role not in (ROLE_ADMINISTRATOR, "updater"):
        return _admin_error(400, "Invalid 'role'")

    expires_at = None
    if expires_at_raw:
        from datetime import datetime as _dt

        try:
            expires_at = _dt.fromisoformat(expires_at_raw)
        except ValueError:
            return _admin_error(400, "Invalid ISO format for 'expires_at'")

    principal = get_principal()
    try:
        api_key, token = create_api_key(
            name=name,
            role=role,
            expires_at=expires_at,
            created_by_key_id=principal.api_key_id if principal else None,
        )
    except ValueError as exc:
        return _admin_error(400, str(exc))
    except IntegrityError:
        db.session.rollback()
        return _admin_error(409, f"An active key named '{safe_name(name)}' already exists")

    db.session.add(
        AuthEvent(
            event="key_created",
            kid=api_key.kid,
            actor_key_id=principal.api_key_id if principal else None,
            remote_addr=request.remote_addr,
            detail=None,
        )
    )
    db.session.commit()

    response = make_response(
        {
            "token": token,
            "kid": api_key.kid,
            "name": api_key.name,
            "role": api_key.role,
            "expires_at": api_key.expires_at.isoformat() if api_key.expires_at else None,
        },
        201,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@admin_bp.route("/keys/<kid>", methods=["GET"])
@require_role(ROLE_ADMINISTRATOR)
def get_key(kid: str):
    """Detail a single API key by kid."""
    row = db.session.scalar(select(ApiKey).where(ApiKey.kid == kid))
    if row is None:
        return _admin_error(404, "Key not found")

    creator_name = None
    if row.created_by_key_id is not None:
        creator = db.session.get(ApiKey, row.created_by_key_id)
        creator_name = creator.name if creator is not None else None

    payload = {
        "kid": row.kid,
        "name": row.name,
        "role": row.role,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "created_by": creator_name,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "status": _key_status(row),
    }

    response = make_response(payload, 200)
    response.headers["Cache-Control"] = "no-store"
    return response


@admin_bp.route("/keys/<kid>", methods=["DELETE"])
@require_role(ROLE_ADMINISTRATOR)
def delete_key(kid: str):
    """Revoke an API key by kid; cascades to its active sessions."""
    return _revoke_key(kid)


@admin_bp.route("/keys/<kid>/revoke", methods=["POST"])
@require_role(ROLE_ADMINISTRATOR)
def revoke_key(kid: str):
    """Revoke an API key by kid (legacy POST alias)."""
    return _revoke_key(kid)


def _revoke_key(kid: str) -> Response:
    """Common implementation for API key revocation."""
    principal = get_principal()
    try:
        row = revoke_api_key(kid, actor_principal=principal)
    except KeyError:
        return _admin_error(404, "Key not found")
    except PermissionError as exc:
        return _admin_error(409, str(exc))

    db.session.add(
        AuthEvent(
            event="key_revoked",
            kid=row.kid,
            actor_key_id=principal.api_key_id if principal else None,
            remote_addr=request.remote_addr,
            detail=None,
        )
    )
    db.session.commit()

    # Cascade to session rows is also handled in revoke_api_key; this is belt-and-suspenders.
    _ = db.session.scalars(
        select(AuthSession).where(AuthSession.api_key_id == row.id, AuthSession.revoked_at.is_(None))
    ).all()

    response = make_response({"revoked": True, "kid": row.kid}, 200)
    response.headers["Cache-Control"] = "no-store"
    return response


@admin_bp.route("/models/manage", methods=["GET"])
def models_page():
    """Render the model-management page; API data is administrator-only."""
    return render_template("admin/models.html", modalities=sorted(ALLOWED_MODALITIES))


@admin_bp.route("/models", methods=["POST"])
@require_role(ROLE_ADMINISTRATOR)
def create_model():
    """Create an AI model. All model attributes are required."""
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    name = name.strip() if isinstance(name, str) else ""

    if not name:
        return _admin_error(400, "Missing 'name'")
    if len(name) > 128:
        return _admin_error(400, "'name' must be at most 128 characters")

    # Check that every model attribute is supplied.
    required_fields = ("price_in", "price_out", "context_tokens", "input_content", "output_content")
    supplied = [f for f in required_fields if f in data and data[f] not in (None, "")]

    if len(supplied) != len(required_fields):
        return _admin_error(400, "All model attributes are required")

    # Validate prices and context_tokens.
    try:
        price_in = float(data["price_in"])
        price_out = float(data["price_out"])
        context_tokens = int(data["context_tokens"])
    except (TypeError, ValueError, OverflowError):
        return _admin_error(400, "Prices must be numbers and context_tokens must be an integer")

    if not (math.isfinite(price_in) and price_in >= 0 and math.isfinite(price_out) and price_out >= 0):
        return _admin_error(400, "Prices must be finite numbers >= 0")
    if context_tokens <= 0:
        return _admin_error(400, "'context_tokens' must be greater than zero")

    # Validate modalities.
    content = {}
    for field in ("input_content", "output_content"):
        values = data[field]
        if not isinstance(values, list) or not values or any(not isinstance(v, str) for v in values):
            return _admin_error(400, f"'{field}' must be a non-empty list of modality names")
        if len(set(values)) != len(values):
            return _admin_error(400, f"'{field}' contains duplicates")
        if not set(values).issubset(ALLOWED_MODALITIES):
            invalid = sorted(set(values) - ALLOWED_MODALITIES)[0]
            return _admin_error(400, f"'{field}' contains invalid modality: {invalid}")
        content[field] = values

    # Check uniqueness and fetch modality rows.
    if db.session.scalar(select(AiModel).where(AiModel.name == name)) is not None:
        return _admin_error(409, f"A model named '{name}' already exists")

    modality_names = set(content["input_content"] + content["output_content"])
    modality_rows = {
        row.name: row
        for row in db.session.scalars(select(Modality).where(Modality.name.in_(modality_names)))
    }
    missing = modality_names - modality_rows.keys()
    if missing:
        return _admin_error(400, f"Unknown modality: {sorted(missing)[0]}")

    # Create the model and association rows.
    model = AiModel(name=name, price_in=price_in, price_out=price_out, context_tokens=context_tokens)
    db.session.add(model)

    try:
        db.session.flush()
        for position, modality_name in enumerate(content["input_content"]):
            db.session.add(
                AiModelInputModality(
                    ai_model_id=model.id,
                    modality_id=modality_rows[modality_name].id,
                    position=position,
                )
            )
        for position, modality_name in enumerate(content["output_content"]):
            db.session.add(
                AiModelOutputModality(
                    ai_model_id=model.id,
                    modality_id=modality_rows[modality_name].id,
                    position=position,
                )
            )
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _admin_error(409, f"A model named '{name}' already exists")

    response = make_response(jsonify({"id": model.id, "name": model.name}), 201)
    response.headers["Cache-Control"] = "no-store"
    return response
