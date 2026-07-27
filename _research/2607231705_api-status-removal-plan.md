# Removal Plan: `/api/status` Endpoint

**Task:** t_bfe2a714 — Verify `/api/status` has no consumers and plan removal
**Author:** chip (architect)
**Date:** 2026-07-23
**Repo:** /var/local/hermes-git/ai-price-dashboard

---

## 1. Summary / Recommendation

The `/api/status` endpoint is a stub with **no internal consumers**. It duplicates
the purpose of the canonical `GET /health` liveness endpoint (added in task
t_b4308af0), which returns the identical payload `{"status": "ok"}`. It should be
removed.

Because `/status` is the **only** route on the `api` blueprint, removing the
endpoint makes the entire `api_bp` blueprint dead code. The recommended plan
removes the blueprint as well (Option A). A minimal alternative that keeps the
empty blueprint for future API routes is documented as Option B.

---

## 2. Evidence: No Consumer References the Endpoint

Full-repo search (excluding `.venv`/`venv`/site-packages third-party noise, which
only match the generic word "status" inside alembic/sqlalchemy).

Non-vendored references to `/api/status`, `api_bp`, or the `api` blueprint:

| # | File | Line(s) | Kind |
|---|------|---------|------|
| 1 | `app/routes/api.py` | 5, 8-11 | Blueprint definition + route handler (the endpoint itself) |
| 2 | `app/__init__.py` | 27, 30 | Blueprint import + registration with `url_prefix="/api"` |
| 3 | `tests/test_api.py` | 1-8 | The only test exercising the endpoint |
| 4 | `_research/2607211910_flask-structure-research.md` | 83-87 | Historical research doc (example factory snippet) |

Consumer surfaces checked and confirmed CLEAN (zero references):

- **Frontend JS** (`app/static/js/dashboard.js`) — placeholder only, no `fetch`/XHR calls.
- **Templates** (`app/templates/base.html`, `index.html`) — no `/api`, no `url_for('api...')`, no "status".
- **`url_for` / reverse-routing** — no `url_for("api.status")` or `api.` endpoint references anywhere.
- **Other routes/services/models/CLI** — no imports of `api_bp` outside `app/__init__.py`.
- **Docs (`README.md`)** — the `{ "status": "ok" }` snippet at lines 53-55 is under the
  `## Health Check` section describing `GET /health`, NOT `/api/status`. No README text
  mentions `/api/status`. **No README edit required.**

**Conclusion:** the endpoint has no internal consumer. The only things that
reference it are its own definition, its registration, and its own test.

---

## 3. Removal Plan — Option A (RECOMMENDED): remove endpoint + dead blueprint

Since `/status` is the sole route on `api_bp`, the blueprint has no remaining
purpose after removal.

### Files to DELETE
- `app/routes/api.py` — entire file (blueprint `api_bp` + handler `status()`).
- `tests/test_api.py` — entire file (only contains `test_api_status`).

### Files to MODIFY
- `app/__init__.py`
  - Delete line 27: `from app.routes.api import api_bp`
  - Delete line 30: `app.register_blueprint(api_bp, url_prefix="/api")`
  - (Leave the `main_bp` import on line 26 and registration on line 29 intact.)

### Symbols removed
- `api_bp` (Blueprint instance) — `app/routes/api.py:5`
- `status()` (view function) — `app/routes/api.py:8-11`
- `test_api_status()` (test) — `tests/test_api.py:4-8`
- URL rule `/api/status` (endpoint name `api.status`)

### Left intentionally untouched
- `_research/2607211910_flask-structure-research.md` — historical/archival record.
  Editing research artifacts is out of scope and would falsify the historical record.
  (Optional: add a one-line note if the team wants the doc kept current — not required.)
- `README.md` — no `/api/status` reference exists; nothing to change.

---

## 4. Removal Plan — Option B (ALTERNATIVE): keep empty `api` blueprint

Use only if the team wants `api_bp` retained as a mount point for imminent future
JSON API routes.

### Files to MODIFY
- `app/routes/api.py` — delete lines 8-11 (`status()` handler); keep the
  `Blueprint` import and `api_bp = Blueprint("api", __name__)` definition.
- `tests/test_api.py` — delete `test_api_status` (lines 4-8). File becomes empty
  of tests; either delete it or leave a docstring-only stub.

### Files unchanged
- `app/__init__.py` — blueprint stays registered (an empty blueprint registers fine).

**Trade-off:** Option B leaves a registered blueprint that serves zero routes —
harmless but dead until a real API route is added. Option A is cleaner (no dead
code). Recommend Option A unless an API route is already planned for the next sprint.

---

## 5. Verification Steps (post-removal)

Baseline established BEFORE removal (this investigation):

- `tests/test_api.py::test_api_status` — **PASSES** today.
- Full suite: **26 passed** when run with the correct workspace
  (`HERMES_KANBAN_WORKSPACE="$(pwd)" .venv/bin/python -m pytest`).
- NOTE: running bare `pytest` shows 1 pre-existing failure in
  `tests/test_run.py::test_direct_execution_uses_development_config`. This is an
  environment artifact — that test uses `HERMES_KANBAN_WORKSPACE` as its cwd, which
  is currently set to the empty stub dir `/var/local/hermes-git/ai-price/dashboard`
  (see §7). It is **unrelated to `/api/status`** and must not be attributed to this change.

After removal, the implementer (Dale) should confirm:

1. `.venv/bin/python -m pytest tests/ -q` (from the repo root, with
   `HERMES_KANBAN_WORKSPACE` unset or pointed at the real repo) — expect
   **25 passed** (26 minus the deleted `test_api_status`), zero new failures.
2. `grep -rn "api/status\|api_bp\|api\.status" app tests README.md` returns nothing
   (Option A) — proves no dangling reference.
3. App still boots: `.venv/bin/python -c "from app import create_app; create_app()"`
   exits 0 with no import error for the removed blueprint.
4. `/health` still returns `{"status":"ok"}` (the surviving liveness endpoint) — the
   removal does not affect it (`app/routes/main.py`).

---

## 6. Affected-Files Manifest (quick reference for implementer)

Option A (recommended):
```
DELETE  app/routes/api.py
DELETE  tests/test_api.py
MODIFY  app/__init__.py   (remove lines 27 and 30)
```

Option B:
```
MODIFY  app/routes/api.py   (remove handler, keep blueprint)
MODIFY  tests/test_api.py   (remove test)
```

---

## 7. Workspace-Path Discrepancy (flag for orchestrator)

This task's kanban `workspace_path` is `/var/local/hermes-git/ai-price/dashboard`,
which is **empty** (no git repo, no files). The actual codebase — and the target of
all sibling tasks (health endpoint, contract, structure research) — lives at
`/var/local/hermes-git/ai-price-dashboard` (hyphenated). The auto-decomposer appears
to have set the wrong workspace path. This investigation was performed against the
real repo. Downstream implementation/QA tasks (t_5a7d94c6, t_d7ad081a) should have
their workspace corrected to `/var/local/hermes-git/ai-price-dashboard` before Dale
edits code, or the same `run.py`-not-found artifact will surface.
