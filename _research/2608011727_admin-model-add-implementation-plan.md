# Admin model addition — implementation plan (reconciliation)

Card: t_f093d8cf ("Research implementation plan for admin model addition")
Root: t_d3b3414f
Author: chip
Date: 2026-08-01 17:27 EDT
Repo state at time of writing: branch `feat/admin-add-model` @ `40585e5`, `origin/main` @ `5c6adce`, PR #7 OPEN

---

## 0. Headline: this feature is already built

This card asks for a plan to implement something that was implemented, reviewed,
and pushed over the previous 24 hours. The auto-decomposer re-decomposed the root
card t_d3b3414f on its third block and produced a fresh research → implement → review
chain (t_f093d8cf → t_d883a726 → t_876b9565) that duplicates the chain already
completed (t_3eb0e09b → t_9cb478fc/t_692c857c → t_fa175a0e/t_c288c232/t_9352d96a).

I verified against the repository and the GitHub API rather than against handoff
prose. Current facts:

| Requirement from the root card | State |
|---|---|
| Web-interface authentication exists and is visible | DONE — merged `5c6adce` (PR #6) |
| Administrator can add a model from the web interface | DONE — `feat/admin-add-model` @ `40585e5`, PR #7 |
| Name required | DONE — `app/routes/admin.py:224-228` |
| All-or-nothing on other attributes | DONE, resolved to "all always required" by ruling D-005 |
| Branch, push, PR opened | DONE — PR #7, base `main` (auto-retargeted after #6 merged) |
| PR review performed | DONE, but **gated**: `reviewDecision=CHANGES_REQUESTED` from `etkeys` |

So the honest plan is not "how to build this." It is: **what is actually left, and
what must not be rebuilt.** Section 5 is the part an implementer should act on.

---

## 1. What exists, with citations

### 1.1 Authentication (merged to `main`)

Opaque API-key bearer tokens, no passwords, no users table. Backend merged as
`6c2144e` (PR #5); browser UI merged as `5c6adce` (PR #6).

- `app/auth/decorators.py:48` — `require_role(role)`; 401 when unauthenticated,
  403 when the principal's rank is below the required role.
- `app/auth/decorators.py:190` — session teardown gated at `ROLE_UPDATER`.
- `app/static/js/auth.js` — token store (sessionStorage), `authFetch` wrapper,
  sign-in dialog, principal display, sign-out.
- `app/templates/base.html:13` — `#auth-control`, the header sign-in affordance.
  This is the element whose absence the root card described as "no visible way to
  authenticate." That gap is closed.
- `app/templates/base.html:18` — `#admin-models-link`, hidden by default, revealed
  by `auth.js:208/230` when the principal's role is `administrator`.

Roles are rank-ordered `updater < administrator`. Ruling **D-007** (Erik,
2026-08-01) defines `updater` as a scraper role for value updates on existing
rows; structural writes (creating models) are administrator-only.

### 1.2 Model creation endpoint

`app/routes/admin.py:219` — `POST /admin/models`, decorated `@require_role(ROLE_ADMINISTRATOR)`.

Validation order, all server-side:
1. `name` present, non-blank after strip, ≤128 chars → else 400.
2. All of `price_in`, `price_out`, `context_tokens`, `input_content`,
   `output_content` present and non-empty → else 400 "All model attributes are required".
3. Numeric coercion; finite, prices ≥ 0, `context_tokens` > 0.
4. Modality lists: non-empty list of strings, no duplicates, subset of
   `ALLOWED_MODALITIES`, all resolvable to `modalities` rows.
5. Name uniqueness → 409, with an `IntegrityError` catch as the race backstop.
6. Insert `AiModel` plus ordered `AiModelInputModality` / `AiModelOutputModality`
   association rows (`position` preserves the submitted order).
7. `201 {id, name}` with `Cache-Control: no-store`.

`app/routes/admin.py:213` — `GET /admin/models/manage` is a **public shell**, no
role decorator. This is correct and deliberate: a top-level browser navigation
cannot carry an `Authorization` header, so page routes are public and the data
endpoints are protected. Nothing sensitive renders in the shell — only the list of
allowed modality names.

### 1.3 Form and client validation

- `app/templates/admin/models.html` — the form; scalar inputs carry native
  `required`, modality groups are checkbox fieldsets.
- `app/static/js/admin-models.js:46-60` — group-level required check, producing
  "<Field> is required." This is the intended enforcement point for the checkbox
  groups; native HTML cannot express "at least one of this checkbox group."
- `app/static/js/admin-models.js:73` — posts via `authFetch`, never a
  `<form method=post>`. This is what keeps CSRF structurally absent: no ambient
  credential, so no cross-site forgery surface.

### 1.4 Tests

`tests/test_admin_models.py` — 15 cases at `40585e5`, 134 in the full suite.
Two of them encode **policy, not behaviour**, and must not be "fixed":

- `test_updater_returns_403` — stays 403 per D-006/D-007.
- `test_all_optional_missing_returns_400` — stays 400 per D-005.

---

## 2. The design question the card poses, and why it is already answered

The card body says: "other attributes can be provided but if one is given all must
be provided." Read literally, that permits a name-only model.

It cannot work as written. `app/models/ai_model.py:96-107` declares `price_in`,
`price_out`, and `context_tokens` as `nullable=False`. A name-only row is
physically unstorable without a migration.

I raised this as **D-005** and recommended making the columns nullable. Erik
**rejected** that and ruled option B: the schema wins, all attributes are always
required, no migration. The implementation and the form copy at
`app/templates/admin/models.html:8` ("All model attributes are required") now match
that ruling.

Consequence for whoever picks up t_d883a726: **the card body's all-or-nothing
wording is superseded.** Implementing it literally would contradict a standing
operator ruling and require a schema migration Erik declined. Do not reopen D-005.

Likewise **D-006**: gate at `administrator`, not `updater`. I recommended `updater`;
Erik rejected that too and added D-007 to give `updater` a coherent purpose
(value-updates on existing rows, a future scraper endpoint). `@require_role(ROLE_ADMINISTRATOR)`
on `POST /admin/models` is correct as it stands.

Rulings source: the completion handoff on t_17b0af72 (see §6). Note that the brief
that carried them, `_research/2608011704_model-create-policy-ruling-followup.md`,
**no longer exists on disk and was never committed** — see §6.

---

## 3. Known open defect (already routed, do not duplicate)

At `40585e5`, `app/templates/admin/models.html:37,47` marked the first checkbox in
each modality fieldset `required` via `{% if loop.first %}`. HTML `required` on a
checkbox constrains that one box, not the group — that is radio semantics. The list
renders from `sorted(ALLOWED_MODALITIES)`, so the constrained box is "Audio."

Effect: the form is unsubmittable unless the user ticks Audio in both groups, and
because the form has no `novalidate`, native validation blocks submit before the
correct JS group check ever runs. All 134 tests pass because none of them render
the form.

Found by Suki during root-card verification; routed to **t_e8df9b08** (dale) →
**t_19b35200** (kova). As of this writing that fix is in progress in the working
tree — `app/templates/admin/models.html` and `tests/test_admin_models.py` are
modified and the `loop.first` attributes are already gone. Nobody else should touch
those two files.

---

## 4. Gaps I found that are not yet routed

### 4.1 README does not document `POST /admin/models`

README §"Creating and using API keys" documents the key endpoints; there is no
section for model creation. README:81 still says updaters "can perform mutating
actions on model data (once those endpoints exist)" — under D-007 that sentence is
now misleading, because the one mutating endpoint that exists is administrator-only
and updaters cannot reach it.

Recommended edit, small and self-contained:
- Amend README:81 to state that `updater` is reserved for value-updates on existing
  model rows (D-007) and grants no access to model creation.
- Add a short "Adding a model" subsection: administrator sign-in via the header
  control, the "Add Model" nav link, all attributes required, and the equivalent
  `curl` for `POST /admin/models`.

This is the "update any documentation as needed" clause of t_d883a726, and it is
the only genuinely unfinished implementation work I can find.

### 4.2 Rendered-template test coverage is near zero

The checkbox defect shipped past two agents and one human because 134 tests all
post JSON and none render HTML. t_e8df9b08 adds one narrow regression assertion,
which closes this instance but not the class. Worth a follow-up card, not worth
blocking on: a handful of assertions over `GET /admin/models/manage` and
`GET /admin/keys/manage` covering presence of the form, the modality options
matching `ALLOWED_MODALITIES`, and absence of any `required` checkbox.

### 4.3 PR #7 is human-gated

`reviewDecision=CHANGES_REQUESTED`, `mergeStateStatus=BLOCKED`, from `etkeys`.
All six of Erik's inline comments are addressed by `40585e5` — his review is stale
relative to HEAD, not unsatisfied. **No agent can clear this.** Erik must dismiss
his review or re-review. This is the correct behaviour and should not be worked
around.

---

## 5. Instructions for the implementer (t_d883a726)

Do **not** create a new branch, and do **not** re-implement the feature. The card
body was written by the auto-decomposer without knowledge of the existing PR.
Concretely:

1. **Wait for t_e8df9b08 to land.** Dale is mid-run on `feat/admin-add-model` in
   this same working directory. Two workers committing to one branch in one shared
   directory is a collision, not a merge. Confirm the working tree is clean and
   `origin/feat/admin-add-model` has advanced before doing anything.
2. **Scope of remaining work: README only** (§4.1). One commit onto the existing
   `feat/admin-add-model` branch, pushed to PR #7. No new PR.
3. **Do not touch** `app/routes/admin.py` validation, the two policy tests in §1.4,
   or the schema. All three are Erik-ruled.
4. **Do not add `novalidate`** to the form. The scalar `required` attributes are
   correct; only the checkbox ones were wrong.
5. Full suite must pass. It is 134 at `40585e5` and will be 135+ after t_e8df9b08.

For the reviewer (t_876b9565): the substantive review already happened
(t_fa175a0e, t_c288c232, t_9352d96a) and t_19b35200 covers the checkbox fix. If
t_876b9565 dispatches, the only new surface is the README delta — review that and
say so plainly rather than re-reviewing 700 lines of already-approved diff.

---

## 6. Decision log referenced

| ID | Question | Ruling | Source |
|---|---|---|---|
| D-005 | Should name-only model creation be valid? | **B** — schema wins, all attributes required, no migration. My recommendation (A, nullable) rejected. | Erik, 2026-08-01 |
| D-006 | Gate model writes at `updater` or `administrator`? | **2c** — administrator only. My recommendation (2a, updater) rejected. | Erik, 2026-08-01 |
| D-007 | Then what is `updater` for? | Scraper role: value-updates on existing rows. Structural writes are administrator. | Erik, 2026-08-01 |

Prior artifacts, and a warning about them:

- `_research/2607302045_web-auth-ui-gap-analysis.md` — exists on disk, uncommitted.
- `_research/2607302123_model-create-policy-decisions.md` — **missing.** Cited by
  Suki on the root card; not on disk, not in any branch.
- `_research/2608011704_model-create-policy-ruling-followup.md` — **missing.**
  Cited in the t_17b0af72 handoff metadata as `artifact_committed: false`; not on
  disk, not in any branch.

This repo's convention of leaving `_research/` artifacts uncommitted has now cost
two decision briefs. The D-005/D-006/D-007 rulings survive only in the t_17b0af72
kanban handoff metadata, which is why I transcribed them into the table above
rather than linking out. **Recommend committing `_research/` going forward**, or at
minimum committing any document that records an operator ruling. A ruling that
exists in exactly one place, and that place is a scratch directory, is a ruling
that will be relitigated.

### Erik commentary
(Erik) I'm adding my commentary to this document to add insight.
On the evening of 2026-07-30, Chip and I discussed how questions could be surfaced to me sooner, ahead of implementation.
Chip suggested a decisionlog, DECISION.md, and he created the file.
All the items in there were based on information that he was able to recompile and knew knowledge from earlier in our discussion.
He left me with homework to finish filling out the decision log.
Chip also created an AGENTS.md file to help sign post conventions for the rest of the team.

I created t_47aec77f (meant for Dale but I forgot to assign to him) and t_9352d96a assigned to Kova.
Both of these tickets were to address "optional" wording still present in the code base after Chip and I discussed D-005.
Wording on this ticket pair explicitly said that there were untracked files in the local repo and they must be preserved.
When the auto-decomposer ran again, the "leave untracked files as they are" requirement must not have got passed along.
The DECISION.md and AGENTS.md file that Chip created on the 30th were deleted from disk.
However, anticipating this event, I created copies of DECISIONS.md and AGENTS.md.
The copies I have are current as of the morning of 2026-08-01.
I'll be pushing these documents in a separate commit after PR#7 is merged.

