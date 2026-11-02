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
AGENT_DOC = Path(__file__).resolve().parents[1] / "CLAUDE.md"
GLOSSARY = Path(__file__).resolve().parents[1] / "GLOSSARY.md"

#: Every run of this workflow that concluded `success` without reviewing
#: anything, because the action found the branch copy of the workflow differed
#: from the default branch's. Re-derived from the Actions API on 2026-10-22,
#: all 25 runs: these three are the *only* greens, and there are no real
#: reviews. `CLAUDE.md` carries the full table; the guard below asserts the two
#: stay in step, so adding a fourth instance cannot leave the prose behind.
WORKFLOW_VALIDATION_SKIP_RUNS = {
    "30537851656": 3,  # claude/review-gate-inline-comments, 1,695 ms
    "35360053668": 14,  # claude/707-reopened-trigger,        1,616 ms
    "36484572525": 16,  # claude/9-review-turn-budget,        1,625 ms
}

#: The action's own log line, and therefore the thing to grep for. Shared
#: between the guard and the prose for the same reason as the run IDs.
VALIDATION_SKIP_LOG_LINE = "Exiting due to workflow validation skip"

#: The first run of this workflow that actually reviewed anything, 2026-10-23.
#: Kept beside the skip list because it is the control for it: every claim
#: about what a skip looks like is only meaningful against a run that did not
#: skip. 42 s, 4 turns, $0.138, `duration_ms=42000`.
FIRST_REAL_REVIEW_RUN = "39897838521"

#: The nested `run` step's `duration_ms` for each skip, from the
#: `##[end-action ...]` line of each run's log. These are what make "~1.6 s is
#: the signature of this failure mode, not a quirk of one run" a checkable
#: claim rather than an assertion: the spread is 79 ms across 14 months.
SKIP_DURATIONS_MS = {"30537851656": 1695, "35360053668": 1616, "36484572525": 1625}

#: Every conclusion the 25 runs produced, re-derived 2026-10-22. Shared with
#: the table in `CLAUDE.md` so a count cannot drift in prose: a review round
#: found that raising `skipped` from 21 to 99 in the document left the suite
#: green, because nothing read that cell.
RUN_TOTALS = {"skipped": 21, "success": len(WORKFLOW_VALIDATION_SKIP_RUNS), "failure": 1}

#: The three instructions scope item 3 of #9 actually asked to be written down.
#: Guarded because the run table was not the deliverable -- this is. A review
#: round deleted the whole `### What to do instead` section, and separately
#: inverted all three bullets, with the suite green both times.
GUIDANCE_PHRASES = (
    "Gets Tom's explicit approval",
    "Is proved by the *next* PR",
    "Should not carry unrelated changes",
)

#: The claim the document's conclusion rests on. Inverting it to "reviews
#: normally and reports `failure`" also passed a green suite.
MECHANISM_PHRASES = (
    # Not the action comparing two copies, which is what an earlier draft said.
    "The validation is **server-side",
    "workflow_not_found_on_default_branch",
    # And the green IS distinguishable without logs, which that draft denied.
    "`conclusion` output is **empty**",
    # Which makes the behaviour auth-mode-dependent rather than absolute.
    "Supplying `github_token` would bypass it entirely",
    # And the recipe this document gives must not be the one that misfires on
    # this document. Run 39897838521 is a real review whose log matches the
    # grep string once, because the reviewer read the paragraph telling it to.
    "**Do not grep the whole log for that string.**",
    '`"num_turns"` is the cheapest positive test',
    # The `conclusion` snippet is useless without an `id:` on the action step,
    # and worse than useless: with no id it is `''` on every run, so a copied
    # guard fails real reviews too. The review caught the prose implying the
    # id rather than showing it.
    # Whitespace-collapsed, because this is matched through `prose()` and the
    # snippet aligns the comment with spaces.
    "id: review # <- this line is load-bearing",
)

