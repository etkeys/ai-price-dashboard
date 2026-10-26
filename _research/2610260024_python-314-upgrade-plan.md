# Python 3.14 container upgrade: implementation and verification plan

- Card: `t_1342914f`; implementation `t_5e830a56`; review `t_b9eabfa4`; root `t_854093f4`.
- Author: Chip
- Date: 2026-10-26 UTC (2026-10-25 EDT)
- Status: ready for implementation; no operator ruling required.
- Inspected code: `main`, `3073d4508a389eddbf1d5f6d5e04abfbf300c97b`; clean tracked worktree before research.
- Alembic head: `a1f2b3c4d5e6`, declared at `migrations/versions/a1f2b3c4d5e6_output_only_pricing_context_types.py:19-23`.
- Scope: research/specification only. No application, image, CI, or live deployment configuration was changed by this card.

## 1. Recommendation

Upgrade directly from the current Python 3.11 container to standard, GIL-enabled CPython 3.14 on the official Debian slim image. Use `python:3.14-slim-trixie`, explicitly naming the Debian suite rather than adopting a moving `slim` OS alias. Keep the existing non-root UID/GID, startup sequence, SQLite volume, port, health probe, and synchronous two-worker Gunicorn configuration.

There is no demonstrated application incompatibility requiring an intermediate 3.12/3.13 deployment, schema migration, new configuration variable, or API change. Both dependency sets tested below passed all 334 existing tests on local CPython 3.14.4, including the populated-database migration round trips. This is evidence for feasibility, not final container certification.

Retain `requires-python = ">=3.11"` and exercise Python 3.11 and 3.14 in CI. The task changes the deployed container, not the package's minimum supported interpreter. Do not remove `from __future__ import annotations` or adopt 3.14-only source syntax.

## 2. Current configuration and exact change surface

| Location | Current state | Implementation instruction |
|---|---|---|
| `Dockerfile:3` | `FROM python:3.11-slim` | Change to `python:3.14-slim-trixie`; build with `--pull` and record resolved image digest/version in the PR. |
| `Dockerfile:19-29` | requirements installed separately; project metadata copied, package not installed | Keep this production layout; do not add test tools, a compiler toolchain, or a runtime editable install. |
| `Dockerfile:15-17,31-47` | UID/GID 1000, `/data`, appuser, HTTP health probe, entrypoint, two workers | Preserve all of these. |
| `.github/workflows/build-and-publish.yml:17-33` | test job selects only Python 3.11; editable dev install | Use a `python-version` matrix containing `'3.11'` and `'3.14'`; feed that matrix value into setup-python. Keep `build-and-publish` gated on the entire test job. Retain action versions unless a concrete failure requires changing one. |
| `.github/workflows/build-and-publish.yml:73-79` | Docker builds without `--pull` | Add `--pull` to both release and PR build commands, preserving image tags, private registry authentication, certificate setup, and publishing conditions. |
| `pyproject.toml:11-24` and `requirements.txt:7-11` | broad, duplicated minimum versions; no lock | Apply the conservative tested floors in §3 to both production declarations; update dev floors in pyproject. Keep packaging minimum Python 3.11. |
| `README.md:7-17` | canonical `.venv`, creation command names python3.11 | Make Python 3.14 the recommended development interpreter matching the container; state that 3.11 remains tested/supported. A venv must be recreated to switch interpreters, never upgraded in place. |
| `docker-compose.yml:10-29` | production environment, named `/data` volume, HTTP probe | No change required. Do not recreate or delete the data volume. |
| `docker-entrypoint.sh:7-12` | migrate, seed, auth bootstrap, then exec Gunicorn | No change required. Preserve single-process migrations and idempotent bootstrap/seed. |
| `.dockerignore:5-9` | excludes `.venv/` and `venv/`, but not `env/` | Also exclude `env/`, which is already gitignored (`.gitignore:23-27`) and now contains an isolated research venv. This prevents unnecessarily sending it as build context; Docker's explicit COPY statements would not put it in the runtime image. |
| `app/models/auth.py:3` | docstring contains invalid escape `\S8` | Replace the documentary notation with plain `§8` or otherwise escape it. No runtime semantics change. |
| `tests/conftest.py:15-19` and other app/engine-owning fixtures | removes sessions/drops tables without disposing the engine | Investigate and close owned connections/dispose engines at fixture teardown, after existing session/table cleanup and while the owning app context is valid. Include migration and independently constructed app fixtures as appropriate. Do not mask ResourceWarnings globally or dispose a production request's shared engine. |

