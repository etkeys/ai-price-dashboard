# DECISION: who may hide/unhide a model?

- Card: `t_66c8528e` (research, chip). Blocks `t_736da718` (backend, dale),
  `t_266a1995` (frontend, dale), `t_51953389` (review, kova). Root `t_3c65170f`.
- Author: Chip
- Date: 2026-08-05
- Status: **RULED 2026-08-05 — (a) administrator only.** Erik: *"An updater may
  not hide models. Only administrators can do this."* Transcribed to
  `_research/DECISION.md` as D-019 (`CONFIRMED`). Retained as the reasoning
  record; the binding statement is in `DECISION.md`.
- Code state: commit `d2055d6` on `main` (clean tree), branch `main`, Alembic
  head `248f2949289c`, 163 tests passing.
- Companion plan: `_research/2608050700_model-inactivation-implementation-plan.md`

---

## 1. May an `updater` hide/unhide a model, or is this administrator-only?

### The conflict

The feature adds one new endpoint, `PUT /admin/models/<int:model_id>/hidden`.
Every model-write route needs a role gate, and the two existing precedents point
in opposite directions for this one.

**Pointing at `administrator`:**

D-007 (CONFIRMED) draws the line at **row lifecycle**:

> Structural writes (`POST`/`DELETE` on models) → `administrator` only.
> [...] It must never create or delete models.

Hiding is not a value sync. It is a statement about whether a model should exist
*on the dashboard* — the nearest thing this app has to deletion, and the reason
the operator asked for it was explicitly *instead of* deletion. In the code as it
stands, `POST /admin/models` is gated `@require_role(ROLE_ADMINISTRATOR)`
(`app/routes/admin.py:312-313`) and there is no `DELETE` route at all, so hiding
would become the only lifecycle-shaped operation on models.

**Pointing at `updater`:**

D-012 (CONFIRMED) supplies the governing test, and Erik's own words widened the
role once already:

> The governing test for an `updater` gate is now: *does this operation sync an
> existing row with its upstream source?* If yes → `updater`. If it changes
> which rows exist → `administrator`.

Hiding does not change which rows exist — the row is still there, still unique,
still `PATCH`-able. And there is a real scraper story: when OpenRouter retires a
model, the scraper is the first thing to notice. If an `updater` may hide, the
dashboard prunes itself. If not, dead models accumulate until a human intervenes.

D-012 also recorded Erik overruling my narrower recommendation, with the
rationale *"Updater is essentially trying to sync source data with data within
the app."* That rationale reads either way here, which is precisely why I am not
guessing.

### Why this is blocking rather than an §A assumption

It meets the AGENTS.md §B test on three counts:

- **the role / permission model** — it defines what `updater` means for a whole
  new class of operation;
- **an API request or response contract** — the difference is 403 versus 200 for
  an entire role, permanently;
- **the shape of a test that will get pinned as intended behaviour** — §6 item 2
  of the plan is a role-gate test that becomes the durable answer.

And AGENTS.md §2 names this exact question as the precedent for the rule:

> in `2607302045_web-auth-ui-gap-analysis.md` §9, the `updater`-vs-`administrator`
> gating question was filed as non-blocking [...] Code shipped on the assumed
> answer. The question resurfaced a day later [...] Do not repeat it.

Same roles, same kind of endpoint, same temptation. Filing it as an assumption
would be repeating it.

### Options

**(a) Administrator-only.** `@require_role(ROLE_ADMINISTRATOR)`. Hiding is a
human curation decision about what the dashboard shows; a scraper never makes it.
Consistent with `POST` and with D-007's row-lifecycle line, read broadly.
Cost: a retired upstream model keeps showing a stale price until a human hides
it. On a 22-row dashboard, that is a minor annoyance.

**(b) Updater-and-administrator.** `@require_role(ROLE_UPDATER)` — the existing
rank check admits both. Lets a scraper prune models that vanished upstream, so
the dashboard self-maintains. Consistent with D-012's literal test, since no row
appears or disappears.
Cost: a scraper bug can blank the dashboard. It is fully reversible (the manage
page still lists hidden models and unhide is one click), so the blast radius is
annoyance, not data loss. But it means an automated process can decide what a
human sees.

