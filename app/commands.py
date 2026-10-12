"""Flask CLI commands for the ai-price-dashboard.

These are registered via ``app.cli.add_command`` in :func:`app.create_app` so that
``flask seed`` is available when ``run.py`` provides the application.
"""

import sys

from datetime import datetime as _datetime
import click
from sqlalchemy import func, select

from app.data.modalities import ALLOWED_MODALITIES
from app.data.sample_models import SAMPLE_MODELS
from app.extensions import db
from app.models import (
    AiModel,
    AiModelInputModality,
    AiModelOutputModality,
    ApiKey,
    AuthEvent,
    AuthSession,
    Modality,
    RecoveryKey,
)
from app.models.ai_model import DEFAULT_CONTEXT_TYPE, DEFAULT_PRICING_UNIT
from app.services.auth_service import (
    ROLE_ADMINISTRATOR,
    ROLE_UPDATER,
    _utcnow,
    claim_recovery_key,
    create_api_key,
    create_recovery_key,
    generate_token,
    revoke_api_key,
)


def register_commands(app):
    """Attach custom Flask CLI commands to the application."""
    app.cli.add_command(seed_command)
    app.cli.add_command(auth_command)


def seed_database(force: bool = False) -> tuple[bool, str]:
    """Seed the database with the sample model data.

    Returns a tuple of (succeeded, message). The command is idempotent: if the
    ``ai_models`` table already contains rows it returns success without
    inserting anything, so it is safe to run on every container startup.

    Args:
        force: When ``True``, delete all existing model rows before seeding.
            Intended for development resets only.

    """
    modality_map = _upsert_modalities()

    if force:
        _clear_models()

    current_count = db.session.scalar(select(func.count()).select_from(AiModel))
    if current_count and current_count > 0:
        return True, f"Database already seeded ({current_count} models); nothing to do."

    try:
        models_by_name: dict[str, AiModel] = {}
        for data in SAMPLE_MODELS:
            model = AiModel(
                name=data["name"],
                price_in=data["price_in"],
                price_out=data["price_out"],
                context_tokens=data.get("context_tokens"),
                context_type=data.get("context_type", DEFAULT_CONTEXT_TYPE),
                pricing_unit=data.get("pricing_unit", DEFAULT_PRICING_UNIT),
            )
            models_by_name[data["name"]] = model
            db.session.add(model)

        # Assign IDs before creating the association rows.
        db.session.flush()

        for data in SAMPLE_MODELS:
            model = models_by_name[data["name"]]
            for position, name in enumerate(data["input_content"]):
                db.session.add(
                    AiModelInputModality(
                        ai_model_id=model.id,
                        modality_id=modality_map[name].id,
                        position=position,
                    )
                )
            for position, name in enumerate(data["output_content"]):
                db.session.add(
                    AiModelOutputModality(
                        ai_model_id=model.id,
                        modality_id=modality_map[name].id,
                        position=position,
                    )
                )

        db.session.commit()
        return True, f"Seeded {len(SAMPLE_MODELS)} models."
    except Exception as exc:
        db.session.rollback()
        return False, f"Seeding failed: {exc}"


@click.command("seed")
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Delete existing model rows and re-seed (development only).",
)
def seed_command(force):
    """Flask CLI entry point for :func:`seed_database`."""
    succeeded, message = seed_database(force=force)
    click.echo(message, err=not succeeded)
    if not succeeded:
        sys.exit(1)


def _upsert_modalities() -> dict[str, Modality]:
    """Ensure the closed vocabulary exists and return a name-to-object map."""
    modality_map: dict[str, Modality] = {}
    for name in ALLOWED_MODALITIES:
        modality = db.session.scalar(select(Modality).where(Modality.name == name))
        if modality is None:
            modality = Modality(name=name)
            db.session.add(modality)
        modality_map[name] = modality
    db.session.commit()
    return modality_map


