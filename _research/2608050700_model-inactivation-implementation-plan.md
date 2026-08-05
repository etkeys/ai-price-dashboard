# Model inactivation / hiding — implementation plan

- Card: `t_66c8528e` (research). Implementation: `t_736da718` (backend, dale),
  `t_266a1995` (frontend, dale). Review: `t_51953389` (kova). Root: `t_3c65170f`.
- Author: Chip
- Date: 2026-08-05
- Status: **READY — §B is empty.** D-019 ruled 2026-08-05 (administrator only);
  see `_research/2608050702_model-hide-gating-decision.md` and `DECISION.md`
  D-019. Hands off to `t_736da718` and `t_266a1995`.
- Code state described: commit `d2055d6` on `main` (clean tree), Alembic head
  `248f2949289c`, SQLAlchemy 2.0.51, Flask 3.1.3, SQLite 3.53.1, 163 tests
  passing.

---

## 1. The request

Root card `t_3c65170f`: *"Need a way to not see models that users don't care
about anymore. We don't want to delete them from the system (we may care about
them again in the future, maybe)."*

Two requirements, and only two:

1. A model can be made to stop appearing where models are listed for viewing.
2. The row survives, and the operation is reversible.

Everything else in the auto-decomposer's child-card bodies — "linked resources",
"IDOR on the toggle endpoint", "loading and error states" — is speculative
framing that does not survive contact with this repo. Corrections in §8.

---

## 2. What exists today

There is exactly one model-listing mechanism, rendered on two surfaces. Both are
server-rendered Jinja over a SQLAlchemy query. There is no client-side model
list, no JSON model-index endpoint, and no client-side filtering.

| Surface | Route | Auth | Query |
|---|---|---|---|
| Public dashboard `/` | `app/routes/main.py:13-24` | public (D-004) | `select(AiModel).options(selectinload×2).order_by(sort_name, name)` |
| Admin `/admin/models/manage` | `app/routes/admin.py:217-230` | **GET is ungated** | identical query |

Write paths on models, complete list:

| Route | Gate | Ruling |
|---|---|---|
| `POST /admin/models` | `@require_role(ROLE_ADMINISTRATOR)` | D-006 |
| `PATCH /admin/models/<int:model_id>` | `@require_role("updater")` | D-012, D-013 |

There is **no** `DELETE` on models anywhere — verified against the live URL map.
So "hiding instead of deleting" is not replacing an existing destructive path;
it is the first lifecycle-adjacent operation models have ever had.

`app/models/ai_model.py` currently has seven columns and no lifecycle state.

---

## 3. Recommended approach

### 3.1 Schema — one nullable `hidden_at` timestamp

Add exactly one column to `ai_models`:

```
hidden_at   DATETIME  NULL   DEFAULT NULL
```

`NULL` means visible. A non-`NULL` timestamp means hidden, and records *when*.
No `CHECK` constraint, no index, no new table, no change to any existing column.

Add a `hidden_at` mapped column to `AiModel` alongside `updated_at`
(`app/models/ai_model.py:114-119`), plus an `is_hidden` **hybrid property**
mirroring the existing `sort_name` pattern at `:155-170` (Python side
`self.hidden_at is not None`; SQL side `cls.hidden_at.is_not(None)`). The hybrid
is the canonical predicate so templates, routes and the anticipated public REST
index (D-013) never re-derive it.

**Why a nullable timestamp rather than `is_active BOOLEAN NOT NULL DEFAULT 1`:**

- A boolean needs `NOT NULL DEFAULT`, which on SQLite means a table rebuild
  under `batch_alter_table` with a server default that then lingers in the
  schema. A nullable column is a pure `ALTER TABLE ADD COLUMN` — verified below.
- "When did this stop being interesting?" is free with a timestamp and
  unrecoverable with a boolean. The operator's own phrasing — *"we may care about
  them again in the future, maybe"* — is a temporal statement.
- It matches the convention already load-bearing in this repo: `ApiKey.revoked_at`,
  `AuthSession.revoked_at`, `RecoveryKey.consumed_at` (`app/models/auth.py:82,133,161`)
  are all nullable-timestamp lifecycle flags, and `_key_status()`
  (`app/routes/admin.py:29-35`) already derives a status string from them. A
  boolean here would be the only lifecycle flag in the codebase shaped
  differently from its three siblings.
