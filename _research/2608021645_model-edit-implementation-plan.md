# Model edit access for `administrator` and `updater` — implementation plan

- Card: `t_d833f297` (research), children `t_1de70700` (Dale), `t_54e744a4` (Kova)
- Root card: `t_23aec619` — "Allow administrator and updater to edit a model."
- Author: Chip
- Date: 2026-08-02
- Code state described: branch `fix/alphabetical-modality-display`, commit
  `c53ff97`, Alembic head `248f2949289c`, 135 tests passing.
- Status: **RULED — hands off to `t_1de70700`.** §B is resolved and removed;
  see D-012 and D-013 (both CONFIRMED) in `_research/DECISION.md`. The decision
  brief `_research/2608021650_model-edit-policy-decisions.md` is superseded by
  those entries and is retained only as the record of how they were reached.

---

## 1. The premise of the card is wrong, and that matters

The card says: *"focus on the existing UI update flow"* and *"Consider any
hidden flags or API calls that might be reused."*

There is no existing update flow, and there are no hidden flags. The complete
inventory of model write paths in the repo is one endpoint:

| Path | Method | Gate | File |
|---|---|---|---|
| `/admin/models` | `POST` | `@require_role(ROLE_ADMINISTRATOR)` | `app/routes/admin.py:220-308` |

There is no `PATCH`, no `PUT`, no `DELETE`, no JSON read endpoint for models, and
no route that accepts a model id. `grep` for `PATCH`/`PUT`/`edit` across `app/`
returns nothing outside the modality words "input"/"output". `app/static/js/dashboard.js`
is a two-line placeholder. The listing at `/` is server-rendered Jinja
(`app/routes/main.py:13-24` → `app/templates/index.html`) with no client-side
data layer to hook into.

Consequence: **this feature cannot be built without adding one server-side write
endpoint.** Dale's card (`t_1de70700`) says "Do not create new REST API
endpoints." **D-013 (CONFIRMED) amends that clause:** it prohibits building the
public, agent-facing REST surface, not adding one internal `/admin` route the
dashboard's own JS consumes. Erik's wording: the intent was "a known use case
will need to be implemented eventually and it is similar to this effort and it
may impact choices made now (e.g., choice of route names)". So: exactly one new
endpoint, and its shape is chosen to be adoptable by the future public card.

---

## 2. Field inventory

From `app/models/ai_model.py:87-152` and the migration
`migrations/versions/637848f507e4_...py`:

| Field | Type / constraint | Editable per card? | Notes |
|---|---|---|---|
| `id` | INTEGER PK | no | addressing only |
| `name` | VARCHAR(128) NOT NULL UNIQUE, indexed | **no — explicitly excluded** | `app/models/ai_model.py:93-95` |
| `price_in` | FLOAT NOT NULL, `CHECK (price_in >= 0)` | yes | `:96-99`, `:139` |
| `price_out` | FLOAT NOT NULL, `CHECK (price_out >= 0)` | yes | `:100-103`, `:140` |
| `context_tokens` | INTEGER NOT NULL, `CHECK (context_tokens > 0)` | yes | `:104-107`, `:141` |
| `input_content` | derived list over `ai_model_input_modalities` | yes | property `:144-147`, assoc `:55-68` |
| `output_content` | derived list over `ai_model_output_modalities` | yes | property `:149-152`, assoc `:71-84` |
| `created_at` | DATETIME NOT NULL, server default | no | not user data |
| `updated_at` | DATETIME NOT NULL, `onupdate=func.now()` | no — maintained automatically | `:113-118` |

`input_content` / `output_content` are **read-only properties**, not setters.
Editing them means rewriting rows in the two association tables, each of which
carries a `NOT NULL position` column (`:68`, `:84`) and a composite
`PK(ai_model_id, modality_id)`.

The closed modality vocabulary is `ALLOWED_MODALITIES` at
`app/routes/admin.py:23` — `{Text, Images, Files, Videos, Audio}` — seeded into
the `modalities` table by `app/commands.py`. Per D-001 this is a closed enum, not
a configurable table.

`updated_at` already ticks on any UPDATE via SQLAlchemy's `onupdate`; no work is
needed to keep it current, and nothing in the UI currently displays it.

---

## 3. Permissions as they exist today

- Roles are a closed two-value enum, `administrator` and `updater`
  (`app/models/auth.py:59-61`, CHECK at `:97`). D-001.
