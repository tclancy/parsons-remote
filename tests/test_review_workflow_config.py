"""Guards on `.github/workflows/claude-code-review.yml` (#9).

Ported from itguy's `tests/test_review_workflow_config.py`, which was written
after that repo's copy of this config had been wrong three times. Each was found
by reading a failed run rather than by anything in the repo, and each cost a red
gate and ~$0.50 — three of the five measured runs produced a complete review and
had it discarded by the action's post-check, which is worse than producing
nothing. This repo carried the byte-identical pre-fix line, so it inherits the
guards before it inherits the failures.

Deliberately parsed as text rather than YAML: the repo declares no yaml
dependency, and a guard that only runs where an optional import succeeded is one
that silently stops guarding.

The cost of that choice is that `claude_args` must stay a single-line scalar.
Reformatted to the block form upstream's own template uses (`claude_args: >-`
over several lines) these go RED even with correct values — the safe direction,
but the message would read as "someone deleted TodoWrite". `extract_claude_args`
detects that case and says so instead.
"""

import re
import textwrap
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "claude-code-review.yml"


def extract_claude_args(text: str) -> str:
    """Return the `claude_args:` line from a workflow document.

    Takes the document rather than reading `WORKFLOW` so its own behaviour is
    testable against synthetic input — the comment-skipping below is the whole
    reason this file does not just grep, and a guard on it that can only be fed
    the real workflow is true by construction rather than by test.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("claude_args:"):
            continue
        if line[:1] not in {" ", "\t"}:
            pytest.fail(
                "claude_args: is at column 0 — de-indented out of the step's `with:` "
                "block, which leaves the action with no allow-list and no turn cap. "
                "YAML still parses."
            )
        value = stripped[len("claude_args:") :].strip()
        # Any `>`/`|` form, not an enumerated set: `>-`, `|+`, `>2` and
        # `|- # note` are all block scalars, and a set-membership check waves
        # through every spelling it forgot.
        if not value or value[0] in {">", "|"}:
            spelling = value or "(empty)"
            pytest.fail(
                f"claude_args: was reformatted to a multi-line block scalar ({spelling!r}). "
                "These guards read a single-line scalar; fold it back, or teach "
                "extract_claude_args to join continuation lines."
            )
        return stripped
    pytest.fail("no claude_args: line in the review workflow")


def pull_request_types(text: str) -> set[str]:
    """The `types:` list on the `pull_request` trigger, and only that one.

    Scoped deliberately. This file has two `types:` keys — `pull_request`'s and
    `issue_comment: types: [created]` — and a bare `^\\s*types:` regex takes
    whichever appears first, which is `pull_request`'s today only because of
    the order the two blocks happen to be written in. Under that regex,
    *deleting* the `types:` line passes the "synchronize is off" guard while
    GitHub falls back to its default `[opened, synchronize, reopened]`, which
    is the once-per-push burn metaframework#320 §5 cut. Returning an empty set
    for an absent list is what makes that case fail the `reopened` guard.
    """
    block = re.search(r"^\s*pull_request:\s*$(.*?)^\s{0,2}\w", text, re.MULTILINE | re.DOTALL)
    assert block, "no `pull_request:` trigger block in the review workflow"
    types = re.search(r"^\s*types:\s*\[([^\]]*)\]", block.group(1), re.MULTILINE)
    if not types:
        return set()
    return {t.strip() for t in types.group(1).split(",") if t.strip()}


@pytest.fixture(scope="module")
def claude_args() -> str:
    """The `claude_args:` value, with comment lines excluded.

    The measurements justifying the current settings live in a comment block
    directly above this line and mention both `TodoWrite` and `--max-turns`.
    A naive grep of the whole file matches that prose and passes no matter what
    the setting says.
    """
    assert WORKFLOW.is_file(), f"workflow not found: {WORKFLOW}"
    return extract_claude_args(WORKFLOW.read_text())


class TestTheReviewGateIsBudgetedForRealReviews:
    def test_todowrite_is_allow_listed(self, claude_args: str):
        """Allow-listed for fleet consistency, and because it is harmless — an
        in-session scratchpad with no filesystem or GitHub write surface.

        Deliberately NOT justified as the fix for the per-run denials. Three of
        itguy's five measured runs ticked their checklists completely with
        `TodoWrite` absent from this list, which refutes that mechanism; the
        streamed log records a denial *count* and never names the tool. An
        earlier draft of itguy's workflow comment asserted the mechanism anyway
        and cited only the two runs consistent with it. What is being denied
        6-10 times a run is still unidentified.
        """
        assert "TodoWrite" in claude_args

    def test_max_turns_is_at_least_40(self, claude_args: str):
        """40 is itguy's measurement, not this repo's: under a cap of 25, its
        PR #216 review ran 32 turns, produced a complete review, and was failed
        anyway by the action's own post-check. 32 is the measured requirement
        and 40 is that plus headroom. No review here has ever reached the cap —
        no review here has ever *started* (see the class below).
        """
        match = re.search(r"--max-turns\s+(\d+)", claude_args)
        assert match, f"no --max-turns in: {claude_args}"
        assert int(match.group(1)) >= 40

    def test_the_inline_comment_tool_is_still_allow_listed(self, claude_args: str):
        """Allow-listed AND registered by track_progress, or inline comments
        silently no-op. Pinned so a future edit to this line cannot drop it."""
        assert "mcp__github_inline_comment__create_inline_comment" in claude_args

    def test_bot_authored_prs_are_still_reviewable(self):
        """The action blocks bot actors by default. Nearly every PR in this repo
        is opened by metaframework-dispatch-bot, so losing this line makes the
        gate silently skip almost everything while staying green.

        Anchored to the quoted *value*: `.*metaframework-dispatch-bot` also
        matches `allowed_bots: 'nobody'  # was metaframework-dispatch-bot`.
        """
        body = WORKFLOW.read_text()
        assert re.search(
            r"^\s*allowed_bots:\s*['\"]metaframework-dispatch-bot['\"]\s*$", body, re.MULTILINE
        )

    def test_track_progress_is_still_on(self):
        """`--allowed-tools` only FILTERS registered MCP servers; it does not
        register them. Without this the inline-comment tool is denied even
        though the test above passes."""
        body = WORKFLOW.read_text()
        assert re.search(r"^\s*track_progress:\s*true\s*$", body, re.MULTILINE)


class TestTheGateCanStillFireAtAll:
    """Every trigger this gate has. Measured 2026-09-28 over all 14 recorded
    runs of this workflow, it has produced **zero** reviews:

    - **11 `skipped`** — filtered out by the job's `if:`. Ten are Dependabot or
      `chore` pull requests; one is an `issue_comment` that did not contain
      `/review`.
    - **2 `success`** — runs 30537851656 (PR #3) and 35360053668 (PR #14), both
      stopped by the action's anti-tamper validation because both PRs edited
      this file. The second concluded `success` in **1.6 seconds**.
    - **1 `failure`** — run 30432219327 (PR #2), `steps=0` ten seconds after
      spawn: the runner was never provisioned, the Actions minute cap.

    So the settings the class above pins have never been exercised here, and
    these guards cannot be validated by "the gate went green once" — two of the
    three greens on record are a gate that did nothing. Pin the triggers
    instead: a dropped trigger is the one failure mode that would keep that
    record at zero forever while looking exactly like it does now.
    """

    def test_reopened_is_a_trigger(self):
        """`opened` alone cannot re-gate a fix-up push, and `/review` cannot
        either — a check-run attaches to the SHA of the *event*, so an
        `issue_comment` run lands its verdict on the default branch tip. An
        absent verdict on the real head renders as green, not as unreviewed.
        See `re-gate` in GLOSSARY.md."""
        assert "reopened" in pull_request_types(WORKFLOW.read_text())

    def test_synchronize_is_still_off(self):
        """Deliberately absent: it fires once per push, which is the exact burn
        metaframework#320 §5 cut. Re-gating is a deliberate close/reopen."""
        types = pull_request_types(WORKFLOW.read_text())
        assert types, (
            "no `types:` list on the pull_request trigger — GitHub then defaults "
            "to [opened, synchronize, reopened], which turns synchronize back on"
        )
        assert "synchronize" not in types

    def test_cancel_in_progress_is_off(self):
        """MUST stay false. Cancellation happens when a run is *created*, before
        job-level `if:` filtering — so with it on, any comment on the PR
        (including the review's own `gh pr comment`) spawned an `issue_comment`
        run in this group and cancelled the in-flight review."""
        body = WORKFLOW.read_text()
        assert re.search(r"^\s*cancel-in-progress:\s*false\s*$", body, re.MULTILINE)


class TestTheGuardsReadTheSettingNotTheComment:
    """A guard aimed at the wrong text reads exactly like a passing one."""

    def test_a_commented_out_claude_args_is_not_returned(self):
        """The property `extract_claude_args` exists for, tested against input
        that can actually express the failure. Asserting it on the real
        workflow instead is true by construction — the function only ever
        returns a line that already passed the `claude_args:` prefix test — so
        it would pass for any workflow content whatsoever.
        """
        document = textwrap.dedent("""\
            with:
              # claude_args: '--allowed-tools "TodoWrite"' --max-turns 999
              claude_args: '--allowed-tools "Real"' --max-turns 40
        """)
        assert (
            extract_claude_args(document)
            == "claude_args: '--allowed-tools \"Real\"' --max-turns 40"
        )

    def test_the_comment_block_alone_would_satisfy_a_naive_grep(self):
        """If this fails, the prose moved and the fixture's reason for existing
        should be re-checked — not the assertion loosened."""
        comments = [
            line for line in WORKFLOW.read_text().splitlines() if line.strip().startswith("#")
        ]
        assert any("TodoWrite" in line for line in comments)
        assert any("--max-turns" in line for line in comments)
