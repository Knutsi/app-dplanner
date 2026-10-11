"""The briefing's ``## Instructions`` block: the step's own words, or generated from what it is.

A landing's instructions are generated from the stretch it closes; anything else is told
what its separate instruction or its description says.
"""

from dplanner.domain.model import Library, Step
from dplanner.domain.store import FilesFor
from dplanner.modules.agent_briefing.blocks import module_asset_paths
from dplanner.modules.agent_briefing.prompt import PromptPart, quoted
from dplanner.modules.step_description.aspect import MODULE_ID as DESCRIPTION_ID
from dplanner.modules.step_description.aspect import read as description_read
from dplanner.planning.agent import asset_paths
from dplanner.planning.agent import read as instruction_read
from dplanner.planning.branches import is_land, reading
from dplanner.planning.kinds import key_of
from dplanner.planning.status import is_done


def instruction(library: Library, step: Step, files: FilesFor) -> PromptPart:
    """The briefing's ``## Instructions`` block: the description is the instructions.

    A step's separate instruction wins when one exists; otherwise the description body and
    its images take the block — one text an agent step needs, written once. Instruction-area
    files always ride with the block: they
    were attached to it. A landing's block is generated (``_landing_instruction``), and that
    same text rides inside it as what else to see to.
    """
    own = instruction_read(step)
    instruction_files = asset_paths(files, step.id)
    if own:
        body, carried = own, instruction_files
    else:
        description_files = module_asset_paths(files, step.id, DESCRIPTION_ID)
        body, carried = description_read(step), (*description_files, *instruction_files)
    if is_land(step):
        body = _landing_instruction(library, step, body)
    return PromptPart(heading="Instructions", body=body, files=carried)


def _landing_instruction(library: Library, land: Step, look_for: str) -> str:
    """A landing's instructions, generated from the stretch it closes: the branch, what it
    merges into, the order it is done in — and its own prose after, as what else to see to.
    A landing whose cut is gone is told to stop."""
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