#: Headings that announce how many bullets follow them. A count in prose
#: cannot be derived from anything, so it drifts the moment a bullet is added
#: -- which is exactly what happened to both of these in review, in a document
#: whose whole subject is one number copied into four places.
BULLET_COUNT_PHRASES = (
    ("Three consequences worth being precise about", 3),
    ("Three things follow, two of which earlier write-ups", 3),
)


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


def prose(path: Path) -> str:
    """Return ``path``'s text with every run of whitespace collapsed to a space.

    Prose guards have to read it this way. The phrases below are sentences a
    human wrote and a human will reflow: ``"is the first real review"`` sat
    across a line break with a two-space indent, and an exact-match guard on it
    went red for a wrap rather than for a change in meaning. Table cells and
    run IDs are matched exactly, because those cannot wrap.
    """
    return " ".join(path.read_text().split())


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
    """Every trigger this gate has. Re-measured 2026-10-22 over all 25 recorded
    runs of this workflow, it has still produced **zero** reviews:

    - **21 `skipped`** — filtered out by the job's `if:`: Dependabot bumps,
      `chore` pull requests, and `issue_comment` runs with no `/review`.
    - **3 `success`** — every one a `workflow validation skip`
      (`WORKFLOW_VALIDATION_SKIP_RUNS` below), each on a PR that edited this
      file. Not two: the 2026-09-28 reading of this predates run 36484572525,
      which is the run on PR #16 — the PR that added this very file.
    - **1 `failure`** — run 30432219327 (PR #2), `steps=0` ten seconds after
      spawn: the runner was never provisioned, the Actions minute cap.

    So the settings the class above pins have never been exercised here, and
    these guards cannot be validated by "the gate went green once" — *all three*
    greens on record are a gate that did nothing. Pin the triggers instead: a
    dropped trigger is the one failure mode that would keep that record at zero
    forever while looking exactly like it does now.
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


class TestTheWorkflowValidationSkipStaysDocumented:
    """Scope item 3 of #9.

    The gate cannot review a PR that edits it, so the only thing standing
    between that fact and the next person reading a 1.6-second green check is
    prose — and prose with nothing asserting it rots. These guards share
    `WORKFLOW_VALIDATION_SKIP_RUNS` and `VALIDATION_SKIP_LOG_LINE` with the
    document rather than restating them, so a fourth instance of the failure
    cannot be recorded in one place and not the other.

    Deliberately NOT a comment block inside `claude-code-review.yml`: writing
    it there would make the PR that adds it unreviewable, which is the rule
    defeating its own documentation. These files are reviewable, which is the
    whole reason the note lives in them.
    """

    def test_the_agent_doc_exists(self):
        assert AGENT_DOC.is_file(), f"CLAUDE.md not found: {AGENT_DOC}"

    def test_the_agent_doc_names_the_log_line_to_grep_for(self):
        """A reader who has the green check needs the string, not a paraphrase."""
        assert VALIDATION_SKIP_LOG_LINE in AGENT_DOC.read_text()

    @pytest.mark.parametrize("run_id", sorted(WORKFLOW_VALIDATION_SKIP_RUNS))
    def test_every_known_instance_is_in_the_agent_doc(self, run_id: str):
        """Parametrised over the constant, not over a hand-typed list.

        A single `assert all(...)` would pass a new entry the document never
        gained, as long as the old ones were still there — the aggregate hides
        which member failed. One case per run is what makes the fourth
        instance fail loudly.
        """
        assert run_id in AGENT_DOC.read_text()

    @pytest.mark.parametrize("run_id,pr", sorted(WORKFLOW_VALIDATION_SKIP_RUNS.items()))
    def test_each_instance_is_attributed_to_its_pull_request(self, run_id: str, pr: int):
        """Run ID *and* PR number, because the two have been mismatched before.

        Membership is not correspondence: asserting both strings appear
        somewhere in the file would pass a table that paired run
        30537851656 with PR #16. Anchored to the table row so the pairing is
        what is checked.
        """
        rows = [line for line in AGENT_DOC.read_text().splitlines() if run_id in line]
        assert rows, f"no line mentions run {run_id}"
        # `/pull/3` is a prefix of `/pull/31`, so a bare substring test passes
        # a row that pairs this run with PR #31. The repo is at PR #22, so that
        # was weeks from being a live false pass rather than a hypothetical.
        assert any(re.search(rf"/pull/{pr}\)", row) for row in rows), (
            f"run {run_id} is documented, but not against PR #{pr}: {rows}"
        )

    @pytest.mark.parametrize("conclusion,count", sorted(RUN_TOTALS.items()))
    def test_every_run_total_is_read_out_of_the_table(self, conclusion: str, count: int):
        """Each cell, not just the one that happens to matter.

        Guarding only `success` left `skipped` free to say 99. One case per
        conclusion because an aggregate hides which cell went stale.
        """
        assert f"| `{conclusion}` | {count} |" in AGENT_DOC.read_text()

    @pytest.mark.parametrize("run_id,duration", sorted(SKIP_DURATIONS_MS.items()))
    def test_each_instances_duration_is_transcribed_correctly(self, run_id: str, duration: int):
        """Anchored to the run's own row, not to the file.

        These are immutable historical measurements, so they cannot go stale —
        they can only be mis-transcribed by a future editor, and a review round
        showed all three could be rewritten to 9,999 ms with the suite green.
        Asserted per row because the document's argument is that they *agree*;
        a check that accepted any one of them would not notice two of three
        being changed.
        """
        rows = [line for line in AGENT_DOC.read_text().splitlines() if run_id in line]
        assert rows, f"no line mentions run {run_id}"
        assert any(f"{duration:,} ms" in row for row in rows), (
            f"run {run_id}'s duration is not documented as {duration:,} ms: {rows}"
        )

    def test_the_durations_support_the_claim_made_about_them(self):
        """The document says the spread is 1.62-1.70 s. Check the data says so.

        A guard on the transcription alone would happily pin three numbers that
        refute the sentence they are cited for.
        """
        # 1,616 ms is the fastest, and it rounds to 1.62 s — so the lower
        # bound is the smallest value the document's own wording admits, not
        # 1,620 with a fudge subtracted from it.
        assert min(SKIP_DURATIONS_MS.values()) >= 1_615
        assert max(SKIP_DURATIONS_MS.values()) <= 1_700
        assert "1.62-1.70 s" in prose(AGENT_DOC).replace("\u2013", "-")

    @pytest.mark.parametrize("phrase", GUIDANCE_PHRASES)
    def test_the_guidance_survives(self, phrase: str):
        """This, not the run table, is what the ticket asked for.

        The historical facts were already pinned by immutable run IDs -- the
        rot risk was never there. It was here: the guidance is the part a
        future edit would trim as verbose, and it is the part that tells
        somebody staring at a 1.6-second green what to do.
        """
        assert phrase in prose(AGENT_DOC)

    @pytest.mark.parametrize("phrase", MECHANISM_PHRASES)
    def test_the_mechanism_is_still_described_correctly(self, phrase: str):
        """Pins the three load-bearing claims, each separately falsifiable.

        An earlier draft said the *action* compared the two copies and that
        nothing distinguished a skip from a review without reading logs. Both
        were wrong -- it is Anthropic's token-exchange endpoint that refuses,
        and the `conclusion` output is empty on a skip. Pinned so the
        corrections cannot quietly revert.
        """
        assert phrase in prose(AGENT_DOC)

    def test_the_first_real_review_is_on_the_record(self):
        """The one run that proves the gate can work, and #9's own proof standard.

        Item 3 of #9 says the proof of a workflow edit is the *next* PR. PR #20
        edited the gate; this document's PR is that next PR, and run
        39897838521 is the first review this repo ever received. Pinned
        because "zero reviews in its entire history" was true when written and
        is the kind of sentence that survives being falsified.
        """
        body = prose(AGENT_DOC)
        assert FIRST_REAL_REVIEW_RUN in body
        assert "is the first real review" in body
        assert "for its first 25 runs" in body, (
            "the zero-reviews claim is no longer bounded — it was falsified by "
            f"run {FIRST_REAL_REVIEW_RUN} and must stay in the past tense"
        )

    @pytest.mark.parametrize("phrase,expected", BULLET_COUNT_PHRASES)
    def test_a_heading_that_counts_its_bullets_still_counts_right(self, phrase: str, expected: int):
        """Counts the bullets under the heading, rather than pinning the word.

        Pinning the phrase alone would hold the number steady while a fourth
        bullet appeared beneath it -- the same drift this document exists to
        complain about, which review found twice in my own prose. So the
        assertion reads the structure and compares it against the word.
        """
        assert phrase in prose(AGENT_DOC), f"heading moved or was reworded: {phrase!r}"
        # Raw text from here on: the count comes from the line structure, which
        # `prose()` destroys. So the heading has to sit on a single line, and
        # the assertion below is what tells a future editor that when they
        # reflow it.
        body = AGENT_DOC.read_text()
        assert phrase in body, (
            f"{phrase!r} is in the document but wrapped across lines, so the "
            "bullet count below cannot be anchored. Keep it on one line."
        )
        after = body.split(phrase, 1)[1]
        # The list ends at the first blank line that is not inside it: bullets
        # here are "- " at column 0, continuation lines are indented.
        bullets = 0
        for line in after.splitlines():
            if line.startswith("- "):
                bullets += 1
            elif line and not line.startswith(" ") and bullets:
                break
        assert bullets == expected, f"{phrase!r} announces {expected}, found {bullets}"

    def test_the_stale_workflow_comment_is_acknowledged(self):
        """The workflow's own comment block still carries the 14-run reading.

        It cannot be corrected from a reviewable PR, so the next best thing is
        saying which copy is authoritative. If someone does fix that comment,
        this guard is the reminder to drop the acknowledgement with it.
        """
        body = prose(AGENT_DOC)
        assert "Known stale copy" in body
        assert "all 14 recorded runs" in WORKFLOW.read_text(), (
            "the workflow comment no longer carries the superseded reading — "
            "drop the 'Known stale copy' section from CLAUDE.md"
        )

    def test_the_glossary_owns_the_term(self):
        """`workflow validation skip` is the canonical name (GLOSSARY discipline).

        Named after the action's own log line rather than after the behaviour,
        so an agent grepping the failure lands on the term. The aliases this
        repo's own issues and comments used — "anti-tamper validation" — ride
        on the row so they lead here too.
        """
        body = GLOSSARY.read_text()
        assert "**workflow validation skip**" in body
        # The spellings this repo's own issues and comments used, so an agent
        # arriving on a legacy name lands here and switches over.
        assert "anti-tamper validation" in body
        # Deliberately does NOT assert a count. The row used to restate "all
        # three of this repo's success runs", which is a fourth copy of one
        # number in a second file — rot the guards cannot see. CLAUDE.md owns
        # the evidence; the row points at it.
        assert "CLAUDE.md" in body


#: Real comment bodies from this repo, abridged to the parts the trigger reads:
#: the opening characters and one `/review` occurrence in context. Every one is
#: a comment that actually exists, cited so a reader can check the excerpt
#: against the source rather than trusting it.
#:
#: Why real bodies rather than invented ones. The defect below is not that
#: `contains` is wrong in the abstract -- it is that the comments this repo's
#: own agents write routinely *mention* `/review`, because the gate's refusal
#: text instructs them to ("Comment /review on PR #N"). An invented fixture
#: would have to guess at that, and a guess is what put the bug here.
TRIGGER_FIXTURES = (
    (
        # https://github.com/tclancy/parsons-remote/pull/26#issuecomment-6563346201
        "genuine-request-6563346201",
        (
            "/review\n\nRe-requesting a review bound to the current head `64d0784`,"
            " which carries only the `issue_comment` documentation commit."
        ),
        True,
    ),
    (
        # https://github.com/tclancy/parsons-remote/pull/26#issuecomment-6563410273
        # Fired run 41346706835 for real: the reviewer replied "Your comment is
        # a status report and doesn't ask for a change, so I changed no files
        # and ran nothing."
        "status-report-6563410273",
        (
            "## Final state — all green, and the gate proved itself on its own PR\n\n"
            "- **head `64d0784`** · `OPEN` / `CLEAN` / `MERGEABLE`\n"
            "… fire `require-review.yml` from a comment, and the `/review` remedy"
            " its own refusal text names does nothing yet."
        ),
        False,
    ),
    (
        # https://github.com/tclancy/parsons-remote/pull/26#issuecomment-6563348913
        # The reviewer's OWN output. Latent rather than live -- see
        # `test_the_reviewers_own_output_would_not_re_trigger_it`.
        "reviewer-output-6563348913",
        (
            "**Claude finished @metaframework-dispatch-bot[bot]'s task in 15s**"
            " —— [View job](https://github.com/tclancy/parsons-remote/actions/runs/1)\n\n"
            'The substrings `"default branch"`, `"issue_comment"` and `"/review"`'
            " appear *anywhere* in the file."
        ),
        False,
    ),
    (
        # The free-form escape hatch, which stays unanchored on purpose. No
        # comment in this repo has used it yet; it is in the workflow's own
        # documented contract and in `require-review.yml`'s sibling condition,
        # so it is pinned here rather than left to the first person to try it.
        "at-claude-midsentence",
        "Thanks -- when you get a chance, @claude review the new fixture please.",
        True,
    ),
    (
        # A URL-quoting comment, the shape that motivated anchoring. `/reviews`
        # contains `/review`, so under the old predicate pasting any reviews
        # endpoint into a comment spawned a reviewer run.
        "quoted-reviews-endpoint",
        "Read it off the thread: `gh api repos/tclancy/parsons-remote/pulls/26/reviews`.",
        False,
    ),
)


def job_if_block(text: str) -> str:
    """The `claude-review` job's `if:` expression, and nothing else.

    Extracted by indentation rather than by "everything up to the next key".
    An earlier draft terminated the match on `^\\s*\\w+:`, which cannot match
    `runs-on:` -- `\\w+` stops at the hyphen -- so the whole regex failed and the
    function returned no terms. Returning no terms is the *safe* direction for
    the fixtures, which is exactly why it had to be caught by a synthetic
    document: against the real workflow a parser that reads nothing and a
    workflow with no trigger are the same observation.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        match = re.match(r"^(\s*)if:(.*)$", line)
        if not match:
            continue
        indent, inline = match.group(1), match.group(2)
        body = [inline]
        for following in lines[i + 1 :]:
            if following.strip() and not following.startswith(indent + " "):
                break
            body.append(following)
        return "\n".join(body)
    return ""


