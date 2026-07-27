# Containerization Specification — ai-price-dashboard

Task: t_748f8b32 (research). Downstream implementer: t_a29510b2 (dale).
Source of truth: the repo at /var/local/hermes-git/ai-price-dashboard as of 2026-07-23.

This document is the build guide for the Dockerfile / docker-compose.yml. It records
what the app actually needs at runtime, derived from reading the code — not assumptions.

---

## 1. App summary

- Flask app, application-factory pattern (`app.create_app(config_name)`).
- WSGI entry point: `run:app` (module `run.py` exposes module-level `app`).
- Serves an HTML dashboard at `/` and a liveness endpoint at `GET /health`
  (returns `{"status":"ok"}`, 200; does not touch the DB — ideal container HEALTHCHECK target).
- Persistence via Flask-SQLAlchemy; default DB is SQLite. Flask-Migrate is wired but
  no migration environment exists yet (see §7).
- Gunicorn is already a declared production dependency.

## 2. Base image

Recommendation: `python:3.11-slim` (Debian slim).

Rationale:
- pyproject declares `requires-python = ">=3.11"`. The repo venv is 3.11; pin to 3.11 for
  parity. (Note: the host shell's default `python` is 3.14, but the project venv and
  metadata target 3.11 — build on 3.11 to match tested behavior.)
- All dependencies are pure Python (Flask, Flask-SQLAlchemy, Flask-Migrate, python-dotenv,
  gunicorn). SQLite support ships in CPython's stdlib. No psycopg/mysqlclient/lxml/etc.,
  so no compiler toolchain is required.
- `-slim` over `-alpine`: avoids musl wheel edge cases; still small. Alpine gives no real
  benefit here and can force source builds.
- Avoid bare `python:3.11` (full image) — unnecessarily large for a pure-Python app.

## 3. System packages

None required for the runtime.

- No `build-essential`, `gcc`, or dev headers needed — nothing compiles.
- Optional (nice-to-have, not required): `curl` if you want a curl-based HEALTHCHECK.
  Prefer a Python one-liner instead (below) to keep the image lean and dependency-free.

## 4. Python dependencies

Install from `requirements.txt` (production set):
```
Flask>=3.0.0
Flask-SQLAlchemy>=3.1.0
Flask-Migrate>=4.0.0
python-dotenv>=1.0.0
gunicorn>=23.0.0
```
- Do NOT install `.[dev]` (pytest, pytest-cov) in the runtime image.
- These are floor-pinned, not locked. For reproducible builds, generating a lock
  (pip-compile / uv) is a future improvement, out of scope for this task.
- Install order for cache efficiency: copy `requirements.txt` first, `pip install`,
  then copy the source. This keeps the dependency layer cached across code changes.
- Use `pip install --no-cache-dir` to avoid leaving the wheel cache in the layer.

## 5. Files to copy / ignore

Copy into the image: `app/` (package incl. templates + static), `run.py`,
`requirements.txt`, and `pyproject.toml` if you choose to `pip install -e .`
(editable install is optional; a plain `pip install -r requirements.txt` + copying
the source is sufficient since `run:app` imports the `app` package directly).

`.dockerignore` MUST exclude (mirrors .gitignore plus build noise):
```
.git
.gitignore
venv/
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.coverage
htmlcov/
tests/
.env
*.db
instance/
_research/
*.md
.vscode/
.idea/
.DS_Store
```
Rationale: `venv/` is ~large and host-specific (would break the image); `.env` and
`*.db` must never bake into an image (secrets / local state); `tests/` and `_research/`
are not runtime artifacts.

## 6. Environment variables

Runtime configuration (see app/config.py, run.py, .env.example):

| Variable      | Required? | Default (in code)        | Notes |
|---------------|-----------|--------------------------|-------|
| `FLASK_CONFIG`| effectively yes | `production` (WSGI path) | Selects config class. WSGI import defaults to `production`. Set explicitly to be safe. |
| `SECRET_KEY`  | YES in production | none — raises `ConfigError` if empty | ProductionConfig REQUIRES a non-empty value. App fails at import if missing. See §8. |
| `DATABASE_URL`| no        | `sqlite:///app.db`       | SQLAlchemy URI. Relative SQLite path resolves against CWD/instance — set an absolute path on a volume for persistence (§7). |
| `FLASK_APP`   | no (for `flask` CLI only) | `run.py` | Only needed if invoking `flask db ...` inside the container. |

Do NOT bake `SECRET_KEY` into the image. Supply at runtime (compose `environment:` /
`env_file:`, or `docker run -e`). `.env` is intentionally excluded from the image.

## 7. Database & persistence — IMPORTANT

