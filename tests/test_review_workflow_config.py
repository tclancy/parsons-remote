"""Guards on `.github/workflows/claude-code-review.yml` (#9).

Ported from itguy's `tests/test_review_workflow_config.py`, which was written
after that repo's copy of this config had been wrong three times — each costing
a red gate and ~$0.50 for zero review, and each time found by reading a failed
run rather than by anything in the repo. This repo carried the byte-identical
pre-fix line, so it inherits the guards before it inherits the failures.

Deliberately parsed as text rather than YAML: the repo declares no yaml
dependency, and a guard that only runs where an optional import succeeded is one
that silently stops guarding.

The cost of that choice is that `claude_args` must stay a single-line scalar.
Reformatted to the block form upstream's own template uses (`claude_args: >-`
over several lines) these go RED even with correct values — the safe direction,
but the message would read as "someone deleted TodoWrite". The fixture detects
that case and says so instead.
"""

import re
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "claude-code-review.yml"


@pytest.fixture(scope="module")
def claude_args() -> str:
    """The `claude_args:` value, with comment lines excluded.

    The measurements justifying the current settings live in a comment block
    directly above this line and mention both `TodoWrite` and `--max-turns`.
    A naive grep of the whole file matches that prose and passes no matter what
    the setting says.
    """
    assert WORKFLOW.is_file(), f"workflow not found: {WORKFLOW}"
    for line in WORKFLOW.read_text().splitlines():
        stripped = line.strip()
        if not stripped.startswith("claude_args:"):
            continue
        if not line.startswith(" "):
            pytest.fail(
                "claude_args: is at column 0 — de-indented out of the step's `with:` "
                "block, which leaves the action with no allow-list and no turn cap. "
                "YAML still parses."
            )
        value = stripped[len("claude_args:") :].strip()
        if value in {">-", ">", "|", "|-", ""}:
            pytest.fail(
                f"claude_args: was reformatted to a multi-line block scalar ({value!r}). "
                "These guards read a single-line scalar; fold it back, or teach the "
                "fixture to join continuation lines."
            )
        return stripped
    pytest.fail("no claude_args: line in the review workflow")


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
        gate silently skip almost everything while staying green."""
        body = WORKFLOW.read_text()
        assert re.search(r"^\s*allowed_bots:\s*.*metaframework-dispatch-bot", body, re.MULTILINE)

    def test_track_progress_is_still_on(self):
        """`--allowed-tools` only FILTERS registered MCP servers; it does not
        register them. Without this the inline-comment tool is denied even
        though the test above passes."""
        body = WORKFLOW.read_text()
        assert re.search(r"^\s*track_progress:\s*true\s*$", body, re.MULTILINE)


class TestTheGateCanStillFireAtAll:
    """Every trigger this gate has. Measured 2026-09-28, this repo's review
    workflow has run 12 times and produced **zero** reviews: 11 filtered out by
    the `if:` below (Dependabot and `chore` PRs, by design) and one — PR #14,
    head 69699fc — stopped by the action's anti-tamper validation because that
    PR edited this file. That last one concluded **`success` in 1.6 seconds**.

    So the settings the class above pins have never been exercised here, and
    these guards cannot be validated by "the gate went green once". Pin the
    triggers instead: a dropped trigger is the one failure mode that would keep
    that record at zero forever while looking exactly like it does now.
    """

    def test_reopened_is_a_trigger(self):
        """`opened` alone cannot re-gate a fix-up push, and `/review` cannot
        either — a check-run attaches to the SHA of the *event*, so an
        `issue_comment` run lands its verdict on the default branch tip. An
        absent verdict on the real head renders as green, not as unreviewed.
        See `re-gate` in GLOSSARY.md."""
        body = WORKFLOW.read_text()
        types = re.search(r"^\s*types:\s*\[([^\]]*)\]", body, re.MULTILINE)
        assert types, "no `types:` list on the pull_request trigger"
        assert "reopened" in {t.strip() for t in types.group(1).split(",")}

    def test_synchronize_is_still_off(self):
        """Deliberately absent: it fires once per push, which is the exact burn
        metaframework#320 §5 cut. Re-gating is a deliberate close/reopen."""
        body = WORKFLOW.read_text()
        types = re.search(r"^\s*types:\s*\[([^\]]*)\]", body, re.MULTILINE)
        assert types
        assert "synchronize" not in {t.strip() for t in types.group(1).split(",")}

    def test_cancel_in_progress_is_off(self):
        """MUST stay false. Cancellation happens when a run is *created*, before
        job-level `if:` filtering — so with it on, any comment on the PR
        (including the review's own `gh pr comment`) spawned an `issue_comment`
        run in this group and cancelled the in-flight review."""
        body = WORKFLOW.read_text()
        assert re.search(r"^\s*cancel-in-progress:\s*false\s*$", body, re.MULTILINE)


class TestTheGuardReadsTheSettingNotTheComment:
    """A guard aimed at the wrong text reads exactly like a passing one."""

    def test_the_fixture_excludes_comment_lines(self, claude_args: str):
        assert not claude_args.lstrip().startswith("#")

    def test_the_comment_block_alone_would_satisfy_a_naive_grep(self):
        """If this fails, the prose moved and the fixture's reason for existing
        should be re-checked — not the assertion loosened."""
        comments = [
            line for line in WORKFLOW.read_text().splitlines() if line.strip().startswith("#")
        ]
        assert any("TodoWrite" in line for line in comments)
        assert any("--max-turns" in line for line in comments)