- `require_role(role)` (`app/auth/decorators.py:48-65`) compares **rank**, not
  identity: `ROLE_RANK = {"updater": 10, "administrator": 20}`
  (`app/services/auth_service.py:46`), and `has_role` is `>=`
  (`:126-128`). Therefore `@require_role(ROLE_UPDATER)` admits **both** roles.
  That single decorator is the mechanism the card asks for; no new permission
  machinery is required.
- Today `updater` can reach exactly one endpoint: `DELETE /auth/session`
  (`app/auth/decorators.py:189-190`). D-007 recorded that the role is
  "provisioned ahead of its purpose". This card is that purpose arriving.
- Page routes are public shells; data endpoints carry the decorator
  (`app/routes/admin.py:41-44`, `:214-217`; pinned by
  `tests/test_web_auth.py:369-377`). Any new page must follow that split.

### Two real defects in the client-side gating, both in scope

1. `renderAuthHeader()` (`app/static/js/auth.js:203-211`) reveals **both**
   `admin-keys-link` and `admin-models-link` (`app/templates/base.html:17-18`)
   to *any* signed-in principal, including an `updater`. `isAdministrator()`
   is defined at `app/static/js/auth.js:171-174` and **is never called
   anywhere** — verified by grep across `app/` and `tests/`. Cosmetic only
   (the server returns 403 correctly, pinned by
   `tests/test_admin_models.py:32-42`), but it means an updater today is shown
   an "Add Model" link to a form that cannot work for them.
2. Once edit lands on the same page as the create form, that leak stops being
   cosmetic-and-harmless and becomes actively confusing: an updater would see
   an "Add AI Model" form that always 403s. The create section must be hidden
   for non-administrators client-side, with the server gate unchanged.

---

## 4. Recommended design

One new write endpoint, one extended page, no migration, no schema change.

### 4.1 Backend — `PATCH /admin/models/<int:model_id>` in `app/routes/admin.py`

- Gate: `@require_role(ROLE_UPDATER)` — admits updater and administrator by rank
  (`ROLE_RANK` at `app/services/auth_service.py:46`, `has_role` `>=` at
  `:126-128`). **That single decorator is the whole gate.** Per D-012
  (CONFIRMED), an `updater` may edit every field except `name`, modality lists
  included — the role's job is syncing an existing row with its upstream source.
  There is **no** in-handler `is_administrator` split, no per-field gating, and
  no disabled fieldsets in the edit dialog. D-007's row-lifecycle line is
  unchanged: create and delete remain administrator-only.
- Body: JSON object, any **subset** of
  `{price_in, price_out, context_tokens, input_content, output_content}`.
  Empty object → 400. This is a partial update; `PATCH` is chosen over `PUT`
  precisely because `name` is not sent and a `PUT` would imply a whole
  representation.
- `name` present in the body → **400**, not silently ignored. A caller trying to
  rename must fail loudly rather than believe it worked. Same for `id`,
  `created_at`, `updated_at`.
- Validation: reuse the exact rules already written for create
  (`app/routes/admin.py:240-264`) — finite non-negative floats, positive int
  context, each modality list non-empty, no duplicates, subset of
  `ALLOWED_MODALITIES`. **Dale should extract these into module-level helpers
  and have `create_model` call them too**, so the two endpoints cannot drift.
  This is the one refactor worth doing here; anything beyond it is out of scope.
- Unknown model id → 404. Unknown-but-allowed modality name missing from the
  `modalities` table → 400, mirroring `:275-277`.
- Modality update semantics: **full replacement of the supplied list.** Delete
  the existing association rows for that side, insert the submitted names with
  `position = enumerate index`, same as create (`:285-300`). Do not attempt a
  diff/merge — the tables have no surrogate key and a delete+insert inside one
  transaction is both simpler and correct. The other side is untouched if not
  supplied.
- Response: `200` with `{"id":…, "name":…}`, `Cache-Control: no-store` (matching
  `:306-308` and the header convention Kova pinned on the create endpoint).
- **Forward-compatibility with the deferred public REST card (D-013).** Erik
  flagged that a public update API is a known future use case and that choices
  made now — "e.g., choice of route names" — will affect it. Therefore:
  - The path is `/admin/models/<int:model_id>` — id-addressed, singular resource,
    no verb in the path. A public card can mount the same shape under its own
    prefix (`/api/v1/models/<id>`) and reuse the request/response contract
    verbatim rather than versioning around it.
  - Method is `PATCH` (partial update). `PUT` is not used and the path must not
    later be given `PUT` semantics without a new ruling.
  - Request and response are JSON both ways. Do not accept form-encoded bodies.
  - Keep the handler's validation and mutation logic in helpers that a future
    public route can call directly. This is the same extraction §4.1 already
    requires for create/update parity — it now has a second justification.
