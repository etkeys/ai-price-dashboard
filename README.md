# AI Price Dashboard

A Flask application for tracking and displaying AI-related prices.

## Quick Start

1. Create and activate the project's virtual environment (`.venv/` is the canonical environment; recreate it with `python3.11 -m venv .venv` if it is missing):
   ```bash
   source .venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   # or, for development:
   pip install -e ".[dev]"
   ```

3. Copy environment variables:
   ```bash
   cp .env.example .env
   ```

4. Create the SQLite database and seed the sample models:
   ```bash
   flask --app run:app db upgrade
   flask --app run:app seed
   ```
   The default `sqlite:///app.db` resolves under the Flask instance folder
   (`<repo>/instance/app.db`).

5. Run the development server:
   ```bash
   python run.py
   ```
   This always uses `DevelopmentConfig`; no `FLASK_CONFIG` or `SECRET_KEY` is required.

6. Open http://127.0.0.1:5000 in your browser.

## Project Structure

- `app/` — Application package
  - `__init__.py` — Application factory (`create_app`)
  - `config.py` — Environment-based configuration classes
  - `extensions.py` — Flask extension instances (db, migrate)
  - `models/` — SQLAlchemy model definitions
  - `commands.py` — Custom Flask CLI commands (e.g. `flask seed`)
  - `routes/` — Flask blueprints (`main`, `auth`, `admin`, `api`)
  - `templates/` — Jinja2 templates
  - `static/` — CSS/JS assets
  - `utils/` — Helper functions
  - `data/` — Seed data modules
- `tests/` — Pytest test suite
- `migrations/` — Database migrations (generated via Flask-Migrate)
- `run.py` — Development entry point

## Database

The application uses a persistent SQLite database via Flask-SQLAlchemy and
Flask-Migrate.

- **New installs** self-seed with the 22 sample models from
  `app/data/sample_models.py` when you run `flask seed` or use the Docker
  entrypoint.
- **Schema changes** are applied with `flask db upgrade`; `create_app()` does
  not perform any DDL, so it is safe to run multi-worker Gunicorn deployments.
- **Development DB location:** the default `sqlite:///app.db` resolves under
  `<repo>/instance/app.db`. Delete `instance/app.db` and rerun `flask db
  upgrade && flask seed` to reset.
- **Container DB location:** `docker-compose.yml` mounts `/data` from an
  `app-data` named volume and sets `DATABASE_URL=sqlite:////data/app.db`, so
  data survives container restarts.
- **Re-seeding:** `flask seed --force` deletes existing model rows and re-seeds
  from `SAMPLE_MODELS`. This is intended for development only and is not run by
  the container entrypoint.

## Public API

`/api/v1/` is the public, agent-facing REST API. Some of its endpoints require
authentication and some do not; the table below is authoritative, and any
endpoint that requires a token returns `401` with a `WWW-Authenticate: Bearer`
header when called without one.

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/v1/modalities` | None | Modality vocabulary assignable to a model |

The `GET /api/v1/modalities` endpoint is unauthenticated and returns the full
set of modality names the model write paths accept:

```bash
curl http://127.0.0.1:5000/api/v1/modalities
```

```json
{
  "modalities": [
    {"name": "Audio"},
    {"name": "Files"},
    {"name": "Images"},
    {"name": "Text"},
    {"name": "Videos"}
  ]
}
```

The returned `name` values are the exact tokens to send in `input_content` /
`output_content` when creating or editing a model (see below). Responses are
cacheable for five minutes and CORS-open so agent and browser clients can poll
freely.

## Authentication

Protected actions use opaque API-key tokens instead of passwords. There are two roles:

- **updater** — value updates on existing model rows. May edit prices, context,
  and modality lists. Cannot create or delete models.
- **administrator** — everything an updater can do, plus creating and deleting
  models, and managing API keys.

Per D-007 (CONFIRMED), creating and deleting models is a structural,
administrator-only action. Per D-012 (CONFIRMED), an updater may edit every
other field on an existing model, including the modality lists, so that a
scraper can sync an existing row with its upstream source. The model name is
not editable by either role.

### Obtaining the first Administrator key

On a fresh database, run the bootstrap command:

```bash
flask --app run:app auth bootstrap
```

In the Docker entrypoint this runs automatically after `flask seed`, so `docker compose up` leaves a one-time Administrator token in the container logs. Copy it, create a personal key, and revoke the `bootstrap` key.

### Creating and using API keys

Administrators can list all keys in the database via the CLI:

```bash
flask --app run:app auth list-keys
```

Administrators can create keys via the CLI:

```bash
flask --app run:app auth create-key --name "price-scraper" --role updater
```

or via the HTTP API (Administrator only):

```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"price-scraper","role":"updater"}' \
  http://127.0.0.1:5000/admin/keys
