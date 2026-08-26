"""output-only pricing and variable context types

Revision ID: a1f2b3c4d5e6
Revises: 453c7603f37a
Create Date: 2026-08-26 19:10:00.000000

D-037..D-039 (rulings 1A/2B/3A). Makes ``price_in`` nullable (``NULL`` = not
applicable; numeric 0 stays a free-input price), adds closed ``context_type``
(``tokens``/``image``) and ``pricing_unit`` (``million_tokens``/``image``)
columns, and makes ``context_tokens`` nullable with validity governed by
``context_type``. Existing rows are backfilled to the legacy token semantics
byte-for-byte: ``context_type='tokens'``, ``pricing_unit='million_tokens'``,
unchanged ``price_in``/``context_tokens`` values.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a1f2b3c4d5e6"
down_revision = "453c7603f37a"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("ai_models", schema=None) as batch_op:
        batch_op.alter_column("price_in", existing_type=sa.Float(), nullable=True)
        batch_op.alter_column("context_tokens", existing_type=sa.Integer(), nullable=True)
        batch_op.add_column(
            sa.Column("context_type", sa.String(16), nullable=False, server_default="tokens")
        )
        batch_op.add_column(
            sa.Column(
                "pricing_unit", sa.String(16), nullable=False, server_default="million_tokens"
            )
        )
        # Replace the legacy unconditional CHECKs with the null-aware and
        # context-type-conditional ones. SQLite batch mode rebuilds the table,
        # carrying the reflected constraints; drop the old, add the new.
        batch_op.drop_constraint("ck_ai_models_price_in_non_negative", type_="check")
        batch_op.drop_constraint("ck_ai_models_context_tokens_positive", type_="check")
        batch_op.create_check_constraint(
            "ck_ai_models_price_in_non_negative",
            "(price_in IS NULL) OR (price_in >= 0)",
        )
        batch_op.create_check_constraint(
            "ck_ai_models_context_type_valid",
            "context_type IN ('tokens', 'image')",
        )
        batch_op.create_check_constraint(
            "ck_ai_models_pricing_unit_valid",
            "pricing_unit IN ('million_tokens', 'image')",
        )
        batch_op.create_check_constraint(
            "ck_ai_models_context_tokens_valid",
            "(context_type = 'tokens' AND context_tokens IS NOT NULL"
            " AND context_tokens > 0)"
            " OR (context_type = 'image' AND context_tokens IS NULL)",
        )


def downgrade():
    """Restore the legacy schema.

    Downgrade is only meaningful when every row still satisfies the legacy
    non-null constraints. Image-context or output-only rows (``price_in`` NULL,
    ``context_type != 'tokens'``, or NULL ``context_tokens``) cannot round-trip
    losslessly; fail loudly rather than silently invent ``context_tokens = 1``,
    which would recreate the defect this feature removes (D-037 rationale).
    """
    conn = op.get_bind()
    bad = conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM ai_models"
            " WHERE price_in IS NULL OR context_type <> 'tokens'"
            " OR context_tokens IS NULL"
        )
    ).scalar()
    if bad:
        raise RuntimeError(
            "Cannot downgrade: %d row(s) use output-only/image-context features "
            "(price_in NULL, context_type != 'tokens', or context_tokens NULL). "
            "Normalize those rows to legacy token semantics before downgrading."
            % int(bad)
        )

    with op.batch_alter_table("ai_models", schema=None) as batch_op:
        batch_op.drop_constraint("ck_ai_models_context_tokens_valid", type_="check")
        batch_op.drop_constraint("ck_ai_models_pricing_unit_valid", type_="check")
        batch_op.drop_constraint("ck_ai_models_context_type_valid", type_="check")
        batch_op.drop_constraint("ck_ai_models_price_in_non_negative", type_="check")
        batch_op.drop_column("pricing_unit")
        batch_op.drop_column("context_type")
        batch_op.alter_column("context_tokens", existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column("price_in", existing_type=sa.Float(), nullable=False)
        batch_op.create_check_constraint(
            "ck_ai_models_price_in_non_negative", "price_in >= 0"
        )
        batch_op.create_check_constraint(
            "ck_ai_models_context_tokens_positive", "context_tokens > 0"
        )
