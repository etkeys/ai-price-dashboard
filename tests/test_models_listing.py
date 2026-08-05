"""Tests for the AI models listing page."""

import pytest
from sqlalchemy import event, func, select

from app.data.sample_models import SAMPLE_MODELS
from app.extensions import db
from app.models import AiModel
from app.utils.helpers import format_context, format_price


ALLOWED_MODALITIES = {"Text", "Images", "Files", "Videos", "Audio"}


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        (1_000_000, "1M"),
        (1_500_000, "1.5M"),
        (200_000, "200K"),
        (66_000, "66K"),
        (500, "500"),
    ],
)
def test_format_context(tokens, expected):
    """format_context should humanize token counts with K/M suffixes."""
    assert format_context(tokens) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1.0, "1.00"),
        (0.09, "0.09"),
        (30.0, "30.00"),
        (2.5, "2.50"),
    ],
)
def test_format_price(value, expected):
    """format_price should render values with two decimals."""
    assert format_price(value) == expected


def test_index_page_renders_table(seeded_client):
    """The home page should render a model listing table."""
    response = seeded_client.get("/")
    assert response.status_code == 200
    html = response.data.decode()
    assert "<table" in html
    assert "anthropic/claude-opus-4.8" in html
    assert "1M" in html
    assert "$5.00" in html


def test_index_page_row_count(seeded_client):
    """Every sample model should produce one table row."""
    response = seeded_client.get("/")
    assert response.status_code == 200
    html = response.data.decode()
    row_count = html.count("<tr>") - 1  # subtract header row
    assert row_count == len(SAMPLE_MODELS)


def test_index_page_renders_modalities_alphabetically(seeded_client):
    """The home page renders modalities alphabetically, apart from persisted order."""
    response = seeded_client.get("/")
    assert response.status_code == 200
    html = response.data.decode()
    # google/gemini-3.5-flash is persisted as Text, Images, Videos, Files, Audio,
    # but the rendered input order is Audio, Files, Images, Text, Videos.
    assert "google/gemini-3.5-flash" in html
    assert "Audio, Files, Images, Text, Videos" in html
    assert "Text, Images, Videos, Files, Audio" not in html


def test_index_page_uses_bounded_query_count(seeded_client, app):
    """Rendering the listing page should not produce N+1 select queries."""
    query_count = 0

    def _count_queries(_conn, _cursor, _statement, _parameters, _context, _executemany):
        nonlocal query_count
        query_count += 1

    with app.app_context():
        event.listen(db.engine, "before_cursor_execute", _count_queries)
        try:
            seeded_client.get("/")
        finally:
            event.remove(db.engine, "before_cursor_execute", _count_queries)

    # One select for models + two selectin loads for input/output modalities.
    assert query_count == 3


def test_sample_models_shape():
    """Every sample record must have the required fields and valid values."""
    assert SAMPLE_MODELS
    names = set()
    for model in SAMPLE_MODELS:
        assert "name" in model
        assert "price_in" in model
        assert "price_out" in model
        assert "context_tokens" in model
        assert "input_content" in model
        assert "output_content" in model

        assert isinstance(model["price_in"], (int, float))
        assert isinstance(model["price_out"], (int, float))
        assert model["price_in"] >= 0
        assert model["price_out"] >= 0

        assert isinstance(model["context_tokens"], int)
        assert model["context_tokens"] > 0

        assert isinstance(model["input_content"], list)
        assert isinstance(model["output_content"], list)
        assert model["input_content"]
        assert model["output_content"]
        assert set(model["input_content"]).issubset(ALLOWED_MODALITIES)
        assert set(model["output_content"]).issubset(ALLOWED_MODALITIES)

        names.add(model["name"])

    assert len(names) == len(SAMPLE_MODELS), "model names must be unique"


def test_seed_inserts_expected_count(seeded_client):  # noqa: ARG001
    """The seed helper should populate one model row per sample."""
    with db.session.begin():
        count = db.session.scalar(select(func.count()).select_from(AiModel))
    assert count == len(SAMPLE_MODELS)


TILDE_MODEL = "~deepseek/deepseek-v4-flash-latest"


def _add_tilde_model(app) -> None:
    """Insert the operator's real tilde-prefixed model into the seeded app."""
    with app.app_context():
        db.session.add(
            AiModel(name=TILDE_MODEL, price_in=0.10, price_out=0.20, context_tokens=1_000_000)
        )
        db.session.commit()


def _assert_tilde_sorts_among_siblings(html: str) -> None:
    """Assert the tilde model renders between its deepseek siblings.

    Uses string *positions* rather than membership: a membership check passes
    under the old (un-sorted) behaviour, but a position comparison can only
    hold if the tilde-prefixed name actually sorts adjacent to the others.
    """
    pos_flash = html.index("deepseek/deepseek-v4-flash")
    pos_latest = html.index(TILDE_MODEL)
    pos_pro = html.index("deepseek/deepseek-v4-pro")
    assert pos_flash < pos_latest < pos_pro


def test_index_page_sorts_tilde_model_among_siblings(seeded_app):
    """'/' should place ~deepseek/...-latest between its deepseek siblings."""
    _add_tilde_model(seeded_app)
    response = seeded_app.test_client().get("/")
    assert response.status_code == 200
    _assert_tilde_sorts_among_siblings(response.data.decode())


def test_admin_models_page_sorts_tilde_model_among_siblings(seeded_app):
    """The admin manage page should order identically to '/'."""
    _add_tilde_model(seeded_app)
    response = seeded_app.test_client().get("/admin/models/manage")
    assert response.status_code == 200
    _assert_tilde_sorts_among_siblings(response.data.decode())


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # No tilde: no-op, keeps existing relative order.
        ("deepseek/deepseek-v4-pro", "deepseek/deepseek-v4-pro"),
        # The operator's real case: one leading tilde is removed.
        ("~deepseek/deepseek-v4-flash-latest", "deepseek/deepseek-v4-flash-latest"),
        # Multiple leading tildes all fold (lstrip, not removeprefix).
        ("~~qwen/qwen3.7-max", "qwen/qwen3.7-max"),
        # Interior / trailing tilde is preserved (leading-only strip).
        ("z-ai/glm-5.2-tilde~inside", "z-ai/glm-5.2-tilde~inside"),
        # Degenerate: a name that is only tildes sorts to the top.
        ("~", ""),
        ("~~", ""),
    ],
)
def test_sort_name_strips_only_leading_tildes(raw, expected):
    """The sort_name sort key folds leading '~' but leaves the rest intact."""
    assert AiModel(name=raw).sort_name == expected
