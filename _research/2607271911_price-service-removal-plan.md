# price_service.py Removal — Verification and Removal Plan

Task: t_7b2d7c01 (research/plan, chip) → implement (@dale) → review (@kova)
Author: chip
Date: 2026-07-27
Repo: /var/local/hermes-git/ai-price-dashboard @ `main`
Predecessor: `_research/2607271901_price-model-removal-plan.md` (§6.1 flagged this file)

---

## 0. Repo state at time of writing — READ THIS FIRST

The working tree is **dirty**. The Price-model removal (t_11bb3355) is complete
and QA-approved but **not committed**:

```
 M README.md
 M app/__init__.py
D  app/models/__init__.py
D  app/models/price.py
 M migrations/README.txt
D  tests/test_models.py
?? _research/2607271901_price-model-removal-plan.md
```

Implication for @dale: this change lands **on top of** uncommitted work. Either
commit the Price-model change first (operator call — @suki should confirm) or
keep both in one commit and say so in the message. Do **not** `git stash`,
`git checkout .`, or `git reset` — that destroys approved work.

Baseline test count, verified just now against the dirty tree:
`.venv/bin/python -m pytest -q` → **30 passed**.

Note: the venv is `.venv`, not `venv`. Memory of a `venv/` here is stale.

---

## 1. Verdict

`app/services/price_service.py` is **unambiguously dead**. Zero references
outside the file itself and prose in `_research/` docs. Removing it is a pure
deletion with no behavioural change and no test-count change.

---

## 2. Evidence — exhaustive reference sweep

The file defines exactly three public symbols: `PriceServiceError`,
`PriceService`, `PriceService.get_latest_price`. Repo-wide grep for
`price_service|PriceService|PriceServiceError|get_latest_price` across every
tracked file (excluding `.git`, `.venv`, `__pycache__`):

| Location | Hit | Live? |
|---|---|---|
| `app/services/price_service.py` | its own definitions | n/a — the file itself |
| `_research/2607271901_price-model-removal-plan.md` (7 hits) | prose flagging it as dead | No — documentation |
| `_research/2607251644_models-listing-spec.md:246` | "`PriceService` remains a placeholder; not wired to this view" | No — documentation |
| `_research/2607211910_flask-structure-research.md:26,151` | original scaffold layout prose | No — documentation |

**Zero hits in:** `app/__init__.py` (factory — imports only `config`,
`extensions`, `utils.helpers`, `routes.main`), `app/routes/main.py`,
`app/cli.py`, `app/config.py`, `app/extensions.py`, `run.py`, `tests/*`,
`app/templates/*.html`, `app/static/js/dashboard.js`, `app/static/css/style.css`,
`Dockerfile`, `docker-compose.yml`, `pyproject.toml`, `requirements.txt`.

Checks that specifically matter for a Flask app:

- **Jinja globals** — `app/__init__.py:22-24` registers exactly two:
  `format_context` and `format_price`, both from `app/utils/helpers.py`.
  Neither comes from the service layer.
- **Blueprints** — only `main_bp`. No service import anywhere in the chain.
- **CLI** — `app/cli.py` has one command (`routes`) and imports only
  `create_app`.
- **Dynamic imports** — no `importlib`, `__import__`, `pkgutil`, or
  entry-point plugin loading anywhere in `app/`. Nothing can reach this module
  by name at runtime.
- **Console scripts** — `pyproject.toml` declares one: `app.cli:main`.
- **Packaging** — `[tool.setuptools.packages.find] include = ["app*"]` is a
  glob; deleting a subpackage needs no pyproject edit.

### Confirmed live — DO NOT TOUCH

- `app/utils/helpers.py::format_price()` — registered as a Jinja global and
  called twice in `app/templates/index.html:25-26`. **Live. Keep.**
- `app/data/sample_models.py` — drives the `/` listing. Unrelated.
- All "AI Price Dashboard" branding and the `Price In` / `Price Out` column
  headers. Unrelated.

---

## 3. Decision: delete the file, or the whole `app/services/` package?

`app/services/` contains exactly two files: `price_service.py` and an
`__init__.py` whose entire content is the docstring
`"""Business logic service layer."""`. Nothing imports `app.services` either.

**Recommendation: Option A — delete the whole `app/services/` package.**

**Option A — delete `app/services/` entirely (RECOMMENDED)**
- Removes both files; the directory goes with them.
- Rationale: an empty package that nothing imports is the same species of dead
  code this ticket exists to remove. It is one `mkdir` + one docstring to
  recreate the day a real service lands. This also matches the precedent set by
  t_11bb3355, which deleted `app/models/` outright rather than leaving a stub.
- Requires the `README.md:39` edit (step 3 below).
- **Verified** (probe, §5): 30/30 pass, `/` 200 with all 22 model rows,
  `/health` 200, CLI `routes` lists `main.index` + `main.health`.

**Option B — keep `app/services/__init__.py` as an empty placeholder**
- Delete only `price_service.py`; leave the package docstring.
- Rationale: preserves the documented layer boundary in README for the next
  service.
- If @dale takes Option B, `README.md:39` stays as-is and step 3 is skipped.

@dale: pick one and be consistent — do not delete the file while leaving a
README bullet that promises a services layer, and do not delete the package
while leaving the bullet in.

---

## 4. Removal plan for @dale

Assumes Option A. Execute in order.

1. `git rm app/services/price_service.py app/services/__init__.py`
2. No source edits required. `app/__init__.py`, `app/routes/main.py`,
   `app/cli.py`, `tests/conftest.py` and every test file are already free of
   service imports — **do not modify them**.