D-000 fixes `.venv/` as canonical. D-001, D-003, D-019, and D-037..D-041 remain binding: this infrastructure change must not alter roles, session policy, numeric acceptance rules, null semantics, or context transitions. Alembic remains the production DDL owner; test-fixture `db.create_all()` is not a replacement for migration testing.

## 3. Dependencies: what is necessary versus precautionary

The existing unbounded requirements already permit working releases. There is no evidence that every old declared minimum supports Python 3.14, and this research did not test every historical minimum. Therefore distinguish resolver success from an honest compatibility floor.

Recommended manifest floors are the following conservative, tested versions, NOT claims about the first upstream releases supporting 3.14:

| Dependency | Existing floor | Recommended floor | Evidence |
|---|---|---|---|
| Flask | 3.0.0 | 3.1.3 | Passed 334 tests on 3.11 and 3.14. |
| Flask-SQLAlchemy | 3.1.0 | 3.1.1 | Passed ORM initialization, queries, and migration tests. |
| Flask-Migrate | 4.0.0 | 4.1.0 | Passed real Alembic migration tests. |
| python-dotenv | 1.0.0 | 1.2.2 | Baseline and first 3.14 run; 1.2.4 also passed. |
| gunicorn | 23.0.0 | 26.0.0 | Installed in the baseline and 3.14 probe; 26.2.0 also installed. Actual import/startup and two-worker HTTP/signal behavior must be verified in Dale's image. |
| SQLAlchemy | implicit via Flask-SQLAlchemy | 2.0.51 | Declare explicitly in BOTH manifests: application imports SQLAlchemy directly. 2.0.51 and 2.1.6 both passed on 3.14. No speculative `<2.1` cap is warranted by these results. |
| pytest (dev) | 8.0.0 | 9.1.1 | Existing local 3.11 environment and 3.14 runs. |
| pytest-cov (dev) | 5.0.0 | 7.1.0 | Full instrumented 3.14 run passed; installed metadata requires coverage >=7.10.6. |

Do not add greenlet, MarkupSafe, Alembic, coverage, or setuptools as runtime dependencies solely because Python changed. They are transitive or build/test tooling; modern compatible distributions resolved successfully. The ORM layer's native-extension dependencies need **cp314/compatible manylinux wheels**, not copied cp311 `.so` files. The initial Linux x86_64 probe downloaded cp314 wheels (including greenlet and MarkupSafe); the target container must independently validate wheel availability.

Preserve the project's existing minimum-version policy rather than introducing a new lockfile system in this card. Record the final image's actual dependency versions (`python -m pip freeze`) in the implementation evidence. A resolver result can change between builds, so record the image digest as well. Full reproducible locking is a separate improvement, not a prerequisite for this interpreter upgrade.

`pyproject.toml:1-3` already declares setuptools/wheel for isolated source builds. Python 3.12+ no longer includes setuptools/pkg_resources in newly created venvs by default; this does not justify installing setuptools into the production image. Verify `pip install -e ".[dev]"` in fresh CI environments to exercise the declared build backend.

## 4. Research execution and results

All tests ran against the inspected commit with no application edits. Existing `.venv` remained on Python 3.11.15.

| Probe | Interpreter/dependencies | Actual result |
|---|---|---|
| Baseline | `.venv/bin/python`, Python 3.11.15 | `334 passed, 38 warnings in 9.15s`. |
| Compatibility probe | Local Python 3.14.4; five direct production dependencies at the 3.11 installed versions; SQLAlchemy 2.0.51, greenlet 3.5.3, pytest 9.1.1, pytest-cov 7.1.0, coverage 7.15.2 | `334 passed, 38 warnings in 9.44s`; `pip check`: no broken requirements. Other transitive dependencies were freshly resolved, so this was not a byte-for-byte dependency replay. |
| Eager resolver + coverage | Python 3.14.4; current requirements with eager dependency upgrades, including SQLAlchemy 2.1.6, gunicorn 26.2.0, python-dotenv 1.2.4, coverage 7.17.0 | `334 passed, 154 warnings in 9.10s`; coverage TOTAL 1165 statements / 116 missed / 90%; `pip check`: no broken requirements. |
| Official image manifest | `docker buildx imagetools inspect python:3.14-slim-trixie` | Tag exists, reports 3.14.9-slim-trixie and Debian trixie; includes linux/amd64 and linux/arm64. Manifest index digest observed: `sha256:35caba83af2fe6da9a5d922f9b0156f21d1246a48278c58a08bd253303ba42e8`. Re-resolve at build time rather than assuming a floating tag is unchanged. |