def issue_comment_trigger_terms(text: str) -> list[tuple[str, str]]:
    """The `(operator, literal)` pairs the job's `if:` applies to a comment body.

    Scoped to the `issue_comment` arm deliberately, and this is the same trap
    `pull_request_types` is written around. A bare search for `startsWith(...)`
    over the whole document also matches
    `!startsWith(github.event.pull_request.title, 'chore')` on the
    `pull_request` arm -- a *different* condition, on a different field, which
    is already anchored and has nothing to do with the comment trigger. A guard
    that picked that one up would go green with the comment trigger left
    entirely unanchored.

    Returns an empty list if the arm is missing, so a deleted condition fails
    the fixtures below rather than vacuously satisfying them.
    """
    block = job_if_block(text)
    marker = "github.event_name == 'issue_comment'"
    if marker not in block:
        return []
    return re.findall(
        r"\b(contains|startsWith)\(\s*github\.event\.comment\.body\s*,\s*'([^']*)'\s*\)",
        block[block.index(marker) :],
    )


def fires_reviewer(body: str, terms: list[tuple[str, str]]) -> bool:
    """Evaluate the workflow's own comment predicate against ``body``.

    The operators are read OUT OF THE WORKFLOW rather than reimplemented from
    the spec, which is what makes the fixtures falsifiable: flipping
    `startsWith` back to `contains` in the YAML changes what this function
    does, and the status-report fixture then fails. A hand-written mirror of
    the intended rule would agree with itself no matter what the file said.

    GitHub's `contains` and `startsWith` are both case-insensitive on strings,
    and neither trims -- so a body whose first character is a newline or space
    before `/review` does NOT match `startsWith`, which is a real narrowing
    and is why `@claude review` keeps the unanchored form.
    """
    lowered = body.lower()
    return any(
        lowered.startswith(literal.lower())
        if operator == "startsWith"
        else literal.lower() in lowered
        for operator, literal in terms
    )


