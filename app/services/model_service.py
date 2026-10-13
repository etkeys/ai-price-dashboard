"""Shared validation and persistence for AiModel scalar/modality updates.

Both the internal admin surface (``app/routes/admin.py``) and the public agent
API (``app/routes/api.py``) write the same ``AiModel`` columns and association
rows.  Housing that logic here means the public route never has to reach across
blueprints and both surfaces stay consistent on coercion, closed vocabularies,
prospective-row coherence and the write transaction.

The two surfaces deliberately differ in exactly the ways Erik ruled:

  - D-040: the public API accepts only strict JSON numeric types (no booleans,
    numeric strings, or fractional context); the admin surface keeps its
    legacy coercion (numeric strings, ``int()`` truncation of fractional
    context) *except* that boolean-to-number coercion is now rejected there
    too, on POST and PATCH alike.
  - D-041: the public API requires ``context_tokens`` only when the request
    actually changes ``context_type``; the admin surface keeps its
    always-require-the-pair rule.

The shared functions return ``(values, error_message)`` where ``error_message``
is a plain string the caller wraps in its own error response, so admin and API
never couple to each other's response helpers.
"""

import math

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.data.modalities import ALLOWED_MODALITIES as _ALLOWED_MODALITIES
from app.extensions import db
from app.models import (
    AiModel,
    AiModelInputModality,
    AiModelOutputModality,
    Modality,
)
from app.models.ai_model import DEFAULT_CONTEXT_TYPE
from app.services.auth_service import _utcnow

EDITABLE_FIELDS = (
    "price_in",
    "price_out",
    "context_tokens",
    "context_type",
    "pricing_unit",
    "input_content",
    "output_content",
)

REQUIRED_CREATE_FIELDS = (
    "price_in",
    "price_out",
    "context_tokens",
    "input_content",
    "output_content",
)

# Fields a caller may never set via PATCH; explicitly identified so the public
# route gives a clear "Cannot update field" instead of a generic unknown-field.
PROTECTED_FIELDS = frozenset(
    {"name", "hidden", "hidden_at", "is_hidden", "id", "created_at", "updated_at"}
)

ALLOWED_MODALITIES = frozenset(_ALLOWED_MODALITIES)


