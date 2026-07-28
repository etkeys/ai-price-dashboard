"""Flask CLI commands for the ai-price-dashboard.

These are registered via ``app.cli.add_command`` in :func:`app.create_app` so that
``flask seed`` is available when ``run.py`` provides the application.
"""

import sys

import click
from sqlalchemy import func, select

from app.data.sample_models import SAMPLE_MODELS
from app.extensions import db
from app.models import AiModel, AiModelInputModality, AiModelOutputModality, Modality


ALLOWED_MODALITIES = ["Text", "Images", "Files", "Videos", "Audio"]


def register_commands(app):
    """Attach custom Flask CLI commands to the application."""
    app.cli.add_command(seed_command)


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
                context_tokens=data["context_tokens"],
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