- **The choice is insulated from the API contract.** The wire format is
  `{"hidden": <bool>}` in both directions regardless of storage (§3.3), so
  switching to a boolean later is an internal migration, not a contract break.
  That is what keeps this out of §B — see §A item 1.

Rejected outright: a `status` enum column (`active|hidden|archived`) — invents
two states the request does not have, and D-001's closed-vocabulary reasoning
argues against a third vocabulary nobody asked for. Also rejected: a separate
`hidden_models` join table — one nullable column on a 22-row table does not need
normalising.

### 3.2 Migration

One Alembic revision, `down_revision = '248f2949289c'`:

```python
def upgrade():
    with op.batch_alter_table('ai_models', schema=None) as batch_op:
        batch_op.add_column(sa.Column('hidden_at', sa.DateTime(), nullable=True))

def downgrade():
    with op.batch_alter_table('ai_models', schema=None) as batch_op:
        batch_op.drop_column('hidden_at')
```

**Do not hand-write this — `flask db migrate` autogenerates it correctly.** I ran
it: it produced exactly the above and nothing else.

No data backfill is required. Every existing row gets `NULL` = visible, which is
the current behaviour, so the migration is behaviour-preserving on its own.

Round-trip verified against a real populated database (22 seeded rows):

```
upgrade   -> cols: [..., updated_at, hidden_at]   rows: 22   index ix_ai_models_name intact
(set 4 rows hidden)
downgrade -> cols: [..., updated_at]              rows: 22   index ix_ai_models_name intact
upgrade   -> clean
```

Note the downgrade discards which models were hidden. That is correct and
acceptable for a reversible display flag; it must be stated in the PR body so
Kova's "migration rollback" criterion is satisfied by a documented answer rather
than a discovered surprise.

### 3.3 Endpoint — `PUT /admin/models/<int:model_id>/hidden`

One new route. Request and response bodies:

```
PUT /admin/models/<int:model_id>/hidden
Authorization: Bearer <session token>
{"hidden": true}                      # or false to unhide

200 {"id": 1, "name": "vendor/model", "hidden": true,
     "hidden_at": "2026-08-05T10:58:14.006272"}     # hidden_at null when visible
```

Design points, each deliberate:

- **`PUT`, not `POST /hide` + `POST /unhide`.** One idempotent state-setter
  instead of two verbs. Re-hiding an already-hidden model is a 200 no-op that
  **preserves the original `hidden_at`** — do not restamp it; the first hide is
  the meaningful timestamp.
- **A `hidden` sub-resource, not a field on `PATCH /admin/models/<id>`.** Two
  reasons, one of which is decisive. The decisive one: `PATCH` is gated at
  `updater` per D-012, so folding `hidden` into it silently grants the hide
  power to updaters and pre-empts D-019 by accident. The secondary one:
  `_validate_model_values(require_all=True)` iterates `_EDITABLE_FIELDS` and
  treats a missing field as fatal, so adding `hidden` to that tuple breaks
  `POST /admin/models` for every existing client. I confirmed both by execution.
  **Dale: `hidden` must not be added to `_EDITABLE_FIELDS`.** The current
  `PATCH` correctly rejects it with `400 Unknown model field`; that behaviour is
  intended and should get a test.
- **Strict boolean validation.** `{"hidden": 1}`, `{"hidden": "yes"}`,
  `{"hidden": null}` and a missing key all return `400`. `isinstance(x, bool)`,
  not truthiness — Python's `1 == True` makes truthiness a real trap here.
- **`Cache-Control: no-store`** on every response, matching every other handler
  in `app/routes/admin.py` and the fix already applied per D-005's follow-up.
- **Errors via `_admin_error(...)`**, reusing the existing helper at
  `app/routes/admin.py:38-41`. No new error shape.
