"""Guards on `.github/workflows/require-review.yml` and its wiring.

Companion to `test_review_workflow_config.py` (which guards the *reviewer*) and
to `test_review_gate_decision.py` (which guards the *decision logic*). This
module guards the third thing: the plumbing that connects them, and the
cross-file agreements that nothing else can see.

Deliberately parsed as text rather than YAML, matching
`test_review_workflow_config.py`: the repo declares no yaml dependency, and a
guard that only runs where an optional import succeeded is one that silently
stops guarding.

Several assertions here are *absence* assertions -- "this token does not appear
in that block". An absence assertion over a file that happens to be clean is
indistinguishable from a tautology, so each detector used below is also driven
to a failure on a synthetic input in ``TestTheDetectorsCanFail``. Without that,
a future refactor could break the extractor and every guard in this module
would go green over whatever it was supposed to catch.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
GATE_WORKFLOW = WORKFLOWS / "require-review.yml"
REVIEWER_WORKFLOW = WORKFLOWS / "claude-code-review.yml"
CI_WORKFLOW = WORKFLOWS / "ci.yml"
GATE_LOGIC = REPO_ROOT / ".github" / "review-gate.jq"
GLOSSARY = REPO_ROOT / "GLOSSARY.md"

#: The commit-status context the gate publishes under. Hard-coded in the
#: workflow and referenced in prose; pinned here so a rename cannot leave a PR
#: carrying two contexts, one of them permanently stale and red.
STATUS_CONTEXT = "dispatch/require-review"

#: The PR authors the gate exempts, and the same set the reviewer's `if:`
#: declines. Shared rather than written twice -- a divergence here is how a
#: gate starts demanding a review the reviewer refuses to perform.
EXEMPT_AUTHORS = ("dependabot[bot]",)

#: The reviewer additionally declines PRs whose title starts with this, and the
#: gate deliberately does NOT exempt them. Asserted to be exactly one prefix:
#: if a `docs` prefix is ever added over there, this goes red and the decision
#: gets made on purpose instead of by omission.
REVIEWER_TITLE_PREFIXES = ("chore",)

#: The GitHub expression opening token. Spelled by concatenation so this
#: constant is not itself an expression when a tool scans this file.
EXPR_OPEN = "${" + "{"


def run_blocks(text: str) -> list[str]:
    """Every `run:` block body in a workflow, as text.

    Handles the block-scalar form (`run: |`) and the one-line form. Returns the
    bodies only, so an assertion about a `run:` body cannot accidentally be
    satisfied or violated by an `env:` value on a neighbouring line -- which is
    the whole point, since passing values through `env:` is the *fix* this
    module asserts, not the defect.
    """
    blocks: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        match = re.match(r"^(\s*)-?\s*run:\s*(\|-?|>-?)?\s*(.*)$", lines[i])
        if not match:
            i += 1
            continue
        indent, scalar, inline = match.group(1), match.group(2), match.group(3)
        if scalar is None:
            blocks.append(inline)
            i += 1
            continue
        body: list[str] = []
        i += 1
        while i < len(lines):
            line = lines[i]
            if line.strip() and not line.startswith(indent + " "):
                break
            body.append(line)
            i += 1
        blocks.append("\n".join(body))
    return blocks


def active_lines(text: str) -> str:
    """``text`` with comments stripped, for assertions about what the file DOES.

    An absence assertion over raw text cannot tell a setting from a paragraph
    explaining why that setting is wrong -- and these workflows carry long
    explanatory comments that name the wrong spellings on purpose. Stripping
    comments is what makes "this file does not key on X" mean it.

    Driven to a failure in ``TestTheDetectorsCanFail``.
    """
    out = []
    for line in text.splitlines():
        stripped = line.split("#", 1)[0] if line.lstrip().startswith("#") else line
        if "#" in stripped and not line.lstrip().startswith("#"):
            # An end-of-line comment (` # v7.0.1`). Only cut on ` #`, so a `#`
            # inside a quoted string or an expression survives.
            stripped = re.split(r"\s#", stripped, maxsplit=1)[0]
        out.append(stripped)
    return "\n".join(out)


def prose(path: Path) -> str:
    """A file's text with runs of whitespace collapsed, for phrase matching."""
    return re.sub(r"\s+", " ", path.read_text())


