# Spec: Persistent SQLite Storage — Integration Approach & Database Schema

Task: t_68d7e9a4 (chip). Parent feature: t_e23d1f1a — "Store data in persistent
sqlite database. Existing sample data can be used as seed data for new installs."

Downstream: t_90242caa (dale — implementation), then t_0500f64e (kova — QA).

Supersedes the "no DB, sample data only" decision recorded in
`_research/2607251644_models-listing-spec.md` §1.1 / §6. That spec deliberately
deferred persistence; this card is the deferral coming due. Everything else in
that spec (record shape, formatting helpers, table UI, units) remains binding and
is preserved verbatim by the design below.

---

## 0. Objective and constraints

Objective: the models listing served at `/` reads from a persistent SQLite
database instead of an in-process Python list, and a brand-new install ends up
with the 22 sample records already present without any manual data entry.

Hard constraints discovered in the repo:

1. **No new dependencies.** `Flask-SQLAlchemy>=3.1.0` and `Flask-Migrate>=4.0.0`
   are already declared in `pyproject.toml:12-18` and `requirements.txt:7-11`,
   and instantiated in `app/extensions.py:11-12` and bound in
   `app/__init__.py:16-19`. The wiring exists and is currently unused — this card
   consumes it. Nothing needs to be added to either manifest.
2. **The template must not change.** `app/templates/index.html:24-29` reads
   `model.name`, `model.price_in`, `model.price_out`, `model.context_tokens`,
   `model.input_content`, `model.output_content` and passes the numerics through
   `format_price` / `format_context` (`app/utils/helpers.py:11-31`). The ORM
   entity MUST expose exactly those six attribute names with exactly those
   Python types (`str`, `float`, `float`, `int`, `list[str]`, `list[str]`).
   Achieving this makes `index.html`, `style.css`, `helpers.py` and the
   `format_*` unit tests a no-op for this card. Treat it as an acceptance
   criterion, not a nice-to-have.
3. **`/health` stays database-free.** `app/routes/main.py:16-19` is contractually
   shallow per `README.md:46-58`. Do not add a DB probe to it.
4. **Container persistence is already provisioned.** `docker-compose.yml:17-19`
   sets `DATABASE_URL=sqlite:////data/app.db` against the `app-data` named
   volume, and `Dockerfile:29` creates `/data` owned by `appuser`. The runtime
   storage story is done; only schema creation and seeding are missing.
5. **`app/data/sample_models.py` is the seed source of truth.** It is already
   shape-validated by `tests/test_models_listing.py:61-90`. Do not re-transcribe
   the data into JSON/SQL/CSV — a second copy is a second thing to drift.

Verified locally in `.venv` (Python 3.11.15): SQLite library 3.53.1, SQLAlchemy
2.0.51, Flask-SQLAlchemy 3.1.1, Flask 3.1.3. The `json1` extension is present,
so a JSON-column design would have been viable — see §3.4 for why it is not
chosen.

---

## 1. Library and integration approach

### 1.1 Use Flask-SQLAlchemy 3.1 declarative models — not raw `sqlite3`

Rationale:

- Already a declared dependency, already initialized against the app, already
  configured (`app/config.py:17-18` reads `DATABASE_URL`, defaulting to
  `sqlite:///app.db`; `TestingConfig` at `app/config.py:50` pins
  `sqlite:///:memory:`).
- Flask-SQLAlchemy 3.x resolves a **relative** SQLite path against
  `app.instance_path` and creates that directory for you. So local development
  lands the file at `<repo>/instance/app.db`, which `.gitignore:33-34` already
  ignores (`instance/`, `*.db`). No gitignore change needed. Dale should confirm
  this path at runtime rather than assume the repo root.
- The four-slash absolute form in compose (`sqlite:////data/app.db`) bypasses
  instance-path resolution and points at the volume. Already correct.

  Verified in this repo: `create_app("development")` reports
  `instance_path=/var/local/hermes-git/ai-price-dashboard/instance` and resolves
  `sqlite:///app.db` to `sqlite:////var/local/hermes-git/ai-price-dashboard/instance/app.db`.
- Raw `sqlite3` would mean hand-rolling connection lifecycle per request,
  parameterization discipline, and row→dict mapping, while leaving two declared
  dependencies dead in the manifest. Rejected.

