# Tilde-insensitive model name sorting — implementation plan

- Card: `t_185a7a47` (research). Implementation: `t_a7bbc3b7` (dale). Review: `t_cb363e73` (kova). Root: `t_8db55901`.
- Author: Chip
- Date: 2026-08-04
- Status: **hands off — §B is empty**
- Code state described: commit `28edfac` on `main` (clean tree), Alembic head `248f2949289c`, SQLAlchemy 2.0.51, SQLite 3.53.1, Jinja 3.1.6, 155 tests passing.

---

## 1. The request

Root card `t_8db55901`: OpenRouter publishes `~deepseek/deepseek-v4-flash-latest`.
The leading `~` marks an OpenRouter-specific alias that redirects to some
underlying model. When model names are sorted for viewing, the leading `~` must
be ignored, so that name sorts adjacent to the other `deepseek/deepseek-*` rows
rather than being exiled to the end of the table.

That is the whole request: **a display-ordering change.** It says nothing about
storing names differently, filtering, badging aliases, or the API.

---

## 2. Where the sort actually lives

There is exactly one sort mechanism for model names in this repo, and it appears
in two places. Both are SQL `ORDER BY` clauses inside route queries.

| Surface | File:line | Current clause |
|---|---|---|
| Public dashboard `/` | `app/routes/main.py:22` | `.order_by(AiModel.name)` |
| Admin `/admin/models/manage` | `app/routes/admin.py:226` | `.order_by(AiModel.name)` |

Everything else that looks like a sort is **not** in scope, and I verified each:

- `app/templates/index.html:28-29` and `app/templates/admin/models.html:40-41`
  — Jinja `| sort` on the modality lists, not on names. That is D-008/D-010
  territory. Untouched.
- `app/routes/admin.py:229` — `sorted(ALLOWED_MODALITIES)` for the checkbox
  vocabulary. Not names. Untouched (D-011).
- `app/routes/admin.py:290,308,391` — `sorted(...)[0]` used to pick a
  deterministic name for an error message. Not display ordering. Untouched.
- `app/static/js/admin-models.js` — **no client-side sort exists.** Grep for
  `sort` across all JS returns zero hits. The tables are server-rendered; the
  edit dialog reloads the page (`window.location.reload()`, lines 112 and 200)
  rather than re-ordering the DOM. There is no comparator in JavaScript to
  modify. The auto-decomposer's card body speculates about "likely in the UI";
  it is in the query.
- `tests/test_admin_models.py` (16 sites) — `select(AiModel).order_by(AiModel.name)`
  used to fetch *the one seeded row* deterministically inside test setup. Not
  display ordering, and changing the app must not require touching these.

**Consequence: there is no "comparator" to modify in the sense the card
implies.** The change is to the ordering expression of two SQLAlchemy queries.

---

## 3. Recommended approach

### Add a `sort_name` hybrid property to `AiModel`, and order by it in both routes.

**File 1 — `app/models/ai_model.py`.** Add a `hybrid_property` named `sort_name`
to the `AiModel` class (alongside the existing `input_content` /
`output_content` properties at `:144-152`), with both a Python getter and a SQL
expression:

- Python side: return the instance's `name` with all leading `~` removed.
- SQL side (`@sort_name.expression`): return `func.ltrim(cls.name, "~")`.

Requires importing `hybrid_property` from `sqlalchemy.ext.hybrid` and adding
`func` — `func` is **already imported** at `app/models/ai_model.py:37`.

**File 2 — `app/routes/main.py:22`.** Change `.order_by(AiModel.name)` to order
by `AiModel.sort_name` first and `AiModel.name` second.

**File 3 — `app/routes/admin.py:226`.** The identical change.

**File 4 — `tests/test_models_listing.py`.** New tests (see §6).

That is three source lines plus one property definition plus tests. No
migration. No schema change. No new endpoint. No API contract change. No
JavaScript.

### Why `ltrim(name, '~')` and not something else

`ltrim(X, Y)` in SQLite strips *every* leading character present in the set `Y`.
Verified against SQLite 3.53.1 in `.venv`:

```
'~~deepseek/x'  -> 'deepseek/x'
'~deepseek/a'   -> 'deepseek/a'
'deepseek/a'    -> 'deepseek/a'     (no-op, as required)
'~'             -> ''
'z-ai/x~inside' -> 'z-ai/x~inside'  (interior '~' untouched, as required)
```

The Python-side mirror is `str.lstrip("~")`, which has identical semantics.
Note explicitly: **`str.removeprefix("~")` is the wrong primitive** — it strips
one occurrence, so `'~~qwen/...'` would still sort under `~`. Verified:
`'~~qwen/qwen3.7-max'.lstrip('~') == 'qwen/qwen3.7-max'` but
`.removeprefix('~') == '~qwen/qwen3.7-max'`. Dale must use `lstrip`.

### Why the second `AiModel.name` sort term is mandatory