- **Naming anticipates the public REST surface (D-013's binding consequence):**
  resource addressed by id, JSON in / JSON out, a noun sub-resource rather than
  an RPC verb, so the deferred public card can adopt the contract verbatim under
  a different prefix.

The gate on this route is **D-019, now CONFIRMED: `administrator` only.** Decorate
`set_model_hidden` with `@require_role(ROLE_ADMINISTRATOR)`, exactly as
`create_model` is at `app/routes/admin.py:312-313`. An `updater` gets 403. Do not
use `@require_role(ROLE_UPDATER)` — the rank check would admit both roles.

### 3.4 Filtering — which surfaces hide, which show

| Surface | Behaviour | Change |
|---|---|---|
| `/` (public dashboard) | hidden models **excluded** | add `.where(AiModel.hidden_at.is_(None))` to `app/routes/main.py:17-23` |
| `/admin/models/manage` | **all** models shown, hidden ones visually marked | no query change; template + JS only |

This asymmetry is the whole design. The manage page is the only place a hidden
model can be found and unhidden, so filtering it too would make hiding a
one-way door reachable only via `sqlite3`. Kova should treat "the manage page
still lists hidden models" as a required behaviour, not an oversight.

Verified: adding the `WHERE` clause keeps `/` at **exactly 3 queries**, so
`tests/test_models_listing.py:76-92 test_index_page_uses_bounded_query_count`
passes untouched. Hiding every row renders the existing
`No models available.` empty state at `app/templates/index.html:31-34` — that
branch already exists and needs no work.

### 3.5 Frontend

`app/templates/admin/models.html`, the existing-models table (`:13-48`):

1. Add a `Status` column header and cell rendering `Hidden` / `Visible` from
   `model.is_hidden`. Text, not colour alone — colour-only state fails
   accessibility, and Kova's card names accessibility explicitly.
2. Add `data-hidden="{{ 'true' if model.is_hidden else 'false' }}"` to the `<tr>`,
   alongside the existing `data-model-*` attributes the edit dialog already reads.
3. Add a class to hidden rows (e.g. `class="row-hidden"`) and one CSS rule in
   `app/static/css/admin-models.css` — muted text, nothing that reduces contrast
   below legibility.
4. Add a second action button per row in the existing `Actions` cell (`:42-44`),
   next to `Edit`: `Hide` on a visible row, `Unhide` on a hidden one, with class
   `js-toggle-hidden`.

`app/static/js/admin-models.js`:

5. Wire `.js-toggle-hidden` with the same pattern the edit buttons use at
   `:144-149` — read the row's `data-model-id` and `data-hidden`, call
   `authFetch('/admin/models/' + id + '/hidden', {method:'PUT', body:{hidden:!current}})`,
   and `window.location.reload()` on success. On failure, surface
   `data.error` through the existing `showMessage` helper. `authFetch` already
   handles 401 centrally (`app/static/js/auth.js:76-80`), so no bespoke expiry
   handling is needed.
6. **Reload, do not mutate the DOM.** The page's established idiom is
   `window.location.reload()` after every successful write (`:112`, `:200`), and
   D-016 records that no client-side sort or re-ordering exists anywhere in this
   repo. Introducing in-place row mutation here would create the codebase's first
   client-side view state for no benefit on a 22-row table.
7. Visibility of the toggle button follows D-019, now CONFIRMED
   **administrator-only**: gate it the way the create section is gated at
   `:22-24` (`isAdministrator()`), and keep the comment noting the server is the
   authority. An `updater` signed into the manage page sees hidden models listed
   and marked, but no Hide/Unhide control.

No changes to `app/templates/index.html`. The public dashboard simply receives
fewer rows; it has no concept of hidden state and should not gain one.

---

## 4. Options considered and rejected

**(a) `is_active BOOLEAN NOT NULL DEFAULT 1`.** The auto-decomposer's first
suggestion. Behaviourally equivalent, loses the timestamp, needs a rebuild-style
migration with a lingering server default, and breaks the nullable-timestamp
convention `ApiKey`/`AuthSession`/`RecoveryKey` already establish. Rejected on
consistency and information content, not correctness. See §A item 1 for the
reversal cost, which is low precisely because the API contract does not change.

**(b) `deleted_at` / generalised soft-delete.** Rejected as a category error.
Soft-delete means "gone, retained for audit"; the operator explicitly wants
"still here, might come back". Naming it `deleted_at` would mislead every future
reader about whether unhiding is supported, and invites a future card to add a
purge job over rows the operator considers live.

**(c) `status VARCHAR` enum (`active|hidden|archived`).** Rejected. Invents
states the request does not contain. Revisit only if the operator asks for a
third state.

**(d) Fold `hidden` into `PATCH /admin/models/<id>`.** Rejected on two grounds
proven by execution: it silently widens the power to `updater` (D-012's gate),
pre-empting D-019; and it breaks `POST /admin/models` via the
`require_all=True` arity check in `_validate_model_values`. §3.3 has detail.

**(e) Filter in Jinja or in JavaScript rather than in the query.** Rejected.
`_research/2607251644_models-listing-spec.md:167` and D-008 both put row
selection in the query; filtering in the template would ship hidden model names
and prices in the public HTML of a page D-004 keeps deliberately public.

**(f) Add a `?include_hidden=1` query parameter to `/`.** Rejected for now, as
an additive change nobody asked for. It is the natural extension point if the
operator later wants to peek at hidden models without visiting the admin page.
See §A item 4.

---

## 5. Edge cases, all confirmed by execution against the real app

| Case | Behaviour | Note |
|---|---|---|
| Hide, then `GET /` | row absent | verified |
| Hide, then `GET /admin/models/manage` | row **present** | required, §3.4 |
| Hide an already-hidden model | 200, `hidden_at` **unchanged** | idempotent |
| Unhide a visible model | 200, `hidden_at` stays `NULL` | idempotent |
| Unhide | row returns to `/` immediately | verified |
| Hide **every** model | `/` renders `No models available.` | existing empty state, no work |
| Unauthenticated `PUT` | 401 `Authentication required` | via `require_role` |
| Unknown `model_id` | 404 `Model not found` | before any mutation |
| `{"hidden": 1}` / `"yes"` / `null` / missing | 400 | strict `isinstance(..., bool)` |
| `PATCH` with `{"hidden": true}` | 400 `Unknown model field` | current behaviour; pin it |
| `updater` PATCHes a **hidden** model | 200, price updated, **stays hidden** | scrapers keep syncing hidden rows; correct |
| `POST` a name that exists but is hidden | **409 already exists** | see below |
| Query count on `/` after the `WHERE` | **3** | baseline preserved |
| Seed idempotency | counts hidden rows | `seed_database` unchanged |
| `/health` | 200 | untouched |

**The 409 case deserves attention.** Hidden rows still occupy the unique index
on `ai_models.name`, so an administrator who hides `openai/gpt-6` and later
tries to re-add it gets `409 A model named 'openai/gpt-6' already exists` while
staring at a dashboard that does not show it. This is correct behaviour with a
confusing message. **Do not change the uniqueness semantics** — scoping the
unique index to visible rows is a real schema change and would let a hidden row
and a visible row share a name, which breaks the unhide path. The proportionate
fix is message copy: when the 409 is caused by a hidden row, say so, e.g.
*"A hidden model named 'X' already exists. Unhide it from the manage page."*
That is a two-line change in `create_model` (`app/routes/admin.py:331-332` and
the `IntegrityError` branch at `:367-369`) and it should ship with this work,
not as a follow-up. See §A item 5.

---

## 6. Test guidance for Dale

Backend, in `tests/test_admin_models.py` (it owns model-endpoint coverage and
already has the `administrator` / `updater` key fixtures):

1. `PUT .../hidden` unauthenticated → 401.
2. `PUT .../hidden` as an **`updater`** → 403 (D-019 CONFIRMED:
   administrator-only). This is the test that pins the permission model — assert
   the status *and* that the row's `hidden_at` is unchanged. Do not weaken it.
3. `PUT .../hidden` as an **`administrator`**, `{"hidden": true}` → 200, body has
   `hidden: true` and a non-null `hidden_at`; DB row confirms.
4. Idempotent re-hide → 200 and the **same** `hidden_at` as the first call.
   This is the assertion that catches a naive restamp.
5. Unhide → 200, `hidden: false`, `hidden_at: null` in the DB.
6. Body validation, parametrised: `{}`, `{"hidden": "yes"}`, `{"hidden": 1}`,
   `{"hidden": null}` → 400 each. `{"hidden": 1}` is the important one.
7. Unknown `model_id` → 404.
8. `PATCH /admin/models/<id>` with `{"hidden": true}` → 400 `Unknown model field`.
   Regression guard for §4d.
9. `updater` PATCHes a hidden model → 200, value changes, `hidden_at` preserved.
10. `POST /admin/models` reusing a hidden model's name → 409 with the
    hidden-specific message (§5).

Listing behaviour, in `tests/test_models_listing.py` (it owns `/` rendering):

11. Hidden model absent from `/`. Assert on the **name string**, and pair it
    with a positive assertion that a visible sibling *is* present, so a broken
    template cannot make the test pass vacuously.
12. Hidden model **present** on `/admin/models/manage`. This is the test that
    stops a future refactor from "helpfully" filtering the manage page.
13. All models hidden → `/` renders `No models available.`.
14. `test_index_page_uses_bounded_query_count` must still assert 3 and must not
    be edited. If it needs editing, the implementation strayed.

Model unit tests, in `tests/test_models.py`:

15. `is_hidden` is `False` when `hidden_at is None`, `True` otherwise.

Migration:

16. Confirm `flask db upgrade` → `flask db downgrade` → `flask db upgrade`
    round-trips on a populated database with the row count and
    `ix_ai_models_name` intact, and record the output in the PR body. I ran
    this; Dale should re-run it on his branch rather than trusting my transcript.

Baseline is **163 passed**. Tests 11 and 12 must fail against `d2055d6`.

---

## 7. Files to change

Backend (`t_736da718`):

1. `app/models/ai_model.py` — `hidden_at` column, `is_hidden` hybrid property,
   docstring schema block at `:3-11` updated.
2. `migrations/versions/<new>.py` — autogenerated, `down_revision = '248f2949289c'`.
3. `app/routes/main.py:17-23` — add `.where(AiModel.hidden_at.is_(None))`.
4. `app/routes/admin.py` — new `set_model_hidden` handler; hidden-aware 409 copy
   in `create_model`.
5. `tests/test_admin_models.py`, `tests/test_models_listing.py`,
   `tests/test_models.py` — per §6.

Frontend (`t_266a1995`):

6. `app/templates/admin/models.html` — Status column, `data-hidden`, row class,
   Hide/Unhide button.
7. `app/static/js/admin-models.js` — toggle handler.
8. `app/static/css/admin-models.css` — one `.row-hidden` rule.

Explicitly **not** changed: `app/templates/index.html`, `app/commands.py`,
`app/data/sample_models.py`, `app/services/auth_service.py`,
`app/auth/decorators.py`, the modality association tables, and every existing
test. No new dependency.

**Parallelism note for Suki:** the two implementation cards are *not* fully
parallel as the decomposition assumes. The frontend needs `is_hidden` on the
template context and the endpoint to call. Either sequence them (backend first —
it is the smaller card) or have Dale take both on one branch, which given the
same assignee is the simpler answer.

---

## 8. Corrections to the child-card bodies

Stated plainly so Dale and Kova do not chase absent work:

- **"handle edge cases like linked resources"** (`t_736da718`) — there are none.
  The only rows referencing `ai_models` are the two modality association tables,
  and they are `ON DELETE CASCADE` for a delete path that does not exist. Hiding
  touches one column on one row and cascades nowhere.
- **"security issues like IDOR on the toggle endpoint"** (`t_51953389`) — IDOR
  is not applicable. Models are a single global collection with no per-principal
  ownership; every authorised principal may act on every model by design. The
  real authorisation question is the role gate, which is D-019.
- **"Maintain responsiveness"** (`t_266a1995`) — the page is a plain table with
  no responsive breakpoints today. Adding one column is not a responsive-design
  task; do not invent a mobile layout under cover of this card.
- **"Cover loading and error states"** (`t_266a1995`) — the page reloads on
  success, so there is no loading state to design. Error state is the existing
  `showMessage` box.
- **"Provide an optional filter to include hidden models"** (`t_266a1995`) —
  satisfied by the manage page showing everything (§3.4). No filter widget is
  needed on a 22-row table; adding one is scope creep. See §A item 4.

---

## §A — Assumptions taken

1. **Storage is one nullable `hidden_at DATETIME`, not `is_active BOOLEAN`.**
   Filed here rather than in §B because the API contract is `{"hidden": bool}`
   either way (§3.3), so the storage shape is genuinely internal.
   *Reversal cost: low — one additive Alembic revision plus a backfill
   (`is_active = (hidden_at IS NULL)`), the hybrid property's definition, and
   nothing else. No endpoint contract change, no client change, no test rewrite
   beyond the model unit test. Costed in the knowledge that the migration would
   run against a live database.*

2. **`/` filters hidden models; `/admin/models/manage` shows all of them,
   marked.** Two views of the same data disagreeing is normally a bug (D-016),
   but here it is the mechanism that makes hiding reversible — the manage page
   is the only place a hidden model can be found again.
   *Reversal cost: trivial — one `where` clause in one route.*

3. **The endpoint is `PUT /admin/models/<id>/hidden` with `{"hidden": <bool>}`,
   idempotent, preserving the original `hidden_at` on re-hide.** Rejected
   alternatives: `POST /hide` + `POST /unhide` (two verbs for one state),
   folding into `PATCH` (§4d, actively harmful).
   *Reversal cost: low but non-zero and it grows — once the dashboard JS speaks
   this contract, the deferred public REST card (D-013) either adopts it or
   versions around it. Same trap D-013 and D-014 already flagged.*

4. **No `?include_hidden=` parameter on `/`, and no filter widget on the manage
   page.** The manage page showing everything already satisfies the child card's
   "optional filter to include hidden models" at 22 rows.
   *Reversal cost: nil — both are purely additive later, and a query parameter
   defaulting to the current behaviour breaks nothing.*

5. **Name uniqueness continues to span hidden rows; only the 409 message
   changes.** A partial unique index scoped to visible rows would permit a
   hidden row and a visible row to share a name, which makes unhiding
   ill-defined.
   *Reversal cost: high and deliberately so — scoping the index later is a
   schema change plus a resolution rule for the duplicate-name collision it
   creates. This assumption is the cheap side of the trade.*

6. **`updater` may continue to `PATCH` hidden models, and hiding never blocks a
   value sync.** Follows directly from D-012's governing test: a scrape syncs an
   existing row regardless of whether a human finds it interesting.
   *Reversal cost: low — one guard in the `PATCH` handler — but it would be a
   behaviour change deserving its own card, since it makes hiding partly
   destructive of the scraper's job.*

7. **The downgrade discards which models were hidden.** Standard for an additive
   nullable column; documented in the PR body rather than engineered around.
   *Reversal cost: n/a — preserving it would mean an archive table, which is
   disproportionate for a display flag.*

8. **No index on `hidden_at`.** 22 rows; `ORDER BY ltrim(name,'~')` already
   forces a temp B-tree per D-018 item 2, so the scan is already the plan.
   *Reversal cost: one additive Alembic revision if the table ever grows.*

## §B — Decisions required (BLOCKING)

**Empty — D-019 is ruled. This document hands off.**

- **D-019 — May an `updater` hide/unhide a model, or is it administrator-only?**
  **RULED 2026-08-05: administrator only** (option (a), Chip's recommendation).
  Erik: *"An updater may not hide models. Only administrators can do this."*
  Transcribed to `_research/DECISION.md` D-019, status `CONFIRMED`, with the
  generalizing rule for the next endpoint: if the operation answers "should this
  model be here at all?" it is `administrator`; if it answers "what are this
  model's current values?" it is `updater`.

Concretely, this fixes three things that were left open above:

1. §3.3 — `set_model_hidden` is decorated `@require_role(ROLE_ADMINISTRATOR)`,
   matching `POST /admin/models` at `app/routes/admin.py:312-313`.
2. §3.5 item 7 — the Hide/Unhide button is gated behind `isAdministrator()` in
   `app/static/js/admin-models.js` (the pattern at `:22-24`). Keep the comment
   noting the server is the real gate.
3. §6 item 2 — the 403 test is written with an **`updater`** principal calling
   `PUT /admin/models/<id>/hidden` and asserting 403. That is the test that pins
   the permission model; do not weaken it to a smoke test.

`t_736da718` and `t_266a1995` are clear to proceed. Everything else above was
already ruling-independent and implementable as written.