def _clear_models() -> None:
    """Remove all model rows. Association rows cascade automatically."""
    db.session.query(AiModel).delete()
    db.session.commit()


@click.group("auth")
def auth_command():
    """Authentication administration commands."""
    pass


@auth_command.command("bootstrap")
def auth_bootstrap():
    """Create the first Administrator key if none exists (idempotent)."""
    existing = db.session.scalar(
        select(func.count(ApiKey.id)).where(
            ApiKey.role == ROLE_ADMINISTRATOR,
            ApiKey.revoked_at.is_(None),
        )
    )
    if existing and existing > 0:
        click.echo("A non-revoked Administrator key already exists; nothing to do.")
        return

    api_key, token = create_api_key(name="bootstrap", role=ROLE_ADMINISTRATOR)
    click.echo("Bootstrap Administrator key created.")
    click.echo("TOKEN (shown once, copy it now):")
    click.echo(token)
    click.echo("Create a personal key and revoke this one immediately.")


@auth_command.command("create-key")
@click.option("--name", required=True, help="Human-meaningful name for the key.")
@click.option(
    "--role",
    required=True,
    type=click.Choice([ROLE_ADMINISTRATOR, ROLE_UPDATER], case_sensitive=False),
    help="Role for the key.",
)
@click.option(
    "--expires-at",
    default=None,
    help="ISO-8601 expiry timestamp (e.g. 2026-12-31T23:59:59).",
)
def auth_create_key(name, role, expires_at):
    """Create a new API key from the command line."""
    expiry = None
    if expires_at:
        try:
            expiry = _datetime.fromisoformat(expires_at)
        except ValueError:
            click.echo("Invalid ISO-8601 timestamp for --expires-at.", err=True)
            sys.exit(1)

    try:
        api_key, token = create_api_key(name=name, role=role.lower(), expires_at=expiry)
    except Exception as exc:
        click.echo(f"Failed to create key: {exc}", err=True)
        sys.exit(1)

    click.echo(f"Created {api_key.role} key '{api_key.name}' ({api_key.kid}).")
    click.echo("TOKEN (shown once):")
    click.echo(token)


@auth_command.command("list-keys")
def auth_list_keys():
    """List all API keys (metadata only, no secrets)."""
    rows = db.session.scalars(select(ApiKey).order_by(ApiKey.created_at.desc())).all()
    if not rows:
        click.echo("No API keys.")
        return

    creator_names = {k.id: k.name for k in rows}
    for row in rows:
        status = "active"
        if row.revoked_at is not None:
            status = "revoked"
        elif row.expires_at is not None and row.expires_at <= _utcnow():
            status = "expired"
        creator = creator_names.get(row.created_by_key_id, "-") if row.created_by_key_id else "-"
        click.echo(
            f"{row.kid:13} {row.role:13} {status:8} {row.name:20} created_by={creator}"
        )


@auth_command.command("revoke-key")
@click.argument("kid")
def auth_revoke_key(kid):
    """Revoke an API key by kid."""
    try:
        revoke_api_key(kid)
    except KeyError:
        click.echo(f"Key {kid} not found.", err=True)
        sys.exit(1)
    except PermissionError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)
    click.echo(f"Revoked key {kid}.")


@auth_command.command("recovery-key")
def auth_recovery_key():
    """Issue a single-use recovery key (container break-glass)."""
    recovery_key, token = create_recovery_key()
    click.echo("Recovery key issued (single use, 15 minutes):")
    click.echo(token)


@auth_command.command("reap-sessions")
def auth_reap_sessions():
    """Delete expired/revoked session rows (hygiene only, not required)."""
    now = _utcnow()
    result = db.session.execute(
        AuthSession.__table__.delete().where(
            (AuthSession.revoked_at.is_not(None)) | (AuthSession.expires_at < now)
        )
    )
    db.session.commit()
    click.echo(f"Reaped {result.rowcount} session row(s).")