`~deepseek/tie` and `deepseek/tie` collapse to the same sort key. Without a
tiebreaker the relative order of such a pair is whatever SQLite feels like,
which means it can change between queries and no test can pin it. Ordering by
the raw `name` second makes the pair deterministic — the un-prefixed name sorts
first, because `'deepseek/tie' < '~deepseek/tie'` under binary collation.

### Verified end-to-end against the real app

I seeded the actual app (`create_app("testing")` + `seed_database()`), added the
operator's real case plus adversarial rows, and ran both orderings. Abridged
result — the proposed clause produces exactly the requested outcome:

```
  'deepseek/deepseek-v4-flash'
  '~deepseek/deepseek-v4-flash-latest'   <-- lands between its siblings
  'deepseek/deepseek-v4-pro'
  'deepseek/tie'
  '~deepseek/tie'                        <-- deterministic tie-break
  ...
  'qwen/qwen3.7-max'
  '~~qwen/qwen3.7-max'                   <-- double tilde also folds
  'qwen/qwen3.7-plus'
```

The emitted SQL is
`ORDER BY ltrim(ai_models.name, ?), ai_models.name` — parameterised, so the
`'~'` literal is bound, not interpolated. No injection surface.

---

## 4. Options considered and rejected

**(a) Inline `func.ltrim(AiModel.name, "~")` directly in both `order_by` calls,
no hybrid property.** Two lines total, zero new model code. Rejected, but only
narrowly: it duplicates the sort-key definition across two files, so the next
surface that lists models (a public REST index — a known expected use case per
D-013) makes it three copies that can silently diverge. The hybrid property
costs six lines and gives one canonical definition plus a Python-side accessor
tests can assert against directly. If Dale finds the hybrid property fights the
type checker, falling back to (a) is acceptable — the *behaviour* is identical
and it is the behaviour that gets reviewed. Say so in the PR if you do.

**(b) Sort in Jinja with a custom filter.** Rejected. Jinja's `sort` filter
takes `attribute=`, not a key function, so this needs a new registered filter or
a `sort(attribute='sort_name')` that still depends on the model property — i.e.
strictly more machinery than (a) or the recommendation. It would also have to be
applied twice (both templates) and it moves ordering off the query, which means
the row order in the HTML no longer matches the row order the query promises.

**(c) Re-sort the result list in Python inside the route.** Rejected on
precedent: `_research/2607251644_models-listing-spec.md:167-168` rules "Keep the
default sort as the data's natural order... Do NOT re-sort in the route", and
D-008 cited exactly that line to reject a route-level view-model for modalities.

  Worth stating plainly for Kova, because it looks close to the line: the
  recommendation does **not** violate that ruling. The sort already lives in the
  route's query (`.order_by(AiModel.name)` is there today). Changing the
  `ORDER BY` *expression* keeps the ordering where it already is — in the
  database, as the data's natural order. The prohibition is on fetching rows and
  then re-sorting them in Python, which this does not do.

**(d) Change `order_by` on a relationship or add a computed column.** Rejected.
There is no relationship involved, and a stored/generated column means an
Alembic revision for a presentation concern. If it were chosen it would be a §B
question. It is not chosen, so it is not one.

**(e) Normalise on write — strip the `~` at creation time, or store a separate
canonical name.** Rejected and out of scope. It destroys or duplicates operator
data to solve a display problem, and `name` is deliberately immutable for both
roles (D-012). A schema change of this kind *would* be a §B blocking question;
raising it is unnecessary because the display-only fix satisfies the request
completely.

---

## 5. Edge cases, all confirmed by execution

| Input | Sort key | Behaviour |
|---|---|---|
| `deepseek/deepseek-v4-pro` (no `~`) | unchanged | No-op. All 23 existing rows keep their current relative order. |
| `~deepseek/deepseek-v4-flash-latest` | `deepseek/deepseek-v4-flash-latest` | Sorts between `...-flash` and `...-v4-pro`. The requested outcome. |
| `~~qwen/qwen3.7-max` (multiple `~`) | `qwen/qwen3.7-max` | All leading tildes stripped. |
| `z-ai/glm-5.2-tilde~inside` | unchanged | Interior/trailing `~` untouched — `ltrim` is leading-only. |
| `~deepseek/tie` vs `deepseek/tie` | identical | Deterministic via the `name` tiebreaker; un-prefixed sorts first. |
| `~` / `~~` (name is only tildes) | `''` | Sorts to the very top. Reachable — `app/routes/admin.py:320-323` only rejects empty and >128 chars — but degenerate and harmless. Do not add validation for it; that would be scope creep into the create contract. |
| `Zebra/uppercase` | unchanged | Uppercase still sorts before lowercase. **Pre-existing** binary-collation behaviour, not introduced or fixed here. See §A item 5. |

---

## 6. Test guidance for Dale