### 1.2 Schema DDL is owned by Alembic (Flask-Migrate), not `db.create_all()`

This is the load-bearing decision of this card, so the reasoning is explicit.

`db.create_all()` inside `create_app()` is the tempting shortcut. Reject it:

- **Multi-worker race.** `Dockerfile:42` runs `gunicorn --workers 2`. Two
  workers importing `run.py` concurrently both execute the factory, so both
  attempt DDL and (with seeding attached) both attempt inserts. SQLite will
  serialize with locking, but the seed-if-empty check becomes a genuine race:
  both read count()==0, both insert, and you get 44 rows or an
  IntegrityError-on-startup depending on timing.
- **No upgrade path.** `create_all()` only creates missing tables. It never
  alters an existing one. The first schema change after go-live silently does
  nothing and the app fails at query time against a stale table.
- **Provenance conflict.** If `create_all()` builds the schema now, the DB has no
  `alembic_version` row. A later `flask db upgrade` will try to re-create tables
  that already exist and fail. Recovering means hand-stamping the version — the
  exact mess `migrations/README.txt` was written to avoid.
- The repo has already declared the intent: `migrations/README.txt:3` says the
  directory "will contain Alembic/Flask-Migrate migration scripts once
  `flask db init` has been run." This card is when that happens.

So: **schema is created and evolved exclusively by `flask db upgrade`**, run as
an explicit, single-process step before the server starts. `create_app()`
performs no DDL and no writes. Startup stays side-effect free, which also keeps
`tests/test_config.py:35-39` (production factory raising on missing SECRET_KEY)
and `app/cli.py:23` (`routes` command builds an app) free of database coupling.

### 1.3 Bootstrap sequencing

Three entry paths exist and each needs a defined bootstrap:

| Path | Bootstrap |
|------|-----------|
| Container (`gunicorn`, `Dockerfile:42`) | New `docker-entrypoint.sh` runs `flask db upgrade` then `flask seed`, then `exec`s gunicorn. Single process, before any fork — no race. |
| Local dev (`python run.py`, `README.md:24-27`) | Documented two-command prelude: `flask --app run:app db upgrade` then `flask --app run:app seed`. Explicit beats magic. |
| Tests (`tests/conftest.py:14-18`) | Keeps `db.create_all()` — this is the one legitimate `create_all()` use. Tests build a schema from live metadata against `:memory:`; they are not an install. |

Note the tension in the last row: tests bypass Alembic, so a migration script
that drifts from the models will not be caught by the suite. Accept it for now
(it is the standard trade-off) and mitigate with the drift check in §6, AC-11.

---

## 2. Database schema

Four tables. Names follow the plural convention established by the removed
`Price` model (`__tablename__ = "prices"`, see `git show e112483~1:app/models/price.py`).

### 2.1 `ai_models`

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | INTEGER | PK, autoincrement | Synthetic surrogate key. The listing spec deliberately omitted an id because there was no DB; with association tables there now must be one. |
| `name` | VARCHAR(128) | NOT NULL, UNIQUE, indexed | `vendor/model-slug`. The natural key; uniqueness enforced in the DB, which also makes the seed idempotency check cheap. Longest current value is 34 chars (`google/gemini-3.1-flash-lite-image`); 128 is ample headroom. |
| `price_in` | FLOAT | NOT NULL, `CHECK (price_in >= 0)` | USD per 1M input tokens. |
| `price_out` | FLOAT | NOT NULL, `CHECK (price_out >= 0)` | USD per 1M output tokens. |
| `context_tokens` | INTEGER | NOT NULL, `CHECK (context_tokens > 0)` | Raw token count, never the display string. |
| `created_at` | DATETIME | NOT NULL, server default `now()` | Row provenance. |
| `updated_at` | DATETIME | NOT NULL, server default `now()`, `onupdate=now()` | Cheap groundwork for "price last changed" without committing to history tables. |

The three CHECK constraints mirror the invariants already asserted in
`tests/test_models_listing.py:75-79`. Push them into the schema so the DB, not
just the test suite, is the guardian.