- `updated_at` needs no explicit handling — `onupdate=func.now()` fires on the
  UPDATE. Note: it will **not** fire if only association rows change and no
  `ai_models` column is dirty. If we want modality-only edits to bump
  `updated_at`, the handler must touch the row explicitly. Recommend doing so;
  it costs one line and keeps the column honest.

### 4.2 Frontend — extend `/admin/models/manage`

Mirror the shape of `app/templates/admin/keys.html`: a table of existing rows
above a create form.

- `models_page()` (`app/routes/admin.py:214-217`) additionally queries the model
  list — the same query as `app/routes/main.py:16-23` — and passes it to the
  template. This leaks nothing: `/` is public by D-004, so the data is already
  world-readable. It also avoids inventing a `GET /admin/models` JSON endpoint,
  keeping the new-endpoint count at exactly one.
- `app/templates/admin/models.html` gains a server-rendered table of existing
  models with an **Edit** button per row, carrying the current values as
  `data-*` attributes (`data-model-id`, `data-price-in`, `data-price-out`,
  `data-context-tokens`, `data-input-content`, `data-output-content`).
- Edit surface: a `<dialog>` modal, consistent with D-002's rationale (less
  context switch) and with the two dialogs already in the codebase
  (`app/templates/base.html:23-41`, `app/templates/admin/keys.html:36-46`).
  The dialog reuses the create form's field set, prefilled from the `data-*`
  attributes, with **Model name rendered as a `readonly` `<input>`** (readonly,
  not `disabled` — it must remain readable and copyable, and it is never
  submitted anyway).
- Submit via the existing `authFetch` wrapper (`app/static/js/auth.js:59-83`),
  which already injects `Authorization`, JSON-encodes object bodies, and
  centrally handles 401 by clearing the token and re-rendering the header. No
  new client auth code.
- Visibility: the edit controls and the models table are shown to any signed-in
  principal; the **create** section is gated on `isAdministrator()` — finally
  giving that dead function a caller. Server enforcement is unchanged and remains
  the authority.
- `app/static/js/admin-models.js` gains the dialog wiring and a `PATCH` submit
  handler alongside the existing create handler. Its `getCheckedValues` helper
  (`:14-16`) queries by `name` attribute globally — the edit dialog's checkbox
  groups therefore need **distinct `name` values** (e.g. `edit-input-content`)
  or the two forms will read each other's checkboxes. This is the single easiest
  bug to introduce in this card; call it out in review.

### 4.3 Tests Dale must add (`tests/test_admin_models.py`, new class)

Red-before/green-after, matching the existing file's style:

1. `PATCH` unauthenticated → 401.
2. `PATCH` as `updater` → 200 for price/context fields (this is the card's whole
   point, and it is the exact inverse of the existing
   `test_updater_returns_403` at `:32-42` — that test covers `POST` and must
   **not** be touched).
2b. `PATCH` as `updater` changing **modality lists** → 200, and the association
   rows are actually rewritten. This test pins D-012 and is the one Kova must
   confirm exists; without it nothing distinguishes the ruled behaviour from the
   rejected option (b).
3. `PATCH` as `administrator` → 200.
4. `PATCH` with `name` in the body → 400, and the persisted name is unchanged.
5. `PATCH` unknown id → 404.
6. Each validation branch: negative price, zero/negative context, unknown
   modality, duplicate modality, empty modality list → 400.
7. Partial update: sending only `price_in` leaves `price_out`,
   `context_tokens` and both modality lists untouched.
8. Modality replacement: submitting a new list replaces the association rows and
   assigns `position` by submitted order. Note this **must not** be written as an
   assertion about display order — `/` renders alphabetically per D-008/D-009.
9. Empty JSON body → 400.
10. Rendered-page regression: the edit dialog's modality checkboxes carry no
    element-level `required` attribute — the same trap that produced
    `t_e8df9b08` and `t_4f256428` on the create form
    (`tests/test_admin_models.py:14-22`).

---

## 5. Files Dale will touch

| File | Change |
|---|---|
| `app/routes/admin.py` | new `PATCH /admin/models/<int:model_id>`; extract shared validators; `models_page()` also passes the model list |
| `app/templates/admin/models.html` | existing-models table, edit `<dialog>`, admin-only wrapper on the create section |
| `app/static/js/admin-models.js` | dialog open/prefill, `PATCH` submit, distinct checkbox `name`s |
| `app/static/js/auth.js` | call `isAdministrator()` when revealing `admin-models-link` / gating the create section |
| `app/static/css/admin-models.css` | styling for the table and dialog |
| `tests/test_admin_models.py` | new `TestUpdateModel` class per §4.3 |
| `README.md` | document the edit workflow and which role may do what |

