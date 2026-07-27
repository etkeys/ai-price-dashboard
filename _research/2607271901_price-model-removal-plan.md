# Price Model Removal — Research Findings and Removal Plan

Task: t_8c3c77f0 (research) → t_0665c6e5 (implement, @dale) → t_f9e261e5 (review, @kova)
Author: chip
Date: 2026-07-27
Repo: /var/local/hermes-git/ai-price-dashboard @ main (4e21f89, clean)

---

## 1. Summary

`Price` is a leftover scaffold model from the initial project skeleton. It is
**not used by any application code path** — no route, service, template, CLI
command, or fixture reads or writes it. Its only consumers are its own module,
the models package `__init__`, the app factory's blanket
`from app import models` side-effect import, and one dedicated test module that
exists solely to assert the model registers itself.

There are **no migration scripts** in the repo (`flask db init` was never run),
so no Alembic revision is required. Removal is a pure code deletion with a
small factory cleanup.

Verified: with the deletions below applied to a pristine `git archive` of HEAD,
the suite goes 32 → 30 passing (the 2 removed tests are the `test_models.py`
pair), `/` returns 200, `/health` returns 200, and `db.create_all()` produces an
empty table list without error.

---

## 2. Inventory — every reference to `Price`

| # | Location | Nature | Action |
|---|----------|--------|--------|
| 1 | `app/models/price.py` (whole file, 19 lines) | Model definition, `__tablename__ = "prices"` | Delete file |
| 2 | `app/models/__init__.py:3` | `from app.models.price import Price` | Delete file (see §4) |
| 3 | `app/models/__init__.py:5` | `__all__ = ["Price"]` | Delete file (see §4) |
| 4 | `app/__init__.py:20-21` | Comment + `from app import models  # noqa: F401` side-effect import | Remove both lines |
| 5 | `tests/test_models.py` (whole file, 21 lines) | Two tests asserting `prices` in metadata / created by `create_all()` | Delete file |
| 6 | `migrations/README.txt:5` | Prose: "Migrations are generated from the SQLAlchemy models in `app/models/`" | Update prose (see §4) |
| 7 | `README.md:38` | Project-structure bullet: "`models/` — SQLAlchemy data models" | Remove bullet if package is deleted |

### Confirmed NON-references (do not touch)

These matched a naive `grep -i price` but have nothing to do with the model:

- `app/services/price_service.py` — `PriceService` / `PriceServiceError`. Pure
  placeholder returning a dict of `Decimal`; **imports nothing from
  `app.models`** and is itself imported by nothing. Dead, but out of scope —
  see §6.
- `app/utils/helpers.py:11` — `format_price()`, a Jinja global registered in the
  factory and used by `templates/index.html` for the sample-model table. **In
  active use. Keep.**
- `app/data/sample_models.py` / `app/routes/main.py` — the `/` listing is driven
  entirely by the static `SAMPLE_MODELS` list, never by the ORM.
- `app/templates/*.html`, `app/static/js/dashboard.js`, `pyproject.toml`,
  `docker-compose.yml`, `README.md` title, `requirements.txt` — all "AI Price
  Dashboard" branding / `Price In`, `Price Out` column headers.
- `ai_price_dashboard.egg-info/SOURCES.txt` — build artifact, not tracked by git
  (`git ls-files` confirms). Regenerates itself. Do not hand-edit.

---

## 3. Database / migration impact

- `migrations/` contains **only** `README.txt`. There is no `env.py`, no
  `alembic.ini`, no `versions/` directory. Flask-Migrate is installed and
  `migrate.init_app()` is called, but the migration environment has never been
  initialized.
- **No Alembic revision is needed.** There is no baseline revision that includes
  the `prices` table, so there is nothing to downgrade from.
- The `prices` table only ever materializes at runtime via `db.create_all()`
  (tests/conftest.py, in-memory SQLite) or manually. Nothing in the repo runs
  `create_all()` at app startup.
- **Deployed-instance caveat:** `docker-compose.yml` persists
  `sqlite:////data/app.db` on the `app-data` named volume. If anyone ever ran
  `create_all()` against a live container, that volume holds an orphaned empty
  `prices` table. It is harmless — SQLAlchemy will simply ignore an unmapped
  table. Dropping it is optional housekeeping, **not** part of this change, and
  must not be done without operator approval.

---

## 4. Decision: delete the `app/models/` package or keep it empty?

Two viable shapes. **Recommendation: Option A (delete the package).**

**Option A — delete `app/models/` entirely (RECOMMENDED)**
- Delete `app/models/price.py` and `app/models/__init__.py` (the directory goes
  with them).
- Remove the `from app import models  # noqa: F401` line and its comment from
  `app/__init__.py`.
- Rationale: `Price` is the only model. An empty package imported purely for a
  side effect that no longer happens is exactly the dead code @kova's review
  brief calls out. The package is trivially re-created the day a real model
  lands, and the factory import line is one line to re-add.
- Verified working (probe B): 30/30 pass, `/` 200, `/health` 200,
  `create_all()` → `[]`.

