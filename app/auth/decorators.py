"""Flask decorators, resolver wiring, and auth error helpers."""

from __future__ import annotations

import functools
import ipaddress
import time
from typing import Callable, TypeVar

from flask import Blueprint, Response, current_app, g, jsonify, make_response, request

from app.services.auth_service import (
    Principal,
    PrincipalKind,
    ROLE_UPDATER,
    _constant_time_equals,
    has_role,
    parse_token,
    resolve_principal,
)

F = TypeVar("F", bound=Callable)

UNAUTHENTICATED_EXCHANGE_ENDPOINTS = frozenset(
    {
        "auth.create_session",
        "auth.claim_recovery",
    }
)


def get_principal() -> Principal | None:
    """Return the resolved principal for the current request, caching on ``g``.

    The cache is keyed to the current ``Authorization`` header so that a
    principal resolved during an earlier request cannot leak across requests
    in tests or threaded contexts where the application context is reused.
    """
    header = request.headers.get("Authorization", "")
    cached = getattr(g, "_principal_cache", None)
    if cached is not None and cached.get("header") == header:
        return cached.get("principal")
    principal = resolve_principal(request)
    g._principal_cache = {"header": header, "principal": principal}
    return principal


def require_role(role: str) -> Callable[[F], F]:
    """Decorator gating a view to principals with at least the required role."""

    def decorator(func: F) -> F:
        func._auth_required_role = role  # type: ignore[attr-defined]

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            principal = get_principal()
            if principal is None:
                return _auth_error(401, "Authentication required", principal)
            if not has_role(principal.role, role):
                return _auth_error(403, "Insufficient role", principal)
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def _auth_error(status: int, message: str, principal: Principal | None) -> Response:
    """Return a JSON or HTML error response for auth failures."""
    response = make_response(jsonify({"error": message}), status)
    response.headers["Cache-Control"] = "no-store"
    if status == 401:
        response.headers["WWW-Authenticate"] = "Bearer"
    return response


def _remote_address() -> str:
    """Return the request's remote address, defaulting to empty string."""
    return request.remote_addr or ""


def _is_throttled(remote_addr: str) -> bool:
    """Check whether the remote address exceeds the crude in-process rate limit.

    This is intentionally per-worker and resets on restart (defence-in-depth
    only). Do not promote to DB-backed storage without WAL mode and a real
    rate-limit design.
    """
    if not remote_addr:
        return False
    try:
        ipaddress.ip_address(remote_addr)
    except ValueError:
        return False

    max_attempts = current_app.config["AUTH_EXCHANGE_MAX_ATTEMPTS"]
    window = current_app.config["AUTH_EXCHANGE_WINDOW_SECONDS"]
    now = time.monotonic()

    store = current_app.extensions.get("_auth_rate_limit_store")
    if store is None:
        store = {}
        current_app.extensions["_auth_rate_limit_store"] = store

    bucket = store.setdefault(remote_addr, [0, now])
    if now - bucket[1] >= window:
        bucket[0] = 0
        bucket[1] = now
    bucket[0] += 1
    return bucket[0] > max_attempts


def _throttled_response() -> Response:
    """Return 429 with Retry-After for throttled exchange endpoints."""
    retry_after = current_app.config["AUTH_EXCHANGE_WINDOW_SECONDS"]
    response = make_response(
        jsonify({"error": "Too many attempts; try again later"}),
        429,
    )
    response.headers["Retry-After"] = str(retry_after)
    response.headers["Cache-Control"] = "no-store"
    return response


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.before_request
def _rate_limit_exchange() -> Response | None:
    """Apply crude throttling to the unauthenticated exchange endpoints."""
    if request.endpoint not in UNAUTHENTICATED_EXCHANGE_ENDPOINTS:
        return None
    if _is_throttled(_remote_address()):
        return _throttled_response()
    return None


