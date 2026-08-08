"""Canonical modality vocabulary for the AI Price Dashboard.

This is the single source of truth for the closed set of modalities that can
be assigned to a model (D-027). The ordering is preserved deliberately: it is
the seed insertion order from the original ``app/commands.py`` literal, and it
determines existing ``modalities.id`` values on fresh installs. Re-ordering
would renumber ids for no benefit.
"""

ALLOWED_MODALITIES: tuple[str, ...] = ("Text", "Images", "Files", "Videos", "Audio")