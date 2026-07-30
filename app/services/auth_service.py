"""Authentication primitives and token lifecycle.

This module is deliberately low on Flask dependencies; ``current_app`` is used
only to read configuration values. Cryptographic helpers fail closed and never
log, echo, or accept user-supplied secrets.
"""

from __future__ import annotations

import datetime
import enum
import hmac
import html
import secrets
from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING

from flask import current_app
from sqlalchemy import select

from app.extensions import db
from app.models.auth import (
    ROLE_ADMINISTRATOR,
    ROLE_UPDATER,
    ROLES,
    ApiKey,
    AuthEvent,
    AuthSession,
    RecoveryKey,
)

if TYPE_CHECKING:
    from flask import Request


TOKEN_PREFIX_API_KEY = "apdk"
TOKEN_PREFIX_SESSION = "apds"
TOKEN_PREFIX_RECOVERY = "apdr"
VALID_PREFIXES = frozenset({TOKEN_PREFIX_API_KEY, TOKEN_PREFIX_SESSION, TOKEN_PREFIX_RECOVERY})

API_KEY_LENGTH = 61  # prefix.kid.secret -> 4 + 1 + 12 + 1 + 43
KID_LENGTH = 12
SECRET_LENGTH = 43

ROLE_RANK = {"updater": 10, "administrator": 20}


class PrincipalKind(enum.Enum):
    KEY = "key"
    SESSION = "session"


@dataclass(frozen=True, slots=True)
class Principal:
    """The resolved identity for an authenticated request."""

    kind: PrincipalKind
    kid: str
    api_key_id: int
    name: str
    role: str

    @property
    def is_administrator(self) -> bool:
        return self.role == ROLE_ADMINISTRATOR


def _utcnow() -> datetime.datetime:
    """Return a naive UTC datetime to match existing func.now() columns."""
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def _hash_secret(secret: str) -> str:
    """SHA-256 of the secret as lowercase hex."""
    return sha256(secret.encode("ascii")).hexdigest()


def _constant_time_equals(a: str, b: str) -> bool:
    """Constant-time string comparison using hmac.compare_digest."""
    return hmac.compare_digest(a, b)


def generate_kid() -> str:
    """Generate a 12-char base64url public key identifier."""
    return secrets.token_urlsafe(9)


def generate_secret() -> str:
    """Generate a 43-char base64url secret (256 bits)."""
    return secrets.token_urlsafe(32)


def build_token(prefix: str, kid: str, secret: str) -> str:
    """Assemble a prefixed token: <prefix>.<kid>.<secret>."""
    return f"{prefix}.{kid}.{secret}"


def generate_token(prefix: str) -> tuple[str, str, str]:
    """Generate a brand-new token and return (token, kid, secret)."""
    kid = generate_kid()
    secret = generate_secret()
    return build_token(prefix, kid, secret), kid, secret


def parse_token(raw: str) -> tuple[str, str, str] | None:
    """Parse a raw token string into (prefix, kid, secret).

    Returns ``None`` for any malformed value. This function performs no database
    access and costs zero queries.
    """
    value = raw.strip()
    if len(value) != API_KEY_LENGTH:
        return None
    parts = value.split(".")
    if len(parts) != 3:
        return None
    prefix, kid, secret = parts
    if prefix not in VALID_PREFIXES:
        return None
    if len(kid) != KID_LENGTH or len(secret) != SECRET_LENGTH:
        return None
    return prefix, kid, secret


def has_role(actual: str, required: str) -> bool:
    """Return True if *actual* role outranks or equals *required* role."""
    return ROLE_RANK[actual] >= ROLE_RANK[required]


def _log_event(
    event: str,
    kid: str | None,
    actor_key_id: int | None,
    remote_addr: str | None,
    detail: str | None,
) -> None:
    """Write an append-only audit row. ``detail`` must contain no secrets."""
    db.session.add(
        AuthEvent(
            event=event,
            kid=_safe_kid_for_log(kid),
            actor_key_id=actor_key_id,
            remote_addr=remote_addr,
            detail=detail,
        )
    )
    db.session.commit()


def _safe_kid_for_log(kid: str | None) -> str | None:
    """Kid values are public, but reject anything that looks malformed."""
    if kid is None:
        return None
    if len(kid) <= 16 and "." not in kid:
        return kid
    return "<invalid>"


def _is_key_live(row: ApiKey, now: datetime.datetime) -> bool:
    """True if the api_keys row is not revoked and not expired."""
    if row.revoked_at is not None:
        return False
    if row.expires_at is not None and row.expires_at <= now:
        return False
    return True