@auth_bp.route("/session", methods=["POST"])
def create_session():
    """Exchange a long-lived API key for a short-lived session token."""
    from app.models.auth import ApiKey
    from app.services.auth_service import (
        ROLE_UPDATER,
        TOKEN_PREFIX_API_KEY,
        create_auth_session,
        parse_token,
    )

    data = request.get_json(silent=True) or {}
    raw = (data.get("key") or "").strip()
    if not raw:
        return _auth_error(400, "Missing 'key'", None)

    parsed = parse_token(raw)
    if parsed is None or parsed[0] != TOKEN_PREFIX_API_KEY:
        return _auth_error(401, "Invalid key", None)

    # The raw key is in the request body, not the Authorization header, so we
    # resolve it manually using the same two-step lookup as resolve_principal.
    from app.services.auth_service import _hash_secret, _is_key_live, _utcnow

    now = _utcnow()
    kid = parsed[1]
    secret = parsed[2]
    row = ApiKey.query.filter_by(kid=kid).first()
    if (
        row is None
        or not _constant_time_equals(row.secret_hash, _hash_secret(secret))
        or not _is_key_live(row, now)
    ):
        return _auth_error(401, "Invalid key", None)

    session_model, token = create_auth_session(row, remote_addr=_remote_address())
    response = make_response(
        jsonify(
            {
                "token": token,
                "name": row.name,
                "role": row.role,
                "expires_at": session_model.expires_at.isoformat(),
            }
        ),
        201,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@auth_bp.route("/session", methods=["DELETE"])
@require_role(ROLE_UPDATER)
def delete_session():
    """Revoke the session token presented by the caller."""
    from app.models.auth import AuthSession
    from app.services.auth_service import TOKEN_PREFIX_SESSION, _hash_secret, revoke_auth_session

    principal = get_principal()
    # Resolve the session row directly from the header.
    header = request.headers.get("Authorization", "")
    scheme = "Bearer "
    if (
        not header[: len(scheme)].lower() == scheme.lower()
        or len(header) <= len(scheme)
    ):
        return _auth_error(401, "Authentication required", None)

    raw = header[len(scheme) :].strip()
    parsed = parse_token(raw)
    if parsed is None or parsed[0] != TOKEN_PREFIX_SESSION:
        return _auth_error(401, "Invalid session", None)

    session_model = AuthSession.query.filter_by(kid=parsed[1]).first()
    if (
        session_model is None
        or not _constant_time_equals(session_model.secret_hash, _hash_secret(parsed[2]))
        or session_model.revoked_at is not None
    ):
        return _auth_error(401, "Invalid session", None)

    revoke_auth_session(session_model)
    g._principal_cache = {"header": header, "principal": None}
    response = make_response(jsonify({"signed_out": True}), 200)
    response.headers["Cache-Control"] = "no-store"
    return response


@auth_bp.route("/whoami", methods=["GET"])
def whoami():
    """Return the authenticated principal's metadata."""
    principal = get_principal()
    if principal is None:
        return _auth_error(401, "Authentication required", None)
    response = make_response(
        jsonify(
            {
                "name": principal.name,
                "role": principal.role,
                "kind": principal.kind.value,
            }
        ),
        200,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@auth_bp.route("/recovery/claim", methods=["POST"])
def claim_recovery():
    """Redeem a recovery key for a new Administrator API key."""
    from app.services.auth_service import claim_recovery_key

    data = request.get_json(silent=True) or {}
    raw = (data.get("recovery_key") or "").strip()
    name = (data.get("name") or "").strip()
    if not raw or not name:
        return _auth_error(400, "Missing 'recovery_key' or 'name'", None)

    try:
        api_key, token = claim_recovery_key(raw, name=name, remote_addr=_remote_address())
    except ValueError:
        return _auth_error(401, "Invalid or expired recovery key", None)

    response = make_response(
        jsonify(
            {
                "token": token,
                "name": api_key.name,
                "role": api_key.role,
            }
        ),
        201,
    )
    response.headers["Cache-Control"] = "no-store"
    return response