3. Edit `README.md` — remove line 39 from the Project Structure list:
   ```
     - `services/` — Business logic
   ```
   Leave the surrounding bullets (`routes/`, `templates/`, `static/`,
   `utils/`) untouched.
4. Purge stale bytecode so a leftover
   `app/services/__pycache__/price_service.cpython-311.pyc` cannot mask an
   import error:
   `find . -path ./.venv -prune -o -name __pycache__ -type d -print -exec rm -rf {} +`
   This is destructive — get operator confirmation per policy, or use the safe
   alternative `.venv/bin/python -B -m pytest -q`.
5. Verify — all five must pass:
   - `.venv/bin/python -m pytest -q` → **30 passed** (unchanged from baseline).
   - `.venv/bin/python -c "from app import create_app; create_app('testing')"` → no error.
   - `.venv/bin/ai-price-dashboard routes` → lists `main.index` and `main.health`.
   - `grep -rn "price_service\|PriceService" --include="*.py" --include="*.html" --include="*.js" --include="*.toml" --include="*.txt" --include="*.yml" app tests run.py pyproject.toml requirements.txt docker-compose.yml` → zero hits.
   - `test -d app/services && echo STILL THERE` → prints nothing (Option A only).

### Do NOT do in this ticket

- Do not touch `format_price()` in `app/utils/helpers.py` — it is live.
- Do not touch `app/data/sample_models.py`, `app/routes/main.py`, or any
  template.
- Do not edit `_research/*.md`. The historical prose references are accurate
  records of what was true when written; they are not code references.
- Do not hand-edit `ai_price_dashboard.egg-info/SOURCES.txt`. It is an untracked
  build artifact (`git ls-files` confirms) and regenerates itself.
- Do not remove `flask-sqlalchemy` / `flask-migrate` from `pyproject.toml` or
  `requirements.txt`. `db`/`migrate` are still wired into the factory and
  `tests/conftest.py`. That is a separate architectural call
  (see t_11bb3355 plan §6.2) requiring operator sign-off.
- Do not `git stash` / `reset` / `checkout` over the uncommitted t_11bb3355 work
  (see §0).

---

## 5. Verification already performed

A pristine copy of the current working tree was extracted to `/tmp/probe_svc`
(excluding `.git`, `.venv`, `__pycache__`, `.pytest_cache`), `app/services/`
deleted, then exercised with the repo's own interpreter:

```
$ python -m pytest -q -p no:cacheprovider
..............................                                    [100%]
30 passed in 0.55s

$ python -c "... create_app('testing') ..."
/       200   (23 <tr> = 1 header row + 22 model rows)
/health 200   {'status': 'ok'}

$ ai-price-dashboard routes
static       {'GET'} /static/<path:filename>
main.index   {'GET'} /
main.health  {'GET'} /health
```

Option A is proven working. No test asserts on the services package, so the
count does not move.

---

## 6. Expected post-change state

| Metric | Before | After |
|---|---|---|
| `pytest -q` | 30 passed | **30 passed** |
| Files deleted | — | `app/services/price_service.py`, `app/services/__init__.py` |
| Files edited | — | `README.md` (1 line removed) |
| Source files edited | — | **none** |
| Migrations added | — | none (none needed) |
| Runtime behaviour change | — | none |

---

## 7. Acceptance criteria for @kova

- [ ] `app/services/price_service.py` no longer exists in the tree.
- [ ] Per §3, either `app/services/` is gone entirely **and** the `README.md`
      `services/` bullet is gone, or the package survives as a docstring-only
      `__init__.py` **and** the README bullet remains — not a mismatched half
      of either.
- [ ] `grep -rn "price_service\|PriceService"` over `app/`, `tests/`, `run.py`,
      `pyproject.toml`, `requirements.txt`, `docker-compose.yml`, and all
      templates/static returns **zero** hits. Hits inside `_research/*.md` are
      expected and correct — those are historical documents.
- [ ] `format_price()` still exists in `app/utils/helpers.py`, is still
      registered as a Jinja global in `app/__init__.py:22-24`, and
      `app/templates/index.html` still calls it twice.
- [ ] No orphaned `.pyc` under `app/services/__pycache__/`.
- [ ] `.venv/bin/python -m pytest -q` → **30 passed**, 0 failed, 0 errors.
- [ ] `/` returns 200 and renders all 22 sample models; `/health` returns
      `{"status": "ok"}` with 200.
- [ ] `ai-price-dashboard routes` lists `main.index` and `main.health`.
- [ ] `pyproject.toml`, `requirements.txt`, `Dockerfile`, `docker-compose.yml`,
      `tests/conftest.py` unmodified.
- [ ] The uncommitted t_11bb3355 deletions (`app/models/*`,
      `tests/test_models.py`) are still staged/present as deletions and were not
      reverted.
- [ ] No migration files added.

---

## 8. Follow-on observations (out of scope — for @suki to triage)

1. **Uncommitted work is accumulating on `main`.** Two completed tickets' worth
   of changes now sit in the working tree with no commit. Worth a ticket, or at
   minimum an operator decision on commit cadence, before a third lands on top.
2. **Post-removal, `app/` has no business-logic layer at all** — the app is
   factory + one blueprint + static sample data + two Jinja helpers. That is
   correct for what it currently does; noting it so nobody re-scaffolds a
   services package on reflex.
3. **SQLAlchemy/Flask-Migrate remain pure overhead** (carried forward from
   t_11bb3355 plan §6.2, still unresolved). With zero models and zero services,
   `db` exists only so `conftest.py` can create and drop an empty schema. Still
   an operator call.