@pytest.fixture(scope="module")
def gate() -> str:
    return GATE_WORKFLOW.read_text()


class TestTheGateFilesExist:
    def test_the_workflow_exists(self):
        assert GATE_WORKFLOW.is_file()

    def test_the_decision_logic_exists_where_the_workflow_looks_for_it(self, gate):
        assert GATE_LOGIC.is_file()
        # The path appears twice: once in `sparse-checkout`, once in the `jq -f`
        # invocation. A sparse checkout of the wrong path yields a job that
        # cannot find its own gate, which the ERR trap turns into `error`.
        rel = ".github/review-gate.jq"
        assert gate.count(rel) >= 2, "the workflow must both check out and run the gate file"
        assert f"sparse-checkout: {rel}" in gate
        assert f"jq -f {rel}" in gate


class TestTheTriggersCoverEveryWayAVerdictCanChange:
    @pytest.mark.parametrize(
        "event,types",
        [
            ("pull_request", ["opened", "synchronize", "reopened"]),
            ("issue_comment", ["created", "edited"]),
            ("pull_request_review", ["submitted"]),
        ],
    )
    def test_each_trigger_and_its_types_are_declared(self, gate, event, types):
        assert re.search(rf"^  {re.escape(event)}:", gate, re.MULTILINE), f"{event} trigger missing"
        declared = re.search(
            rf"^  {re.escape(event)}:\n(?:.*\n)*?\s+types: \[([^\]]+)\]", gate, re.MULTILINE
        )
        assert declared, f"{event} declares no types"
        assert {t.strip() for t in declared.group(1).split(",")} == set(types)

    def test_synchronize_is_on_here_even_though_the_reviewer_drops_it(self, gate):
        # The asymmetry is the design: a fix-up push moves the head, the
        # reviewer does not re-run (metaframework#320 §5 burn cut), and this
        # status therefore goes red on the new head. Asserting both halves so
        # the pair cannot drift into agreeing by accident.
        assert "synchronize" in gate
        reviewer = REVIEWER_WORKFLOW.read_text()
        pr_types = re.search(
            r"^  pull_request:\n(?:.*\n)*?\s+types: \[([^\]]+)\]", reviewer, re.MULTILINE
        )
        assert pr_types, "the reviewer declares no pull_request types"
        assert "synchronize" not in pr_types.group(1)

    def test_edited_is_declared_because_the_progress_comment_is_edited_in_place(self, gate):
        issue_comment = re.search(
            r"^  issue_comment:\n(?:.*\n)*?\s+types: \[([^\]]+)\]", gate, re.MULTILINE
        )
        assert "edited" in issue_comment.group(1)


class TestTheStatusLandsOnThePrHead:
    def test_it_posts_a_commit_status_rather_than_relying_on_its_own_check(self, gate):
        assert "statuses/${SHA}" in gate, "the status must be POSTed to the resolved head SHA"
        assert f'context="{STATUS_CONTEXT}"' in gate

    def test_it_requests_the_permission_that_post_needs(self, gate):
        assert "statuses: write" in gate

    def test_concurrency_does_not_cancel(self, gate):
        # A *cancelled* run paints the PR red even when the authoritative
        # status is green (metaframework#511).
        assert "cancel-in-progress: false" in gate

    def test_the_issue_comment_path_resolves_a_head_sha(self, gate):
        # `issue_comment` carries no pull_request object; without the lookup the
        # status would be posted to an empty SHA.
        assert 'sha="$(gh api "repos/${REPO}/pulls/${number}" --jq .head.sha)"' in gate