**Option B — keep the package as an empty placeholder**
- Keep `app/models/__init__.py` reduced to a docstring + `__all__: list[str] = []`,
  keep the factory import.
- Rationale: preserves the documented project layout and the "models are
  auto-registered" hook for the next model.
- Also verified working (probe A): 30/30 pass, `create_all()` → `[]`.

If @dale takes Option A, `README.md:38` must lose the `models/` bullet and
`migrations/README.txt:5` should be reworded to drop the `app/models/` path
reference (e.g. "Migrations are generated from the SQLAlchemy models registered
on `db.metadata`."). If Option B is chosen instead, both docs stay as-is.

---

## 5. Removal plan for @dale (t_0665c6e5)

Execute in this order. Option A assumed.

1. `git rm app/models/price.py app/models/__init__.py tests/test_models.py`
2. Edit `app/__init__.py` — delete these two lines (currently 20-21) and the
   blank line that follows them:
   ```
   # Register SQLAlchemy models so metadata is populated for migrations.
   from app import models  # noqa: F401
   ```
   Leave `db.init_app(app)` and `migrate.init_app(app, db)` untouched — the
   ordering between them no longer matters once the import is gone.
3. Edit `README.md` — remove the `  - models/ — SQLAlchemy data models` bullet
   from the Project Structure list (line 38).
4. Edit `migrations/README.txt` — reword line 5 so it no longer points at
   `app/models/`.
5. Purge stale bytecode so a leftover `app/models/__pycache__/price.cpython-311.pyc`
   cannot mask an import error:
   `find . -path ./.venv -prune -o -name __pycache__ -type d -print -exec rm -rf {} +`
   (destructive-ish — confirm with the operator if your policy requires it; the
   safe alternative is `python -B -m pytest`.)
6. Verify, all four must pass:
   - `.venv/bin/python -m pytest -q` → expect **30 passed** (was 32).
   - `.venv/bin/python -c "from app import create_app; create_app('testing')"` → no error.
   - `.venv/bin/ai-price-dashboard routes` → lists `main.index` and `main.health`.
   - `grep -rnE "\bPrice\b" --include="*.py" app tests run.py | grep -v __pycache__`
     → the only surviving hits are `PriceService` / `PriceServiceError` in
     `app/services/price_service.py`. Note `\bPrice\b` does **not** match
     `PriceService` (no word boundary after "Price"), so a truly clean tree
     returns zero lines here.

**Do NOT do in this ticket:**
- Do not remove `flask_sqlalchemy` / `flask_migrate` from `pyproject.toml` or
  `requirements.txt`. `db` and `migrate` remain wired into the factory and
  `tests/conftest.py` still calls `db.create_all()` / `db.drop_all()`.
- Do not touch `app/services/price_service.py`, `format_price()`, the sample-data
  listing, or any "Price" branding.
- Do not drop tables on any deployed volume.

---

## 6. Follow-on observations (out of scope — for @suki to triage, not for @dale)

1. **`app/services/price_service.py` is now unambiguously dead.** `PriceService`
   is imported by nothing, tested by nothing, and returns a hardcoded
   `Decimal("0.00")`. It was scaffolded alongside `Price`. A separate removal
   ticket is warranted; folding it into this one would exceed the ticket's
   stated scope.
2. **Zero models means SQLAlchemy + Flask-Migrate are pure overhead.** After
   this change the only thing `db` does is let `conftest.py` create and drop an
   empty schema. Ripping out the ORM would shed two runtime dependencies and
   the `migrations/` directory — but it is a real architectural decision (does
   this app ever persist anything?) and needs an operator call, not a drive-by.
   Flagging, not recommending.
3. **`app/data/sample_models.py` is the de-facto data layer.** If persistence is
   ever wanted, the replacement model belongs at `app/models/model_price.py`
   shaped like the 6-field `SAMPLE_MODELS` record, not like the old `Price`
   (symbol/price/currency/source) which modelled a completely different domain.

---

## 7. Acceptance criteria for @kova (t_f9e261e5)

- [ ] `app/models/price.py` and `tests/test_models.py` no longer exist in the tree.
- [ ] Per §4, either `app/models/` is gone **and** the factory's `from app import models`
      line is gone, or the package is an empty placeholder **and** the import remains —
      not a mismatched half of either.
- [ ] `grep -rnE "\bPrice\b" --include="*.py" app tests run.py` returns zero hits.
      (`PriceService` / `PriceServiceError` in `app/services/price_service.py` do not
      match this pattern and are intentionally left in place — see §6.1.)
- [ ] No orphaned `.pyc` for the deleted modules under `app/models/__pycache__/`.
- [ ] `.venv/bin/python -m pytest -q` → 30 passed, 0 failed, 0 errors.
- [ ] `/` returns 200 and still renders all 22 sample models; `/health` returns
      `{"status": "ok"}` with 200.
- [ ] `README.md` and `migrations/README.txt` are consistent with the chosen option.
- [ ] `flask_sqlalchemy` / `flask_migrate` still declared in `pyproject.toml` and
      `requirements.txt`; `conftest.py` fixtures untouched and working.
- [ ] No migration files added (none are needed).