@pytest.fixture(scope="module")
def terms() -> list[tuple[str, str]]:
    """The live workflow's comment-trigger terms, or a failure naming the gap."""
    parsed = issue_comment_trigger_terms(WORKFLOW.read_text())
    assert parsed, (
        "no contains()/startsWith() on github.event.comment.body inside the "
        "issue_comment arm of the job `if:` — the on-demand trigger is gone, or "
        "the arm was reshaped past what issue_comment_trigger_terms parses"
    )
    return parsed


class TestOnlyAnActualReviewRequestFiresTheReviewer:
    """The `issue_comment` trigger must detect a *request*, not a *mention*.

    Measured on this repo on 2026-11-02, over every `issue_comment` run of this
    workflow in its history. Two passed the job filter and ran the reviewer for
    real; the rest were skipped. **One of the two was not a review request** --
    run 41346706835, fired by the status report in `TRIGGER_FIXTURES`, whose
    only relationship to a review was the word `/review` twice in prose. The
    reviewer spawned, read the comment, and answered that it had been asked for
    nothing. Half of this repo's on-demand reviews have been that.

    It keeps happening for a structural reason rather than by accident: the
    gate's own refusal text is *"Comment /review on PR #N to run the
    reviewer"*, so every agent comment that quotes the remedy, explains the
    gate, or summarises a gate PR contains the trigger. `contains` cannot tell
    those from a request. Anchoring can -- a request IS the comment that opens
    with the command.
    """

    @pytest.mark.parametrize("name,body,expected", [(f[0], f[1], f[2]) for f in TRIGGER_FIXTURES])
    def test_each_measured_comment_shape_gets_the_right_verdict(
        self, name: str, body: str, expected: bool, terms: list[tuple[str, str]]
    ):
        """One case per shape, not one `all(...)` over the set.

        An aggregate would hide which shape regressed, and the two directions
        fail for opposite reasons: a false positive costs a billable run that
        reviews nothing, a false negative leaves an agent unable to ask for a
        review at all. Both have to be nameable.
        """
        assert fires_reviewer(body, terms) is expected, (
            f"{name}: expected fires_reviewer={expected} under the workflow's own terms {terms}"
        )

    def test_the_slash_review_spelling_is_anchored(self, terms: list[tuple[str, str]]):
        """`startsWith`, and the point is that `contains` is *absent*.

        Asserting only that `startsWith` appears would pass a condition
        carrying both operators, where the unanchored one still admits every
        prose mention — the fix present and inert beside the defect.

        A `{literal: operator}` dict is NOT enough to say that, and the first
        draft of this guard used one. Duplicate keys collapse last-wins, so a
        condition spelling `contains(...) || startsWith(...)` — the defect with
        the fix appended — read back as `startsWith` and passed. Measured: that
        mutant was killed only by the behavioural fixtures, which are
        order-independent, while this assertion stayed green. The SET of
        operators bound to the literal is what has no preferred order.
        """
        operators = {operator for operator, literal in terms if literal == "/review"}
        assert operators == {"startsWith"}, (
            f"the /review trigger must be anchored and anchored ONLY; its "
            f"operators are {operators or 'none'} in {terms}"
        )

    def test_the_at_claude_spelling_stays_unanchored(self, terms: list[tuple[str, str]]):
        """Deliberately `contains`: it is the free-form escape hatch.

        Anchoring is a real narrowing -- `startsWith` does not trim, so a body
        beginning with a blank line or a courtesy sentence misses. `@claude
        review` mid-sentence is the remedy for that, and `require-review.yml`
        admits both spellings for the same reason, so dropping this one would
        leave the two halves of the gate disagreeing about what asks for a
        review.
        """
        operators = {operator for operator, literal in terms if literal == "@claude review"}
        assert operators == {"contains"}, (
            f"the @claude review trigger must be present and unanchored; its "
            f"operators are {operators or 'none'} in {terms}"
        )

    def test_the_reviewers_own_output_would_not_re_trigger_it(self, terms: list[tuple[str, str]]):
        """The latent self-trigger loop, and the second reason to anchor.

        `claude[bot]`'s finished review quotes `/review` -- it is explaining
        the gate -- so its FINAL body matches `contains`. That loop is not live
        today, and it is held off by something narrow: this workflow listens to
        `issue_comment: types: [created]`, and at *created* time the bot's
        comment is still the in-flight `Claude Code is working…` stub with no
        `/review` in it. The real body arrives by EDIT, which is not a trigger
        here. Measured: every `claude[bot]`-actor run of this workflow concluded
        `skipped` with `steps=0`.

        `require-review.yml` must listen to `[created, edited]` to see a review
        finish at all, so "add `edited` here too" is a natural future edit --
        and under `contains` it would make every review the bot posts spawn
        another review. Anchoring defuses that in advance: the bot's output
        opens with `**Claude finished`.
        """
        reviewer_output = next(
            body for name, body, _ in TRIGGER_FIXTURES if name.startswith("reviewer-output")
        )
        assert "/review" in reviewer_output, (
            "fixture no longer contains the substring the old predicate matched, "
            "so it cannot demonstrate the loop it is here for"
        )
        assert not fires_reviewer(reviewer_output, terms)

    def test_the_comment_block_still_describes_the_trigger_it_has(self):
        """The `# Run when:` block above the `if:` is the first thing a reader
        sees, and it said "a comment ... explicitly asks for `/review`" while
        the condition matched any mention. Prose and condition had to disagree
        for the bug to survive being read."""
        assert "opens with `/review`" in prose(WORKFLOW)


