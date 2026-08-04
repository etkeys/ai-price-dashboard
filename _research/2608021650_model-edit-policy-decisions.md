# Decision brief — model edit access for `updater` and `administrator`

- Card: `t_d833f297` (research; children `t_1de70700` Dale, `t_54e744a4` Kova)
- Root card: `t_23aec619` — "Allow administrator and updater to edit a model."
- Author: Chip
- Date: 2026-08-02
- **Status: RULED 2026-08-02.** Q1 → option (a) (Chip's recommendation (b)
  rejected). Q2 → option (a) (Chip's recommendation accepted). Q3 drew no
  ruling. Transcribed to `_research/DECISION.md` as **D-012**, **D-013**
  (both CONFIRMED) and **D-014** (ASSUMED). Those entries are now authoritative;
  this brief is retained only as the record of how they were reached.
- Code state: branch `fix/alphabetical-modality-display`, commit `c53ff97`,
  Alembic head `248f2949289c`, 135 tests passing, working tree clean at time of
  writing.
- Companion plan: `_research/2608021645_model-edit-implementation-plan.md`

Nothing has been implemented. Two questions must be answered before Dale starts,
because each one changes something AGENTS.md §2 defines as blocking.

---

## Question 1 — Which fields may an `updater` edit?

### The conflict

The root card `t_23aec619` says, in full:

> Focus is web ui. All fields should editable except Model Name.

Applied to both roles, that grants `updater` the ability to change
`input_content` and `output_content` — the modality lists.

D-007 (**CONFIRMED**, `_research/DECISION.md:136-157`) says:

> The `updater` role exists for **agents that scrape pricing data on a regular
> basis and update existing model records.** … Value updates on existing models
> (`PATCH`/`PUT` on **price and context fields**) → `updater` is the correct gate
> when that endpoint is built.

D-007 names price and context. It does not name modalities. It also states the
general test to apply:

> Any new endpoint must be classified as structural or value-mutating before a
> gate is chosen.

A modality list is genuinely ambiguous under that test. It is not row lifecycle
— the model still exists, nothing is created or deleted, so by the letter of
D-007 it is not "structural". But it is also not a scraped price: changing a
model from `Text` to `Text, Images` is a claim about what the model *is*, and it
rewrites rows in `ai_model_input_modalities` / `ai_model_output_modalities`
rather than a column on `ai_models`.

The concrete stakes: a compromised or buggy scraper key. Under option A it can
silently rewrite the capability metadata of every model in the dashboard. Under
option B, the worst it can do is publish wrong numbers — which is the risk you
already accepted when you defined the role.

### Relevant code

- `app/services/auth_service.py:46` — `ROLE_RANK = {"updater": 10,
  "administrator": 20}`; `:126-128` — `has_role` is `>=`. So
  `@require_role(ROLE_UPDATER)` admits both roles with no extra machinery.
- `app/models/ai_model.py:144-152` — `input_content` / `output_content` are
  read-only properties over the association tables; editing them means
  delete+insert on `ai_model_input_modalities` / `ai_model_output_modalities`
  (`:55-84`), each row carrying `NOT NULL position`.
- `app/routes/admin.py:220-221` — the create endpoint is
  `@require_role(ROLE_ADMINISTRATOR)`, per D-006.
- `app/services/auth_service.py:64-66` — `Principal.is_administrator` already
  exists, so an in-handler split costs one `if`.

### Options

**A. `updater` edits everything except `name`.** One decorator,
`@require_role(ROLE_UPDATER)`, on one endpoint. Matches the card's literal text.
Simplest possible implementation and the simplest possible mental model:
"updaters edit, administrators also create and delete."
*Cost:* stretches D-007's "price and context" wording to cover capability
metadata. A scraper key can rewrite what every model claims to do.

**B. `updater` edits `price_in`, `price_out`, `context_tokens` only;
modality lists are administrator-only.** Endpoint is gated at
`ROLE_UPDATER`, then the handler checks `principal.is_administrator` before
touching association rows and returns 403 otherwise.
*Cost:* one extra branch, one extra test, and a UI that must disable two
fieldsets for updaters. Matches D-007's enumeration exactly. Narrows the card's
literal wording — which is why it needs your ruling rather than my assumption.

**C. Two endpoints — a value-update endpoint at `updater` and a
metadata-update endpoint at `administrator`.** Cleanest gate story, worst
ergonomics: a single "Save" in the UI becomes two requests with no shared
transaction, so a partial failure leaves the model half-updated.
*Cost:* rejected. The atomicity loss buys nothing that B's in-handler check
does not already buy.

### Chip recommends

**B.** D-007's rationale — "the role is defined by its intended operator — a
scraper, not a person" — reads to me as decisive here. A scraper reads a pricing
page; it does not decide that a model gained vision support. The card's "all
fields" was almost certainly written about *the form the human sees*, not as a
deliberate widening of a role you defined 48 hours ago.

I want to be honest about the counter-argument, because it is not weak: option A
is simpler, matches the card as literally written, and the blast radius of a
wrong modality is embarrassing rather than dangerous. If your instinct is "it's
my dashboard, stop gold-plating", A is a perfectly defensible answer and I will
implement it without complaint.

### Reversal cost

- Ruling A, later want B: one `if` in the handler, one UI change, one new test —
  plus any updater client that was already editing modalities starts getting
  403s. Low, but it is a contract break for a caller that may exist by then.
- Ruling B, later want A: delete one `if`, delete one test. Trivial.

B is the cheaper mistake to make.

---

## Question 2 — May this card add `PATCH /admin/models/<id>`?

### The conflict

Dale's implementation card `t_1de70700` says:

> Verify proper role checks are in place and that the form submission works with
> **the current backend/API**. **Do not create new REST API endpoints**; future
> REST support is a separate card.

This research card `t_d833f297` says:

> Consider any **hidden flags or API calls that might be reused**. The future
> REST API for updates is out of scope; focus on the **existing UI update flow**.

There is no existing UI update flow, and there are no hidden flags. Verified
exhaustively: the only model write path in the repository is
`POST /admin/models` (`app/routes/admin.py:220-308`). There is no `PATCH`, no
`PUT`, no `DELETE`, no JSON read endpoint, and no route anywhere that accepts a
model id. `app/static/js/dashboard.js` is a two-line placeholder. `/` is
server-rendered Jinja with no client data layer
(`app/routes/main.py:13-24`, `app/templates/index.html`).

So the instruction as written makes the card unimplementable. I read the intent
as "don't build the *public agent-facing* REST API — that's the deferred card"
rather than "don't add a server route", but I am not willing to assume that: it
defines an API request/response contract, which AGENTS.md §2 lists as blocking.
The `2607302045` precedent quoted in AGENTS.md is exactly this shape of question
being waved through as obvious.

### Options

**A. Add exactly one endpoint, `PATCH /admin/models/<int:model_id>`**, under the
existing `/admin` blueprint, consumed only by the dashboard's own JS via
`authFetch`. It is not documented as a public API and the deferred card remains
free to design the public surface however it likes.
*Cost:* none beyond the work itself.

**B. Reuse `POST /admin/models` as an upsert.** Rejected outright, and I mention
it only to close it off. It would require relaxing the 409-on-duplicate-name
branch (`app/routes/admin.py:267-268`), which is pinned by
`test_duplicate_model_name_returns_409` (`tests/test_admin_models.py:206`) and
gated at `administrator` per D-006 — so it would simultaneously break a passing
test and silently widen model *creation* to updaters. Strictly worse in every
dimension.

**C. HTML form POST to a new page route.** Contradicts the established
fetch+`authFetch` pattern and `tests/test_web_auth.py:354-367` ("no
`<form method=post>` targets a protected endpoint"), and would need a token in
the form body since auth is header-based by design.

### Chip recommends

**A**, with the deliberate constraint that the count of new endpoints is exactly
one. The plan keeps it at one by server-rendering the existing-models table into
`/admin/models/manage` from the same query `/` already uses, rather than adding
a `GET /admin/models` JSON endpoint. Since `/` is public under D-004, that leaks
nothing new.

### Reversal cost

Low but non-zero. Once the dashboard's JS speaks `PATCH /admin/models/<id>`,
the deferred REST card either adopts that contract or versions around it. If you
would rather the public API design come *first* and the UI be built against it,
say so now — that is a sequencing call only you can make, and it would park this
card behind the REST card rather than ahead of it.

---

## What I need from Erik

1. **Modality edits for `updater`: yes or no?**
   - a) Yes — updater edits everything except `name` (card as literally written).
   - b) No — updater edits `price_in`, `price_out`, `context_tokens`; modality
        lists are administrator-only (D-007 as literally written). **← Chip's
        recommendation**