**Why FLOAT and not NUMERIC/DECIMAL.** SQLite has no native decimal type;
SQLAlchemy's `Numeric` on SQLite stores a float anyway and emits a
loss-of-precision warning, while returning `Decimal` objects. Returning
`Decimal` would break `format_price(value: float)` at `app/utils/helpers.py:11`
and the `isinstance(model["price_in"], (int, float))` assertions. Values are
2–4 significant decimals of a per-million-token rate used only for display, so
binary float error is orders of magnitude below the rounding already applied by
`f"{value:.2f}"`. Decision: `FLOAT`. Documented caveat for a future cost
calculator: convert to `Decimal` at the arithmetic boundary, not in storage.

Default ordering: `ORDER BY name ASC`, which reproduces the current mockup order
(`SAMPLE_MODELS` is already alphabetical) so the page is byte-identical
pre/post change.

### 2.2 `modalities`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | INTEGER | PK, autoincrement |
| `name` | VARCHAR(32) | NOT NULL, UNIQUE |

A closed vocabulary lookup table: `Text`, `Images`, `Files`, `Videos`, `Audio`
— exactly the set documented at `app/data/sample_models.py:15` and enforced by
`ALLOWED_MODALITIES` in `tests/test_models_listing.py:9`. Seeded before the
model rows.

### 2.3 `ai_model_input_modalities` and `ai_model_output_modalities`

Two structurally identical association tables:

| Column | Type | Constraints |
|--------|------|-------------|
| `ai_model_id` | INTEGER | PK part, FK → `ai_models.id`, `ON DELETE CASCADE` |
| `modality_id` | INTEGER | PK part, FK → `modalities.id`, `ON DELETE RESTRICT` |
| `position` | INTEGER | NOT NULL |

Composite primary key `(ai_model_id, modality_id)` — a model cannot list the same
modality twice in one direction.

`position` preserves the per-row modality ordering that the listing spec requires
("Preserve mockup ordering per row", `_research/2607251644_models-listing-spec.md:84`).
Note `google/gemini-3.5-flash` orders its inputs `Text, Images, Videos, Files, Audio`
while its siblings use `Text, Images, Files, Videos, Audio` — that difference is in
the mockup and must survive the round-trip, which is precisely what `position`
buys. Relationships load with `order_by=position`.

**Two tables instead of one with a `direction` discriminator.** A single
association table would need `and_()`-qualified `primaryjoin`/`secondaryjoin`
expressions on both relationships to filter by direction. Two plain
`secondary=` relationships are simpler, harder to get wrong, and the duplication
is three column definitions.

**`ON DELETE CASCADE` requires `PRAGMA foreign_keys=ON`,** which SQLite disables
per-connection by default. Register a `connect` event listener that issues it, or
accept that FK enforcement is inert. See §5.2 — this is the single most commonly
missed item in SQLite+SQLAlchemy work and Kova should verify it explicitly.

### 2.4 Entity relationship

```
modalities 1 ──< ai_model_input_modalities  >── 1 ai_models
modalities 1 ──< ai_model_output_modalities >── 1 ai_models
```

### 2.5 Preserving the template contract

`AiModel` exposes `name`, `price_in`, `price_out`, `context_tokens` as mapped
columns, and the two modality lists as **read-only properties** over the ordered
relationships:

```
input_content  -> [m.name for m in self.input_modalities]    # list[str]
output_content -> [m.name for m in self.output_modalities]   # list[str]
```

With those two properties, `app/templates/index.html` and
`app/utils/helpers.py` need zero edits. Jinja's `model.input_content | join(', ')`
resolves against the property identically to the old dict key.

**N+1 warning.** Naively iterating 22 rows triggers 44 extra SELECTs. The query
in the route MUST eager-load both relationships:
`select(AiModel).options(selectinload(...), selectinload(...)).order_by(AiModel.name)`
— three queries total. Alternatively declare `lazy="selectin"` on the
relationships so the default load path is safe. Prefer the relationship-level
default; it cannot be forgotten at a future second call site.

---

## 3. Seeding

### 3.1 Mechanism: an idempotent Flask CLI command

Add `app/commands.py` exposing `register_commands(app)`, called from
`create_app()`. Registering via `app.cli.add_command(...)` keeps it separate from
`app/cli.py`, which is the argparse-based `ai-price-dashboard` console script
(`pyproject.toml:27`) and should not grow a DB dependency.

Commands:

