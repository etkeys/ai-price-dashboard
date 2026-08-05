"""ORM models for AI model pricing data.

Schema:
    ai_models
        id                INTEGER PK
        name              VARCHAR(128) NOT NULL UNIQUE
        price_in          FLOAT NOT NULL, CHECK (price_in >= 0)
        price_out         FLOAT NOT NULL, CHECK (price_out >= 0)
        context_tokens    INTEGER NOT NULL, CHECK (context_tokens > 0)
        created_at        DATETIME NOT NULL, DEFAULT CURRENT_TIMESTAMP
        updated_at        DATETIME NOT NULL, DEFAULT CURRENT_TIMESTAMP

    modalities
        id                INTEGER PK
        name              VARCHAR(32) NOT NULL UNIQUE

    ai_model_input_modalities
        ai_model_id       INTEGER FK -> ai_models.id ON DELETE CASCADE
        modality_id       INTEGER FK -> modalities.id ON DELETE RESTRICT
        position          INTEGER NOT NULL
        PK(ai_model_id, modality_id)

    ai_model_output_modalities
        (same structure as input association table)

The ``AiModel`` entity preserves the public attribute contract required by
``app/templates/index.html``: ``name``, ``price_in``, ``price_out``,
``context_tokens`` as mapped columns, and ``input_content`` / ``output_content``
as read-only ``list[str]`` properties over the ordered relationships.
"""

from __future__ import annotations

import datetime
from typing import List

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


class Modality(db.Model):
    """Closed vocabulary of content modalities."""

    __tablename__ = "modalities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)

    def __repr__(self) -> str:
        return f"<Modality {self.name!r}>"


class AiModelInputModality(db.Model):
    """Ordered many-to-many link between an AiModel and its input modalities."""

    __tablename__ = "ai_model_input_modalities"

    ai_model_id: Mapped[int] = mapped_column(
        ForeignKey("ai_models.id", ondelete="CASCADE"),
        primary_key=True,
    )
    modality_id: Mapped[int] = mapped_column(
        ForeignKey("modalities.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class AiModelOutputModality(db.Model):
    """Ordered many-to-many link between an AiModel and its output modalities."""

    __tablename__ = "ai_model_output_modalities"

    ai_model_id: Mapped[int] = mapped_column(
        ForeignKey("ai_models.id", ondelete="CASCADE"),
        primary_key=True,
    )
    modality_id: Mapped[int] = mapped_column(
        ForeignKey("modalities.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class AiModel(db.Model):
    """An AI model entry with pricing and modality metadata."""

    __tablename__ = "ai_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True, index=True
    )
    price_in: Mapped[float] = mapped_column(
        db.Float,
        nullable=False,
    )
    price_out: Mapped[float] = mapped_column(
        db.Float,
        nullable=False,
    )
    context_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        db.DateTime,
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        db.DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships load eagerly via selectin to avoid N+1 on the listing page.
    input_modalities: Mapped[List[Modality]] = relationship(
        Modality,
        secondary=AiModelInputModality.__tablename__,
        backref="input_models",
        lazy="selectin",
        order_by=AiModelInputModality.position.asc(),
        passive_deletes=True,
    )
    output_modalities: Mapped[List[Modality]] = relationship(
        Modality,
        secondary=AiModelOutputModality.__tablename__,
        backref="output_models",
        lazy="selectin",
        order_by=AiModelOutputModality.position.asc(),
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint("price_in >= 0", name="ck_ai_models_price_in_non_negative"),
        CheckConstraint("price_out >= 0", name="ck_ai_models_price_out_non_negative"),
        CheckConstraint("context_tokens > 0", name="ck_ai_models_context_tokens_positive"),
    )

    @property
    def input_content(self) -> list[str]:
        """Input modalities as an ordered list of names."""
        return [m.name for m in self.input_modalities]

    @property
    def output_content(self) -> list[str]:
        """Output modalities as an ordered list of names."""
        return [m.name for m in self.output_modalities]

    @hybrid_property
    def sort_name(self) -> str:
        """Display-order key with leading '~' prefixes ignored.

        OpenRouter publishes aliases like ``~deepseek/deepseek-v4-flash-latest``;
        the leading tilde must not exile such names to the end of a sorted
        listing. ``lstrip`` (not ``removeprefix``) strips *every* leading tilde,
        matching the SQL ``ltrim`` expression below.
        """
        return self.name.lstrip("~")

    @sort_name.inplace.expression
    @classmethod
    def _sort_name_expression(cls):
        """SQL expression mirroring :attr:`sort_name` for ``ORDER BY``."""
        return func.ltrim(cls.name, "~")

    def __repr__(self) -> str:
        return f"<AiModel {self.name!r}>"