class TestFailureModesPublishSomethingRatherThanNothing:
    def test_an_unset_reviewer_secret_publishes_pending(self, gate):
        assert "publish pending" in gate
        assert 'if [ -z "${REVIEWER_TOKEN}" ]' in gate
        assert "CLAUDE_CODE_OAUTH_TOKEN" in gate

    def test_an_internal_failure_publishes_error_via_a_trap(self, gate):
        # Without the trap the step dies under `set -e` and NO status is posted,
        # so the PR keeps its previous verdict -- which on a re-evaluation of an
        # approved-then-pushed PR is a stale GREEN.
        # `active_lines`, not the raw text: commenting the trap out with a
        # leading `#` leaves the substring in place, and the raw-text version of
        # this assertion reported the disabled trap as present (mutation round,
        # 2026-11-01).
        assert re.search(r"trap 'publish error", active_lines(gate))
        assert "|| true" in gate, "a failing publish inside the trap must not recurse"

    def test_the_shell_is_strict_in_every_run_block(self, gate):
        for block in run_blocks(gate):
            assert "set -euo pipefail" in block, f"non-strict run block: {block[:60]!r}"


class TestTheForkDiscriminatorIsTheOneThatAnswersTheQuestion:
    def test_it_compares_head_repo_full_name(self, gate):
        assert "head.repo.full_name" in active_lines(gate)

    def test_it_does_not_key_on_head_repo_fork(self, gate):
        # `.fork` is a property of the REPO, so in a repo that is itself a fork
        # it is true for every same-repo branch and skips 100% of its PRs while
        # looking like a correctly-installed gate. True of bluelinky; not of
        # this repo today, which is exactly why it is worth pinning before
        # someone "simplifies" it. Read against the active YAML, because the
        # comment above that `if:` names `.fork` on purpose in order to warn
        # the next reader off it.
        assert "head.repo.fork" not in active_lines(gate)


class TestNoGitHubExpressionsInsideRunBlocks:
    """The trap that made bluelinky's copy of this file unparseable.

    GitHub evaluates `${{ … }}` before the shell sees the script, so an
    expression inside a `#` **comment** is still parsed -- and an invalid one
    makes the whole workflow file invalid. The tell was a run that FAILED with
    zero jobs, no annotation and no log, while `check-yaml`, `prettier` and
    `@action-validator/cli` all passed the file.

    Passing values through `env:` instead also removes the command-injection
    surface, which matters because one of the fields this gate reads is the PR
    title.
    """

    def test_the_gate_workflow_has_none(self, gate):
        for block in run_blocks(gate):
            assert EXPR_OPEN not in block, (
                "a GitHub expression inside a run: block -- pass it through env: instead:\n"
                f"{block[:200]}"
            )

    def test_the_gate_workflow_does_pass_values_through_env(self, gate):
        # The positive half. Without it the test above is satisfied by a
        # workflow that reads no event data at all.
        assert "REPO: ${{ github.repository }}".replace("${{", EXPR_OPEN) in gate
        assert "EVENT_NAME:" in gate and "PR_HEAD_SHA:" in gate

    def test_the_reviewer_workflow_is_a_known_exemption(self):
        """`claude-code-review.yml` violates this rule and cannot be fixed here.

        Stated rather than silently scoped around. The reviewer's `Resolve PR
        head SHA` step interpolates `github.event_name`,
        `github.event.issue.number`, `github.repository` and
        `github.event.pull_request.head.sha` directly into its script.

        Two things are true and both matter:

        * It is **not currently an injection**. All four of those values are
          GitHub-controlled -- an event name from a fixed set, two numbers, a
          repo slug and a SHA. None carries attacker-supplied text. So this is
          the pattern, not a live vulnerability, and this test does not claim
          otherwise.
        * It **cannot be fixed from a reviewable PR**. Editing
          `claude-code-review.yml` triggers the *workflow validation skip* this
          repo documents in `CLAUDE.md` and `GLOSSARY.md`: the run goes green
          having reviewed nothing. So the fix needs Tom's explicit approval and
          is proved by the PR after it.

        This test pins the exemption to the file it is about, so the day
        somebody does fix the reviewer it goes red and gets deleted, rather
        than the exemption outliving its reason.
        """
        reviewer_blocks = run_blocks(REVIEWER_WORKFLOW.read_text())
        offending = [b for b in reviewer_blocks if EXPR_OPEN in b]
        assert offending, (
            "claude-code-review.yml no longer interpolates expressions in a run: "
            "block -- delete this exemption and fold it into the rule above."
        )


