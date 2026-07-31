"""Administrator key-management API and pages."""

from flask import Blueprint, Response, make_response, render_template, request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth import require_role
from app.auth.decorators import get_principal
from app.extensions import db
from app.models.auth import ROLE_ADMINISTRATOR, ApiKey, AuthEvent, AuthSession
from app.services.auth_service import (
    _utcnow,
    create_api_key,
    revoke_api_key,
    safe_name,
)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _key_status(row: ApiKey) -> str:
    """Derived status string for a key row."""
    if row.revoked_at is not None:
        return "revoked"
    if row.expires_at is not None and row.expires_at <= _utcnow():
        return "expired"
    return "active"


def _admin_error(status: int, message: str) -> Response:
    from flask import jsonify

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
