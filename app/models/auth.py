"""Authentication and authorization ORM models.

Schema (see \S8 of _research/2607301109_api-key-auth-design.md):

    api_keys
        id                  INTEGER PK autoincrement
        kid                 VARCHAR(12)  NOT NULL UNIQUE
        secret_hash         VARCHAR(64)  NOT NULL
        name                VARCHAR(64)  NOT NULL
        role                VARCHAR(16)  NOT NULL
        created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
        created_by_key_id   INTEGER      NULL FK -> api_keys.id
        last_used_at        DATETIME     NULL
        expires_at          DATETIME     NULL
        revoked_at          DATETIME     NULL

    auth_sessions
        id                  INTEGER PK autoincrement
        kid                 VARCHAR(12)  NOT NULL UNIQUE
        secret_hash         VARCHAR(64)  NOT NULL
        api_key_id          INTEGER      NOT NULL FK -> api_keys.id
        created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
        last_seen_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
        expires_at          DATETIME     NOT NULL
        revoked_at          DATETIME     NULL

    recovery_keys
        id                  INTEGER PK autoincrement
        kid                 VARCHAR(12)  NOT NULL UNIQUE
        secret_hash         VARCHAR(64)  NOT NULL
        created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
        expires_at          DATETIME     NOT NULL
        consumed_at         DATETIME     NULL

    auth_events
        id                  INTEGER PK autoincrement
        created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
        event               VARCHAR(32)  NOT NULL
        kid                 VARCHAR(12)  NULL
        actor_key_id        INTEGER      NULL FK -> api_keys.id
        remote_addr         VARCHAR(64)  NULL
        detail              VARCHAR(255) NULL
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

if TYPE_CHECKING:
    pass


ROLE_ADMINISTRATOR = "administrator"
ROLE_UPDATER = "updater"
ROLES = frozenset({ROLE_ADMINISTRATOR, ROLE_UPDATER})


class ApiKey(db.Model):
    """A long-lived API key used by agents or exchanged for a session."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kid: Mapped[str] = mapped_column(String(12), nullable=False, unique=True)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        db.DateTime, nullable=False, server_default=db.text("(CURRENT_TIMESTAMP)")
    )
    created_by_key_id: Mapped[int | None] = mapped_column(
        ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True
    )
    last_used_at: Mapped[datetime.datetime | None] = mapped_column(db.DateTime, nullable=True)
    expires_at: Mapped[datetime.datetime | None] = mapped_column(db.DateTime, nullable=True)
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(db.DateTime, nullable=True)

    created_by: Mapped["ApiKey"] = relationship(
        "ApiKey",
        remote_side="[ApiKey.id]",
        post_update=True,
    )
    sessions: Mapped[list["AuthSession"]] = relationship(
        "AuthSession",
        back_populates="api_key",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint("role IN ('administrator','updater')", name="ck_api_keys_role_valid"),
        CheckConstraint("length(kid) = 12", name="ck_api_keys_kid_length"),
        CheckConstraint(
            "length(secret_hash) = 64", name="ck_api_keys_secret_hash_length"
        ),
        Index(
            "uq_api_keys_active_name",
            "name",
            unique=True,
            sqlite_where=text("revoked_at IS NULL"),
        ),
    )

    def __repr__(self) -> str:
        return f"<ApiKey {self.kid!r} {self.name!r}>"


class AuthSession(db.Model):
    """A short-lived session token bound to a single browser tab."""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kid: Mapped[str] = mapped_column(String(12), nullable=False, unique=True)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    api_key_id: Mapped[int] = mapped_column(
        ForeignKey("api_keys.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        db.DateTime, nullable=False, server_default=db.text("(CURRENT_TIMESTAMP)")
    )
    last_seen_at: Mapped[datetime.datetime] = mapped_column(
        db.DateTime, nullable=False, server_default=db.text("(CURRENT_TIMESTAMP)")
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(db.DateTime, nullable=False)
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(db.DateTime, nullable=True)

    api_key: Mapped["ApiKey"] = relationship("ApiKey", back_populates="sessions")

    __table_args__ = (
        CheckConstraint("length(kid) = 12", name="ck_auth_sessions_kid_length"),
        CheckConstraint(
            "length(secret_hash) = 64", name="ck_auth_sessions_secret_hash_length"
        ),
        Index("ix_auth_sessions_api_key_id", "api_key_id"),
    )

    def __repr__(self) -> str:
        return f"<AuthSession {self.kid!r}>"


class RecoveryKey(db.Model):
    """Single-use, short-lived key used for container break-glass recovery."""

    __tablename__ = "recovery_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kid: Mapped[str] = mapped_column(String(12), nullable=False, unique=True)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        db.DateTime, nullable=False, server_default=db.text("(CURRENT_TIMESTAMP)")
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(db.DateTime, nullable=False)
    consumed_at: Mapped[datetime.datetime | None] = mapped_column(db.DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint("length(kid) = 12", name="ck_recovery_keys_kid_length"),
        CheckConstraint(
            "length(secret_hash) = 64", name="ck_recovery_keys_secret_hash_length"
        ),
    )

    def __repr__(self) -> str:
        return f"<RecoveryKey {self.kid!r}>"


class AuthEvent(db.Model):
    """Append-only audit trail for authentication lifecycle events."""

    __tablename__ = "auth_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        db.DateTime, nullable=False, server_default=db.text("(CURRENT_TIMESTAMP)")
    )
    event: Mapped[str] = mapped_column(String(32), nullable=False)
    kid: Mapped[str | None] = mapped_column(String(12), nullable=True)
    actor_key_id: Mapped[int | None] = mapped_column(
        ForeignKey("api_keys.id", ondelete="SET NULL"),
        nullable=True,
    )
    remote_addr: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (Index("ix_auth_events_created_at", "created_at"),)

    def __repr__(self) -> str:
        return f"<AuthEvent {self.event!r} {self.kid!r}>"
