"""Behavioural guards on `.github/review-gate.jq`.

The gate's whole job is to answer one question -- "has a review happened for
*this* head?" -- and every way it can be wrong is silent. A gate that says
`success` when nothing reviewed anything is indistinguishable, on the PR page,
from a gate that is working.

So these are *behavioural* tests: each one feeds the real jq program a document
shaped like what `require-review.yml` actually builds and asserts the verdict.
They are not text guards. The workflow's text is guarded separately in
`tests/test_require_review_workflow.py`, which is also where the control lives
that keeps `jq`'s absence from quietly disabling this whole module (see
``test_ci_proves_jq_is_available`` there).

The fixture set is the part with history. bluelinky's first cut of this logic
shipped with a rule -- "a bot comment counts unless it has an outstanding
``- [ ]`` item" -- that passed *both* shapes `claude-code-action` emits when it
has reviewed nothing, because neither carries a checklist at all. Three
all-killed mutation rounds did not find it: every fixture in that family was
hand-written and every one carried an unticked box, so the suite only ever
exercised the shapes the rule already handled. **The fixtures were the defect.**
Hence `NON_REVIEW_SHAPES` below, which names each no-checklist shape
explicitly, and `test_no_fixture_family_is_empty`, which fails if a future edit
empties one of these families out from under the loop that reads it.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE = REPO_ROOT / ".github" / "review-gate.jq"

HEAD_TS = "2026-10-23T04:00:00Z"
BEFORE_HEAD = "2026-10-23T03:00:00Z"
AFTER_HEAD = "2026-10-23T05:00:00Z"

#: The exact body prefix of the three real reviews this repo has ever had, on
#: PR #23 on 2026-10-23. Pinned as live data rather than invented: it is the
#: only comment shape this repo is known to produce, so if the gate rejected
#: it the gate would be red on every real review here.
REAL_FINISHED_COMMENT = (
    "**Claude finished @metaframework-dispatch-bot[bot]'s task in 24s** "
    "—— [View job](https://github.com/tclancy/parsons-remote/actions/runs/39897838521)\n"
    "\n---\n\n### Review of PR #23\n\n"
    "This PR touches no workflow file, so this is a real review."
)

#: Bodies that must NEVER satisfy the gate. Each is a shape the action emits
#: when it has reviewed nothing. The first two are the ones that defeated the
#: original checklist-only rule: they have no checklist to be outstanding.
NON_REVIEW_SHAPES = {
    "in_flight": (
        'Claude Code is working… <img src="https://example.invalid/spin.gif" />\n'
        "\nI'll analyze this and get back to you.\n"
        "\n[View job run](https://example.invalid/run)"
    ),
    "errored_no_checklist": (
        "**Claude encountered an error** —— [View job](https://example.invalid/run)"
    ),
    "errored_with_elapsed_no_checklist": (
        "**Claude encountered an error after 2m 10s** —— [View job](https://example.invalid/run)"
    ),
    "errored_partial_checklist": (
        "**Claude encountered an error**\n\n- [x] Read the diff\n- [ ] Post findings"
    ),
    # No preceding newline before the marker. This is what makes the `(^|\n)`
    # anchor in `has_outstanding_item` a contested predicate rather than a
    # defensive one a mutation round is blind to: with the anchor reduced to
    # `\n` this body sails through.
    # EXACTLY ONE item, at byte offset 0, and both halves of that are load
    # bearing. The first draft of this fixture had two items -- and the second
    # one *was* preceded by a newline, so reducing the anchor to `\n` still
    # matched it and the mutation round reported SURVIVED. A fixture meant to
    # contest an anchor has to be the one shape the anchor is the only thing
    # catching.
    "body_opening_with_an_outstanding_item": "- [ ] Read the diff",
    # Contests the `^` anchor on `says_finished`: the body is an errored-run
    # status comment that happens to quote the finished line in prose. Without
    # the anchor this reads as a completed review.
    "errored_but_quoting_the_finished_line": (
        "**Claude encountered an error** —— [View job](https://example.invalid/run)\n"
        "\nThe previous attempt said **Claude finished in 2s** and it had not."
    ),
    "in_flight_partial_checklist": ("Claude Code is working…\n\n- [ ] Read the diff"),
}

#: Bodies that must satisfy the gate.
REVIEW_SHAPES = {
    "real_finished": REAL_FINISHED_COMMENT,
    "finished_bolded": "**Claude finished in 3m 48s**\n\n### Review\n\nNothing blocking.",
    "errored_but_completed": (
        "**Claude encountered an error**\n\n- [x] Read the diff\n- [x] Post findings\n\n"
        "Found two things before running out of budget."
    ),
    "plain_summary": ("### Review\n\nTwo findings, neither blocking. Posted inline."),
    # The marker appears mid-sentence in prose. A review that *discusses*
    # checklists must not be thrown away for quoting the syntax.
    "prose_quoting_the_marker": (
        "### Review\n\nThe progress comment left a `- [ ] ` item unticked, which is worth "
        "knowing but is not a finding."
    ),
}


def run_gate(doc: dict) -> dict:
    """Evaluate the real jq program against ``doc`` and return its verdict."""
    proc = subprocess.run(
        ["jq", "-f", str(GATE)],
        input=json.dumps(doc),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


def pr(**overrides) -> dict:
    """A gate input with no reviews of any kind, plus ``overrides``."""
    doc = {
        "number": 23,
        "author": "metaframework-dispatch-bot[bot]",
        "title": "feat: a change",
        "head_committed_at": HEAD_TS,
        "bot_logins": ["claude[bot]"],
        "comments": [],
        "reviews": [],
    }
    doc.update(overrides)
    return doc


def comment(body: str, *, login: str = "claude[bot]", updated_at: str = AFTER_HEAD) -> dict:
    return {"user": {"login": login}, "body": body, "updated_at": updated_at}


def review(state: str, *, login: str = "tclancy", submitted_at: str = AFTER_HEAD) -> dict:
    return {"user": {"login": login}, "state": state, "submitted_at": submitted_at}


class TestTheBaselineRefuses:
    """Without this, every ``success`` below could be a tautology."""

    def test_jq_is_available(self):
        # Deliberately NOT a skipif: this module's value is that it runs. If jq
        # is missing the honest outcome is a red test naming the missing tool,
        # not a green run that proved nothing. CI's jq is pinned separately by
        # `test_ci_proves_jq_is_available` in the workflow-guard module.
        assert shutil.which("jq") is not None, (
            "jq is required to evaluate .github/review-gate.jq. "
            "Install it (brew install jq); ubuntu-latest ships it."
        )

    def test_a_pr_with_nothing_is_refused(self):
        verdict = run_gate(pr())
        assert verdict["state"] == "failure"
        assert "No code review for this head" in verdict["description"]

    def test_the_refusal_names_the_remedy_and_the_pr(self):
        verdict = run_gate(pr(number=99))
        assert "/review" in verdict["description"]
        assert "#99" in verdict["description"]


class TestAReviewThatNeverHappenedIsNotAReview:
    """The family that defeated the first version of this rule."""

    @pytest.mark.parametrize("shape", sorted(NON_REVIEW_SHAPES))
    def test_non_review_shapes_are_refused(self, shape):
        verdict = run_gate(pr(comments=[comment(NON_REVIEW_SHAPES[shape])]))
        assert verdict["state"] == "failure", (
            f"{shape!r} satisfied the gate; it is a shape the action emits when "
            "it has reviewed nothing."
        )

    @pytest.mark.parametrize("shape", sorted(REVIEW_SHAPES))
    def test_review_shapes_are_accepted(self, shape):
        verdict = run_gate(pr(comments=[comment(REVIEW_SHAPES[shape])]))
        assert verdict["state"] == "success", f"{shape!r} was refused but is a real review"

    def test_an_empty_or_null_body_is_not_a_review(self):
        assert run_gate(pr(comments=[comment("")]))["state"] == "failure"
        assert run_gate(pr(comments=[comment(None)]))["state"] == "failure"

    def test_no_fixture_family_is_empty(self):
        # A parametrize list scoped to an empty collection passes every time it
        # runs, so the two loops above would go green having asserted nothing.
        assert len(NON_REVIEW_SHAPES) >= 5
        assert len(REVIEW_SHAPES) >= 5

    def test_both_families_are_disjoint(self):
        assert not set(NON_REVIEW_SHAPES.values()) & set(REVIEW_SHAPES.values())


class TestOnlyTheAllowListedBotCounts:
    def test_a_login_that_is_a_prefix_of_the_allow_listed_one_is_refused(self):
        # `["claude[bot]"] | inside/contains("claude")` is TRUE -- substring
        # matching on array elements. This case is why the gate uses `index`
        # with a scalar bound to a variable first.
        verdict = run_gate(pr(comments=[comment(REAL_FINISHED_COMMENT, login="claude")]))
        assert verdict["state"] == "failure"

    def test_an_unrelated_login_is_refused(self):
        verdict = run_gate(pr(comments=[comment(REAL_FINISHED_COMMENT, login="totally-unrelated")]))
        assert verdict["state"] == "failure"

    def test_a_human_review_comment_does_not_satisfy_the_bot_arm(self):
        verdict = run_gate(pr(comments=[comment("### Review\n\nLooks fine.", login="tclancy")]))
        assert verdict["state"] == "failure"

    def test_the_bot_list_is_configurable(self):
        verdict = run_gate(
            pr(
                bot_logins=["some-other-reviewer[bot]"],
                comments=[comment(REAL_FINISHED_COMMENT, login="some-other-reviewer[bot]")],
            )
        )
        assert verdict["state"] == "success"


class TestStaleness:
    def test_a_review_older_than_the_head_is_refused(self):
        verdict = run_gate(pr(comments=[comment(REAL_FINISHED_COMMENT, updated_at=BEFORE_HEAD)]))
        assert verdict["state"] == "failure"
        assert "predate its head commit" in verdict["description"]
        assert "/review" in verdict["description"]

    def test_the_stale_refusal_differs_from_the_absent_refusal(self):
        stale = run_gate(pr(comments=[comment(REAL_FINISHED_COMMENT, updated_at=BEFORE_HEAD)]))
        absent = run_gate(pr())
        assert stale["description"] != absent["description"], (
            "the two refusals have different causes and must send the reader to different fixes"
        )

    def test_a_review_exactly_at_the_head_timestamp_counts(self):
        verdict = run_gate(pr(comments=[comment(REAL_FINISHED_COMMENT, updated_at=HEAD_TS)]))
        assert verdict["state"] == "success"

    def test_a_null_head_timestamp_cannot_make_anything_stale(self):
        verdict = run_gate(
            pr(
                head_committed_at=None,
                comments=[comment(REAL_FINISHED_COMMENT, updated_at=BEFORE_HEAD)],
            )
        )
        assert verdict["state"] == "success"

    def test_one_fresh_review_among_stale_ones_is_enough(self):
        verdict = run_gate(
            pr(
                comments=[
                    comment(REAL_FINISHED_COMMENT, updated_at=BEFORE_HEAD),
                    comment(REAL_FINISHED_COMMENT, updated_at=AFTER_HEAD),
                ]
            )
        )
        assert verdict["state"] == "success"
        assert AFTER_HEAD in verdict["description"]


class TestFormalReviews:
    @pytest.mark.parametrize("state", ["APPROVED", "CHANGES_REQUESTED"])
    def test_a_formal_verdict_satisfies_the_gate(self, state):
        verdict = run_gate(pr(reviews=[review(state)]))
        assert verdict["state"] == "success"
        assert state in verdict["description"]

    @pytest.mark.parametrize("state", ["COMMENTED", "DISMISSED", "PENDING"])
    def test_a_non_verdict_review_state_does_not(self, state):
        assert run_gate(pr(reviews=[review(state)]))["state"] == "failure"

    def test_a_null_submitted_at_is_not_treated_as_stale(self):
        verdict = run_gate(pr(reviews=[review("APPROVED", submitted_at=None)]))
        assert verdict["state"] == "success"

    def test_a_stale_formal_review_is_refused(self):
        verdict = run_gate(pr(reviews=[review("APPROVED", submitted_at=BEFORE_HEAD)]))
        assert verdict["state"] == "failure"
        assert "predate its head commit" in verdict["description"]

    def test_a_bot_comment_is_reported_in_preference_to_a_formal_review(self):
        verdict = run_gate(
            pr(comments=[comment(REAL_FINISHED_COMMENT)], reviews=[review("APPROVED")])
        )
        assert verdict["state"] == "success"
        assert "comment by claude[bot]" in verdict["description"]


class TestTheDependabotExemption:
    def test_dependabot_is_exempt_with_no_review_at_all(self):
        verdict = run_gate(pr(author="dependabot[bot]"))
        assert verdict["state"] == "success"
        assert "Dependabot" in verdict["description"]

    def test_a_chore_title_is_NOT_exempt(self):
        # Deliberate: a title prefix is a one-word self-service bypass for any
        # agent, which is the opposite of what the gate is for. The remedy is
        # `/review`, so this is backpressure rather than a dead end.
        verdict = run_gate(pr(title="chore(deps): bump something"))
        assert verdict["state"] == "failure"

    def test_a_login_merely_containing_dependabot_is_not_exempt(self):
        assert run_gate(pr(author="not-dependabot[bot]-really"))["state"] == "failure"


class TestTheDescriptionFitsTheCommitStatusField:
    """GitHub truncates a status description past 140 characters."""

    def test_every_verdict_in_this_suite_fits(self):
        docs = [
            pr(),
            pr(author="dependabot[bot]"),
            pr(comments=[comment(REAL_FINISHED_COMMENT)]),
            pr(comments=[comment(REAL_FINISHED_COMMENT, updated_at=BEFORE_HEAD)]),
            pr(reviews=[review("APPROVED")]),
        ]
        for doc in docs:
            assert len(run_gate(doc)["description"]) <= 140

    def test_a_long_login_is_truncated_with_an_ellipsis(self):
        verdict = run_gate(pr(comments=[comment(REAL_FINISHED_COMMENT, login="x" * 300)]))
        # Refused (not an allow-listed bot) -- the point is the length bound.
        assert len(verdict["description"]) <= 140

    def test_truncation_actually_triggers_on_an_overlong_why(self):
        verdict = run_gate(
            pr(
                bot_logins=["b" * 200],
                comments=[comment(REAL_FINISHED_COMMENT, login="b" * 200)],
            )
        )
        assert verdict["state"] == "success"
        assert len(verdict["description"]) == 140
        assert verdict["description"].endswith("...")


class TestTheVerdictShape:
    @pytest.mark.parametrize(
        "doc",
        [pr(), pr(author="dependabot[bot]"), pr(comments=[comment(REAL_FINISHED_COMMENT)])],
        ids=["absent", "exempt", "present"],
    )
    def test_the_verdict_has_exactly_the_two_expected_keys(self, doc):
        verdict = run_gate(doc)
        assert set(verdict) == {"state", "description"}
        assert verdict["state"] in {"success", "failure"}

    def test_missing_optional_fields_do_not_crash_the_gate(self):
        # `require-review.yml` builds this document from four API calls; a
        # field absent from an unexpected payload must not take the gate down,
        # because a dead gate publishes `error` and tells nobody anything.
        verdict = run_gate({"comments": [], "reviews": []})
        assert verdict["state"] == "failure"
        assert "#0" in verdict["description"]
