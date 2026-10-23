# parsons-remote

PWA remote for the fans and 433 MHz lamps at the Parsons house. `www/` is the
whole product and is served verbatim — no build step. Start with `README.md`
for architecture and `GLOSSARY.md` for what to call things.

## The review gate cannot review a PR that edits it

`.github/workflows/claude-code-review.yml` cannot grade a change to itself.
A PR that edits it gets a **green `claude-review` check that reviewed
nothing**, and three of this repo's PRs have already had one.

### The mechanism, as of `claude-code-action` v1.0.248

The validation is **server-side, and it is a property of how this workflow
authenticates** — not something the action compares locally and not something
this repo sets.

1. This workflow supplies `claude_code_oauth_token` and **no `github_token`**,
   so `setupGitHubToken()` takes the OIDC path: it mints a GitHub OIDC token
   and POSTs it to `https://api.anthropic.com/api/github/github-app-token-exchange`
   to be exchanged for an App token (`src/github/token.ts:158`, `:121`).
2. **Anthropic's endpoint** refuses the exchange when the workflow the OIDC
   token was issued for is not found byte-identical on the repository's
   default branch, with `error_code: "workflow_not_found_on_default_branch"`
   (`token.ts:25`). The action only *recognises* that response
   (`isWorkflowValidationError`, `token.ts:34`) and raises
   `WorkflowValidationSkipError`.
3. `run.ts:179-182` catches it, logs `Exiting due to workflow validation
   skip`, and **returns**. The job then completes with no error, so the check
   is green.

It exists so a PR cannot grant itself a laxer gate by editing the gate.
Three consequences worth being precise about:

- **It is scoped to the workflow the run came from**, which is what the error
  code's name and the OIDC `job_workflow_ref` claim imply — so editing
  `ci.yml` does not trip it. That is server behaviour, not provable from the
  action's source, so do not state it harder than that.
- **It compares against the default branch at exchange time**, which is a
  slightly wider rule than "the PR edited the file". Phrase it that way.
- **Supplying `github_token` would bypass it entirely** —
  `setupGitHubToken()` returns the provided token and never reaches the
  exchange (`token.ts:160-166`). Keeping the OIDC path, and therefore keeping
  the validation, is the deliberate choice here.

### How to recognise it

**Without reading logs:** the action's `conclusion` output is **empty**. The
skip `return`s at `run.ts:182`, well before `core.setOutput("conclusion", …)`
at `run.ts:315`, whereas a completed review sets `success` or `failure`. The
coarser tells are duration — the job runs 9–11 s and the `Run Claude Code
Review` step 4–5 s, against minutes for a real review — and both are visible
in the API and the Actions UI.

(`run.ts:180` also sets `skipped_due_to_workflow_validation_mismatch`, but
that output is **not** declared in the action's `action.yml` `outputs:`, so it
is unreachable from a workflow. Do not reach for it; use `conclusion`.)

**In the log**, under the `Run Claude Code Review` step:

```
##[warning]Skipping action due to workflow validation: Workflow validation failed.
The workflow file must exist and have identical content to the version on the
repository's default branch. ...
Exiting due to workflow validation skip
```