def validate_model_values(
    data: dict,
    *,
    require_all: bool = False,
    current: dict | None = None,
    strict: bool = False,
    transition_only: bool = False,
) -> tuple[dict | None, str | None]:
    """Validate a model-field payload.

    Returns ``(values, None)`` on success, where ``values`` holds only the keys
    present in ``data`` (converted and validated), or ``(None, error_message)``
    on failure.  ``strict`` selects the public API's strict JSON numeric rules
    (D-040); ``transition_only`` selects the public API's D-041 pairing rule.

    Shared semantics (D-037..D-039):
      - Key absence differs from explicit ``null``. ``price_in: null`` means
        "not applicable"; numeric ``0`` stays a distinct free-input price.
      - ``price_out`` must be finite and ``>= 0``; ``null`` is rejected.
      - ``context_type``/``pricing_unit`` are exact closed-vocabulary strings.
      - The *prospective complete row* must be coherent: ``tokens`` context
        requires ``context_tokens > 0``; ``image`` requires ``null``.
    """
    if require_all:
        missing = [f for f in REQUIRED_CREATE_FIELDS if f not in data]
        if missing:
            return None, "All model attributes are required"

    values: dict = {}
    for field in EDITABLE_FIELDS:
        if field not in data:
            continue
        values[field] = data[field]

    # --- numeric price / context ---
    if "price_in" in values:
        v = values["price_in"]
        if v is None:
            values["price_in"] = None  # explicitly "not applicable"
        elif strict:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                return None, "'price_in' must be a finite non-negative number"
            values["price_in"] = float(v)
        else:
            if isinstance(v, bool):
                return None, "Prices must be numbers and context_tokens must be an integer"
            try:
                values["price_in"] = float(v)
            except (TypeError, ValueError, OverflowError):
                return None, "Prices must be numbers and context_tokens must be an integer"

    if "price_out" in values:
        v = values["price_out"]
        if strict:
            if v is None:
                return None, "'price_out' is required"
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                return None, "'price_out' must be a finite non-negative number"
            values["price_out"] = float(v)
        else:
            if v is None or v == "":
                return None, "'price_out' is required"
            if isinstance(v, bool):
                return None, "Prices must be numbers and context_tokens must be an integer"
            try:
                values["price_out"] = float(v)
            except (TypeError, ValueError, OverflowError):
                return None, "Prices must be numbers and context_tokens must be an integer"

    if "context_tokens" in values:
        v = values["context_tokens"]
        if strict:
            if v is None:
                values["context_tokens"] = None  # valid only for image context
            elif isinstance(v, bool) or not isinstance(v, int):
                return None, "'context_tokens' must be a positive integer"
            else:
                values["context_tokens"] = v
        else:
            if isinstance(v, bool):
                return None, "Prices must be numbers and context_tokens must be an integer"
            if v is None or v == "":
                values["context_tokens"] = None  # valid only for image context
            else:
                try:
                    values["context_tokens"] = int(v)
                except (TypeError, ValueError, OverflowError):
                    return None, "Prices must be numbers and context_tokens must be an integer"

    if any(
        field in values
        and values[field] is not None
        and (not math.isfinite(values[field]) or values[field] < 0)
        for field in ("price_in", "price_out")
    ):
        return None, "Prices must be finite numbers >= 0"

    # --- closed vocabularies: exact string match, no coercion ---
    if "context_type" in values:
        ct = values["context_type"]
        if not isinstance(ct, str) or ct not in ("tokens", "image"):
            return None, "'context_type' must be 'tokens' or 'image'"
        values["context_type"] = ct
    if "pricing_unit" in values:
        pu = values["pricing_unit"]
        if not isinstance(pu, str) or pu not in ("million_tokens", "image"):
            return None, "'pricing_unit' must be 'million_tokens' or 'image'"
        values["pricing_unit"] = pu

    # --- atomic prospective-row coherence (ruling 3A) ---
    prospective = dict(current or {})
    prospective.update(values)
    result_context_type = prospective.get("context_type", DEFAULT_CONTEXT_TYPE)
    result_ctx = prospective.get("context_tokens")

    if "context_type" in values:
        if transition_only:
            # D-041: an unchanged context_type alone is a valid no-op; require
            # the pair only when the type actually changes.
            if values["context_type"] != (current or {}).get("context_type") and (
                "context_tokens" not in data
            ):
                return (
                    None,
                    "Changing 'context_type' requires 'context_tokens' in the same request",
                )
        else:
            if "context_tokens" not in data:
                return (
                    None,
                    "Changing 'context_type' requires 'context_tokens' in the same request",
                )

    if result_context_type == "image":
        if result_ctx is not None:
            return None, "'context_tokens' must be null for image context"
    elif result_ctx is None or result_ctx <= 0:
        return None, "'context_tokens' must be greater than zero for token context"

    for field in ("input_content", "output_content"):
        if field not in values:
            continue
        content = values[field]
        if not isinstance(content, list) or not content or any(
            not isinstance(v, str) for v in content
        ):
            return None, f"'{field}' must be a non-empty list of modality names"
        if len(set(content)) != len(content):
            return None, f"'{field}' contains duplicates"
        if not set(content).issubset(ALLOWED_MODALITIES):
            invalid = sorted(set(content) - ALLOWED_MODALITIES)[0]
            return None, f"'{field}' contains invalid modality: {invalid}"

    return values, None


def resolve_modality_rows(values: dict) -> tuple[dict[str, Modality] | None, str | None]:
    """Resolve submitted modality names to persisted ``Modality`` rows.

    Returns ``(rows, None)`` on success, ``(None, error_message)`` on failure.
    """
    names = set(values.get("input_content", []) + values.get("output_content", []))
    rows: dict[str, Modality] = {
        row.name: row
        for row in db.session.scalars(select(Modality).where(Modality.name.in_(names)))
    }
    missing = names - rows.keys()
    if missing:
        return None, f"Unknown modality: {sorted(missing)[0]}"
    return rows, None


def apply_model_update(
    model: AiModel, values: dict, modality_rows: dict[str, Modality] | None
) -> str | None:
    """Persist scalar and modality edits on ``model`` in one transaction.

    Returns ``None`` on success or an error message on ``IntegrityError``
    (after rolling back so no partial write survives).
    """
    try:
        for field in (
            "price_in",
            "price_out",
            "context_tokens",
            "context_type",
            "pricing_unit",
        ):
            if field in values:
                setattr(model, field, values[field])
        for field, association in (
            ("input_content", AiModelInputModality),
            ("output_content", AiModelOutputModality),
        ):
            if field in values:
                db.session.execute(
                    delete(association).where(association.ai_model_id == model.id)
                )
                for position, modality_name in enumerate(values[field]):
                    db.session.add(
                        association(
                            ai_model_id=model.id,
                            modality_id=modality_rows[modality_name].id,
                            position=position,
                        )
                    )
        # Bump updated_at explicitly so modality-only edits still tick the column.
        model.updated_at = _utcnow()
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return "Unable to update model"
    return None