class TestTheTriggerGuardsReadTheRightCondition:
    """The scoping property `issue_comment_trigger_terms` exists for.

    Asserted against synthetic documents, because against the real workflow
    these are true by construction — the same reason
    `test_a_commented_out_claude_args_is_not_returned` is written that way.
    """

    def test_the_pull_request_arms_own_startswith_is_not_picked_up(self):
        """The `pull_request` arm anchors a *title* check. A guard that read
        that one would report the comment trigger as anchored while it was
        still `contains`."""
        document = textwrap.dedent("""\
            jobs:
              claude-review:
                if: |
                  (github.event_name == 'pull_request'
                    && !startsWith(github.event.pull_request.title, 'chore'))
                  || (github.event_name == 'issue_comment'
                    && contains(github.event.comment.body, '/review'))
                runs-on: ubuntu-latest
        """)
        assert issue_comment_trigger_terms(document) == [("contains", "/review")]

    def test_a_missing_issue_comment_arm_returns_no_terms(self):
        """Empty, not "nothing to check". The `terms` fixture turns that into a
        failure; returning a permissive default would make a deleted trigger
        pass every fixture above."""
        document = textwrap.dedent("""\
            jobs:
              claude-review:
                if: github.event_name == 'pull_request'
                runs-on: ubuntu-latest
        """)
        assert issue_comment_trigger_terms(document) == []

    def test_fires_reviewer_follows_the_operator_it_is_given(self):
        """The discriminator itself, driven both ways on one body.

        If this passed under both operators the fixtures above would be
        measuring nothing.
        """
        body = "## Status\n\nthe `/review` remedy is named in the refusal text."
        assert fires_reviewer(body, [("contains", "/review")]) is True
        assert fires_reviewer(body, [("startsWith", "/review")]) is False