- **`flask seed`** — the install-time seed. Algorithm:
  1. Upsert the modality vocabulary: for each of the five names, insert if absent.
     Do this first and unconditionally so the lookup table self-heals.
  2. Guard: `if db.session.scalar(select(func.count()).select_from(AiModel)) > 0:`
     print `"Database already seeded (N models); nothing to do."` and return
     **exit code 0**. Non-zero would abort the container entrypoint on every
     restart after the first.
  3. Otherwise iterate `SAMPLE_MODELS`, construct `AiModel` rows, resolve
     modality names to the vocabulary objects, assign `position` from list index.
  4. Single `db.session.commit()` for the whole batch. On exception:
     `db.session.rollback()`, print the error to stderr, return exit code 1 — a
     partially seeded database is worse than an empty one that fails loudly.
  5. Print `"Seeded N models."` on success.

- **`flask seed --force`** (optional, dev convenience) — deletes all `ai_models`
  rows and re-seeds. Must be opt-in, never invoked by the entrypoint. If Dale
  judges this scope creep, drop it; it is not an acceptance criterion.

**Emptiness, not a marker table, as the "new install" signal.** A
`schema_seeded` flag table would be more precise but adds a table to explain.
`COUNT(ai_models) == 0` is unambiguous for this app: there is no legitimate state
where the app is in service with zero models. Recorded as a deliberate trade-off:
if an operator deletes all rows on purpose, the next restart repopulates them.

### 3.2 Where the seed data comes from

`from app.data.sample_models import SAMPLE_MODELS`. That module stays exactly as
it is — pure data, already validated by `tests/test_models_listing.py:61-90`.
The seed command is the only consumer after this change; `app/routes/main.py:5`
drops its import.

Do **not** convert it to JSON/YAML/SQL. A Python module is import-time syntax
checked, needs no file IO or packaging-data rules, and is already covered by
tests. Its docstring (`app/data/sample_models.py:1-16`) should gain one line
noting it is now seed data rather than the live source.

### 3.3 Migration file contents

`flask db migrate -m "Add ai_models, modalities and modality association tables"`
generates the DDL. Review the autogenerated script before committing —
Alembic's SQLite support renders CHECK constraints and named FKs inconsistently.

**Keep data out of the migration.** Vocabulary and sample rows belong in
`flask seed`, not in an Alembic `op.bulk_insert`. Mixing DDL and seed data makes
the migration untestable in isolation and couples schema history to demo content.

### 3.4 Rejected schema alternatives

| Alternative | Why rejected |
|---|---|
| Modalities as a JSON column (`db.JSON`, list[str]) | Works — `json1` is available and it is ~40 fewer lines. But the mockup's per-column filter icons (`_research/2607251644_models-listing-spec.md:29-32`) make modality filtering the next likely card, and `json_each` filtering is clumsier than a join. It also gives up any vocabulary enforcement: a typo'd `"Imags"` is silently valid. For a *comparison* dashboard, the queryable shape wins. |
| Modalities as a comma-delimited string | Same objections, plus parsing on read. No. |
| Single association table with a `direction` discriminator | Forces `and_()`-qualified `primaryjoin`/`secondaryjoin` on both relationships. More fragile than three duplicated column definitions. |
| `db.create_all()` at app startup | Multi-worker race, no upgrade path, conflicts with Alembic versioning. See §1.2. |
| Storing pre-formatted `"200K"` / `"$5.00"` strings | Unsortable, unfilterable. Formatting stays in the presentation layer per the listing spec §1.3. |
| Price history table (`price_observations`) now | Genuinely valuable later, and `updated_at` is deliberate groundwork for it. But nothing in this card or the mockup asks for history. Out of scope; file a separate card if wanted. |

---

## 4. Change manifest for the implementer (t_90242caa → dale)

### New files

- `app/models/__init__.py` — re-export `AiModel`, `Modality`. Recreates the
  package deleted in commit `e112483`.
