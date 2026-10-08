"""What a playbook's stage adds to a step's briefing (``docs/architecture/playbooks.md``).

A stage is briefed with the step's own briefing, so a session that has to start afresh — a
loop-back whose resume failed — knows everything one resumed was told. What differs is the
ask: a plan and a review end with their answer as the final message, and never with the
step's status, a commit or a PR, which are the work's (:func:`stage_epilogue`); a fix is
handed the findings it is to act on, numbered (:func:`findings_part`); an execute after its
plan is told the plan was approved (:func:`approved_part`).
"""

from collections.abc import Mapping, Sequence
from typing import Any

from dplanner.domain.headless import StageKind
from dplanner.domain.model import Step
from dplanner.modules.agent_briefing.prompt import PromptPart, quoted
from dplanner.planning.kinds import key_of

_HELD = (
    "Do not edit files, commit, push, open a PR or set the step's status or agent state:"
    " this stage only reads, and the playbook decides what happens next."
)


def stage_epilogue(step: Step, stage: StageKind) -> str:
    """The closing words of a plan or a review, in place of the work's epilogue."""
    ref = quoted(key_of(step) or step.title or "Untitled step")
    end = (
        "Before your final message, end your at-work claim:"
        f" `dplanner agent-work end --step {ref}`."
    )
    ask = (
        f"If you must ask before you can go on, `dplanner question ask '<question>' --choice"
        f" '<answer>' … --step {ref}`, then end your turn: the answer resumes you."
    )
    if stage is StageKind.PLAN:
        return (
            f"This is the plan stage of {ref}'s playbook, run unattended. Read the step and the"
            " code it touches, then end with your plan as your final message — the plan"
            f" itself, in markdown, with nothing after it. {_HELD} {ask} {end}"
        )
    return (
        f"This is a review stage of {ref}'s playbook, run unattended. {_HELD} End with your"
        " verdict as your final message, in the schema you were given: `outcome` `pass` or"
        " `changes`, a one-line `summary`, and `findings`, each with `severity`, `file`,"
        " `line`, `text` and `evidence`. A finding is something that must change for the work"
        " to pass, shown by its evidence; a matter of taste is not one. `pass` with no findings"
        f" when nothing must change. {ask} {end}"
    )


def review_part(history: Sequence[Mapping[str, Any]]) -> PromptPart:
    """What a review reads: the work on this worktree's branch against its base, and what
    earlier rounds of this gate found and the implementer declined, with its reasons."""
    body = (
        "The work is on this worktree's branch. Review it against the branch its pull request"
        " is opened against — `gh pr view --json baseRefName,url` names both; with no PR yet,"
        " against the branch this one started from (`git merge-base`). Check that it does"
        " what the step asks and nothing it should not; run what you need to be sure, but"
        " change nothing."
    )
    if history:
        body += (
            "\n\nEarlier rounds found these. Where the implementer declined one, its reason"
            " follows: hold the finding again only if it still must change.\n\n" + numbered(history)
        )
    return PromptPart("Review", body)


def findings_part(findings: Sequence[Mapping[str, Any]]) -> PromptPart:
    """The findings a fix acts on, numbered as its typed answer names them."""
    return PromptPart(
        "Findings to address",
        "A gate sent the work back. Act on each finding below, or decline it: list it in"
        " your final message's `declined` by its number, with your reason — the next round"
        " reads it. When you have acted on them, finish as the step says below.\n\n"
        + numbered(findings),
    )


def approved_part(plan: str) -> PromptPart:
    """An execute that follows its plan: the plan, approved."""
    body = "Your plan below is approved. Implement it."
    return PromptPart("The plan is approved", body + (f"\n\n{plan.strip()}" if plan else ""))


def numbered(findings: Sequence[Mapping[str, Any]]) -> str:
    """Findings as a numbered list: a review's ``{severity, file, line, text, evidence}``, or
    a person's ``{text}``, with an implementer's ``declined`` reason where it gave one."""
    lines = []
    for number, finding in enumerate(findings, 1):
        where = str(finding.get("file") or "")
        if where and finding.get("line"):
            where += f":{finding['line']}"
        head = " ".join(
            part
            for part in (f"[{finding['severity']}]" if finding.get("severity") else "", where)
            if part
        )
        line = f"{number}. " + (f"{head} — " if head else "") + str(finding.get("text", ""))
        if finding.get("evidence"):
            line += f" (evidence: {finding['evidence']})"
        if finding.get("declined"):
            line += f"\n   Declined: {finding['declined']}"
        lines.append(line)
    return "\n".join(lines)
