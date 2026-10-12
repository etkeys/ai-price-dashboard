"""General-purpose helper functions."""

from typing import Any

from app.models.ai_model import (
    CONTEXT_TYPES,
    PRICING_UNITS,
)


def safe_get(mapping: dict[str, Any], key: str, default: Any = None) -> Any:
    """Return mapping[key] if it exists, otherwise default."""
    return mapping.get(key, default)


def format_price(value: float) -> str:
    """Format a price as a fixed two-decimal string."""
    return f"{value:.2f}"


def _format_price_precise(value: float) -> str:
    """Format a price keeping meaningful precision for sub-cent unit prices.

    ``0.035`` must render as ``0.035`` (a per-image price), not ``0.04``, while
    whole/dollar prices keep the conventional cents form (``5.0`` -> ``5.00``).
    Renders up to 6 decimals, trims trailing zeros, and pads back to at least
    two decimal places.
    """
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    if "." in text:
        whole, frac = text.split(".", 1)
        if len(frac) < 2:
            text = f"{whole}.{frac}{'0' * (2 - len(frac))}"
    else:
        text = f"{text}.00"
    return text


_PRICING_SUFFIXES = {
    PRICING_UNITS.MILLION_TOKENS: "/1M tokens",
    PRICING_UNITS.IMAGE: "/image",
}


def render_price(value: float | None, pricing_unit: str) -> str:
    """Render a price cell with its billing unit.

    ``None`` means the input price is not applicable (e.g. an output-only image
    model) and renders ``N/A`` with no dollar sign. Numeric ``0`` remains a
    distinct free-input price and renders ``$0.00``. The suffix comes from the
    model's ``pricing_unit`` (D-037..D-039, ruling 1A/2B).
    """
    if value is None:
        return "N/A"
    suffix = _PRICING_SUFFIXES.get(pricing_unit, _PRICING_SUFFIXES[PRICING_UNITS.MILLION_TOKENS])
    return f"${_format_price_precise(value)} {suffix}"


def format_context(context_tokens: int | None, context_type: str | None = None) -> str:
    """Humanize a context window, making the context type visible.

    Image-context models have no numeric token notion and render as ``Image``.
    Token-context models keep the ``K``/``M`` humanization. ``context_type``
    defaults to token processing when omitted, preserving the legacy behaviour
    of the previous single-arg calls.

    Examples:
        (200000, 'tokens') -> "200K"
        (1000000, 'tokens') -> "1M"
        (None, 'image')     -> "Image"
        (200000)            -> "200K"
    """
    if context_type == CONTEXT_TYPES.IMAGE:
        return "Image"
    if context_tokens is None:
        # Token context should always carry a number; fall back gracefully.
        return "N/A"
    if context_tokens >= 1_000_000:
        value = context_tokens / 1_000_000
        return f"{value:g}M"
    if context_tokens >= 1_000:
        return f"{context_tokens // 1_000}K"
    return str(context_tokens)