- `app/models/ai_model.py` — `AiModel`, `Modality`, the two association tables,
  the `input_content` / `output_content` properties. (Single module: the three
  mapped classes are one cohesive unit. Splitting is Dale's call.)
- `app/commands.py` — `register_commands(app)` + the `seed` command.
- `migrations/` Alembic scaffolding + the initial revision (generated, then
  reviewed).
- `docker-entrypoint.sh` — `set -e`; `flask db upgrade`; `flask seed`;
  `exec gunicorn "$@"`. Must be `chmod +x` and committed with the exec bit.

### Modified files

- `app/__init__.py` — import the models module so `db.metadata` is populated
  before `migrate.init_app` (Alembic autogenerate sees nothing otherwise), call
  `register_commands(app)`, and register the SQLite `PRAGMA foreign_keys=ON`
  listener (§5.2). No DDL, no writes.
- `app/routes/main.py` — replace the `SAMPLE_MODELS` import with an eager-loaded,
  name-ordered `AiModel` query. `render_template("index.html", models=...)` and
  `/health` otherwise unchanged.
- `app/data/sample_models.py` — docstring note only: this is now seed data.
- `tests/conftest.py` — add a `seeded_app` (or `seed_models`) fixture that
  populates the in-memory DB, since the route no longer has data for free.
- `tests/test_models_listing.py` — the two `client.get("/")` tests
  (`:41-58`) must consume the seeding fixture; the `format_*` and
  `SAMPLE_MODELS`-shape tests are untouched.
- `Dockerfile` — `COPY migrations ./migrations`, `COPY docker-entrypoint.sh`,
  set `ENV FLASK_APP=run.py`, and switch to
  `ENTRYPOINT ["/app/docker-entrypoint.sh"]` with the existing gunicorn line as
  `CMD`. `.dockerignore` was checked and does not exclude `migrations/`; its
  `*.md` rule is harmless because Alembic's generated `README` has no extension.
  No `.dockerignore` change needed.
- `README.md` — a "Database" section: the two-command dev bootstrap, where the
  dev DB file lives (`instance/app.db`), how to reset it, and the fact that new
  installs self-seed from `app/data/sample_models.py`.
- `.env.example` — clarify that the default `sqlite:///app.db` resolves under
  the Flask instance folder.

### Explicitly NOT changed

`app/templates/index.html`, `app/static/css/style.css`,
`app/utils/helpers.py`, `app/config.py`, `docker-compose.yml`,
`pyproject.toml`, `requirements.txt`, `app/cli.py`, `run.py`. If Dale finds
himself editing the template or the formatting helpers, the ORM attribute names
are wrong — fix the model, not the view.

---

## 5. Pitfalls (ordered by likelihood of biting)

### 5.1 `flask db init` will fail on the existing `migrations/README.txt`

Alembic refuses to initialize a directory that exists and is non-empty.
`migrations/README.txt` is tracked. Sequence:

1. `git rm migrations/README.txt`
2. `flask --app run:app db init`  (generates its own `README`, `env.py`,
   `alembic.ini`, `script.py.mako`, `versions/`)
3. `flask --app run:app db migrate -m "..."`, review, `flask --app run:app db upgrade`

Do not delete the file outside git; the removal belongs in the commit.

### 5.2 SQLite ignores foreign keys unless you turn them on per connection

Without `PRAGMA foreign_keys=ON`, the FKs and `ON DELETE CASCADE` in §2.3 are
decorative. Register a SQLAlchemy `connect` event listener (guarded so it only
fires for SQLite dialects) during app setup. Alembic's migration connection is
separate — SQLite batch-mode ALTER also needs
`render_as_batch=True` in `migrations/env.py` for any future column change, so
set it now while the file is fresh.

### 5.3 In-memory test DB and connection pooling

`TestingConfig.SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"`
(`app/config.py:50`). Flask-SQLAlchemy 3.x applies a `StaticPool` for in-memory
SQLite so all sessions share one connection and `create_all()` + seeded rows
persist for the fixture's lifetime. This is expected to work as-is, but no
current test actually exercises the DB, so it is **unverified in this repo**.
Dale must confirm the first DB-backed test passes before assuming the fixture is
sound; if rows vanish between sessions, that is the pool, not the code.

### 5.4 Order of `import models` vs `migrate.init_app`

If `app/models` is not imported before Alembic autogenerate runs,
`db.metadata` is empty and `flask db migrate` cheerfully produces an empty
migration. Import the models module inside `create_app()` alongside the
extension init (`app/__init__.py:16-19`).

### 5.5 The entrypoint must not swallow failures

`set -e` and `exec` are both load-bearing. Without `exec`, gunicorn runs as a
child of the shell and does not receive SIGTERM, so container stops degrade into
10-second SIGKILL timeouts. Without `set -e`, a failed `db upgrade` starts a
server against a missing schema and every request 500s.

### 5.6 The healthcheck will now pass while the app is broken

`Dockerfile:38-39` probes `/health`, which never touches the DB. A schema or
seed failure therefore reports "healthy". That is the intended contract
(`README.md:55-58`), so do not change it — but be aware during debugging that
green health says nothing about the database. A readiness endpoint is a
legitimate follow-up card, not this one.

### 5.7 SQL injection

Effectively a non-issue here: all access goes through the ORM with bound
parameters, and there is no user input on this path — `/` takes no query
parameters. The rule for Kova to enforce is simply that no `db.session.execute()`
receives an f-string or `%`-formatted SQL body. `PRAGMA` statements are the one
place raw SQL is acceptable, and they take no user input.

---

## 6. Acceptance criteria

Definition of done for t_90242caa, and the checklist for t_0500f64e.

1. `migrations/versions/` contains exactly one reviewed revision creating
   `ai_models`, `modalities`, `ai_model_input_modalities`,
   `ai_model_output_modalities` with the columns, PKs, uniques, FKs and CHECK
   constraints in §2. No `bulk_insert` of data in the migration.
2. `flask --app run:app db upgrade` on an empty database creates the four tables
   plus `alembic_version`. Verifiable with `sqlite3 <db> ".schema"`.
3. `flask --app run:app seed` on a fresh database inserts 5 modalities and
   exactly `len(SAMPLE_MODELS)` (22) model rows, and prints the count.
4. Running `flask seed` a second time inserts nothing, prints an
   already-seeded message, and **exits 0**.
5. `GET /` returns 200 and renders 22 data rows whose rendered HTML is
   equivalent to the pre-change page — same order (alphabetical by name), same
   `$X.XX` prices, same `1M`/`200K`/`66K`/`262K` context strings, same
   comma-joined modality lists including `google/gemini-3.5-flash`'s
   `Text, Images, Videos, Files, Audio` ordering.
6. `app/templates/index.html`, `app/static/css/style.css` and
   `app/utils/helpers.py` are byte-identical to `main`.
7. Rendering `/` issues a bounded number of queries (3 with `selectin` loading),
   not 1+2N. Verifiable via SQLAlchemy echo or an event-listener query counter.
8. `create_app()` performs no DDL and no INSERT. Proof: `create_app("development")`
   against a `DATABASE_URL` pointing at a non-existent path leaves no file
   behind, and `flask routes` / `ai-price-dashboard routes` still works with no
   database present.
9. `PRAGMA foreign_keys` reports `1` on an application connection, and deleting
   an `ai_models` row cascades away its association rows.
10. Restarting the container (`docker compose restart`) preserves data —
    row count and any manual edit survive — proving the volume-backed file, not
    a fresh in-container DB, is in use.
11. `flask db upgrade` on an empty DB followed by `flask db migrate` produces an
    **empty** diff, proving the migration script and the models agree. (This is
    the mitigation for tests using `create_all()`; run it manually and record the
    result in the handoff.)
12. Full suite green: `.venv/bin/python -m pytest`. Current baseline is 30 tests
    across `tests/`; new DB tests are additive and none of the existing tests may
    be deleted or weakened to pass.
13. New tests cover: seed inserts the expected count; seed is idempotent; the
    `input_content`/`output_content` properties return ordered `list[str]`;
    `name` uniqueness raises on duplicate insert; `/` renders seeded rows.
14. `README.md` documents the dev bootstrap commands, the on-disk DB location,
    and the self-seeding behaviour for new installs.
15. No new entries in `pyproject.toml` or `requirements.txt`.

---

## 7. Open questions (non-blocking)

1. **Price history.** `updated_at` is groundwork only. If the operator wants
   "price changed on date X", that needs a `price_observations` table and a
   separate card. Not built.
2. **Admin/CRUD UI.** With a real database, editing models through the browser
   becomes plausible. Nothing asks for it; there is no auth in the app, so
   anything mutating would be unauthenticated. Explicitly out of scope, and a
   security review prerequisite if it is ever requested.
3. **`--force` reseed.** Included above as optional dev convenience. Drop it if
   Dale considers it scope creep; it is not an acceptance criterion.
4. **Backups.** The SQLite file lives on a Docker named volume with no backup
   story. Worth a card once the data stops being reproducible from
   `sample_models.py` — i.e. as soon as anyone edits a row by hand.
