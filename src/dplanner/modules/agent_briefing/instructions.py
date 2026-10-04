"""The briefing's ``## Instructions`` block: the step's own words, or generated from what it is.

A review's instructions are generated from its aspect and its subject, a landing's from the
stretch it closes; anything else is told what its separate instruction or its description
says.
"""

from dplanner.domain.model import Library, Step
from dplanner.domain.store import FilesFor
from dplanner.modules.agent_briefing.prompt import PromptPart, listed, quoted
from dplanner.modules.agent_briefing.sections import module_asset_paths
from dplanner.modules.step_description.aspect import MODULE_ID as DESCRIPTION_ID
from dplanner.modules.step_description.aspect import read as description_read
from dplanner.planning.agent import asset_paths
from dplanner.planning.agent import read as instruction_read
from dplanner.planning.branches import is_land, reading
from dplanner.planning.kinds import key_of
from dplanner.planning.review import is_review, lens, settings, subjects
from dplanner.planning.status import is_done


def instruction(library: Library, step: Step, files: FilesFor) -> PromptPart:
    """The briefing's ``## Instructions`` block: the description is the instructions.

    A step's separate instruction wins when one exists; otherwise the description body and
    its images take the block — one text an agent step needs, written once. Instruction-area
    files always ride with the block: they
    were attached to it. A review's block is generated (``_review_instruction``), and that
    same text rides inside it as what to look for.
    """
    own = instruction_read(step)
    instruction_files = asset_paths(files, step.id)
    if own:
        body, carried = own, instruction_files
    else:
        description_files = module_asset_paths(files, step.id, DESCRIPTION_ID)
        body, carried = description_read(step), (*description_files, *instruction_files)
    if is_review(step):
        body = _review_instruction(library, step, body)
    elif is_land(step):
        body = _landing_instruction(library, step, body)
    return PromptPart(heading="Instructions", body=body, files=carried)


def _landing_instruction(library: Library, land: Step, look_for: str) -> str:
    """A landing's instructions, generated from the stretch it closes, as a review's are
    from its subject: the branch, what it merges into, the order it is done in — and its
    own prose after, as what else to see to. A landing whose cut is gone is told to stop."""
    found = reading(library.project_of(land.id), is_done)
    stretch = found.of_land(land.id)
    ref = quoted(key_of(land) or land.title)
    if stretch is None:
        return (
            "This step lands a feature branch, but the cut that started it is gone or no longer"
            " upstream of it — stop, and tell the developer: `dplanner land set"
            f" {ref} --cut <cut>` names it again."
        )
    branch = stretch.branch
    base = found.base_of(land.id, "")
    into = f"`{base}`" if base else "the repository's default branch"
    against = f"--base {base} " if base else ""
    lines = [
        f"Land the feature branch `{branch}` into {into}: every step on it has merged its work"
        " into that branch, and this step brings the branch back as one pull request.",
        "",
        f"1. `git fetch origin`. Make sure every step under *Work you land* has merged into"
        f" `origin/{branch}` — its PR reads merged into {branch}, or its branch is contained in"
        " it. One that has not: stop, and tell the developer which.",
        f"2. Merge `origin/{base or 'HEAD'}` into `{branch}` as a merge commit — never a rebase"
        " or a squash, since a branch cut from this one keeps its history — settle every"
        " conflict, and run the project's checks.",
        f"3. `git push origin {branch}`, then `gh pr create {against}--head {branch}`, the"
        " title opening with this step's key.",
        f"4. Leave `{branch}` on the remote until this step is done: a step still working on it"
        " would lose what it starts from.",
    ]
    if look_for.strip():
        lines += ["", "Also see to this:", "", look_for.strip()]
    return "\n".join(lines)


def _review_instruction(library: Library, review: Step, look_for: str) -> str:
    """A review's instructions, generated from its aspect and its subject: whom it reviews,
    through which lenses, how the rounds go and how many there may be — then ``look_for``,
    what the review's own prose asks it to watch. A review that does not have exactly one
    subject is told to stop, since every verb it would run names that one step."""
    ref = quoted(key_of(review) or review.title)
    reviewed = subjects(library, review)
    if len(reviewed) != 1:
        which = (
            "reviews nothing yet"
            if not reviewed
            else f"reviews {listed([key_of(each) or each.title for each in reviewed])} at once"
        )
        return (
            f"This review {which}, and a review takes exactly one subject — the step it waits"
            " on. Stop, and tell the developer: `dplanner step link"
            f" {ref} <step>` gives it one, `dplanner step unlink {ref} <step>` takes one away."
        )
    subject = reviewed[0]
    them = quoted(key_of(subject) or subject.title)
    chosen = settings(review)
    cap = chosen.max_rounds
    lines = [
        f"You review **{key_of(subject)}** {subject.title} — *Work you review* says where its"
        f" work is. You comment; you never commit, push or edit its files: {them}'s own agent"
        " makes every change, in answer to what you find.",
        "",
    ]
    if chosen.lenses:
        lines.append("Look at it through these lenses:")
        for each in chosen.lenses:
            known = lens(each)
            lines.append(
                f"- **{known.label}** — {known.asks}"
                if known is not None
                else f"- **{each}** — a lens of the developer's own: use your `{each}` skill"
                " for it."
            )
        lines.append("")
    if look_for.strip():
        lines += ["What to look for, as this review says it:", "", look_for.rstrip(), ""]
    lines += [
        f"The review goes in rounds, at most {cap} with {them}:",
        f"1. `dplanner review wait {ref}` returns once {them} reads ready for review; exit 3"
        " means nothing yet after nine minutes — run it again.",
        f"2. `dplanner review start {ref}` opens the round. Read the work through every lens,"
        f" then `dplanner review post {ref} --file <findings.md>`: each finding with its file"
        f" and line, what is wrong and what would settle it. Posting puts {them} back in"
        " progress.",
        f"3. `dplanner agent-state set {ref} pending-approval`, then `dplanner review wait"
        f" {ref}` for the answer — read the reply and what changed since your last round.",
        f"4. Nothing left to ask: `dplanner review approve {ref}` — {them} is done, and this"
        f" review is ready to merge, carrying {them}'s branch and PR. Something left: back to"
        f" 2 for the next round. After round {cap}, approve, or hand it to a person:"
        f" `dplanner review escalate {ref} --text '<what they must decide>'`.",
    ]
    return "\n".join(lines)