No migration. No change to `app/models/ai_model.py`. No change to
`app/templates/index.html` or `app/routes/main.py`.

Branch per AGENTS.md §4 — suggest `feat/model-edit`.

---

## 6. Explicitly out of scope

- Any public/agent-facing REST API for updates (the deferred card).
- Model deletion. Structural, administrator-only under D-006/D-007, not asked for.
- Editing the model name. Excluded by the card.
- Retiring the `position` column — D-008 says that needs an Erik ruling first.
- Converting `modalities` into a configurable table — D-001 forbids it.

---

## §A — Assumptions taken

1. **The edit surface is a modal `<dialog>` on `/admin/models/manage`, not
   inline editing on `/`.** `/` is the public dashboard (D-004) and is rendered
   with no client-side data layer; putting write controls there means injecting
   JS into a public page for a minority of visitors.
   *Reversal cost: low.* Template + JS rework on one page; the endpoint and its
   tests are unaffected.

2. **The models table on `/admin/models/manage` is server-rendered from the same
   query as `/`, not fetched from a new JSON endpoint.** Keeps the new-endpoint
   count at one and leaks nothing that `/` does not already publish (D-004).
   *Reversal cost: low.* Adding `GET /admin/models` later is additive.

3. **Modality edits are a full replacement of the submitted list**, with
   `position` reassigned from submission order — identical to create
   (`app/routes/admin.py:285-300`). Display is unaffected: `/` sorts
   alphabetically per D-008, and the checkbox order is already alphabetical per
   D-011.
   *Reversal cost: low mechanically* (rewrite the handler's association block),
   *but* any test written against `position` pins it — see D-009's warning about
   which tests own which behaviour.

4. **`name` in an update payload is rejected with 400, not silently dropped.**
   Silent drops let a caller believe a rename succeeded.
   *Reversal cost: trivial* — one branch and one test.

5. **No optimistic concurrency control.** Last write wins. Two updaters
   scraping the same model concurrently can overwrite each other. Single-user
   dashboard with one automated scraper; the risk is theoretical today.
   Recorded as **D-014 (ASSUMED)** — offered to Erik as non-blocking, no ruling
   given.
   *Reversal cost: moderate.* Adding `If-Match` / `updated_at` precondition
   later changes the request contract and every client that speaks it — and the
   deferred REST API card is the natural place for it to bite. Flagged
   deliberately; re-raise it on that card.

6. **`updated_at` is explicitly touched when only association rows change**, so
   modality-only edits still bump the column.
   *Reversal cost: trivial* — delete one line.

7. **`isAdministrator()` starts gating the create section and the "Add Model"
   nav link.** This fixes a live cosmetic leak (§3) that this card would
   otherwise make worse.
   *Reversal cost: trivial.* Client-side only; the server gate is untouched
   either way.

8. **Shared validation is extracted into helpers used by both create and
   update.** Duplicating ~25 lines of validation across two endpoints is how
   they drift.
   *Reversal cost: none worth counting* — but it does mean `create_model` is
   edited, so Kova should diff it for behaviour change. The create endpoint's
   observable behaviour must not change; all 135 existing tests must still pass
   untouched.

---

## §B — Decisions required (BLOCKING)

**Empty. This document hands off.**

Both prior blockers were ruled by Erik on 2026-08-02 and transcribed to
`_research/DECISION.md`:

1. ~~Which fields may `updater` edit?~~ → **D-012 CONFIRMED, option (a).**
   `updater` edits every field except `name`, modality lists included. One
   `@require_role(ROLE_UPDATER)` decorator, no in-handler split. Chip's
   recommendation (b) was rejected. Rationale: an updater is syncing an existing
   row against upstream source data, and source data can change after creation.
   D-007 is clarified, not superseded — its line remains row lifecycle.
2. ~~May this card add `PATCH /admin/models/<id>`?~~ → **D-013 CONFIRMED,
   option (a).** Yes. The "no new REST API endpoints" clause on `t_1de70700`
   targets the public agent-facing surface, not this internal route. See the
   forward-compatibility constraints in §4.1.

Question 3 (optimistic concurrency) was offered as non-blocking and drew no
ruling. Last-write-wins stands as §A item 5 / **D-014 (ASSUMED)**. The deferred
public REST card is the natural place to revisit it, and is where the cost of
not deciding now would land.
