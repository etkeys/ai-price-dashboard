# venv / .venv Consolidation and Symlink Repair — Implementation Spec

Task: t_26bbc9d7 (chip, research)
Date: 2026-07-25 17:53
Repo: /var/local/hermes-git/ai-price-dashboard
Upstream context: kova's finding on t_1110fc89 ("broken venv/bin/python3 symlink";
`test_run.py::test_direct_execution_uses_development_config` failing under a
subprocess that could not import flask).

---

## 1. Executive summary

The repo carries two complete, independently working virtual environments,
`venv/` (77 MB) and `.venv/` (79 MB). Both are CPython 3.11.15 and both run the
full 32-test suite green today.

Correction to the upstream finding: **there are no dangling symlinks in either
environment.** Every symlink resolves to a real file. The actual defect in
`venv/` is worse than a dangling link and easy to misdiagnose as one:
`venv/bin/python` and `venv/bin/python3` point at the **system 3.14 interpreter**
instead of the venv's own 3.11 interpreter. They resolve fine, they just run the
wrong Python against an empty `venv/lib/python3.14/site-packages`, so anything
that goes through `python`/`python3` inside that venv gets
`ModuleNotFoundError: No module named 'flask'`.

Recommendation: **keep `.venv/`, delete `venv/`.** `.venv/` has correct
interpreter symlinks, matches the documented convention in README.md, and is the
uv/modern-tooling default. The one capability `venv/` has that `.venv/` lacks —
the editable install of the project — is reproduced with a single pip command.

---

## 2. Evidence

### 2.1 `venv/bin` symlink state (the defect)

```
python      -> python3          => /usr/bin/python3.14      WRONG
python3     -> /usr/bin/python3 => /usr/bin/python3.14      WRONG
python3.11  -> /home/erik/.local/bin/python3.11 => uv cpython-3.11.15   correct
python3.14  -> python3          => /usr/bin/python3.14      non-standard
𝜋thon       -> python3          => /usr/bin/python3.14      junk artifact
```

A stock `python3.11 -m venv venv` produces exactly three links —
`python -> python3`, `python3 -> python3.11`, `python3.11 -> <base interpreter>`.
The `python3 -> /usr/bin/python3` retarget, the `python3.14` link and the
`𝜋thon` link are all hand-made. This environment was tampered with after
creation.

Consequences observed live:

```
venv/bin/python -V                 -> Python 3.14.4
venv/bin/python -c "import flask"  -> ModuleNotFoundError
venv/bin/python3.11 -c "import flask" -> ok
```

`venv/lib/` contains both a populated `python3.11/site-packages` (64 entries)
and an empty `python3.14/site-packages`, which is where the 3.14 interpreter
looks. `venv/pyvenv.cfg` still declares `version = 3.11.15`, so the venv is
internally inconsistent with its own `bin/python`.

### 2.2 `.venv/bin` symlink state (clean)

```
python      -> python3.11 => uv cpython-3.11.15
python3     -> python3.11 => uv cpython-3.11.15
python3.11  -> /home/erik/.local/bin/python3.11 => uv cpython-3.11.15
```

Stock layout, correct interpreter, `import flask` works.

### 2.3 Why the failing test now passes

`tests/test_run.py` spawns `sys.executable`. When pytest is launched via
`venv/bin/pytest`, the shebang is `#!.../venv/bin/python3.11`, so
`sys.executable` is the *correct* 3.11 binary and the subprocess works. Kova's
failure came from a run whose `sys.executable` had resolved to the 3.14 path.
Verified just now, both green:

```
venv/bin/pytest -q            -> 32 passed
.venv/bin/python -m pytest -q -> 32 passed
```

So this is a latent landmine, not a currently-red test. It re-fires the moment
anyone activates `venv/` and types `python`.

### 2.4 Package delta between the two environments

`pip freeze` is identical except:

- `venv/` additionally has the project itself installed editable
  (`-e /var/local/hermes-git/ai-price-dashboard`, plus
  `__editable__.ai_price_dashboard-0.1.0.pth`, the finder module, the
  `ai-price-dashboard` console script from `[project.scripts]`, `wheel`,
  `setuptools 83.0.0`).
- `.venv/` has `pkg_resources` and `setuptools 79.0.1`, no editable install, no
  console script.

Practical effect: from a directory other than the repo root, `venv/bin/python3.11`
can `import app` and `.venv/bin/python` cannot. Tests pass under `.venv` today
only because pytest's rootdir insertion puts the repo root on `sys.path`.

### 2.5 Conventions and external references

- `README.md` line 7: "the workspace already has `.venv`" / `source .venv/bin/activate`.
- `_research/2607211910_flask-structure-research.md`: "`.venv` directory already
  exists in the workspace — do not recreate it."
- `.gitignore` and `.dockerignore` both ignore `venv/` and `.venv/`; neither is
  or ever was tracked.
- The Dockerfile installs into the image's system Python; it uses neither venv.
- No systemd unit, cron entry, or Hermes config references either path. The only
  matches for `ai-price-dashboard/venv` outside the repo are agent log files.
- **There is no `.git` directory in this workspace** — `git rev-parse` fails.
  Deleting `venv/` is therefore unrecoverable from VCS. It is also, for the same
  reason, invisible to any commit.

Later research docs (`2607230701_health-endpoint-contract.md`) used
`venv/bin/pytest` in their verification commands; that is the source of the
drift. Those are historical records and should not be rewritten.