- Default `DATABASE_URL=sqlite:///app.db` writes a SQLite file relative to the working
  directory. In a container this lands on the ephemeral writable layer and is LOST on
  container recreation. If any persistence is expected, mount a volume and point
  `DATABASE_URL` at an absolute path on it, e.g. `sqlite:////data/app.db`
  (four slashes = absolute path).
- Schema creation caveat: `migrations/` currently contains ONLY a placeholder README —
  there is no Alembic `env.py`, `alembic.ini`, or versions/. Therefore `flask db upgrade`
  will FAIL (no migration environment initialized). Do NOT put `flask db upgrade` in the
  Dockerfile or an entrypoint yet. Options for the implementer:
    a) Ship the image without DB bootstrap; the app serves `/` and `/health` fine without
       any table access (routes don't query the DB). This is the recommended minimal path.
    b) If table creation is wanted, it must be done via `db.create_all()` in an entrypoint
       or a real migration env — but that is a code/process change beyond this task's scope
       and should be a separate ticket, not smuggled into the Dockerfile.
  Recommendation: build the image so it runs the web server; leave DB provisioning to a
  follow-up. Note this explicitly in the compose file as a comment.

## 8. Startup command

Use Gunicorn (already a dependency), not the Flask dev server.

Canonical command:
```
gunicorn "run:app" --bind 0.0.0.0:8000 --workers 2 --timeout 30
```
- `run:app` is the WSGI target. On import it reads `FLASK_CONFIG` (default `production`),
  which enforces `SECRET_KEY`. If `SECRET_KEY` is missing the worker will crash-loop at
  boot — this is the intended fail-loud behavior; the compose/run docs must set it.
- Worker count: 2 is a sane container default; real tuning is `(2*cores)+1`. Keep it small
  and let the orchestrator scale replicas. Do not hardcode a large number.
- Bind to `0.0.0.0` so the port is reachable outside the container.
- Prefer exec form in the Dockerfile (`CMD ["gunicorn", "run:app", "--bind", ...]`) so
  Gunicorn is PID 1 and receives SIGTERM for clean shutdown.

Do NOT use `python run.py` as the container command — direct execution forces
DevelopmentConfig + debug=True (debugger/reloader), which is unsafe and inappropriate
for an image.

## 9. Ports

- Container listens on **8000** (matches the README production example). EXPOSE 8000.
- Note: the dev server (`python run.py`) uses 5000, but that path is not used in the
  container. Standardize on 8000 for the image and document the published mapping
  (e.g. compose `ports: ["8000:8000"]`).

## 10. Non-root user (hardening)

Run as a non-root user. `python:3.11-slim` runs as root by default. Create an unprivileged
user and `USER` to it before CMD. If using a volume-backed SQLite path, ensure the mounted
dir is writable by that UID (document this in compose).

## 11. Health check

Container HEALTHCHECK should hit `GET /health` (no DB dependency, constant-time 200).
Dependency-free Python probe (no need to install curl):
```
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"
```

## 12. docker-compose.yml (optional, recommended for local runs)

A single `web` service is sufficient (the app has no external service dependencies today):
- build from local Dockerfile
- `ports: ["8000:8000"]`
- `environment:` set `FLASK_CONFIG=production` and `SECRET_KEY` (via `.env` / `env_file`,
  NOT committed)
- optional named volume mounted at `/data` with `DATABASE_URL=sqlite:////data/app.db`
- `restart: unless-stopped`
- add a comment noting DB migrations are not yet available (§7).

No database service (Postgres/MySQL) is warranted yet — the app defaults to SQLite and
nothing in the code targets a networked DB. Add one only if/when `DATABASE_URL` is pointed
at a server, which is a separate decision.

---

## Build-order checklist for the implementer (t_a29510b2)

1. FROM python:3.11-slim
2. Set workdir (e.g. /app), `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1`.
3. COPY requirements.txt; `pip install --no-cache-dir -r requirements.txt`.
4. COPY app/ and run.py (and pyproject.toml if doing an editable install).
5. Create non-root user; chown workdir; `USER`.
6. EXPOSE 8000.
7. HEALTHCHECK hitting /health.
8. CMD exec-form gunicorn on 0.0.0.0:8000.
9. Add .dockerignore (§5).
10. Optional docker-compose.yml (§12) with SECRET_KEY via env_file and a note on §7.

Acceptance for the build task:
- `docker build` succeeds.
- `docker run -e SECRET_KEY=... -p 8000:8000 <img>` starts, and `curl :8000/health`
  returns `{"status":"ok"}` 200.
- Container started WITHOUT SECRET_KEY crash-loops at boot (expected fail-loud) — verify
  the error message references the required SECRET_KEY, confirming ProductionConfig is active.
