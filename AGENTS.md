# AGENTS.md — ai-price-dashboard

Conventions for the agent team working this repo: **Suki** (orchestration),
**Chip** (architecture/research), **Dale** (implementation), **Kova** (review).
Operator: **Erik**.

This file is the contract. If a skill, memory, or habit disagrees with it, this
file wins for work inside this repo.

---

## 1. The decisions log is read first, always

`_research/DECISION.md` is the append-only record of operator rulings and
standing agent assumptions.

- **Chip** reads it before writing any research doc or spec, and cites relevant
  entries by ID (`D-003`) instead of re-deriving or re-asking.
- **Dale** treats a `CONFIRMED` entry as binding. If a spec contradicts a
  confirmed ruling, stop and raise it — do not silently pick one.
- **Kova** checks changes against `CONFIRMED` entries as part of review.
- Only **Erik** writes the `Ruling` and `Rationale` fields.

Never edit a `CONFIRMED` entry in place. Add a new entry, mark the old
`SUPERSEDED by D-xxx`.

---

## 2. Research documents

Location: `_research/`. Filename: `YYMMDDHHMM_<slug>.md` (timestamp prefix
first, so chronological sort is free).

Every research doc or spec ends with **two** sections, not one. The old catch-all
"Open questions for the operator" is retired — it was a mailbox with no delivery
and it mixed cheap defaults with schema-changing decisions.

### §A — Assumptions taken

Decisions the author made unilaterally so implementation can proceed. Each item
must state:

1. the assumption in force,
2. **the cost to reverse it.**

Dale proceeds against these. Erik may never read them; that is the point. Each
one gets a corresponding `ASSUMED` entry in `DECISION.md`.

### §B — Decisions required (BLOCKING)

**If §B is non-empty, the document does not hand off.** Chip blocks his task to
get a decision from Erik.

A question belongs in §B if a different answer would change any of:

- the database schema or a migration
- the role / permission model
- an API request or response contract
- the shape of a test that will get pinned as intended behaviour
- anything already shipped on a branch with an open PR

Everything else goes in §A with a stated reversal cost.

> **Precedent for why this rule exists:** in
> `2607302045_web-auth-ui-gap-analysis.md` §9, the `updater`-vs-`administrator`
> gating question was filed as non-blocking with a note that a different answer
> would make the `updater` role pointless "wholesale". Code shipped on the
> assumed answer. The question resurfaced a day later as Question 2 of
> `2607302123_model-create-policy-decisions.md`, after the fact. That question
> met the §B test on two counts and was misfiled. Do not repeat it.
> (Erik commentary): Note that the file `2607302123_model-create-policy-decisions.md`
> was deleted from disks accidentally before it could be committed; however,
> the point being made here is still applicable.

---

## 3. Decision briefs

When §B is non-empty, Chip writes a decision brief — a standalone doc in
`_research/` whose only job is to get a ruling.

Required shape (see `2607302123_model-create-policy-decisions.md` as the
reference implementation):

- Header: card ID, author, date, `Status: awaiting Erik's ruling`, and the exact
  code state it describes (commit SHA, branch, Alembic head).
- One numbered section per question.
- **The conflict**, with real file:line citations. No hand-waving.
- Every viable option, with its true cost — including the ones you reject.
- An explicit recommendation.
- `## What I need from Erik` — the questions reduced to a pickable list.
- `## Implementation cards to spawn once ruled` — so the ruling converts
  directly into work with no second research pass.

Chip blocks his ticket as stating that he needs operator ruling. Once ruled,
Chip transcribes the answer into `DECISION.md`, he finishes his plan, edits
Dale's and Kova's tickets as needed to reflect the ruling (he may only be able
to add comments), and completes his ticket. Dale's implementation tickets will
then auto promote to `ready`.

---

## 4. Implementation and review flow

- Dale must make changes in a branch dedicated to the work being performed.
  He can create as many or a few branches that he deems appropriate.
- Dale must commit all changes, including Chip's created files in `_research/`,
  push them to Github, and open a PR for review.
- Kova will review Dale's work and approve/reject using Github PR approval tools.
- Once Kova approves Dale's work, Erik will do a final review and handle the
  the merge.

Per `_research/2607232050_dale-workflow-update.md` (workflow v2):

> **NOTE:** All instructions here are in addition to the above.

- Dale self-verifies, comments findings on his ticket, and **completes** it.
  He never blocks a ticket as `review-required` — that deadlocks the board.
- Kova's review ticket is a child and auto-promotes to `ready`.
- On changes requested, Kova creates a remediation ticket for Dale and a
  re-review ticket for herself. Forward-flowing only, no cycles.
- Suki and Chip: If either of you need to create additional tickets for
  Dale to do additional work, you must also create child review ticket(s) for
  Kova. Kova's ticket in this situation should have a child that points back
  to the top level parent ticket. This blocks Suki from signaling that all
  work has been completed when that is not true.
- Everyone uses the native `kanban_*` tools, not `hermes kanban` in a shell.

---

## 5. Repo facts worth not rediscovering

- Canonical virtualenv: `.venv/` (`D-000`). `venv/` was removed deliberately.
- Tests: `pytest`. Schema DDL is owned by Alembic / Flask-Migrate, **not**
  `db.create_all()`.
- Closed vocabularies (roles, modalities) are plain enums with CHECK
  constraints, not configurable tables. See `D-001`.
- Research docs are documentation, not code. They are never the place to record
  an operator ruling — that is `DECISIONS.md`.
