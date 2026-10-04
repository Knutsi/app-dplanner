"""The agent-instruction aspect, in the running application: the Agent tab and the Agent
tab of Project ▸ Settings….

The tab is the writing half — :class:`AgentSection` stacks the briefing's three parts
(the project's standing instruction, what the project's notes hold for it, this step's own)
and ``ModuleTextField`` does the binding work. The project's own tab is the same field in
the Project dialog, registered into ``deps.project_settings`` like any project-level section.

Running the briefing is ``agent_launch``'s: the tab's buttons run its verbs by their action
ids, and its Prompt view shows the assembly a launch is handed (``deps.assembled``).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Step, StepId
from dplanner.domain.repositories import RepositoryFacts
from dplanner.domain.store import FilesFor
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.aspect_toggle import aspect_toggle
from dplanner.framework.context import ContextService
from dplanner.framework.debounce import DebounceService
from dplanner.framework.dictation import DictationService
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.mime_files import Payload
from dplanner.framework.undo import UndoService
from dplanner.modules.agent_briefing import worktree as where
from dplanner.modules.agent_briefing.blocks import note_parts, step_sections
from dplanner.modules.agent_briefing.prompt import AssembledPrompt, PromptPart
from dplanner.modules.step_agent_instruction.section import (
    AgentSection,
    ProjectInstructionSection,
)
from dplanner.planning.agent import (
    DATA_FORMAT,
    MODULE_ID,
    SPEC,
    enabled,
    no_agent,
    uses_worktree,
    with_worktree,
    write_state,
)
from dplanner.planning.kinds import works_nobody
from dplanner.theme.icons import spark_icon, typewriter_icon

PLACEHOLDER = "How to carry this step out: which files, which conventions, what done means."


@dataclass(frozen=True)
class StepAgentInstructionDeps:
    library: Library
    undo: UndoService[Library]
    sections: InspectorSectionRegistry
    actions: ActionRegistry
    context: ContextService  # The Agent tab's buttons evaluate their verbs against it.
    debounce: DebounceService
    # The store's file areas and raw byte access — how instruction images are listed and
    # shown in the tab.
    files: FilesFor
    read_asset: Callable[[str], bytes | None]
    # Both repositories of the step's project as this machine sees them — what the
    # briefing's sections say about where the work is.
    facts_for: Callable[[StepId], RepositoryFacts]
    # The briefing exactly as Run Agent launches with it, unstaged — ``agent_launch``'s
    # assembly, which the Prompt view shows.
    assembled: Callable[[Step], AssembledPrompt]
    # The Project dialog's tabs; None is a build without one.
    project_settings: InspectorSectionRegistry | None = None
    # Insert from Assets…: a modal picker over the node's project's catalog, composed by
    # the root. Node id in, picked payloads out; None is a build without the browser.
    pick_assets: Callable[[str], "list[Payload]"] | None = None
    # What the step's agent runs have consumed, in words, for the Agent tab — the usage
    # ledger (``agent_usage``), read through the root; "" when nothing has been recorded.
    usage_words: Callable[[StepId], str] = field(default=lambda _step_id: "")
    # Dictation into the editors; None is a build without a microphone.
    dictation: DictationService | None = None


class StepAgentInstructionModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: StepAgentInstructionDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps

        # The tab thinks per step id; the briefing speaks the shared (library, step,
        # files) vocabulary. The one adapter lives here.
        def parts_for(step_id: StepId) -> Sequence[PromptPart]:
            return note_parts(deps.library, deps.library.step(step_id), deps.files)

        def sections_for(step_id: StepId) -> Sequence[PromptPart]:
            step = deps.library.step(step_id)
            return step_sections(deps.library, step, deps.files, deps.facts_for(step_id))

        def make_section() -> AgentSection:
            # The tab's buttons are the same verbs the menus run — evaluated lazily, so
            # the registration order of action and section never matters.
            return AgentSection(
                deps.library,
                deps.undo,
                PLACEHOLDER,
                debounce=deps.debounce,
                prompt_parts=parts_for,
                prompt_sections=sections_for,
                read_asset=deps.read_asset,
                # The Prompt tab shows the same assembly Run Agent launches with —
                # unstaged, so its paths are the on-disk absolutes read_asset resolves.
                assembled=lambda step_id: deps.assembled(deps.library.step(step_id)),
                files=deps.files,
                run_state=lambda: deps.actions.spec("agent.run").state(deps.context.current()),
                run=lambda: deps.actions.run("agent.run", deps.context.current()),
                preview_state=lambda: deps.actions.spec("agent.preview").state(
                    deps.context.current()
                ),
                preview=lambda: deps.actions.run("agent.preview", deps.context.current()),
                pick_assets=deps.pick_assets,
                worktree=lambda step_id: where.worktree(deps.library.step(step_id)),
                set_worktree=self._set_worktree,
                no_worktree=lambda step_id: where.no_worktree(deps.library.step(step_id)),
                usage=deps.usage_words,
                dictation=deps.dictation,
            )

        deps.sections.register(
            InspectorSection(
                id=f"{MODULE_ID}.tab",
                label=SPEC.label,
                order=40,
                factory=make_section,
                shown_for=lambda step_id: (
                    step_id is not None
                    and deps.library.has(step_id)
                    and enabled(deps.library.step(step_id))
                ),
            )
        )
        if deps.project_settings is not None:
            deps.project_settings.register(
                InspectorSection(
                    id=f"{MODULE_ID}.project",
                    label="Agent",
                    order=20,
                    factory=lambda: ProjectInstructionSection(
                        deps.library, deps.undo, deps.files, deps.pick_assets, deps.dictation
                    ),
                    icon=typewriter_icon,
                )
            )
        deps.actions.register(
            aspect_toggle(
                id="agent.toggle",
                label="Agent",
                order=30,
                module_id=MODULE_ID,
                library=deps.library,
                undo=deps.undo,
                enabled=enabled,
                fresh=lambda _step, _project: write_state(True),
                icon=spark_icon,
                tip="Mark this step for agent execution; its description is the briefing",
                refusal=lambda step: no_agent(kind) if (kind := works_nobody(step)) else "",
            )
        )

    def _set_worktree(self, step_id: StepId, worktree: bool) -> None:
        """The Agent tab's checkbox: one undoable write of this aspect's own entry."""
        step = self._deps.library.step(step_id)
        if uses_worktree(step) == worktree:
            return
        label = "Agent Worktree On" if worktree else "Agent Worktree Off"
        self._deps.undo.push(
            SetModuleDataCommand(step_id, MODULE_ID, with_worktree(step, worktree), label=label)
        )
