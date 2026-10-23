# parsons-remote

PWA remote for the fans and 433 MHz lamps at the Parsons house. `www/` is the
whole product and is served verbatim — no build step. Start with `README.md`
for architecture and `GLOSSARY.md` for what to call things.

## The review gate cannot review a PR that edits it

`.github/workflows/claude-code-review.yml` validates itself before doing
anything: `anthropics/claude-code-action` compares the workflow file it is
running from against the copy on the default branch, and **if they differ it
exits without reviewing, reporting `success`.** The job renders as a green
`claude-review` check. Nothing distinguishes it from a passing review except
reading the log.

This is upstream anti-tamper behaviour, not a bug and not something this repo
configures. It exists so a PR cannot grant itself a laxer gate by editing the
gate. The consequence is that **the one class of change most worth reviewing
here — a change to the review gate — is the one class this gate structurally
cannot review.**

### How to recognise it

In the run log, under the `Run Claude Code Review` step:

```
##[warning]Skipping action due to workflow validation: Workflow validation failed.
The workflow file must exist and have identical content to the version on the
repository's default branch. ...
Exiting due to workflow validation skip
```

`Exiting due to workflow validation skip` is the string to grep for. The
cheapest tell without reading logs is **duration**: the action's own nested
`run` step reports ~1.6 s, against minutes for a real review.

### Every instance in this repo, re-derived 2026-10-22

All 25 recorded runs of this workflow, read from the Actions API:

| | count | what it was |
|---|---|---|
| `skipped` | 21 | filtered out by the job's `if:` — Dependabot bumps, `chore` PRs, and `issue_comment` runs with no `/review` |
| `success` | **3** | **all three are workflow validation skips** |
| `failure` | 1 | run `30432219327`, `steps=0` ten seconds after spawn — the runner was never provisioned (Actions minute cap), not a review |

The three greens, each on a PR that edited `claude-code-review.yml`:

| run | PR | job | `Run Claude Code Review` step | action's nested `run` step |
|---|---|---|---|---|
| [`30537851656`](https://github.com/tclancy/parsons-remote/actions/runs/30537851656) | [#3](https://github.com/tclancy/parsons-remote/pull/3) | 9 s | 4 s | **1,695 ms** |
| [`35360053668`](https://github.com/tclancy/parsons-remote/actions/runs/35360053668) | [#14](https://github.com/tclancy/parsons-remote/pull/14) | 11 s | 4 s | **1,616 ms** |
| [`36484572525`](https://github.com/tclancy/parsons-remote/actions/runs/36484572525) | [#16](https://github.com/tclancy/parsons-remote/pull/16) | 9 s | 5 s | **1,625 ms** |

Two things follow that the earlier write-ups of this got wrong:

- **~1.6 s is the signature of this failure mode, not a quirk of one run.**
  Previous notes attributed "concluded `success` in 1.6 seconds" to run
  `35360053668` alone. All three are 1.62–1.70 s at that level, because the
  action does the same fixed work every time: set up, read the workflow,
  find a mismatch, exit. The number is also **the nested action step's**
  `duration_ms`, not the run's or the step's — those are 9–11 s and 4–5 s. If
  you are comparing against a wall-clock figure, compare like with like.
- **This repo has produced zero reviews in its entire history.** Not "has not
  hit the failure yet" — the gate has never run to completion once. So no
  setting in that workflow has ever been exercised here, and "the gate went
  green" is not evidence that any of it works. `tests/test_review_workflow_config.py`
  exists because of this: the guards are the only thing standing in for a gate
  that has never fired.

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

Conversely: a PR that does *not* touch that file is reviewable normally, so
documentation about this behaviour belongs **outside** the workflow — here.
Writing it as a comment inside `claude-code-review.yml` would make the PR
adding it unreviewable, which is the rule defeating its own documentation.

See **workflow validation skip** in `GLOSSARY.md`, and `re-gate` for the
separate matter of binding a verdict to the current head SHA.