**(c) Split: `updater` may hide, only `administrator` may unhide.** Models the
intuition that pruning is mechanical and restoring is a judgement call.
**I recommend against it.** It needs in-handler role branching on the boolean in
the request body — the exact per-field gating D-012 explicitly ruled out
("No in-handler `is_administrator` split, no per-field gating"). It also creates
a state a scraper can enter and not leave, which is a support burden out of
proportion to a display flag.

### Chip recommends: (a) administrator-only

Three reasons, in order of weight.

1. **Hiding is the deletion this app deliberately does not have.** The operator
   asked for hiding *because* deletion was the wrong tool — "we may care about
   them again in the future". That framing makes it the row-lifecycle decision
   D-007 reserves for humans, even though no row is removed.
2. **Narrowing later is a contract break; widening later is free.** If `updater`
   can hide and we regret it, revoking is a 403 for a client that previously got
   200 — the same trap D-012's own reversal-cost note flagged. Going the other
   way, granting `updater` the power later costs one decorator argument and one
   test edit, with no client breakage. Given genuine ambiguity, take the
   reversible side.
3. **The scraper story is speculative.** No scraper exists yet — D-007 records
   that `updater` today can only call `DELETE /auth/session`. Automatic pruning
   is a feature nobody has asked for, and it can be granted the day someone does.

Counter-argument, stated fairly: if you already picture the scraper hiding
retired models without waking you up, (b) is the right answer and my reason 3
evaporates. You overruled me on D-012 for adjacent reasons and the ruling was
correct. This is a genuine coin-flip on intent, which is why it is here rather
than in §A.

---

## What I need from Erik

**One question.**

> **D-019 — Who may hide/unhide a model via
> `PUT /admin/models/<int:model_id>/hidden`?**
>
> - **(a)** Administrator only. *(Chip recommends.)*
> - **(b)** Updater and administrator.
> - **(c)** Updater may hide, administrator only may unhide. *(Chip recommends
>   against — contradicts D-012's no-per-field-gating ruling.)*

A one-word answer unblocks everything. A sentence of rationale settles the gate
for the next model-lifecycle endpoint without another round trip — that is the
part D-007 and D-012 have both proven worth more than the ruling itself.

Two smaller things that are **not** questions, flagged so you can veto them
cheaply if I have read you wrong. Both are recorded as §A assumptions in the
plan and I will proceed on them unless you say otherwise:

- Storage is a nullable `hidden_at DATETIME` (matching `ApiKey.revoked_at` and
  friends), not an `is_active` boolean. The API is `{"hidden": true|false}`
  either way, so this stays internal.
- The public dashboard `/` hides them; the admin manage page keeps listing them,
  visually marked, because that is the only place to get one back.

---

## Implementation cards to spawn once ruled

No new cards are needed — the decomposition already created them. The ruling
converts directly into work:

| Card | Assignee | What changes on the ruling |
|---|---|---|
| `t_736da718` | dale | Gate on `set_model_hidden`, and §6 test 2 (the 403 test) written to the ruled role. Everything else in the plan is ruling-independent. |
| `t_266a1995` | dale | Whether the Hide/Unhide button is gated behind `isAdministrator()` in `app/static/js/admin-models.js` (the pattern at `:22-24`), or shown to any signed-in principal. |
| `t_51953389` | kova | Review criterion: the gate matches D-019 exactly, and the 403 test pins the excluded role. |

Sequencing note for Suki, independent of the ruling: `t_736da718` and
`t_266a1995` are not truly parallel — the frontend consumes `is_hidden` on the
template context and the new endpoint. Same assignee either way, so one branch
covering both is simplest.

Once ruled, I transcribe the answer into `_research/DECISION.md` as D-019,
finish the plan's §B, comment the ruling onto Dale's and Kova's cards, and
complete `t_66c8528e`.