def _is_session_live(row: AuthSession, now: datetime.datetime) -> bool:
    """True if the auth_sessions row is within absolute, idle, and revocation bounds."""
    if row.revoked_at is not None:
        return False
    if row.expires_at <= now:
        return False
    idle_deadline = row.last_seen_at + datetime.timedelta(
        seconds=current_app.config["AUTH_SESSION_IDLE_TIMEOUT"]
    )
    if idle_deadline <= now:
        return False
    return True


def _maybe_touch_session(row: AuthSession, now: datetime.datetime) -> None:
    """Refresh last_seen_at, throttled by AUTH_SESSION_TOUCH_INTERVAL."""
    interval = current_app.config["AUTH_SESSION_TOUCH_INTERVAL"]
    if (now - row.last_seen_at).total_seconds() >= interval:
        row.last_seen_at = now
        db.session.commit()


def _maybe_touch_key(row: ApiKey, now: datetime.datetime) -> None:
    """Refresh last_used_at for api_keys, throttled."""
    interval = current_app.config["AUTH_SESSION_TOUCH_INTERVAL"]
    if row.last_used_at is None or (now - row.last_used_at).total_seconds() >= interval:
        row.last_used_at = now
        db.session.commit()


def resolve_principal(
    request: Request | None,
    *,
    log: bool = True,
) -> Principal | None:
    """Resolve an ``Authorization: *** header into a :class:`Principal`.

    Handles API keys and session tokens; recovery keys are rejected outright.
    The caller is responsible for enforcing roles (see ``require_role``).
    """
    if request is None:
        return None

    header = request.headers.get("Authorization", "")
    if not header:
        return None

    # Require literal "Bearer " scheme, case-insensitive per RFC 7235.
    scheme = "Bearer "
    if not header[: len(scheme)].lower() == scheme.lower() or len(header) <= len(scheme):
        return None

    raw = header[len(scheme) :].strip()
    parsed = parse_token(raw)
    if parsed is None:
        return None
    prefix, kid, secret = parsed
    secret_hash = _hash_secret(secret)
    now = _utcnow()
    remote_addr = request.remote_addr

    # Sessions (apds)
    if prefix == TOKEN_PREFIX_SESSION:
        row = db.session.scalar(
            select(AuthSession).where(AuthSession.kid == kid, AuthSession.secret_hash == secret_hash)
        )
        if row is None:
            return None
        if not _is_session_live(row, now):
            return None
        parent = db.session.get(ApiKey, row.api_key_id)
        if parent is None or not _is_key_live(parent, now):
            return None
        _maybe_touch_session(row, now)
        principal = Principal(
            kind=PrincipalKind.SESSION,
            kid=row.kid,
            api_key_id=parent.id,
            name=parent.name,
            role=parent.role,
        )
        if log:
            _log_event(
                "auth_success",
                kid=row.kid,
                actor_key_id=parent.id,
                remote_addr=remote_addr,
                detail="via session token",
            )
        return principal

    # API keys (apdk)
    if prefix == TOKEN_PREFIX_API_KEY:
        row = db.session.scalar(
            select(ApiKey).where(ApiKey.kid == kid, ApiKey.secret_hash == secret_hash)
        )
        if row is None:
            return None
        if not _is_key_live(row, now):
            return None
        _maybe_touch_key(row, now)
        principal = Principal(
            kind=PrincipalKind.KEY,
            kid=row.kid,
            api_key_id=row.id,
            name=row.name,
            role=row.role,
        )
        if log:
            _log_event(
                "auth_success",
                kid=row.kid,
                actor_key_id=row.id,
                remote_addr=remote_addr,
                detail="via api key",
            )
        return principal

    # Recovery keys are not accepted as general bearer credentials.
    return None


def create_api_key(
    name: str,
    role: str,
    *,
    expires_at: datetime.datetime | None = None,
    created_by_key_id: int | None = None,
    commit: bool = True,
) -> tuple[ApiKey, str]:
    """Create a new named API key and return the model plus the plaintext token."""
    if role not in ROLES:
        raise ValueError(f"Invalid role: {role}")
    clean_name = name.strip()
    if not clean_name or len(clean_name) > 64:
        raise ValueError("Key name must be between 1 and 64 characters after stripping.")
    if expires_at is not None and expires_at <= _utcnow():
        raise ValueError("expires_at must be in the future")

    token, kid, secret = generate_token(TOKEN_PREFIX_API_KEY)
    api_key = ApiKey(
        kid=kid,
        secret_hash=_hash_secret(secret),
        name=clean_name,
        role=role,
        expires_at=expires_at,
        created_by_key_id=created_by_key_id,
    )
    db.session.add(api_key)
    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return api_key, token