class TestTheTwoHalvesAgreeWithEachOther:
    def test_the_exempt_author_lists_agree(self, gate):
        logic = GATE_LOGIC.read_text()
        reviewer = REVIEWER_WORKFLOW.read_text()
        for author in EXEMPT_AUTHORS:
            assert author in logic, f"{author} not exempt in the decision logic"
            assert author in reviewer, f"{author} not declined by the reviewer"
            assert author in gate or author in logic

    def test_the_reviewers_title_prefix_list_is_exactly_chore(self):
        # The gate deliberately does not exempt title prefixes. That choice is
        # only safe while the reviewer declines exactly one, so a new prefix
        # over there must surface as a decision here.
        reviewer = REVIEWER_WORKFLOW.read_text()
        found = set(
            re.findall(r"startsWith\(github\.event\.pull_request\.title, '([^']+)'\)", reviewer)
        )
        assert found == set(REVIEWER_TITLE_PREFIXES), f"reviewer title prefixes drifted: {found}"

    def test_the_gate_does_not_exempt_a_title_prefix(self):
        logic = GATE_LOGIC.read_text()
        exempt = logic[logic.index("def exempt_reason:") :]
        exempt = exempt[: exempt.index(";")]
        assert ".title" not in exempt, (
            "a title prefix is a one-word self-service bypass for any agent"
        )

    def test_both_remedy_spellings_the_reviewer_accepts_also_re_fire_the_gate(self, gate):
        reviewer = REVIEWER_WORKFLOW.read_text()
        spellings = set(
            re.findall(r"contains\(github\.event\.comment\.body, '([^']+)'\)", reviewer)
        )
        assert spellings, "the reviewer accepts no comment remedy at all"
        for spelling in spellings:
            assert f"'{spelling}'" in gate, (
                f"the reviewer runs on {spelling!r} but the gate ignores that comment, "
                "so asking for a review that way would not re-publish the status"
            )

    def test_the_bot_login_the_gate_trusts_is_the_one_the_reviewer_posts_as(self, gate):
        assert "claude[bot]" in GATE_LOGIC.read_text()
        assert "claude[bot]" in gate


class TestTheDependencyOnJqIsDeclaredWhereItRuns:
    def test_ci_proves_jq_is_available(self):
        # This is the control that keeps `test_review_gate_decision.py` honest.
        # That module shells out to jq; if jq were absent in CI its tests would
        # fail confusingly rather than naming the cause, and a `skipif` there
        # would have made the whole module vanish silently instead.
        ci = CI_WORKFLOW.read_text()
        assert "jq --version" in ci, "CI must prove jq is on the runner before running tests"

    def test_the_decision_tests_do_not_skip_themselves_away(self):
        decision_tests = (REPO_ROOT / "tests" / "test_review_gate_decision.py").read_text()
        assert "pytestmark" not in decision_tests, (
            "a module-level skipif would also cover the test asserting jq exists, so "
            "a missing jq would read as 43 skipped and exit 0"
        )


class TestTheVocabularyIsRecorded:
    def test_the_glossary_has_a_row_for_the_status(self):
        assert STATUS_CONTEXT in GLOSSARY.read_text(), (
            f"{STATUS_CONTEXT} is a new domain term and needs a GLOSSARY.md row"
        )

    def test_the_glossary_distinguishes_the_status_from_a_re_gate(self):
        # `re-gate`'s existing row says `/review` cannot move the PR's check
        # state, which is true of a check-run and NOT of this commit status.
        # Left unqualified, the two rows contradict each other.
        text = prose(GLOSSARY)
        assert "commit status" in text, (
            "the glossary must say why /review moves this status but not the check-run"
        )


