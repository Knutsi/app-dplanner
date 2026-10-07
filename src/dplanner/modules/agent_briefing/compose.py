"""The whole briefing for a step, assembled once for every surface.

Run Agent, its preview and fallback dialogs, the Agent tab's Prompt pane and ``dplanner agent
prompt`` all call :func:`brief`, so what an agent is launched with and what the verb prints
are the same text by construction.
"""

from collections.abc import Callable, Sequence

from dplanner.domain.locations import LocationRole
from dplanner.domain.model import Library, Step
from dplanner.domain.repositories import RepositoryFacts
from dplanner.domain.store import FilesFor
from dplanner.modules.agent_briefing.blocks import note_parts, project_sections, step_sections
from dplanner.modules.agent_briefing.instructions import instruction
from dplanner.modules.agent_briefing.prompt import AssembledPrompt, PromptPart, assemble
from dplanner.modules.agent_briefing.protocol import epilogue, preamble
from dplanner.modules.agent_briefing.worktree import worktree
from dplanner.planning.agent import asset_paths, read_project
from dplanner.planning.branches import BranchPlan, is_land


def _unmoved(path: str) -> str:
    return path


def brief(
    library: Library,
    step: Step,
    files: FilesFor,
    facts: RepositoryFacts | None,
    branches: BranchPlan,
    roles: Sequence[LocationRole],
    place: Callable[[str], str] = _unmoved,
) -> AssembledPrompt:
    """The briefing for a run of ``step`` that carries it out, on ``branches``.

    ``place`` maps each file the step's own blocks reference to where the run will read it
    — Run Agent stages them beside the prompt — and leaves them on disk by default.
    """
    project = library.project_of(step.id)

    def placed(part: PromptPart) -> PromptPart:
        return PromptPart(part.heading, part.body, tuple(place(path) for path in part.files))

    own = instruction(library, step, files)
    # The project's standing instruction is written for the work on a stretch — "work in your
    # worktree, open a PR into the branch" — and a landing's own instructions, generated from
    # the stretch it closes, already say how the branch comes back.
    standing, standing_files = (
        ("", ())
        if is_land(step)
        else (read_project(project), tuple(place(path) for path in asset_paths(files, project.id)))
    )
    return assemble(
        step_title=step.title or "Untitled step",
        project_title=project.title or "Untitled project",
        instruction=own.body,
        parts=[placed(part) for part in note_parts(library, step, files)],
        sections=[placed(section) for section in step_sections(library, step, files, facts)],
        project_sections=project_sections(library, step, files),
        epilogue=epilogue(library, step, branches),
        preamble=preamble(step, worktree(step), facts, branches, roles),
        project_instruction=standing,
        project_files=standing_files,
        instruction_files=tuple(place(path) for path in own.files),
    )