The eager-resolved 3.14 environment contained:

```text
alembic==1.20.1
blinker==1.9.0
click==8.5.0
coverage==7.17.0
Flask==3.1.3
Flask-Migrate==4.1.0
Flask-SQLAlchemy==3.1.1
greenlet==3.5.3
gunicorn==26.2.0
iniconfig==2.3.1
itsdangerous==2.2.0
Jinja2==3.1.6
Mako==1.4.3
MarkupSafe==3.0.4
packaging==26.3
pluggy==1.7.0
Pygments==2.21.0
pytest==9.1.1
pytest-cov==7.1.0
python-dotenv==1.2.4
SQLAlchemy==2.1.6
typing_extensions==4.16.0
Werkzeug==3.1.9
```

Local 3.14.4 reports SQLite 3.46.1 and OpenSSL 3.5.5. These are **host probe** versions, not claims about the official Docker image. No upgraded application image was built or deployed by this research card; no production database was opened for this work. The existing suite includes real file-backed migration tests (`tests/test_migration_roundtrip.py:34-47,123-268`) as well as in-memory fixture tests.

The host's Python 3.14 lacks ensurepip/python3.14-venv. Venv creation left an isolated environment at `env/py314-research`; using the existing pip's `--python env/py314-research/bin/python` support installed into that environment successfully without apt, sudo, replacing `.venv`, or changing the host interpreter. Probe logs/coverage data remain under that gitignored directory and are not release deliverables.

## 5. Breaking changes and operational risks

1. **Deferred annotations (3.14, PEP 649/749).** ORM models use `Mapped[...]`, relationship forward references, unions, and `from __future__ import annotations` (`app/models/ai_model.py:41-48,127-188`; `app/models/auth.py:45-51,69-94`). The future import's behavior remains unchanged in 3.14. Keep it; modern SQLAlchemy passed import/query tests. Do not rewrite annotation handling or remove quotes as upgrade cleanup.
2. **SQLite changes across 3.12–3.14.** Unclosed connections now emit ResourceWarning (3.13). These were reproduced in the 3.14 test runs, including at interpreter shutdown. The common fixture cleans sessions/tables but never disposes its engine; that is a likely contributor, not a conclusively traced allocation for every warning. Diagnose fixture-owned connection lifetime and fix teardown, not warning filters. Python 3.14 removes `sqlite3.version/version_info` and rejects sequences supplied to named SQL placeholders. No such direct application use was found; migration restoration passes dictionaries to named SQL (`a1f2b3c4d5e6...py:61-69`). Use `sqlite3.sqlite_version` to report the SQLite library version. Do not change autocommit/transaction policy in this work.
3. **Existing migration data-loss regression must stay fixed.** The current migration snapshots and restores modality assignments across SQLite batch rebuilds (`a1f2b3c4d5e6...py:26-69,73-109,137-153`). Test both a database already at head and a disposable legacy database requiring the existing migration. Compare association **rows and positions**, not just parent counts. This interpreter change adds no revision and must not edit old migration behavior speculatively.
4. **Invalid escape diagnostics (3.12+).** The literal `\S8` in `app/models/auth.py:3` produces SyntaxWarning under 3.14; documentation-only correction is appropriate. Treat additional warnings individually. Existing 38-warning baseline includes unrelated warnings and is not a clean warnings-as-errors guarantee.
5. **Removed standard-library modules.** 3.12 removes distutils; 3.13 removes modules such as cgi, crypt, imghdr, telnetlib, asyncore/asynchat. No direct imports of the audited removed modules were found in app source. Modern dependencies and tests pass; do not install unrelated replacement libraries in anticipation of a failure that has not occurred.
6. **Process creation.** 3.14 changes multiprocessing/ProcessPoolExecutor defaults on Linux to forkserver. The app has no such use. Gunicorn uses a pre-fork server model; this is not a reason to add `multiprocessing.set_start_method('fork')`. Verify actual default sync workers and graceful termination in the image. No free-threaded `3.14t`, gevent worker, or experimental JIT change is included.
7. **TLS/OS drift.** Python 3.13 makes default certificate checking stricter; a different Debian suite also changes SQLite/OpenSSL/CA versions. The app's liveness URL is plain loopback HTTP and unaffected by TLS settings. CI private-registry trust/Tailscale setup belongs to the runner/Docker daemon, not this app's Python SSL context. Do not bypass certificate validation if a failure appears; inspect the relevant trust chain. Record final OS/SSL/SQLite versions.
8. **Development environment migration.** A 3.11 `.venv` cannot be converted by running a different interpreter inside it. Preserve it during validation, then have the operator recreate canonical `.venv` with Python 3.14 when desired. Container deployment does not require modifying the host/system Python or Hermes runtime.