2. **May this card add `PATCH /admin/models/<int:model_id>`?**
   - a) Yes — one internal endpoint under `/admin`, public REST stays deferred.
     **← Chip's recommendation**
   - b) No — park this card until the public REST API is designed first.

3. *(Optional, not blocking — answer only if you have an opinion.)* Concurrency:
   the plan assumes last-write-wins with no `If-Match` precondition (§A item 5).
   If you want optimistic concurrency, it is much cheaper to decide it now than
   after the deferred REST card ships a contract without it.

---

## Implementation cards to spawn once ruled

Existing children already cover the work; no new cards are needed for the main
path. On a ruling I will:

- Transcribe the answers into `_research/DECISION.md` as **D-012** (Question 1)
  and **D-013** (Question 2), CONFIRMED.
- Finalise `_research/2608021645_model-edit-implementation-plan.md` §4.1 to
  match the ruling and drop §B.
- Comment the binding constraints onto `t_1de70700` (Dale) — in particular
  whichever of these applies:
  - under 1(b): the endpoint is gated `ROLE_UPDATER` but the handler must
    reject association-row writes from a non-administrator with 403, and the
    edit dialog must disable both modality fieldsets for updaters;
  - under 1(a): a single `@require_role(ROLE_UPDATER)` gate, no in-handler
    split.
- Comment the review criteria onto `t_54e744a4` (Kova), including the two
  standing traps: the `getCheckedValues` name-collision between the create and
  edit forms (`app/static/js/admin-models.js:14-16`), and element-level
  `required` on modality checkboxes, which has already caused two remediation
  cards (`t_e8df9b08`, `t_4f256428`).
- Complete `t_d833f297`, which auto-promotes `t_1de70700` to `ready`.

If the ruling on Question 2 is (b), I will instead comment the reason onto
`t_1de70700` and `t_54e744a4` and raise the sequencing change with Suki, since
the root card would then be waiting on a card that does not yet exist.
