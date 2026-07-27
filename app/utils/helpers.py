"""General-purpose helper functions."""

from typing import Any


def safe_get(mapping: dict[str, Any], key: str, default: Any = None) -> Any:
    """Return mapping[key] if it exists, otherwise default."""
    return mapping.get(key, default)


def format_price(value: float) -> str:
    """Format a price as a fixed two-decimal string."""
    return f"{value:.2f}"


def format_context(context_tokens: int) -> str:
    """Humanize a token count using K/M suffixes.

    Examples:
        1000000 -> "1M"
        1500000 -> "1.5M"
        200000  -> "200K"
        66000   -> "66K"
        500     -> "500"
    """
    if context_tokens >= 1_000_000:
        value = context_tokens / 1_000_000
        return f"{value:g}M"
    if context_tokens >= 1_000:
        return f"{context_tokens // 1_000}K"
    return str(context_tokens)