## 6. Ordered implementation strategy for Dale

1. Start a dedicated branch from the current base; inspect status first and include this research doc and its new decision-log entries in the implementation commit/PR (AGENTS.md §4).
2. Apply only the configuration/dependency/documentation changes listed in §§2–3. Keep Python >=3.11 metadata and existing production contracts. Add the two-interpreter CI matrix; do not change private publishing credentials or registry paths.
3. In clean interpreter-specific environments run editable dev installation, `python -m pip check`, the full suite, and an instrumented run such as `python -m pytest --cov=app --cov-report=term-missing`. Keep coverage data in a disposable test location. Diagnose the reproduced docstring and SQLite resource warnings; inspect warnings with `-o addopts=--strict-markers` so the repository's `--disable-warnings` default does not conceal their summaries.
4. Build the actual Dockerfile with a local candidate tag and `docker build --pull ...`. Verify the image's `python --version`, `python -m pip check`, frozen dependencies, OS suite, `sqlite3.sqlite_version`, OpenSSL version, and UID/GID. A wheel-only dependency download/install check in the same base is useful before considering native builds; do not add compilers just to make an obsolete dependency build.
5. Exercise the real entrypoint in production configuration against disposable `/data` storage, never the live compose volume. Supply a disposable non-production secret without logging credentials. Confirm migrations reach `a1f2b3c4d5e6`, initial seed works, and bootstrap does not reissue credentials on restart. Bootstrap intentionally emits a token on a fresh DB: do not paste raw container logs containing it into tickets/PRs.
6. Confirm health, `/`, `/api/v1/modalities`, and `/api/v1/models` return expected responses through Gunicorn with both workers booted. Confirm an unauthenticated protected write still returns 401, and run existing authenticated update/role tests in 3.14. Restart against the same disposable data directory and verify exact model, modality, hidden-state, price/context, and auth-record preservation. Exercise the existing migration on a populated disposable pre-head fixture, preserving association positions.
7. Verify SIGTERM reaches Gunicorn and workers stop gracefully; ensure no application exceptions, import failures, permission failures, or new runtime warnings occur in sanitized logs. The existing healthcheck must report healthy.
8. Commit/push and open the PR per repo workflow. Self-verify and complete `t_5e830a56`, releasing the existing Kova review card rather than blocking for same-card review. Include measured results, image/dependency identities, warnings disposition, and this plan. Kova reviews/approves; Erik owns final merge and rollout.

Do not expand this card into an OS Python installation, dependency-lock migration, Docker platform expansion, or database schema modernization. If genuinely necessary incompatibilities imply API/schema/permission changes, stop and obtain an operator ruling rather than weakening current tests.

## 7. Release, rollback, and reviewer acceptance

Before rollout, retain the exact known-good deployed image reference/digest and make a consistent SQLite backup using the SQLite backup facility or a stopped-writer snapshot. Include WAL state correctly if using filesystem copies. Do not copy an actively written SQLite main file alone. No live backup/deployment operation is authorized or performed by this research.

