# Dale — Kanban Workflow Update (v2)

## Background

The Hermes Kanban board's dependency model can't express "implementation is
done only after review passes." When you block your ticket as `review-required`
and Kova's review ticket is a child of yours, the board deadlocks: your ticket
can't be `done` until the review passes, but the review can't be claimed until
your ticket is `done`. This has happened three times on the ai-price-dashboard
project and required manual intervention (unlinking tickets) each time.

The fix is a workflow change. Under v2, you always complete your implementation
tickets after self-verification. Review happens on a separate child ticket that
becomes claimable automatically. If Kova finds issues, a remediation/re-review
cycle kicks off — all forward-flowing, no cycles.

## What changes for you

### Complete your tickets — do not block for review

1. Implement the work per the spec/plan.
2. Self-verify: run the build, run the tests, exercise the endpoints. Do
   everything you'd expect Kova to check.
3. Leave a comment on your ticket using the `kanban_comment` tool:
   - task_id: your ticket ID
   - body: changed files (absolute paths), verification steps you ran and
     their results, any caveats or things you intentionally left out of scope
4. Complete the ticket using the `kanban_complete` tool:
   - task_id: your ticket ID
   - result: one-line summary
   - summary: structured handoff — changed files, verification done, caveats
   - metadata: JSON dict, e.g. {"changed_files": [...], "tests_passed": N,
     "verifications_run": [...]}

Do NOT block your ticket as `review-required`. Completing it is correct — the
review ticket (child of yours) will auto-promote to `ready` and the dispatcher
sends it to Kova automatically. The open review ticket makes it clear the work
isn't fully shipped yet.

### When Kova requests changes — a remediation ticket comes to you

If Kova finds issues, she will:
1. Complete her review ticket with result "changes-requested"
2. Create a remediation ticket assigned to you (child of her review)
3. Create a re-review ticket assigned to herself (child of your remediation)

Your remediation ticket will auto-promote to `ready` when she creates it. Claim
it, fix the specific issues she listed, self-verify, and complete it — same as
any other ticket. The re-review ticket then auto-promotes and the cycle
continues until Kova approves.

### Do not create your own review tickets

Under v2, Kova creates the remediation and re-review tickets as part of her
review process. You do not need to create or route review tickets. Just
complete your work and let the dependency chain handle the rest.

### Use native kanban tools, not the CLI

You have the `kanban_*` toolset available in your dispatched sessions. Use the
native tools (`kanban_complete`, `kanban_comment`, `kanban_create`,
`kanban_link`, etc.) instead of shelling out to `hermes kanban <verb>` in the
terminal. The native tools are the preferred interface — they handle locking,
heartbeat, and task context automatically.

## Why this is better

- No dependency deadlocks — the board's linear model works as designed
- No operator intervention needed to unlink tickets
- Clean audit trail: each review round is a discrete ticket pair
- The full chain is visible on the board at all times

## Summary (the one-line version)

Self-verify, comment your findings, complete the ticket. If Kova finds
issues, a remediation ticket will come to you — fix it and complete it.
Never block a ticket as `review-required`.