Add to `tests/test_models_listing.py` (it already owns `/` rendering
assertions). Do **not** modify the 16 `order_by(AiModel.name)` call sites in
`tests/test_admin_models.py` — those are row-fetch helpers, not ordering
assertions, and the change must not require touching them. If it does, something
is wrong with the implementation.

Three tests, minimum:

1. **`/` places a tilde-prefixed model among its siblings.** Seed, insert
   `~deepseek/deepseek-v4-flash-latest`, GET `/`, and assert on the *positions*
   of the three `deepseek/` names in the response HTML — i.e. compare
   `html.index(...)` values, not just membership. A membership assertion passes
   under the old behaviour and proves nothing.
2. **`/admin/models/manage` orders identically.** Same shape, same assertion,
   against the admin surface. This page is not role-gated for GET
   (`app/routes/admin.py:217-230` has no decorator), so the plain `client`
   fixture reaches it.
3. **Sort-key unit test.** Parametrised over the §5 table, asserting the
   `sort_name` property directly: no tilde is a no-op, one and two leading
   tildes both fold, an interior tilde survives. This is where the
   `lstrip`-vs-`removeprefix` distinction gets pinned.

Confirm red-before / green-after: test 1 must fail against `28edfac`.

`tests/test_models_listing.py:76-92 test_index_page_uses_bounded_query_count`
asserts exactly 3 queries for `/`. Changing an `ORDER BY` expression does not add
a query, so that assertion should still pass untouched — if it fails, the
implementation strayed. Run the full suite; the baseline is 155 passed.

---

## 7. Files to change

1. `app/models/ai_model.py` — add `sort_name` hybrid property; import
   `hybrid_property`. (`func` already imported at `:37`.)
2. `app/routes/main.py:22` — order by `sort_name`, then `name`.
3. `app/routes/admin.py:226` — same.
4. `tests/test_models_listing.py` — three new tests per §6.

Nothing else. Specifically: no migration, no template change, no JavaScript, no
`app/commands.py` change, no `sample_models.py` change, no new endpoint, no
change to any existing test.

---

## §A — Assumptions taken

1. **The change is presentation-only; stored names keep their `~` verbatim.**
   Nothing normalises, strips, or duplicates the name on write, and `name`
   remains immutable for both roles per D-012. *Reversal cost: none for the
   display behaviour. Choosing otherwise later means a schema change plus a data
   migration and would be a §B question at that time.*

2. **All leading tildes are stripped, not just the first, and the exact name is
   the secondary sort term.** `ltrim`/`lstrip` semantics, not `removeprefix`.
   *Reversal cost: trivial — one expression in one property.*

3. **Both listing surfaces get the new ordering** (`/` and
   `/admin/models/manage`). Two views of the same data ordering differently is a
   bug, not a feature, and the operator would have to ask for that explicitly.
   *Reversal cost: trivial — revert one line.*

4. **The sort key is defined once, as a `hybrid_property` on `AiModel`**, rather
   than inlined at both call sites. Falling back to inline `func.ltrim` is
   acceptable if the property causes friction (§4a). *Reversal cost: trivial,
   and the observable behaviour is identical either way.*

5. **Case-sensitivity of name ordering is unchanged and out of scope.** SQLite's
   default binary collation sorts `Zebra/x` before `anthropic/x`. That is today's
   behaviour on `main`, the operator did not raise it, and no seeded name has an
   uppercase leading character. D-010 records the same standing trap for
   modality sorting. *Reversal cost: low but not free — adding `COLLATE NOCASE`
   or a `lower()` wrapper changes ordering for any future mixed-case name and
   needs its own test. Raise it as a separate card if the operator wants it.*

6. **No functional index is added.** `ORDER BY ltrim(name, '~')` cannot use the
   existing index on `ai_models.name`; SQLite falls back to `USE TEMP B-TREE FOR
   ORDER BY` (confirmed via `EXPLAIN QUERY PLAN`). At 23 rows this is
   unmeasurable. *Reversal cost: one Alembic revision adding an expression index
   if the table ever grows enough to matter — additive, no data change.*

7. **SQLite is the only backend that has to work.** `SQLALCHEMY_DATABASE_URI`
   defaults to `sqlite:///app.db` (`app/config.py:17`) and every environment in
   `config` inherits it. `ltrim(string, chars)` is confirmed working on SQLite
   3.53.1 and has the same two-argument signature on PostgreSQL. MySQL's `LTRIM`
   takes only one argument, so a MySQL port would need `TRIM(LEADING '~' FROM
   name)`. *Reversal cost: one expression in one place, and only if the project
   ever moves to MySQL — which nothing suggests it will.*

## §B — Decisions required (BLOCKING)

**None.** Every question this work raises reverses at trivial or low cost, and
none of them touches the database schema, a migration, the role/permission model,
an API request or response contract, or a test that pins shipped behaviour. The
one question that *would* meet the §B test — normalising names on write (§4e) —
is rejected outright rather than deferred, because the display-only change fully
satisfies the request. This document hands off to `t_a7bbc3b7`.