Roll out only after the actual candidate image passes the above tests and normal PR review. Keep UID/GID 1000 and the same named volume. This card adds no migration; an already-head database should remain at the same revision after entrypoint startup. Rollback means returning to the known-good application image on the unchanged schema, **not** running `flask db downgrade` and not deleting/reseeding the volume. Restore a backup only if integrity checks show data changed incorrectly and the operator approves the restore.

Kova's acceptance checklist:

- Standard CPython 3.14 in the actual image; no accidental 3.15/free-threaded image, root runtime, or extra test/compiler tooling.
- CI tests 3.11 and 3.14; both test paths use supported dependency floors and complete before publish.
- Packaging and requirements declarations agree; real image dependency check passes; actual versions/digest are recorded, not inferred from host tests.
- Existing 334 tests still pass (plus any added regression coverage); coverage tooling runs on 3.14. No test is weakened to force interpreter compatibility.
- Resource/SyntaxWarning findings are diagnosed and their disposition recorded. Do not classify the upgrade as warning-free from a default pytest run alone.
- Fresh and persistent-data startup, migrations, exact modality assignments, FK integrity, auth persistence, production configuration validation, health, two-worker HTTP, and graceful stop are verified in the candidate image.
- No schema revision, API/role/numeric-policy change, destructive reseed, live volume manipulation, credential exposure, or host-runtime replacement.
- Dale includes this plan and decision entries, commits/pushes, and opens the PR; Kova reviews it; Erik merges/deploys.

## 8. Sources and evidence boundaries

Primary upstream references consulted, 2026-10-26 UTC:

- Python 3.14 What's New, annotations/porting/sqlite3/multiprocessing sections: https://docs.python.org/3.14/whatsnew/3.14.html (browser text inspected).
- Python 3.13 What's New, SQLite connection ResourceWarning and stricter SSL defaults: https://docs.python.org/3.13/whatsnew/3.13.html (official-source search excerpts).
- Python 3.12 What's New, venv/setuptools and removals: https://docs.python.org/3.12/whatsnew/3.12.html (official-source search excerpts).
- SQLAlchemy 2.0 changes: https://docs.sqlalchemy.org/en/20/changelog/changelog_20.html (search; empirical ORM testing is the decisive project evidence).
- Official Python image source/distribution: https://github.com/docker-library/python and https://hub.docker.com/_/python (manifest metadata inspected with Docker CLI).
- Package metadata retrieved from PyPI JSON endpoints, e.g. https://pypi.org/pypi/SQLAlchemy/json and corresponding endpoints for all direct dependencies/test tools. Classifiers are supporting metadata, not proof of runtime compatibility.

The text-extraction backend was unavailable; official browser content, source-specific search excerpts, package metadata, actual pip resolution, and executed tests were used instead. Floating upstream docs/package versions can move; the concrete tested versions and observed image digest above are the auditable snapshot. No CVE audit or candidate-container security certification was performed; Kova's security review remains required.

## §A — Assumptions taken

1. **D-042: deployment target and interpreter support.** Use ordinary CPython `python:3.14-slim-trixie`, keep >=3.11 package support with a 3.11/3.14 CI matrix, and preserve runtime/process/storage policy. Reversal cost: image/CI/docs edits plus rerunning image and persistence checks; raising the package minimum later separately drops older interpreter support.
2. **D-043: tested dependency floors, not a lockfile redesign.** Raise the five direct dependency floors to tested baseline versions, explicitly declare SQLAlchemy >=2.0.51 in both manifests, and raise pytest/pytest-cov floors as in §3. Retain the existing unbounded minimum-version policy. Reversal cost: manifest edits and full dependency/CI revalidation; returning to historical floors would require testing their actual 3.14 compatibility.
3. **D-044: compatibility-only application/test cleanup.** Correct the model docstring's invalid escape and diagnose/close fixture-owned SQLite resources without changing production transaction policy or intended API/test behavior. Reversal cost: a small documentation/fixture diff and rerunning warnings diagnostics; if investigation reveals a real production behavior change, obtain a separate ruling rather than extending this assumption.

## §B — Decisions required (BLOCKING)

None. The operator already selected Python 3.14. No schema, permission, API-contract, or intended behavioral-test-policy decision is needed for the recommended infrastructure upgrade. Any such change discovered during implementation must be escalated before it is made.
