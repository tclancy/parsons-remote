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

It exists so a PR cannot grant itself a laxer gate by editing the gate. Two
consequences worth being precise about:

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

`Exiting due to workflow validation skip` is the string to grep for.

**A PR that *deletes* the workflow produces no run at all** — GitHub evaluates
`pull_request` workflows from the merge ref, so there is nothing to skip. That
is an *absent* check rather than a green one, and on GitHub Free with no
branch protection on this repo the two read the same in the PR UI. Worth
knowing, because the "if they differ" framing above does not cover it.

### Every instance in this repo, re-derived 2026-10-22

All 25 recorded runs of this workflow, read from the Actions API:

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

Two things follow that earlier write-ups of this got wrong:

- **~1.6 s is the signature of this failure mode, not a quirk of one run.**
  Previous notes attributed "concluded `success` in 1.6 seconds" to run
  `35360053668` alone. Every row above sits in 1.62–1.70 s, because the action
  does the same fixed work every time: set up, attempt the exchange, be
  refused, exit. That figure is also **the nested action step's**
  `duration_ms`, which appears only in the `##[end-action …]` log line — not
  the run's or the step's, which are the columns beside it. Compare like with
  like.
- **This repo has produced zero reviews in its entire history.** Not "has not
  hit the failure yet" — the gate has never run to completion once, which is
  independently checkable: `/pulls/comments` is empty repo-wide and
  `/pulls/N/reviews` is empty for every PR. So no setting in that workflow has
  ever been exercised here, and "the gate went green" is not evidence that any
  of it works. `tests/test_review_workflow_config.py` exists for that reason:
  the guards are the only thing standing in for a gate that has never fired.

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
4. **Could make the green honest, and that is worth doing separately.** Give
   the action step an `id:` and fail the job when it produced no verdict:

   ```yaml
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