def revoke_api_key(kid: str, actor_principal: Principal | None = None) -> ApiKey:
    """Revoke an API key by kid and cascade to its sessions.

    Raises:
        KeyError: if no such key exists.
        PermissionError: if the actor attempts to revoke their own key.
    """
    row = db.session.scalar(select(ApiKey).where(ApiKey.kid == kid))
    if row is None:
        raise KeyError(kid)

    if actor_principal is not None and actor_principal.api_key_id == row.id:
        raise PermissionError("Administrators cannot revoke the key backing their own session")

    if row.revoked_at is None:
        now = _utcnow()
        row.revoked_at = now
        for session in row.sessions:
            if session.revoked_at is None:
                session.revoked_at = now
        db.session.commit()

    return row


def create_auth_session(api_key: ApiKey, remote_addr: str | None = None) -> tuple[AuthSession, str]:
    """Mint a new session token bound to the given API key."""
    now = _utcnow()
    absolute_seconds = current_app.config["AUTH_SESSION_ABSOLUTE_LIFETIME"]
    token, kid, secret = generate_token(TOKEN_PREFIX_SESSION)
    session = AuthSession(
        kid=kid,
        secret_hash=_hash_secret(secret),
        api_key_id=api_key.id,
        created_at=now,
        last_seen_at=now,
        expires_at=now + datetime.timedelta(seconds=absolute_seconds),
    )
    db.session.add(session)
    db.session.commit()
    _log_event(
        "session_created",
        kid=session.kid,
        actor_key_id=api_key.id,
        remote_addr=remote_addr,
        detail=None,
    )
    return session, token


def revoke_auth_session(session: AuthSession) -> None:
    """Revoke a single session row."""
    if session.revoked_at is None:
        session.revoked_at = _utcnow()
        db.session.commit()


def create_recovery_key() -> tuple[RecoveryKey, str]:
    """Mint a single-use, short-lived recovery key, invalidating any prior live one."""
    now = _utcnow()
    lifetime = current_app.config["AUTH_RECOVERY_KEY_LIFETIME"]

    # Invalidate any outstanding unconsumed recovery key.
    prior = db.session.scalars(
        select(RecoveryKey).where(
            RecoveryKey.consumed_at.is_(None),
            RecoveryKey.expires_at > now,
        )
    ).all()
    for key in prior:
        key.consumed_at = now

    token, kid, secret = generate_token(TOKEN_PREFIX_RECOVERY)
    recovery_key = RecoveryKey(
        kid=kid,
        secret_hash=_hash_secret(secret),
        expires_at=now + datetime.timedelta(seconds=lifetime),
    )
    db.session.add(recovery_key)
    db.session.commit()
    _log_event(
        "recovery_issued",
        kid=recovery_key.kid,
        actor_key_id=None,
        remote_addr=None,
        detail=None,
    )
    return recovery_key, token


def claim_recovery_key(raw_token: str, name: str, remote_addr: str | None = None) -> tuple[ApiKey, str]:
    """Redeem a recovery key for a new Administrator API key.

    The operation is atomic: a guarded UPDATE prevents concurrent consumption.
    Any failure path leaves the recovery key unconsumed so typos do not burn it.
    """
    parsed = parse_token(raw_token)
    if parsed is None:
        raise ValueError("Invalid recovery key format")
    prefix, kid, secret = parsed
    if prefix != TOKEN_PREFIX_RECOVERY:
        raise ValueError("Not a recovery key")

    now = _utcnow()
    secret_hash = _hash_secret(secret)

    row = db.session.scalar(
        select(RecoveryKey).where(
            RecoveryKey.kid == kid,
            RecoveryKey.secret_hash == secret_hash,
            RecoveryKey.consumed_at.is_(None),
            RecoveryKey.expires_at > now,
        )
    )
    if row is None:
        raise ValueError("Recovery key not found or expired")

    try:
        # Guarded update: exactly one row must be consumed.
        from sqlalchemy import update

        result = db.session.execute(
            update(RecoveryKey)
            .where(RecoveryKey.id == row.id, RecoveryKey.consumed_at.is_(None))
            .values(consumed_at=now)
        )
        db.session.flush()  # flush to see rowcount without finalizing
        if result.rowcount != 1:
            db.session.rollback()
            raise ValueError("Recovery key already consumed")

        api_key, token = create_api_key(
            name=name,
            role=ROLE_ADMINISTRATOR,
            created_by_key_id=None,
            commit=False,
        )
        _log_event(
            "recovery_claimed",
            kid=row.kid,
            actor_key_id=api_key.id,
            remote_addr=remote_addr,
            detail=None,
        )
        db.session.commit()
        return api_key, token
    except Exception:
        db.session.rollback()
        raise


def _mask_token(token: str) -> str:
    """Return a developer/log-safe rendering of a token (never the full secret)."""
    if len(token) < 12:
        return "<short>"
    return token[:9] + "..."


# HTML escape helper for safe template rendering of user-controlled names.
safe_name = html.escape