---

## 3. Decision

Canonical environment: **`.venv/`**.

Rationale, in priority order:

1. It is what README.md documents; the alternative is editing docs to match an
   accident.
2. Its interpreter symlinks are correct and unmodified; `venv/`'s are not, and
   repairing them means hand-fixing four links plus deleting a stray
   `lib/python3.14` tree — more work than reproducing the one missing feature in
   the clean env.
3. `.venv` is the uv / PDM / modern-tooling default and the dot-prefix keeps it
   out of casual directory listings.
4. Both are 3.11.15 with identical third-party package versions, so there is no
   dependency-state argument for keeping `venv/`.

No merge is needed or wanted. Merging two venvs is not a supported operation;
the correct "merge" is one `pip install -e` into the survivor.

---

## 4. Implementation plan

Work in `/var/local/hermes-git/ai-price-dashboard`. Steps 1–3 are non-destructive
and should be completed and verified before step 4 is proposed to the operator.

### Step 1 — Bring `.venv` to feature parity

```bash
.venv/bin/python -m pip install -e ".[dev]"
```

This adds the editable-install finder, the `ai-price-dashboard` console script,
and pulls `wheel`/updated `setuptools` in as build deps — i.e. exactly the delta
identified in 2.4.

### Step 2 — Verify `.venv` standalone

All five must pass:

```bash
.venv/bin/python -V                                   # Python 3.11.15
.venv/bin/python -c "import flask, app; print('ok')"  # from repo root
(cd /tmp && /var/local/hermes-git/ai-price-dashboard/.venv/bin/python \
    -c "import app; print(app.__file__)")             # editable install proves out
.venv/bin/ai-price-dashboard --help                   # console script exists
.venv/bin/python -m pytest -q                         # 32 passed
```

Also confirm the interpreter chain is still clean after the install:

```bash
for f in .venv/bin/python .venv/bin/python3 .venv/bin/python3.11; do
  printf '%-24s %s\n' "$f" "$(readlink -f "$f")"; done
```

All three must resolve to the same `cpython-3.11.15` binary.

### Step 3 — Documentation touch-ups

`README.md`:

- Under Quick Start, make `.venv` explicitly canonical rather than incidental.
  Replace "the workspace already has `.venv`" with a line stating that `.venv/`
  is the project's only virtual environment and, if it is missing, is recreated
  with `python3.11 -m venv .venv`.
- Under "Running Tests", change the bare `pytest` to `.venv/bin/python -m pytest`
  so a copy-paste from an unactivated shell cannot pick up a foreign interpreter.

Do **not** edit files under `_research/`. They are dated records.

### Step 4 — Remove the redundant environment (DESTRUCTIVE — operator approval required)

Do not run this yourself. Present it to the operator and let them execute, or get
an explicit go-ahead in a task comment first.

```bash
rm -rf /var/local/hermes-git/ai-price-dashboard/venv
rm -f  /var/local/hermes-git/ai-price-dashboard/__pycache__/run.cpython-314.pyc
```

The second line clears a 3.14 bytecode artifact left by the mis-symlinked
interpreter. Note again that there is no git history here — once `venv/` is gone
it is gone. Since it is 100% reproducible from `requirements.txt` /
`pyproject.toml`, that is acceptable, but the operator should say so out loud.

Optional cheap insurance before deleting: `mv venv /tmp/venv.bak-2607251753` and
remove it after the next clean test run.

### Step 5 — Re-verify after removal

```bash
.venv/bin/python -m pytest -q     # 32 passed
.venv/bin/python run.py           # dev server boots; Ctrl-C
```

---

## 5. Fallback: if the operator insists on keeping `venv/`

Repair rather than delete. Exact commands:

```bash
cd /var/local/hermes-git/ai-price-dashboard/venv/bin
rm -f python python3 python3.14 '𝜋thon'
ln -s python3.11 python3
ln -s python3    python
cd ..
rm -rf lib/python3.14
```

Then re-run the section 2.1 readlink check — `python`, `python3`, `python3.11`
must all resolve to `cpython-3.11.15`. This restores the stock layout. It does
not solve the two-environments problem; it only defuses the landmine.

---

## 6. Acceptance criteria

1. Exactly one virtual environment directory exists in the repo root, named
   `.venv/` (or, under the section 5 fallback, both exist and both have correct
   symlink chains).
2. `readlink -f` on `.venv/bin/python`, `python3`, and `python3.11` yields the
   same CPython 3.11.15 binary.
3. `.venv/bin/python -c "import flask"` succeeds.
4. `import app` succeeds from a working directory outside the repo using
   `.venv/bin/python` (proves the editable install landed).
5. `.venv/bin/python -m pytest -q` reports 32 passed, 0 failed — specifically
   including `tests/test_run.py::test_direct_execution_uses_development_config`,
   which is the regression net for this whole class of bug.
6. `README.md` names `.venv` as the canonical environment and its test command
   invokes the venv interpreter explicitly.
7. No file under `_research/` has been modified.
8. `venv/` removal was executed by, or explicitly approved by, the operator.

## 7. Out of scope

- Adding a `Makefile`, `tox.ini`, `AGENTS.md`, or any new env-bootstrap script.
- Switching the project to uv-managed environments or adding a lockfile.
- Initialising git in this workspace (worth raising separately — the absence of
  version control here is a bigger risk than either venv).
- Rewriting the Dockerfile, which correctly uses neither environment.