```

The plaintext token is returned only once. Revoke a key with:

```bash
flask --app run:app auth revoke-key <kid>
```

or `POST /admin/keys/<kid>/revoke`. An administrator cannot revoke the key backing their own session.

### Browser sessions

For interactive use, paste an API key once to exchange it for a short-lived session token that is kept in `sessionStorage` (tab-scoped). The browser sends the session token as:

```
Authorization: Bearer apds....
```

Closing the tab destroys the session token. Signing out also revokes the session server-side.

Agents and scripts should use the long-lived API key directly on every request:

```
Authorization: Bearer ***
```

### Adding a model

Administrators can add a model from the browser. Sign in with an Administrator
API key using the **Authenticate** control in the header, then open
**Manage Models** from the navigation. The **Add AI Model** section is only
shown to administrators; updaters see the existing-models table and the edit
dialog only.

All model attributes are required, including at least one input modality and
one output modality.

The equivalent HTTP request is:

```bash
curl -X POST \
  -H "Authorization: Bearer ***" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "vendor/model-slug",
    "price_in": 1.0,
    "price_out": 2.0,
    "context_tokens": 128000,
    "input_content": ["Text"],
    "output_content": ["Text"]
  }' \
  http://127.0.0.1:5000/admin/models
```

The endpoint returns `201` with the new model's ID and name. It is restricted to
Administrators; updater keys receive `403 Forbidden`.

### Editing a model

Both updaters and administrators can edit every field of an existing model
except its name. Open **Manage Models**, click **Edit** on any row, change
prices, context, or modality lists, and submit. The modal submits a `PATCH`
request and reloads the page on success.

Modality lists are a **full replacement**: the submitted list replaces the
existing associations for that side. The other side is left untouched when
not submitted. Display on the public `/` page is alphabetical regardless of
submission order.

The equivalent HTTP request is:

```bash
curl -X PATCH \
  -H "Authorization: Bearer ***" \
  -H "Content-Type: application/json" \
  -d '{
    "price_in": 0.95,
    "context_tokens": 256000,
    "input_content": ["Text", "Images"],
    "output_content": ["Text"]
  }' \
  http://127.0.0.1:5000/admin/models/<model_id>
```

Any subset of `price_in`, `price_out`, `context_tokens`, `input_content`,
and `output_content` may be sent; omitted fields are left unchanged.
`name`, `id`, `created_at`, and `updated_at` are immutable and rejected with
`400` if present in the body.

### Recovery

If all Administrator keys are lost, someone with container access can issue a recovery key:

```bash
flask --app run:app auth recovery-key
```

This prints a single-use `apdr.…` token valid for 15 minutes. Redeem it in the browser:

```bash
curl -H "Content-Type: application/json" \
  -d '{"recovery_key":"apdr...","name":"new-admin"}' \
  http://127.0.0.1:5000/auth/recovery/claim
```

A recovery key cannot be used as a general bearer credential; it only mints one Administrator key.

### Transport security

Bearer tokens in headers are only safe over a trusted channel. Plaintext HTTP over an untrusted network exposes every key. Run the service behind a TLS-terminating reverse proxy or on a trusted overlay network.

## Health Check

`GET /health` is an unauthenticated, shallow liveness endpoint used by load
balancers and orchestrators. It returns HTTP 200 with the JSON payload:

```json
{ "status": "ok" }
```

This endpoint intentionally does not query the database or any upstream price
providers. It only confirms that the Flask process can accept and dispatch a
request. Dependency readiness checks (readiness probes) should target a separate
endpoint if they become necessary.

## Running Tests

```bash
.venv/bin/python -m pytest
```

## Production

Use a WSGI server such as Gunicorn. The provided `docker-entrypoint.sh` runs
migrations and seeding once before exec'ing Gunicorn:

```bash
# Make sure SECRET_KEY is set to a real, secret value.
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export FLASK_CONFIG=production

gunicorn "run:app" --bind 0.0.0.0:8000
```

`ProductionConfig` requires a non-empty `SECRET_KEY`; Gunicorn will fail to
start if `SECRET_KEY` is missing, empty, or whitespace.

To run locally, use the development server which always selects
`DevelopmentConfig`:

```bash
python run.py
```