**Do not grep the whole log for that string.** This file quotes it, and this
file is in the review's own reading — run
[`39897838521`](https://github.com/tclancy/parsons-remote/actions/runs/39897838521)
is a *real* review whose log matches `Exiting due to workflow validation skip`
exactly once, at line 507, because the reviewer read this paragraph aloud. A
bare grep over any run that touched these docs reports a skip that did not
happen. The `##[warning]` prefix does not save you either — the block above
quotes that too.

Use a discriminator the prose cannot forge:

| check | real review | validation skip |
|---|---|---|
| action's `conclusion` output | `success` / `failure` | **empty** |
| `"num_turns"` in the log | present | **absent** — the skip returns before Claude is ever invoked |
| nested `run` step `duration_ms` | tens of seconds | ~1,600 |
| job wall clock | ~50 s | 9-11 s |

`"num_turns"` is the cheapest positive test from a log: run `39897838521`
reports `"num_turns": 4`, `"total_cost_usd": 0.138` and
`duration_ms=42000`, and no skip can.

**A PR that *deletes* the workflow produces no run at all** — GitHub evaluates
`pull_request` workflows from the merge ref, so there is nothing to skip. That
is an *absent* check rather than a green one, and on GitHub Free with no
branch protection on this repo the two read the same in the PR UI. Worth
knowing, because the "if they differ" framing above does not cover it.

### Every instance in this repo, re-derived 2026-10-22

The first 25 recorded runs of this workflow — everything up to and including
`39570227467`, i.e. every run before the one on this file's own PR — read from
the Actions API:

| conclusion | count | what it was |
|---|---|---|
| `skipped` | 21 | filtered out by the job's `if:` — 15 Dependabot bumps, 5 `issue_comment` runs with no `/review`, and 1 `chore`-titled PR ([#11](https://github.com/tclancy/parsons-remote/pull/11)) |
| `success` | 3 | every one a workflow validation skip — the table below |
| `failure` | 1 | run `30432219327`, `steps=0` ten seconds after spawn: the runner was never provisioned (Actions minute cap), not a review |

Each green, and the PR that caused it by editing `claude-code-review.yml`:

| run | PR | job | `Run Claude Code Review` step | action's nested `run` step |
|---|---|---|---|---|
| [`30537851656`](https://github.com/tclancy/parsons-remote/actions/runs/30537851656) | [#3](https://github.com/tclancy/parsons-remote/pull/3) | 9 s | 4 s | 1,695 ms |
| [`35360053668`](https://github.com/tclancy/parsons-remote/actions/runs/35360053668) | [#14](https://github.com/tclancy/parsons-remote/pull/14) | 11 s | 4 s | 1,616 ms |
| [`36484572525`](https://github.com/tclancy/parsons-remote/actions/runs/36484572525) | [#16](https://github.com/tclancy/parsons-remote/pull/16) | 9 s | 5 s | 1,625 ms |

Three things follow, two of which earlier write-ups of this got wrong:

- **~1.6 s is the signature of this failure mode, not a quirk of one run.**
  Previous notes attributed "concluded `success` in 1.6 seconds" to run
  `35360053668` alone. Every row above sits in 1.62–1.70 s, because the action
  does the same fixed work every time: set up, attempt the exchange, be
  refused, exit. That figure is also **the nested action step's**
  `duration_ms`, which appears only in the `##[end-action …]` log line — not
  the run's or the step's, which are the columns beside it. Compare like with
  like.
- **This repo produced zero reviews for its first 25 runs.** Not "has not hit
  the failure yet" — across exactly the 25 runs tabled above the gate had
  never once run to completion, which was independently checkable:
  `/pulls/comments` empty
  repo-wide and `/pulls/N/reviews` empty for every PR. So no setting in that
  workflow had ever been exercised here, and "the gate went green" was not
  evidence that any of it worked. `tests/test_review_workflow_config.py`
  exists for that reason: the guards were the only thing standing in for a
  gate that had never fired.
- **Run `39897838521`, on the PR that added this file, is the first real
  review.** 4 turns, $0.138, a posted verdict. It is also the proof #9 asked
  for: PR #20 edited the workflow and could not be reviewed, so the *next* PR
  was the first test of whether the edit worked. It did.

  That run reports **four different durations**, which is the "compare like
  with like" point above biting immediately: the job 50 s, the `Run Claude
  Code Review` step 44 s, the action's nested `run` step `duration_ms=42000`,
  and the posted comment's own *"finished in 24s"*, which is the agent's
  elapsed time inside the action. They are not inconsistent; they are nested.
  The skip table's right-hand column is the third of those, so compare against
  that one.

### What to do instead

A PR that touches `.github/workflows/claude-code-review.yml`:

1. **Gets Tom's explicit approval**, in a comment on the PR, as the substitute
   for the bot review. Say in the PR body that the gate cannot review it and
   why, so the green check is not read as a verdict.
2. **Is proved by the *next* PR**, not by itself. Once merged, the branch copy
   and the default-branch copy agree again, so the following PR is the first
   one the edited gate can actually grade. If that PR gets a real review, the
   edit worked.
3. **Should not carry unrelated changes.** Anything bundled in rides through
   unreviewed under the same green check.
4. **Could make the green honest, and that is worth doing separately.** Add
   `id: review` to the existing `anthropics/claude-code-action` step — it has
   none today, and without it `steps.review.outputs.conclusion` is `''` on
   *every* run, so the guard below would fail real reviews too — then fail the
   job when the step produced no verdict:

   ```yaml
         - name: Review
           id: review                    # <- this line is load-bearing
           uses: anthropics/claude-code-action@...
           with: ...

         - name: A green check must mean a review happened
           if: steps.review.outputs.conclusion == ''
           run: |
             echo "::error::Gate exited without reviewing (workflow validation skip)."
             exit 1
   ```

   That turns the misleading green into a red, which is the honest state. It
   has not been done because it is itself an edit to this workflow — so it
   needs Tom's approval and is proved by the PR after it, exactly like
   everything else here. Confirm `conclusion` really is empty on the first
   workflow-editing PR that lands after it.

Conversely: a PR that does *not* touch that file is reviewable normally, so
documentation about this behaviour belongs **outside** the workflow — here.
Writing it as a comment inside `claude-code-review.yml` would make the PR
adding it unreviewable, which is the rule defeating its own documentation.

### Known stale copy

The comment block at `.github/workflows/claude-code-review.yml:154-165` still
carries the superseded 2026-09-28 reading — "all 14 recorded runs", "11
skipped", "2 success", "Two of the three greens" — and still calls this
"anti-tamper validation", now an alias-to-avoid. **This file is the authority
for the count.** Correcting that comment needs its own PR, with Tom's
approval, for the reason this whole section exists.

See **workflow validation skip** in `GLOSSARY.md`, and `re-gate` for the
separate matter of binding a real verdict to the current head SHA.