class TestTheDetectorsCanFail:
    """Drive each detector to a failure, so no guard above is a tautology."""

    def test_run_blocks_finds_a_block_scalar_body(self):
        blocks = run_blocks(
            "jobs:\n  a:\n    steps:\n      - name: x\n        run: |\n"
            "          set -euo pipefail\n          echo hi\n      - uses: actions/checkout@v4\n"
        )
        assert len(blocks) == 1
        assert "echo hi" in blocks[0]
        assert "actions/checkout" not in blocks[0], "the extractor ran past the end of the block"

    def test_run_blocks_finds_an_inline_body(self):
        assert run_blocks("      - run: jq --version\n") == ["jq --version"]

    def test_run_blocks_excludes_env_values_above_the_body(self):
        blocks = run_blocks(
            "      - name: x\n        env:\n          REPO: "
            + EXPR_OPEN
            + " github.repository }}\n"
            '        run: |\n          echo "$REPO"\n'
        )
        assert len(blocks) == 1
        assert EXPR_OPEN not in blocks[0], (
            "the extractor swept in an env: line, which would make the expression ban "
            "fire on the correct fix"
        )

    def test_the_expression_ban_catches_an_expression_in_a_run_body(self):
        blocks = run_blocks(
            "      - run: |\n          echo " + EXPR_OPEN + " github.event.pull_request.title }}\n"
        )
        assert any(EXPR_OPEN in b for b in blocks), "the ban cannot see a real violation"

    def test_the_expression_ban_catches_one_inside_a_comment(self):
        # The bluelinky case exactly: a commented-out expression is still
        # parsed by GitHub, and an invalid one invalidates the file.
        blocks = run_blocks(
            "      - run: |\n          # see " + EXPR_OPEN + " }}\n          true\n"
        )
        assert any(EXPR_OPEN in b for b in blocks)

    def test_the_strict_shell_guard_catches_a_non_strict_block(self):
        blocks = run_blocks("      - run: |\n          echo hi\n")
        assert not any("set -euo pipefail" in b for b in blocks)

    def test_active_lines_strips_a_whole_line_comment(self):
        assert "head.repo.fork" not in active_lines("        # never use head.repo.fork\n")

    def test_active_lines_strips_an_end_of_line_comment(self):
        assert "v7.0.1" not in active_lines("      - uses: actions/checkout@abc # v7.0.1\n")

    def test_active_lines_keeps_the_setting_it_is_asked_about(self):
        # The half that makes the two above meaningful: a stripper that removed
        # everything would satisfy every absence assertion in this module.
        kept = active_lines('          head_repo="$HEAD_REPO"  # a comment\n')
        assert "head_repo=" in kept

    def test_active_lines_can_still_see_a_real_violation(self):
        assert "head.repo.fork" in active_lines(
            "          HEAD_FORK: " + EXPR_OPEN + " github.event.pull_request.head.repo.fork }}\n"
        )

    def test_the_title_prefix_detector_finds_more_than_one_when_there_is_more_than_one(self):
        synthetic = (
            "!startsWith(github.event.pull_request.title, 'chore') "
            "&& !startsWith(github.event.pull_request.title, 'docs')"
        )
        found = set(
            re.findall(r"startsWith\(github\.event\.pull_request\.title, '([^']+)'\)", synthetic)
        )
        assert found == {"chore", "docs"}, "the detector cannot see a second prefix"

    def test_the_remedy_spelling_detector_finds_both_spellings(self):
        synthetic = (
            "contains(github.event.comment.body, '/review') "
            "|| contains(github.event.comment.body, '@claude review')"
        )
        found = set(re.findall(r"contains\(github\.event\.comment\.body, '([^']+)'\)", synthetic))
        assert found == {"/review", "@claude review"}
