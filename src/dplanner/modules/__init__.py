"""Feature modules, and the composition root that wires them together.

``default_modules()`` **is** the application. Which features run, what each one may touch
(its typed ``Deps``), and how features cooperate — all of it is readable in this one file,
and nowhere else.

This is the only file allowed to import every module and :class:`AppServices`. Modules never
see the whole bundle and never import each other; when one needs something another provides,
it declares a typed callback on its own ``Deps`` and this file supplies one. So the answer to
"what is this application, and who depends on whom?" has exactly one place to look.

**Order matters.** The returned list is registration order, and it fixes status-bar widget
order, index segment order, and — the one that bites — that surfaces exist before whoever
renders them is built. Every constrained position below carries a comment saying why.

**The imports are inside the functions on purpose.** Importing this package must not load Qt,
because the CLI reaches a module's ``cli.py`` through it and has to start in milliseconds on
machines with no GUI libraries at all. The inventory is still in one place: it is the first
lines of each function instead of the first lines of the file, and
``tests/test_architecture.py`` reads them either way.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING

from dplanner.core.module_data import ModuleDataFormat

if TYPE_CHECKING:
    from collections.abc import Container, Sequence

    from dplanner.cli import CliCommand
    from dplanner.cli.gate import TopologyGate
    from dplanner.domain.aspects import AspectSpec
    from dplanner.domain.assets import AssetSource
    from dplanner.domain.model import Library, Project, Step
    from dplanner.domain.ordering import Placed
    from dplanner.domain.schedule import Scheduled
    from dplanner.domain.scope import ScopeKind
    from dplanner.domain.store import FilesFor, ModuleFileArea
    from dplanner.framework.mime_files import Payload
    from dplanner.framework.module import Module
    from dplanner.framework.services import AppServices
    from dplanner.modules.coverage.trace import Trace
    from dplanner.modules.feature.catalogue import FeatureSource
    from dplanner.modules.project_editor.clipboard import PastePolicy
    from dplanner.modules.step_agent_instruction.prompt import Briefing, PromptPart

__all__ = [
    "aspect_specs",
    "default_cli_commands",
    "default_module_formats",
    "default_modules",
]


def default_modules(services: "AppServices") -> list["Module"]:
    from pathlib import Path

    from dplanner.core.storage.locations import find_repo_root, origin_url
    from dplanner.domain.commands import (
        Command,
        CompositeCommand,
        EditTextCommand,
        SetModuleDataCommand,
    )
    from dplanner.domain.model import Library, TextEdit
    from dplanner.domain.ordering import placed
    from dplanner.domain.schedule import format_date, format_days, schedule
    from dplanner.domain.scope import gatherers
    from dplanner.domain.store import LibraryStore
    from dplanner.framework.aspect_bar import AspectTemplate
    from dplanner.framework.context import SCOPE_SELECTION, Context, ContextNode, selection_uri
    from dplanner.modules.agent_skill.module import AgentSkillDeps, AgentSkillModule
    from dplanner.modules.appshell.module import AppShellDeps, AppShellModule
    from dplanner.modules.coverage.activity import CoverageDeps
    from dplanner.modules.coverage.module import CoverageModule
    from dplanner.modules.debug.module import DebugDeps, DebugModule
    from dplanner.modules.docs.module import DocsCompiledModule, DocsDeps, DocsModule
    from dplanner.modules.estimation.aspect import MODULE_ID as ESTIMATION_ID
    from dplanner.modules.estimation.aspect import read as estimated_days
    from dplanner.modules.estimation.aspect import write as estimate_write
    from dplanner.modules.estimation.module import EstimationDeps, EstimationModule
    from dplanner.modules.estimation.schedule import start_of, write_start
    from dplanner.modules.feature.aspect import MODULE_ID as FEATURE_ID
    from dplanner.modules.feature.aspect import is_feature
    from dplanner.modules.feature.aspect import read as feature_read
    from dplanner.modules.feature.aspect import write as feature_write
    from dplanner.modules.feature.catalogue import (
        FEATURE_MIME,
        instance_of,
        parse_drag,
        read_catalogue,
    )
    from dplanner.modules.feature.module import FeatureDeps, FeatureModule
    from dplanner.modules.feature.panel import panel_context
    from dplanner.modules.github.aspect import pr_label
    from dplanner.modules.github.aspect import read as github_read
    from dplanner.modules.github.module import GithubDeps, GithubModule
    from dplanner.modules.library.module import LibraryDeps, LibraryModule
    from dplanner.modules.library_watch.module import LibraryWatchDeps, LibraryWatchModule
    from dplanner.modules.llm.module import LlmDeps, LlmModule
    from dplanner.modules.llm_anthropic.module import LlmAnthropicDeps, LlmAnthropicModule
    from dplanner.modules.llm_openai.module import LlmOpenAIDeps, LlmOpenAIModule
    from dplanner.modules.progression.module import ProgressionDeps, ProgressionModule
    from dplanner.modules.project_assets.module import (
        ProjectAssetsDeps,
        ProjectAssetsModule,
    )
    from dplanner.modules.project_editor.drops import CanvasDrop
    from dplanner.modules.project_editor.module import ProjectEditorDeps, ProjectEditorModule
    from dplanner.modules.project_editor.renderers import NodeAccent
    from dplanner.modules.projects.module import ProjectEntry, ProjectsDeps, ProjectsModule
    from dplanner.modules.reopen_tabs.module import ReopenTabsDeps, ReopenTabsModule
    from dplanner.modules.settings.module import SettingsDeps, SettingsModule
    from dplanner.modules.spec.aspect import MODULE_ID as SPEC_ID
    from dplanner.modules.spec.cli import digest_of as spec_digest_of
    from dplanner.modules.spec.cli import document_names as spec_document_names
    from dplanner.modules.spec.module import SpecDeps, SpecModule
    from dplanner.modules.step_agent_instruction.aspect import MODULE_ID as AGENT_INSTRUCTION_ID
    from dplanner.modules.step_agent_instruction.aspect import enabled as agent_enabled
    from dplanner.modules.step_agent_instruction.aspect import read as agent_instruction_read
    from dplanner.modules.step_agent_instruction.aspect import (
        separate_instruction as agent_separate,
    )
    from dplanner.modules.step_agent_instruction.aspect import write_state as agent_write_state
    from dplanner.modules.step_agent_instruction.module import (
        StepAgentInstructionDeps,
        StepAgentInstructionModule,
    )
    from dplanner.modules.step_agent_run.aspect import read as agent_run_state
    from dplanner.modules.step_agent_run.module import StepAgentRunDeps, StepAgentRunModule
    from dplanner.modules.step_check.aspect import read as check_read
    from dplanner.modules.step_check.module import StepCheckDeps, StepCheckModule
    from dplanner.modules.step_description.aspect import read as description_read
    from dplanner.modules.step_description.aspect import summary as description_summary
    from dplanner.modules.step_description.module import (
        StepDescriptionDeps,
        StepDescriptionModule,
    )
    from dplanner.modules.step_description.section import SeparateInstructionLink
    from dplanner.modules.step_handoff.module import StepHandoffDeps, StepHandoffModule
    from dplanner.modules.step_milestone.aspect import read as milestone_read
    from dplanner.modules.step_milestone.module import StepMilestoneDeps, StepMilestoneModule
    from dplanner.modules.step_order.module import StepOrderDeps, StepOrderModule
    from dplanner.modules.step_properties.module import (
        StepPropertiesDeps,
        StepPropertiesModule,
    )
    from dplanner.modules.step_status.aspect import read as step_status
    from dplanner.modules.step_status.module import StepStatusDeps, StepStatusModule
    from dplanner.modules.step_ticket.module import StepTicketDeps, StepTicketModule
    from dplanner.modules.sync.module import SyncDeps, SyncModule
    from dplanner.modules.taskcenter.module import TaskCenterDeps, TaskCenterModule
    from dplanner.modules.testing.aspect import enabled as test_enabled
    from dplanner.modules.testing.aspect import read as tests_read
    from dplanner.modules.testing.module import TestsDeps, TestsModule
    from dplanner.modules.time_estimates.module import TimeEstimatesDeps, TimeEstimatesModule
    from dplanner.theme.icons import (
        clock_icon,
        coverage_icon,
        gauge_icon,
        graph_icon,
        image_icon,
        list_icon,
        spec_icon,
    )

    library: Library = services.document
    # The composition root knows the concrete store, exactly as it knows the concrete
    # document — modules reach a file area only through the typed callback on their Deps.
    store = services.repo
    assert isinstance(store, LibraryStore)

    def project_dir_of(step_id: str) -> "Path":
        return store.project_dir(library.project_of(step_id).id)

    def read_absolute(path: str) -> bytes | None:
        """Asset bytes by absolute path — module file areas hand those out now."""
        file = Path(path)
        return file.read_bytes() if file.is_file() else None

    def focused_project(context: object) -> str | None:
        """The project the user is in: the focused project, else the focused step's."""
        from dplanner.framework.context import Context

        assert isinstance(context, Context)
        project_id = context.focus_entity("project")
        if project_id is not None and library.has(project_id):
            return project_id
        step_id = context.focus_entity("step")
        if step_id is not None and library.has(step_id):
            return library.project_of(step_id).id
        return None

    def projects_in(group: object) -> list[str]:
        """The titles a repository group covers — for the diff picker and quit dialog."""
        return [
            project.title or project.folder_name
            for project in library.projects
            if store.repo_for(project.id) is group
        ]

    def skill_files() -> dict[str, str]:
        from dplanner.cli.command import CliRegistry
        from dplanner.cli.skill import generate

        registry = CliRegistry()
        registry.register_all(default_cli_commands())
        return generate(registry, aspect_specs())

    def step_aspects(step_id: str, skip: "Container[str]" = ()) -> list[str]:
        """One short phrase per aspect that has something to say about this step."""
        step = library.step(step_id)
        summaries = aspect_summaries(skip)
        return [phrase for phrase in (summary(step) for summary in summaries) if phrase]

    def milestone_stats(project: "Project") -> dict[str, str]:
        """What each milestone answers with: the schedule's accumulated days and landing
        date at its row — the same pair the order table's milestone row highlights.

        A milestone closes the block of work above it, so its number is the walk's total
        at that row. One walk per project rather than one per milestone, because a canvas
        sync asks for every milestone at once and the order is the same for all of them.
        A milestone the project cannot date is absent; so is every step when nothing is a
        milestone, which costs the sync no walk at all.
        """
        if not any(milestone_read(step) for step in project.steps):
            return {}
        stats: dict[str, str] = {}
        for scheduled in step_schedule(project.id, placed(library, project)):
            step = scheduled.place.step
            if not milestone_read(step):
                continue
            if scheduled.finish is not None:
                stats[step.id] = (
                    f"{format_days(scheduled.accumulated)} · {format_date(scheduled.finish)}"
                )
            elif scheduled.accumulated:
                stats[step.id] = format_days(scheduled.accumulated)
        return stats

    def step_type_icons(step: "Step") -> tuple[str, ...]:
        """What kind of thing a step is, in the medallion vocabulary the canvas painted
        first: "tag" a milestone, "layers" a feature, "spark" an agent step, "beaker" one
        carrying tests, "shield" a check. The order table's title column reads the same
        answer, so a step is the same kind everywhere."""
        return (
            *(("tag",) if milestone_read(step) else ()),
            *(("layers",) if is_feature(step) else ()),
            *(("spark",) if agent_enabled(step) else ()),
            *(("beaker",) if test_enabled(step) else ()),
            *(("shield",) if check_read(step) else ()),
        )

    def set_separate_instruction(step_id: str, separate: bool) -> None:
        """The Description block's checkbox, translated into the agent aspect's writes.

        Unchecking merges back into the description — the separate text is dropped and
        the mark stays — as one undo step, so Ctrl+Z restores text and flag together.
        """
        if separate:
            services.undo.push(
                SetModuleDataCommand(
                    step_id,
                    AGENT_INSTRUCTION_ID,
                    agent_write_state(True, separate=True),
                    label="Separate Agent Instruction",
                )
            )
            return
        current = agent_instruction_read(library.step(step_id))
        mark: Command = SetModuleDataCommand(
            step_id,
            AGENT_INSTRUCTION_ID,
            agent_write_state(True),
            label="Use Description as Instructions",
        )
        if not current:
            services.undo.push(mark)
            return
        services.undo.push(
            CompositeCommand(
                "Use Description as Instructions",
                [
                    EditTextCommand(
                        TextEdit(step_id, AGENT_INSTRUCTION_ID, 0, current, ""),
                        label="Set Agent Instruction",
                    ),
                    mark,
                ],
            )
        )

    def step_accents(project_id: str) -> "dict[str, NodeAccent]":
        """How every step of a project looks on the canvas — one call per canvas sync, so
        the schedule behind the milestone stats is walked once for all of them."""
        project = library.project(project_id)
        stats = milestone_stats(project)
        return {step.id: step_accent(step, stats.get(step.id, "")) for step in project.steps}

    def step_accent(step: "Step", milestone_stat: str) -> "NodeAccent":
        """How a step looks on the canvas, translated from aspects the canvas never learns.


        A done step is muted with a green body — finished work recedes into a colour the
        eye can skip; the spine down the card's left carries the step's key and is shaded
        by status — busy for in-progress, bad for blocked, good for done, quiet otherwise;
        a milestone is a purple-highlighted node wearing its label as a badge, a tag
        medallion and the schedule's accumulated days and date as its stat (done outranks
        it on the body — a shipped milestone reads finished, and the tag still says what
        it was); an agent instruction is the spark medallion; a PR is a pill with its
        state as a tone and a branch the fork glyph; a live agent run is the chip on the
        bottom edge; a plain step's stat is its own estimate. The card says nothing in
        words beyond its title and its key: every aspect it wears is one of these, never
        a phrase.
        """
        refs = github_read(step)

        pill = ""
        if refs is not None and refs.has_pr():
            pill = pr_label(refs)
        chip_text, chip_tone = {
            "launched": ("launched", "info"),
            "working": ("working", "info"),
            "plan-for-review": ("plan ready", "attention"),
            "pending-approval": ("needs approval", "attention"),
            "needs-input": ("needs input", "attention"),
        }.get(agent_run_state(step), ("", ""))
        status = step_status(step)
        milestone = milestone_read(step)
        if milestone:
            stat = milestone_stat
        else:
            days = estimated_days(step)
            stat = format_days(days) if days is not None else ""
        return NodeAccent(
            muted=status == "done",
            badge=milestone,
            pill_text=pill,
            pill_tone={"merged": "good", "closed": "bad"}.get(refs.pr_state, "") if refs else "",
            branch=bool(refs is not None and refs.branch),
            key_text=_step_key(step),
            spine_tone={"in-progress": "busy", "blocked": "bad", "done": "good"}.get(status, ""),
            chip_text=chip_text,
            chip_tone=chip_tone,
            # Done outranks a kind, and a milestone outranks a feature: the coarser claim
            # wins the body, and the medallion still says what the node also is.
            body_tone=(
                "good"
                if status == "done"
                else "highlight"
                if milestone
                else "feature"
                if is_feature(step)
                else ""
            ),
            icons=step_type_icons(step),
            stat_text=stat,
            stat_strong=bool(milestone),
        )

    def step_schedule(project_id: str, order: "Sequence[Placed]") -> "list[Scheduled]":
        """The order carrying days and dates: the domain's walk, over one module's numbers.

        The domain never learns where an estimate is stored — it is handed a function that
        answers for a step — and the order view never learns that estimates exist.
        """
        return schedule(order, estimated_days, start_of(library.project(project_id)))

    # The one briefing both the window and the CLI assemble from — see _default_briefing.
    briefing = _default_briefing()

    # Three modules constructed before the list, because what each one hands the others
    # reads better as wiring than as ordering:
    #
    #   step_properties  anchors THE step detail panel in the window's right area
    #   project_editor   anchors the project form beside it, and opens projects into tabs
    #   projects         puts projects in the index and opens them through the editor
    #   estimation       owns the estimate, the start date and the bulk Estimates tab; the
    #                    order view hosts its bar
    #
    # None of them imports any other, and the two panel modules do not even wire to each
    # other: each registers a panel and the dock decides what is on screen, so neither knows
    # the other is in the same area. Construction is side-effect-free, so ordering here is
    # about legibility; what matters at run time is that the aspect modules have registered
    # their sections before step_properties builds the panel, which is a position in the list
    # below.
    step_properties = StepPropertiesModule(
        StepPropertiesDeps(
            # The templates on the bar's left: what a step *amounts to*, as the set of
            # Type toggles that are on — clicking one moves every toggle to match, and a
            # step carrying exactly that set lights it up. Step is the catch-all: any
            # combination no other template names is still a step. Collectors carry no
            # estimate of their own; an agent step gets what an agent reports back
            # through. Each wears its body tone when selected: violet the milestone, teal
            # the feature, the agent-run chip's blue for an agent step; Step and Check
            # keep the accent. Wired, never inferred, like the scope kinds.
            templates=(
                AspectTemplate(
                    "Step",
                    frozenset({"estimate.toggle", "description.toggle"}),
                    catch_all=True,
                ),
                AspectTemplate(
                    "Milestone",
                    frozenset({"milestone.toggle", "description.toggle"}),
                    tone="highlight",
                    glyph="tag",
                ),
                AspectTemplate(
                    "Feature",
                    frozenset({"feature.toggle", "description.toggle"}),
                    tone="feature",
                    glyph="layers",
                ),
                AspectTemplate(
                    "Agent",
                    frozenset(
                        {
                            "agent.toggle",
                            "description.toggle",
                            "estimate.toggle",
                            "handoff.toggle",
                        }
                    ),
                    tone="info",
                    glyph="spark",
                ),
                AspectTemplate(
                    "Check", frozenset({"check.toggle", "description.toggle"}), glyph="shield"
                ),
            ),
            library=library,
            undo=services.undo,
            panels=services.panels,
            actions=services.actions,
            parent=services.window,
            sections=services.inspector_sections,
            details=services.step_details,
            theme=services.theme,
        )
    )

    def place_feature(project_id: str, payload: bytes, at: tuple[float, float] | None) -> list[str]:
        """A feature dragged from the Features panel onto a canvas becomes the step that
        realises it — born through the same ``create`` as New ▸ Feature, marked in the same
        undo step. Refuses, in the CLI's words, a payload from another project or a record
        that already has its instance: a feature is implemented once."""
        from dplanner.cli.command import CliError

        parsed = parse_drag(payload)
        if parsed is None:
            return []
        origin_project, feature_id = parsed
        if origin_project != project_id:
            raise CliError("That feature belongs to another project")
        project = library.project(project_id)
        record = next((r for r in read_catalogue(project) if r.id == feature_id), None)
        if record is None:
            raise CliError(f"No feature {feature_id} in {project.title!r} any more")
        holder = instance_of(project, record.id)
        if holder is not None:
            raise CliError(
                f"{record.title!r} is already placed as {holder.title!r} — a feature is "
                "implemented once"
            )
        return [
            project_editor.create_step(
                project_id,
                record.title,
                at=at,
                # Born as the *Feature* template above: the marker, and the estimate
                # opted out — a collector carries no estimate of its own — so the modal
                # lights Feature rather than the catch-all. The set written here and the
                # template's set are the same fact; change one, change the other.
                carrying=lambda step: [
                    SetModuleDataCommand(step.id, FEATURE_ID, feature_write(record.id)),
                    SetModuleDataCommand(step.id, ESTIMATION_ID, estimate_write(None, on=False)),
                ],
                label="Place Feature",
            ).id
        ]

    project_editor = ProjectEditorModule(
        ProjectEditorDeps(
            library=library,
            debounce=services.debounce,
            actions=services.actions,
            context=services.context,
            tabs=services.tabs,
            undo=services.undo,
            status=services.window,
            parent=services.window,
            panels=services.panels,
            theme=services.theme,
            files=store.files,
            file_modules=tuple(source.id for source in _asset_sources()),
            paste_policies=_paste_policies(),
            step_accents=step_accents,
            # The timeline sort reads a step's length through this seam; estimation owns it.
            days_for=estimated_days,
            # The project panel renders whatever registered a card here — the project-level
            # counterpart of the step panel's inspector_sections.
            cards=services.detail_cards,
            # What the canvas takes by drop: a feature from the Features panel.
            drops=(CanvasDrop(FEATURE_MIME, place_feature),),
        )
    )
    # Constructed before the list because the Specs tab reads the catalogue's passages
    # through it and cites a selection into it — the feature side of one seam.
    feature = FeatureModule(
        FeatureDeps(
            library=library,
            debounce=services.debounce,
            undo=services.undo,
            actions=services.actions,
            panels=services.panels,
            sections=services.inspector_sections,
            files=store.files,
            theme=services.theme,
            parent=services.window,
            documents_of=lambda project_id: spec_document_names(library.project(project_id)),
            digest_of=lambda project_id, name: spec_digest_of(library.project(project_id), name),
        )
    )

    # Constructed before the list because the projects index opens it and the Specs tab
    # jumps into it. Its picture is every module's Qt-free half read once (_coverage_trace);
    # the surfaces a double-click reaches arrive as callables, and the Specs tab's is
    # resolved lazily because the two modules point at each other.
    def _step_passages(step_id: str) -> list[tuple[str, str]]:
        """The passages a step reaches: its own record's, or its gathering features'."""
        if not library.has(step_id):
            return []
        step = library.step(step_id)
        project = library.project_of(step_id)
        records = {record.id: record for record in read_catalogue(project)}
        named = [feature_read(step)] if feature_read(step) else []
        if not named:
            owners = gatherers(
                library,
                project,
                carried_by=is_feature,
                stops_at=lambda other: is_feature(other) or bool(milestone_read(other)),
            ).get(step_id, ())
            named = [feature_read(project.step(owner) or step) or "" for owner in owners]
        return [
            (source.document, source.quote)
            for record_id in named
            if record_id in records
            for source in records[record_id].sources
            if source.quote
        ]

    coverage = CoverageModule(
        CoverageDeps(
            library=library,
            actions=services.actions,
            context=services.context,
            tabs=services.tabs,
            debounce=services.debounce,
            files=store.files,
            trace_of=_coverage_trace,
            parent=services.window,
            show_passages=lambda *args: spec.show_passages(*args),
            open_docs=lambda _project_id, step_id: services.actions.run(
                "docs.open_step",
                Context({SCOPE_SELECTION: (ContextNode(selection_uri("step", step_id)),)}),
            ),
            open_feature=lambda project_id, feature_id: services.actions.run(
                "feature.edit", panel_context(project_id, feature_id)
            ),
            feature_of=lambda step_id: (
                feature_read(library.step(step_id)) or None if library.has(step_id) else None
            ),
            is_milestone=lambda step_id: (
                bool(milestone_read(library.step(step_id))) if library.has(step_id) else False
            ),
            tests_of=lambda step_id: (
                [test.id for test in tests_read(library.step(step_id))]
                if library.has(step_id)
                else []
            ),
            passages_of=_step_passages,
        )
    )

    # Constructed before the list because the projects index opens Specs through it — the
    # same seam as open_project, one level down.
    spec = SpecModule(
        SpecDeps(
            library=library,
            actions=services.actions,
            context=services.context,
            tabs=services.tabs,
            undo=services.undo,
            theme=services.theme,
            parent=services.window,
            files=lambda node_id: store.files(node_id, SPEC_ID),
            details=services.step_details,
            passages_of=lambda project_id, document: [
                source.quote
                for record in read_catalogue(library.project(project_id))
                for source in record.sources
                if source.document == document and source.quote
            ],
            cite=feature.cite_passage,
            open_coverage=coverage.show_passage,
        )
    )
    # Constructed before the list because the projects index opens the board through it.
    # Run Agent arrives as the real action's state and verb, resolved lazily so the agent
    # module's registration order does not matter; neither module knows the other's name.
    progression = ProgressionModule(
        ProgressionDeps(
            library=library,
            debounce=services.debounce,
            actions=services.actions,
            context=services.context,
            tabs=services.tabs,
            # Statuses and estimates through the aspects' Qt-free readers — the board
            # never learns what either is stored as.
            status_for=step_status,
            days_for=estimated_days,
            agent_state=lambda ctx: services.actions.spec("agent.run").state(ctx),
            agent_run=lambda ctx: services.actions.run("agent.run", ctx),
        )
    )
    estimation = EstimationModule(
        EstimationDeps(
            library=library,
            undo=services.undo,
            details=services.step_details,
            actions=services.actions,
            context=services.context,
            tabs=services.tabs,
            # A step's description, one line for the row and the prose for its tooltip.
            # Handed as answers, so the estimation module never learns where prose lives.
            step_summary=lambda step_id: description_summary(library.step(step_id)),
            describe_step=lambda step_id: description_read(library.step(step_id)),
        )
    )
    # Constructed before the list because the projects index opens the matrix through it.
    time_estimates = TimeEstimatesModule(
        TimeEstimatesDeps(
            library=library,
            debounce=services.debounce,
            undo=services.undo,
            actions=services.actions,
            context=services.context,
            tabs=services.tabs,
            # Estimates, agent-ness and the start date through the owners' Qt-free
            # readers — the matrix never learns what any of them is stored as.
            days_for=estimated_days,
            is_agent=agent_enabled,
            milestone_label=milestone_read,
            start_of=lambda project_id: start_of(library.project(project_id)),
            # Clicking the calendar re-dates the plan: one undoable write of the
            # estimation module's own entry, composed here so neither module imports
            # the other.
            set_start=lambda project_id, when: services.undo.push(
                SetModuleDataCommand(
                    project_id, ESTIMATION_ID, write_start(when), label="Set Start Date"
                )
            ),
        )
    )
    # Constructed before the list for the same reason — its index row opens the tab. The
    # sources tuple is the same one the CLI reports read (`_asset_sources`), so the tab,
    # the picker and `dplanner asset list` can never disagree about what a project holds.
    asset_sources = _asset_sources()
    project_assets = ProjectAssetsModule(
        ProjectAssetsDeps(
            library=library,
            actions=services.actions,
            context=services.context,
            tabs=services.tabs,
            undo=services.undo,
            parent=services.window,
            debounce=services.debounce,
            files=store.files,
            sources=asset_sources,
        )
    )

    def pick_assets(node_id: str) -> "list[Payload]":
        """Insert from Assets…: the picker over the node's project's whole catalog.

        Composed here because it is cross-module three ways — the catalog is every
        module's areas, the titles are the asset browser's data, and the host knows only
        its own node. The picked bytes go back to the host, which attaches them into its
        *own* area: reuse is a copy, so a link never points into another module's
        directory.
        """
        from pathlib import PurePosixPath

        from dplanner.domain.assets import AssetEntry, catalog
        from dplanner.framework.asset_picker import AssetPickerDialog, PickerEntry
        from dplanner.modules.project_assets.cli import read_titles

        node = library.node(node_id)
        project = (
            library.project(node_id) if node.kind == "project" else library.project_of(node_id)
        )
        titles = read_titles(project)

        def reader(entry: "AssetEntry") -> "Callable[[], bytes | None]":
            def read() -> bytes | None:
                for _source, location in entry.locations:
                    try:
                        area = store.files(location.node_id, location.module_id)
                    except KeyError:
                        continue
                    data = area.read_bytes(location.name)
                    if data is not None:
                        return data
                return None

            return read

        choices = []
        for entry in catalog(library, project, store.files, asset_sources):
            basename = PurePosixPath(entry.name).name
            title = titles.get(entry.name, "")
            choices.append(
                PickerEntry(
                    key=entry.name,
                    title=title or basename,
                    detail=", ".join(dict.fromkeys(source.label for source, _l in entry.locations)),
                    # The display name becomes the typed link's alt text; the suffix
                    # stays the content's own.
                    filename=f"{title}{PurePosixPath(entry.name).suffix}" if title else basename,
                    read=reader(entry),
                )
            )
        dialog = AssetPickerDialog(choices, services.window)
        picked = dialog.chosen() if dialog.exec() == AssetPickerDialog.DialogCode.Accepted else []
        dialog.deleteLater()
        return picked

    # Constructed before the list for the same reason — its index row opens the table.
    step_order = StepOrderModule(
        StepOrderDeps(
            library=library,
            debounce=services.debounce,
            actions=services.actions,
            context=services.context,
            tabs=services.tabs,
            parent=services.window,
            # The estimate has a column of its own here, so it does not also belong in
            # the row's trailing summary. On the canvas, which has no columns, it does.
            step_aspects=lambda step_id: step_aspects(step_id, skip={ESTIMATION_ID}),
            # Days and dates, computed by the domain from what the estimation module
            # stores. Neither module knows the other's name.
            step_schedule=step_schedule,
            start_bar=estimation.create_start_bar,
            # A milestone row wears a rule and a tint; the name itself stays in the
            # trailing aspects column, which is why the milestone is not skipped here.
            milestone_label=lambda step_id: milestone_read(library.step(step_id)),
            # The same kind vocabulary the canvas medallions wear, one translation.
            step_icons=lambda step_id: step_type_icons(library.step(step_id)),
        )
    )

    def reveal_step(step_id: str) -> None:
        """Select a step in its project: ``steps.reveal`` against a context naming it."""
        from dplanner.framework.context import SCOPE_SELECTION, Context, ContextNode, selection_uri

        services.actions.run(
            "steps.reveal",
            Context({SCOPE_SELECTION: (ContextNode(selection_uri("step", step_id)),)}),
        )

    # Built ahead of the list because Run Agent's module closes over it: every launch is
    # handed here, and this is the one place that keeps an eye on the shell afterwards.
    agent_runs = StepAgentRunModule(
        StepAgentRunDeps(
            library=library,
            undo=services.undo,
            actions=services.actions,
            context=services.context,
            status=services.window,
            parent=services.window,
            # An exit is never written over a plan that changed underneath — the same
            # narrowed store the library watcher reads.
            repo=store,
            reveal=reveal_step,
        )
    )

    # Built ahead of the list too: the library watcher hands an entry two writers changed
    # at once to this module's launcher, and it is listed before this module.
    agent_instruction = StepAgentInstructionModule(
        StepAgentInstructionDeps(
            library=library,
            debounce=services.debounce,
            undo=services.undo,
            sections=services.inspector_sections,
            actions=services.actions,
            context=services.context,
            settings_sections=services.settings_sections,
            status=services.window,
            parent=services.window,
            # Its project-level card: the standing instruction every briefing opens with.
            cards=services.detail_cards,
            files=store.files,
            # How staged assets are read at launch — bytes by absolute path.
            read_asset=read_absolute,
            # Where the agent runs: the project's git repository root, derived from
            # its directory. "" (a disabled verb) when the repository has vanished.
            workdir_for=lambda step_id: str(find_repo_root(project_dir_of(step_id)) or ""),
            briefing=briefing,
            # The spawned shell goes to the run tracker: it stamps the launch — directly,
            # off the undo stack, since Ctrl+Z cannot un-launch a shell — and watches
            # the run's files for the shell's end.
            record_launch=lambda step_id, files: agent_runs.track(
                step_id, str(files.shell_file), str(files.exit_file)
            ),
            pick_assets=pick_assets,
            # Run Agent asks before launching on a step whose prerequisites are not
            # done — the same status reader the progression board's frontier uses.
            status_for=step_status,
            # What names the run — its worktree, its branch, its window: the key and
            # the ticket, composed here from aspects the agent module never reads.
            step_key=_step_key,
            ticket_key=_ticket_key,
        )
    )

    return [
        # -- the shell -------------------------------------------------------------------
        AppShellModule(
            AppShellDeps(
                actions=services.actions,
                context=services.context,
                tabs=services.tabs,
                theme=services.theme,
                undo=services.undo,
                debounce=services.debounce,
                zoom=services.zoom,
                window=services.window,
                # Registered before any panel exists, which is why it listens to the registry
                # rather than reading it: View ▸ Panels grows an entry as each one arrives.
                panels=services.panels,
                chrome=services.window,
            )
        ),
        LibraryModule(
            LibraryDeps(
                library=library,
                actions=services.actions,
                parent=services.window,
                status=services.window,
                window=services.window,
                library_path=store.library_path,
                # The store's membership face: attach/detach track directories, the model
                # change itself is the caller's, applied off the undo stack.
                attach=store.attach,
                detach=store.detach,
                project_dirs=lambda: (
                    [store.project_dir(project.id).resolve() for project in library.projects]
                    + [problem.path.resolve() for problem in store.problems()]
                ),
                problems=store.problems,
            )
        ),
        # Before the task centre, so the library path and branch sit left of the task
        # button in the status bar.
        SyncModule(
            SyncDeps(
                actions=services.actions,
                autosave=services.autosave,
                context=services.context,
                status=services.window,
                tasks=services.tasks,
                chrome=services.window,
                theme=services.theme,
                parent=services.window,
                switcher=services.switcher,
                library=library,
                library_path=store.library_path,
                # One provider per distinct git repository, scoped to its projects'
                # directories — the store owns the grouping, sync only operates on it.
                repos=store.repo_groups,
                repo_for=store.repo_for,
                focused_project=focused_project,
                projects_in=projects_in,
            )
        ),
        # After sync, so the conflict button lands to the right of the library path.
        LibraryWatchModule(
            LibraryWatchDeps(
                # The narrowed store from above: the watcher needs changed_underneath()
                # and adopt_outside_changes(), which the Repository protocol deliberately
                # does not promise.
                repo=store,
                autosave=services.autosave,
                actions=services.actions,
                switcher=services.switcher,
                status=services.window,
                parent=services.window,
                library=library,
                # An entry both writers changed goes to Run Agent's launcher with both
                # versions; the run is tracked on the step like any other.
                hand_to_agent=agent_instruction.hand_conflicts,
                agent_refusal=agent_instruction.conflict_refusal,
            )
        ),
        TaskCenterModule(
            TaskCenterDeps(
                tasks=services.tasks,
                actions=services.actions,
                status=services.window,
                parent=services.window,
            )
        ),
        # -- AI --------------------------------------------------------------------------
        # Providers before the llm module: its settings page lists whatever has registered.
        LlmOpenAIModule(
            LlmOpenAIDeps(
                llm_providers=services.llm_providers,
                llm=services.llm,
                settings_sections=services.settings_sections,
            )
        ),
        LlmAnthropicModule(
            LlmAnthropicDeps(
                llm_providers=services.llm_providers,
                llm=services.llm,
                settings_sections=services.settings_sections,
            )
        ),
        LlmModule(
            LlmDeps(
                llm_providers=services.llm_providers,
                llm=services.llm,
                settings_sections=services.settings_sections,
            )
        ),
        DebugModule(
            DebugDeps(
                llm=services.llm,
                telemetry=services.telemetry,
                actions=services.actions,
                tabs=services.tabs,
                context=services.context,
            )
        ),
        # -- the planner ------------------------------------------------------------------
        ProjectsModule(
            ProjectsDeps(
                library=library,
                debounce=services.debounce,
                actions=services.actions,
                context=services.context,
                undo=services.undo,
                segments=services.index_segments,
                theme=services.theme,
                parent=services.window,
                # The index opens a project without knowing what an editor is.
                open_project=project_editor.open,
                detach=store.detach,
                problems=store.problems,
                # Rows under each project — a project row itself only folds; these are
                # what opens. Each renders the Project menu: the row stands for its
                # project, and the project's verbs all live there.
                # A single click opens the same surface as a preview tab — the VS Code
                # gesture: the next click's preview replaces it, activation keeps it.
                entries=(
                    ProjectEntry(
                        id="steps",
                        label="Steps",
                        open=project_editor.open,
                        open_preview=lambda pid: project_editor.open(pid, preview=True),
                        icon=graph_icon,
                        menu="Project",
                        order=10,
                    ),
                    ProjectEntry(
                        id="order",
                        label="Order",
                        open=step_order.open,
                        open_preview=lambda pid: step_order.open(pid, preview=True),
                        icon=list_icon,
                        menu="Project",
                        order=15,
                    ),
                    ProjectEntry(
                        id="spec",
                        label="Specs",
                        open=spec.open,
                        open_preview=lambda pid: spec.open(pid, preview=True),
                        icon=spec_icon,
                        menu="Project",
                        order=20,
                    ),
                    ProjectEntry(
                        id="coverage",
                        label="Coverage",
                        open=coverage.open,
                        open_preview=lambda pid: coverage.open(pid, preview=True),
                        icon=coverage_icon,
                        menu="Project",
                        order=22,
                    ),
                    ProjectEntry(
                        id="assets",
                        label="Assets",
                        open=project_assets.open,
                        open_preview=lambda pid: project_assets.open(pid, preview=True),
                        icon=image_icon,
                        menu="Project",
                        order=25,
                    ),
                    ProjectEntry(
                        id="progression",
                        label="Progression",
                        open=progression.open,
                        open_preview=lambda pid: progression.open(pid, preview=True),
                        icon=gauge_icon,
                        menu="Project",
                        order=30,
                    ),
                    ProjectEntry(
                        id="time",
                        label="Time Estimates",
                        open=time_estimates.open,
                        open_preview=lambda pid: time_estimates.open(pid, preview=True),
                        icon=clock_icon,
                        menu="Project",
                        order=40,
                    ),
                ),
            )
        ),
        spec,
        coverage,
        project_assets,
        # -- the step aspects --------------------------------------------------------------
        # Each registers one tab into the step detail panel — or, for the estimate and
        # description, a block into its Details tab (services.step_details). They must
        # come before step_properties, which builds the panel from whatever has
        # registered by then.
        estimation,
        StepTicketModule(
            StepTicketDeps(
                library=library,
                undo=services.undo,
                sections=services.inspector_sections,
                actions=services.actions,
            )
        ),
        StepDescriptionModule(
            StepDescriptionDeps(
                actions=services.actions,
                library=library,
                undo=services.undo,
                details=services.step_details,
                files=store.files,
                # The "Separate agent instruction" checkbox: the agent aspect through
                # typed callbacks, so neither module learns the other's name.
                agent_link=SeparateInstructionLink(
                    agent_enabled=lambda sid: agent_enabled(library.step(sid)),
                    separate=lambda sid: agent_separate(library.step(sid)),
                    has_text=lambda sid: bool(agent_instruction_read(library.step(sid))),
                    set_separate=set_separate_instruction,
                ),
                # Insert from Assets…, composed above over every module's catalog slice.
                pick_assets=pick_assets,
            )
        ),
        # Run Agent, built above the list; the library watcher borrows its launcher.
        agent_instruction,
        # The shells Run Agent above spawns, and the canvas reads the aspect through
        # step_accents above.
        agent_runs,
        DocsModule(
            DocsDeps(
                library=library,
                debounce=services.debounce,
                undo=services.undo,
                actions=services.actions,
                sections=services.inspector_sections,
                context=services.context,
                tabs=services.tabs,
                segments=services.index_segments,
                theme=services.theme,
                llm=services.llm,
                tasks=services.tasks,
                # Read, never added to: grouping the Docs view by feature or milestone is
                # the same walk the Tests tab makes. A fourth ScopeKind of its own would
                # teach four tests surfaces about documentation to serve none of it.
                scopes=_scope_kinds(check_read, is_feature, milestone_read),
                files=store.files,
                # Its project-level card: the standing style every composed document follows.
                cards=services.detail_cards,
                # The description *is* the instructions (ARCHITECTURE.md), and which prose
                # briefs a compile is a cross-module fact, so it is decided here.
                instructions=description_read,
                parent=services.window,
                pick_assets=pick_assets,
            )
        ),
        # Declares the compiled-document format only; DocsModule and the CLI write it.
        DocsCompiledModule(),
        StepHandoffModule(
            StepHandoffDeps(
                actions=services.actions,
                library=library,
                undo=services.undo,
                sections=services.inspector_sections,
                files=store.files,
            )
        ),
        StepMilestoneModule(
            StepMilestoneDeps(
                library=library,
                undo=services.undo,
                sections=services.inspector_sections,
                actions=services.actions,
            )
        ),
        # No tab: the status vocabulary is a Status submenu of checkable Step verbs.
        StepStatusModule(
            StepStatusDeps(library=library, undo=services.undo, actions=services.actions)
        ),
        # No tab either: a check carries nothing, and the Covers tab that shows what it
        # gathers is the tests module's — it renders a list of tests, which is that
        # module's business, not this one's.
        StepCheckModule(
            StepCheckDeps(library=library, undo=services.undo, actions=services.actions)
        ),
        # A feature is a record in the project's catalogue and, once placed, the step that
        # realises it; it gathers the work behind it, stopping at the previous feature.
        # The Covers tab that shows what it gathers is still the tests module's.
        feature,
        TestsModule(
            TestsDeps(
                library=library,
                debounce=services.debounce,
                undo=services.undo,
                actions=services.actions,
                context=services.context,
                tabs=services.tabs,
                sections=services.inspector_sections,
                segments=services.index_segments,
                theme=services.theme,
                parent=services.window,
                files=store.files,
                # A check declares a scope; a feature and a milestone already were ones, and
                # all three are the same walk with a different stopping rule. Named here,
                # the one place that may know every aspect, so none learns the others.
                scopes=_scope_kinds(check_read, is_feature, milestone_read),
                pick_assets=pick_assets,
            )
        ),
        GithubModule(
            GithubDeps(
                actions=services.actions,
                library=library,
                undo=services.undo,
                sections=services.inspector_sections,
                tasks=services.tasks,
                parent=services.window,
                # Which repository a step's refs belong to: derived from its project's
                # directory — git's answer, so nothing stored can disagree with it.
                repository_for=lambda step_id: origin_url(project_dir_of(step_id)),
            )
        ),
        step_properties,
        project_editor,
        step_order,
        progression,
        time_estimates,
        AgentSkillModule(
            AgentSkillDeps(
                actions=services.actions,
                tasks=services.tasks,
                parent=services.window,
                # The window writes exactly what `dplanner skill install` writes, from the
                # same generator over the same registry.
                skill_files=skill_files,
            )
        ),
        # After every module that registers an activity factory: it reopens the tabs the
        # last session had, and a kind whose factory has not arrived yet is one it would
        # decide this build no longer has.
        ReopenTabsModule(
            ReopenTabsDeps(
                tabs=services.tabs,
                settings_sections=services.settings_sections,
                # Which tabs were open is true of this library alone.
                scope=services.source_scope,
                # A remembered tab whose project has since been deleted is dropped; the
                # module never learns what a project is.
                exists=library.has,
            )
        ),
        # Last: its dialog is built during register() and must see every other module's
        # settings sections.
        SettingsModule(
            SettingsDeps(
                actions=services.actions,
                settings_sections=services.settings_sections,
                parent=services.window,
            )
        ),
    ]


def _module_asset_paths(
    files: "Callable[[str, str], ModuleFileArea]", node_id: str, module_id: str
) -> tuple[str, ...]:
    """A node's module files as absolute paths; a never-flushed node has none."""
    from dplanner.domain.assets import assets

    try:
        area = files(node_id, module_id)
    except KeyError:
        return ()
    return tuple(str(area.absolute(name)) for name in assets(area))


def _handoff_parts(
    library: "Library", step: "Step", files: "Callable[[str, str], ModuleFileArea]"
) -> "list[PromptPart]":
    """The briefing's inherited blocks: handoffs become prompt parts here, and neither the
    agent module nor the handoff module learns the other's name. Both surfaces call this
    one function, so the window and the CLI cannot brief a step two ways."""
    from dplanner.modules.step_agent_instruction.prompt import PromptPart
    from dplanner.modules.step_handoff.handoff import inherited

    return [
        PromptPart(heading=h.title, body=h.note, files=h.assets)
        for h in inherited(library, step, files)
    ]


def _passage_place(source: "FeatureSource") -> str:
    page = f" p.{source.page}" if source.page is not None else ""
    return f"{source.document}{page}"


def _briefing_sections(
    library: "Library", step: "Step", files: "Callable[[str, str], ModuleFileArea]"
) -> "list[PromptPart]":
    """The step's own facts as briefing sections: what it is, why it exists, where the
    work lands. Cross-module prose, so it is worded here in the one file allowed to know
    every module's vocabulary — the agent module renders the blocks without learning what
    a description, a requirement or a PR is. An empty fact contributes no section.
    """
    from dplanner.domain.scope import gatherers
    from dplanner.modules.feature.aspect import is_feature
    from dplanner.modules.feature.aspect import read as feature_read
    from dplanner.modules.feature.catalogue import image_paths, read_catalogue
    from dplanner.modules.github.aspect import pr_label
    from dplanner.modules.github.aspect import read as github_read
    from dplanner.modules.spec.aspect import attachment_paths
    from dplanner.modules.step_agent_instruction.aspect import read as instruction_read
    from dplanner.modules.step_agent_instruction.prompt import PromptPart
    from dplanner.modules.step_description.aspect import MODULE_ID as DESCRIPTION_ID
    from dplanner.modules.step_description.aspect import read as description_read
    from dplanner.modules.step_milestone.aspect import read as milestone_read

    sections: list[PromptPart] = []
    # Without a separate instruction the description IS the ## Instructions block (see
    # _briefing_instruction), so a Description section here would say everything twice.
    description = description_read(step)
    description_files = _module_asset_paths(files, step.id, DESCRIPTION_ID)
    if instruction_read(step) and (description or description_files):
        sections.append(
            PromptPart(heading="Description", body=description, files=description_files)
        )
    project = library.project_of(step.id)
    records = {record.id: record for record in read_catalogue(project)}

    def record_lines(record_id: str) -> list[str]:
        record = records.get(record_id)
        if record is None:
            # A marker may name a record that was removed (undo restores either side
            # independently); the briefing says so rather than pretending otherwise.
            return [f"- {record_id} (no longer in the feature catalogue)"]
        where = ""
        if len(record.sources) == 1:
            where = f", from {_passage_place(record.sources[0])}"
        lines = [f"- **{record.title}** ({record.id}{where})"]
        for source in record.sources:
            if len(record.sources) > 1:
                lines.append(f"  from {_passage_place(source)}:")
            lines += [f"  > {quoted}" for quoted in source.quote.splitlines()]
        return lines

    realised = feature_read(step)
    if realised:
        record = records.get(realised)
        body = "\n".join(record_lines(realised))
        if record is not None and record.description:
            body += "\n\n" + record.description.rstrip()
        sections.append(
            PromptPart(
                heading="The feature this step realises",
                body=body,
                files=image_paths(files, project.id, record) if record is not None else (),
            )
        )
    elif realised is None:
        # A work step reaches the spec through the feature it flows into: the graph's
        # answer, the same walk the Covers tab and `scope show` read.
        owners = gatherers(
            library,
            project,
            carried_by=is_feature,
            stops_at=lambda other: is_feature(other) or bool(milestone_read(other)),
        ).get(step.id, ())
        named = [feature_read(project.step(owner) or step) for owner in owners]
        lines = [line for record_id in named if record_id for line in record_lines(record_id)]
        if lines:
            sections.append(PromptPart(heading="Flows into", body="\n".join(lines)))
    figures = attachment_paths(files, step.id)
    if figures:
        sections.append(
            PromptPart(
                heading="Figures from the spec",
                body="Rendered from the specification for this step — look at them.",
                files=figures,
            )
        )
    refs = github_read(step)
    if refs is not None:
        lines = []
        if refs.branch:
            lines.append(f"Branch: {refs.branch}")
        if refs.has_pr():
            pr = pr_label(refs)
            if refs.pr_title:
                pr += f" — {refs.pr_title}"
            if refs.pr_state:
                pr += f" ({refs.pr_state})"
            if refs.pr_url:
                pr += f" {refs.pr_url}"
            lines.append(pr)
        if lines:
            sections.append(PromptPart(heading="Where the work lands", body="\n".join(lines)))
    return sections


def _briefing_project_sections(
    library: "Library", step: "Step", _files: "Callable[[str, str], ModuleFileArea]"
) -> "list[PromptPart]":
    """The project's own facts as briefing sections: its topology — how the graph is
    shaped, which every step is read against. Root prose for the same reason as the
    step's sections: it names another module's vocabulary."""
    from dplanner.modules.spec.aspect import read_topology
    from dplanner.modules.step_agent_instruction.prompt import PromptPart

    topology = read_topology(library.project_of(step.id))
    if not topology.strip():
        return []
    return [PromptPart(heading="Topology — how this project's graph is shaped", body=topology)]


def _briefing_instruction(
    library: "Library", step: "Step", files: "Callable[[str, str], ModuleFileArea]"
) -> "PromptPart":
    """The briefing's ``## Instructions`` block: the description is the instructions.

    A step's separate instruction wins when one exists; otherwise the description body and
    its images take the block — one text an agent step needs, written once. Cross-module
    (it reads the description on the agent module's behalf), so it is decided here, in the
    one file allowed to know both. Instruction-area files always ride with the block: they
    were attached to it.
    """
    from dplanner.modules.step_agent_instruction.aspect import asset_paths
    from dplanner.modules.step_agent_instruction.aspect import read as instruction_read
    from dplanner.modules.step_agent_instruction.prompt import PromptPart
    from dplanner.modules.step_description.aspect import MODULE_ID as DESCRIPTION_ID
    from dplanner.modules.step_description.aspect import read as description_read

    own = instruction_read(step)
    instruction_files = asset_paths(files, step.id)
    if own:
        return PromptPart(heading="Instructions", body=own, files=instruction_files)
    description_files = _module_asset_paths(files, step.id, DESCRIPTION_ID)
    return PromptPart(
        heading="Instructions",
        body=description_read(step),
        files=(*description_files, *instruction_files),
    )


def _default_briefing() -> "Briefing":
    """The briefing every surface assembles from: the shared block builders below, and
    the root's own opening and closing prose. One object, two callers — the window's
    Deps and ``dplanner agent prompt`` — so what an agent is launched with and what the
    verb prints are the same text by construction."""
    from dplanner.modules.step_agent_instruction.prompt import Briefing

    return Briefing(
        parts=_handoff_parts,
        sections=_briefing_sections,
        project_sections=_briefing_project_sections,
        epilogue=_agent_epilogue,
        preamble=_agent_preamble,
        instruction=_briefing_instruction,
    )


def _step_key(step: "Step") -> str:
    """The step's readable key: a letter for what it is, the number the project dealt.

    ``M`` a milestone, ``F`` a feature, ``C`` a check, ``S`` any other step — the coarser
    claim wins, in the order the body tone ranks them, so a milestone that is also a
    feature reads ``M``. The letter is presentation over the stored number, which is why
    a step keeps its number when its kind changes and the letter follows. Read by the
    canvas spine, every CLI row and lookup, the branch a run is named after, and the
    briefing that tells the agent which step it holds.
    """
    from dplanner.modules.feature.aspect import is_feature
    from dplanner.modules.step_check.aspect import read as check_read
    from dplanner.modules.step_milestone.aspect import read as milestone_read

    if not step.number:
        return ""
    letter = (
        "M"
        if milestone_read(step)
        else "F"
        if is_feature(step)
        else "C"
        if check_read(step)
        else "S"
    )
    return f"{letter}{step.number}"


def _ticket_key(step: "Step") -> str:
    from dplanner.modules.step_ticket.aspect import read as ticket_read

    ticket = ticket_read(step)
    return ticket.key if ticket is not None else ""


def _run_name(step: "Step") -> str:
    """What a step's agent run is called — the same rule the launcher applies, read here
    so the briefing can name the worktree the script prepared."""
    from dplanner.modules.step_agent_instruction.launcher import run_name

    return run_name(_step_key(step), _ticket_key(step), step.title)


def _agent_preamble(step: "Step", in_worktree: bool) -> str:
    """The briefing's preflight: the agent proves it can report back, and that it is
    where this run said it would be, before it starts.

    An agent without the DPlanner skill would do the work and leave the plan blind — no
    status, no handoff — so the briefing makes the check the first move and stopping the
    honest fallback. The second check is the worktree: two agents once "launched into
    fresh worktrees" and did their work on the same branch, so an agent whose step asks
    for a worktree confirms it is in one — by the name the launcher prepared — and stops
    if it is not. ``in_worktree`` is the caller's word on *this run* — the step's own
    choice for Run Agent and ``agent prompt``, never for a conflict the window hands over.
    Root prose for the same reason as the epilogue: it names other modules' verbs and the
    launcher's naming.
    """
    from dplanner.modules.step_agent_instruction.launcher import (
        WORKTREES_DIR,
        branch_name,
    )

    lines = [
        "First, confirm you can drive DPlanner: run `dplanner skill status`. If the"
        " command is missing or the skill is not installed, STOP — do not carry out the"
        " step — and tell the developer this step needs the DPlanner skill"
        " (`dplanner skill install`)."
    ]
    if in_worktree:
        name = _run_name(step)
        lines.append(
            "Second, confirm you are in this step's own git worktree: `git rev-parse"
            f" --show-toplevel` must end in `{WORKTREES_DIR}/{name}` and `git branch"
            f" --show-current` must print `{branch_name(name)}`. If either differs, STOP"
            " — do not touch the main checkout — and tell the developer the worktree"
            " was not prepared. Commit on that branch; every `dplanner` command still"
            " reaches the plan the window shows."
        )
    else:
        lines.append(
            "This step works in the checkout itself (its worktree option is off), on the"
            " branch that is checked out — take care: other agents may be in worktrees"
            " beside you, but this one shares the developer's working tree."
        )
    lines.append(
        "Other agents may be working beside you in this repository, each in a worktree"
        " of its own, and their processes carry the same names and paths as yours. Never"
        " kill a process by name or pattern (`pkill -f`, `killall`, `kill $(pgrep …)`):"
        " kill only by a pid your own shell started."
    )
    return "\n\n".join(lines)


def _agent_epilogue(step: "Step") -> str:
    """The briefing's closing words: how the agent reports back through the CLI.

    Cross-module prose — it names the status and handoff verbs — so it is written here, in
    the one file allowed to know every module's vocabulary, and handed to the agent module
    as a callback on both surfaces. Every verb names the step by its key: a key is
    unambiguous where a title may match two steps, and it is what the branch and the
    PR are named after.
    """
    key = _step_key(step) or step.title or "Untitled step"
    ref = f"'{key}'" if " " in key else key
    return (
        f"This step is {key}. Its branch and worktree carry that key; open the PR title"
        f" with it (`{key}: …`) and record the branch and the PR on the step as they"
        f" exist: `dplanner github set {ref} --branch $(git branch --show-current)`,"
        f" then `dplanner github set {ref} --pr <number>`.\n"
        "As you work, keep the run state current:\n"
        f"- `dplanner agent-state set {ref} plan-for-review` when your plan is ready"
        " to review\n"
        f"- `dplanner agent-state set {ref} working` while implementing\n"
        f"- `dplanner agent-state set {ref} pending-approval` while waiting on an"
        " approval\n"
        f"- `dplanner agent-state set {ref} needs-input` when you have a question the"
        " developer must answer before you can go on\n"
        "When the work is finished, record it in DPlanner:\n"
        f"- `dplanner status set {ref} done` and `dplanner agent-state clear {ref}`\n"
        f"- `dplanner handoff set {ref} --file -` with anything later steps should"
        " know (add `--scope project` to reach the whole project;"
        f" `dplanner handoff attach {ref} <file>` for files).\n"
        f"If you cannot finish, `dplanner status set {ref} blocked` and say why in the"
        " handoff."
    )


def _scope_kinds(
    is_check: Callable[["Step"], bool],
    is_feature: Callable[["Step"], bool],
    milestone_label: Callable[["Step"], str],
) -> tuple["ScopeKind", ...]:
    """The collectors this build knows, and where each one's cone stops.

    Read most specific first: a step marked as both a milestone and a feature is a milestone,
    because that is the coarser claim and the one a person is looking for.

    The stopping rules are the whole design. A **check** stands for everything behind it
    having been verified, so it stops at nothing. A **milestone** collects what is new since
    the previous milestone, so it stops at milestones. A **feature** collects its own work up
    to the previous feature — and at a milestone too, since a milestone is a boundary anything
    below it also respects.

    A milestone and a check are then *read* as lists of features; a feature is the finest
    grain and is read flat. That is a different question from where the walk stops, and
    saying both here is what keeps a surface from having to guess either.

    Written literally rather than derived from a rank, because three lines a reader can
    check by eye beat an ordering abstraction over exactly three things.
    """
    from dplanner.domain.scope import ScopeKind

    # A milestone declares itself by carrying a label, so the aspect's reader is a string
    # one; the walk wants a predicate, and this is the one place that has to know both.
    def is_milestone(step: "Step") -> bool:
        return bool(milestone_label(step))

    return (
        ScopeKind("step_milestone", "Milestone", is_milestone, is_milestone, gathers="feature"),
        ScopeKind(
            "feature",
            "Feature",
            is_feature,
            lambda step: is_feature(step) or is_milestone(step),
        ),
        ScopeKind("step_check", "Check", is_check, lambda _step: False, gathers="feature"),
    )


def _coverage_trace(library: "Library", project: "Project", files: "FilesFor") -> "Trace":
    """The coverage picture: spec passages → features → milestones → tests and docs.

    The one place the spec, the feature catalogue, the collectors, the tests and the docs
    meet; each answers through its own Qt-free reader and ``coverage/trace.py`` only
    arranges them. Derived on every read, like everything the graph could contradict.
    """
    from dplanner.modules.coverage.trace import (
        Citation,
        Document,
        Feature,
        Readers,
        TestRow,
        build,
    )
    from dplanner.modules.docs.aspect import read as docs_read
    from dplanner.modules.docs.collect import sources_for
    from dplanner.modules.docs.collect import state_of as docs_state
    from dplanner.modules.feature.aspect import is_feature
    from dplanner.modules.feature.catalogue import instance_of, read_catalogue
    from dplanner.modules.spec.aspect import MODULE_ID as SPEC_ID
    from dplanner.modules.spec.cli import anchor_sources
    from dplanner.modules.spec.documents import document_text, read_index
    from dplanner.modules.step_check.aspect import read as check_read
    from dplanner.modules.step_milestone.aspect import read as milestone_read
    from dplanner.modules.step_status.aspect import read as step_status
    from dplanner.modules.testing.aspect import covered
    from dplanner.modules.testing.runs import latest_results
    from dplanner.modules.testing.runs import read as read_runs

    scopes = _scope_kinds(check_read, is_feature, milestone_read)

    def features(library: "Library", project: "Project", files: "FilesFor") -> list[Feature]:
        records = read_catalogue(project)
        refs = [(s.document, s.quote, s.digest) for r in records for s in r.sources]
        anchors = iter(anchor_sources(files, project, refs))
        found = []
        for record in records:
            instance = instance_of(project, record.id)
            citations = tuple(
                Citation(s.document, s.quote, s.page, next(anchors)) for s in record.sources
            )
            found.append(
                Feature(
                    record.id,
                    record.title,
                    instance.id if instance is not None else None,
                    citations,
                )
            )
        return found

    def documents(project: "Project", files: "FilesFor") -> list[Document]:
        try:
            area = files(project.id, SPEC_ID)
        except KeyError:
            area = None
        return [
            Document(doc.name, doc.kind, document_text(area, doc) if area is not None else None)
            for doc in read_index(project).documents
        ]

    def tests(
        library: "Library",
        project: "Project",
        step_id: str,
        stops_at: "Callable[[Step], bool] | None",
    ) -> list[TestRow]:
        return [
            TestRow(test.id, test.title, step.id, step.title)
            for step, test in covered(library, project, step_id, stops_at=stops_at)
        ]

    def results(project: "Project") -> dict[str, str]:
        outcomes = latest_results(read_runs(project))
        return {test_id: outcome.result.status for test_id, outcome in outcomes.items()}

    def docs(library: "Library", project: "Project", step_id: str) -> str:
        step = project.step(step_id)
        if step is None:
            return ""
        state = docs_state(scopes, library, project, step_id)
        if state != "never":
            return state
        # Never compiled, but there is something to compile — or a note of its own.
        has_notes = bool(docs_read(step)) or bool(sources_for(scopes, library, project, step_id))
        return "never" if has_notes else ""

    return build(
        Readers(
            features=features,
            documents=documents,
            is_feature=is_feature,
            is_milestone=lambda step: bool(milestone_read(step)),
            milestone_label=milestone_read,
            is_done=lambda step: step_status(step) == "done",
            tests=tests,
            results=results,
            docs=docs,
        ),
        library,
        project,
        files,
    )


def _covered_tests(
    library: "Library",
    project: "Project",
    step_id: str,
    stops_at: "Callable[[Step], bool] | None" = None,
) -> list[tuple[str, str, str]]:
    """What a collector stands for: (test id, test title, owning step's title).

    The one place the collector aspects and the tests aspect meet. None imports another; the
    walk is the domain's and the filtering is testing's, and this hands the pair over as the
    tuple a report can print. ``stops_at`` is where that walk gives way to the next collector
    — passed through rather than interpreted here. Derived on every read: a stored coverage
    list could disagree with the graph the moment ``dplanner step link`` runs with no window
    open to notice.
    """
    from dplanner.modules.testing.aspect import covered

    return [
        (test.id, test.title, step.title)
        for step, test in covered(library, project, step_id, stops_at=stops_at)
    ]


def _paste_policies() -> tuple["PastePolicy", ...]:
    """What a copied step may not carry verbatim, one policy per module that has a say.

    Assembled here because each policy lives in its owner's Qt-free half and no module may
    import another's; both the window's Paste/Duplicate and ``step duplicate`` read this
    tuple. Three entries, on purpose: an id minted per project (a test's), the state of a
    shell somebody is running, and a feature's marker — a record has one instance, and
    the original keeps it. Everything else a step carries copies as it is.
    """
    from dplanner.modules.feature.catalogue import drop_marker_for_paste
    from dplanner.modules.step_agent_run.aspect import forget_for_paste
    from dplanner.modules.testing.aspect import remint_for_paste

    return (remint_for_paste, forget_for_paste, drop_marker_for_paste)


def _asset_sources() -> tuple["AssetSource", ...]:
    """Every module's slice of the asset catalog, in reading order.

    The tuple both surfaces read — ``asset list``/``uses``/``prune`` and the Assets tab —
    assembled here because each ``asset_source()`` lives in its owner's Qt-free half and
    no module may import another's. The order is the report order: the prose surfaces a
    person writes first, then what rides along to agents, then the spec's figures and
    the features', then the pool.
    """
    from dplanner.modules.docs.aspect import asset_source as documentation
    from dplanner.modules.feature.catalogue import asset_source as feature_images
    from dplanner.modules.project_assets.cli import asset_source as pool
    from dplanner.modules.spec.documents import asset_source as spec_figures
    from dplanner.modules.step_agent_instruction.aspect import asset_source as instructions
    from dplanner.modules.step_description.aspect import asset_source as descriptions
    from dplanner.modules.step_handoff.aspect import asset_source as handoffs
    from dplanner.modules.testing.aspect import asset_source as tests

    return (
        descriptions(),
        tests(),
        documentation(),
        instructions(),
        handoffs(),
        spec_figures(),
        feature_images(),
        pool(),
    )


def default_cli_commands(gate: "TopologyGate | None" = None) -> list["CliCommand"]:
    """Every ``dplanner <noun> <verb>``, from the same modules the window is built from.

    The headless half of the composition root. It imports each module's ``cli.py`` and
    nothing else — no ``module.py``, no Qt — which is what lets ``dplanner project list``
    start in milliseconds and run where a graphics stack does not exist.

    ``gate`` is the topology gate every graph-editing verb runs behind; None builds the
    real one over the user's config directory. The test suite's shared registry passes a
    gate with no record file, so no test ever writes the per-user file.
    """
    from dplanner.cli.aspects import commands as aspect_commands
    from dplanner.cli.assets import catalog_commands
    from dplanner.cli.command import CliRegistry
    from dplanner.cli.gate import RECORD_FILE, TopologyGate, gated
    from dplanner.cli.lint import commands as lint_commands
    from dplanner.cli.scopes import commands as scope_commands
    from dplanner.cli.scopes import lint_checks as scope_lint
    from dplanner.cli.skill import commands as skill_commands
    from dplanner.cli.telemetry import commands as telemetry_commands
    from dplanner.core.config_dir import config_dir
    from dplanner.core.telemetry import crash_log_path, journal_path
    from dplanner.modules.coverage import cli as coverage_cli
    from dplanner.modules.docs import cli as docs_cli
    from dplanner.modules.estimation import cli as estimation_cli
    from dplanner.modules.estimation.aspect import read as estimated_days
    from dplanner.modules.estimation.schedule import start_of
    from dplanner.modules.feature import cli as feature_cli
    from dplanner.modules.feature.aspect import is_feature
    from dplanner.modules.github import cli as github_cli
    from dplanner.modules.library import cli as library_cli
    from dplanner.modules.progression import cli as progression_cli
    from dplanner.modules.project_assets import cli as assets_cli
    from dplanner.modules.project_assets.cli import read_titles
    from dplanner.modules.project_editor import cli as layout_cli
    from dplanner.modules.projects import cli as projects_cli
    from dplanner.modules.spec import cli as spec_cli
    from dplanner.modules.spec.aspect import read_topology
    from dplanner.modules.step_agent_instruction import cli as agent_cli
    from dplanner.modules.step_agent_instruction.aspect import enabled as agent_marked
    from dplanner.modules.step_agent_run import cli as agent_state_cli
    from dplanner.modules.step_check import cli as check_cli
    from dplanner.modules.step_check.aspect import read as check_read
    from dplanner.modules.step_description import cli as description_cli
    from dplanner.modules.step_description.aspect import read as description_read
    from dplanner.modules.step_handoff import cli as handoff_cli
    from dplanner.modules.step_milestone import cli as milestone_cli
    from dplanner.modules.step_milestone.aspect import read as milestone_read
    from dplanner.modules.step_order import cli as order_cli
    from dplanner.modules.step_status import cli as status_cli
    from dplanner.modules.step_status.aspect import read as step_status
    from dplanner.modules.step_ticket import cli as ticket_cli
    from dplanner.modules.testing import cli as testing_cli
    from dplanner.modules.testing.aspect import enabled as test_enabled
    from dplanner.modules.time_estimates import cli as time_cli

    specs = aspect_specs()
    scopes = _scope_kinds(check_read, is_feature, milestone_read)
    sources = _asset_sources()
    if gate is None:
        gate = TopologyGate(record_path=config_dir() / RECORD_FILE, topology_of=read_topology)
    commands = [
        *library_cli.commands(),
        # The step authors let `step add` author the step in the same call; the list
        # order is the report order — the same order the skill teaches authoring in.
        *projects_cli.commands(
            step_authors=[
                description_cli.step_author(),
                agent_cli.step_author(),
                estimation_cli.step_author(),
                feature_cli.step_author(),
                spec_cli.step_author(),
                testing_cli.step_author(),
            ],
            # The key a row prints is the one the canvas paints: one rule, here.
            key_of=_step_key,
        ),
        # `topology show` tells the gate what it printed; the gate is built here, so the
        # spec module never learns where the record lives.
        *spec_cli.commands(note_read=gate.record),
        *estimation_cli.commands(),
        *ticket_cli.commands(),
        *description_cli.commands(),
        *docs_cli.commands(kinds=scopes),
        *agent_cli.commands(briefing=_default_briefing()),
        *agent_state_cli.commands(),
        *status_cli.commands(),
        *milestone_cli.commands(),
        # A feature's passages are anchored in the spec documents by the spec module's
        # one derivation, handed across here — `feature add`, `cite`, `reanchor` and lint
        # all judge a quote the same way.
        *feature_cli.commands(anchor=spec_cli.anchor_sources),
        *handoff_cli.commands(),
        *testing_cli.commands(),
        *check_cli.commands(),
        # What any collector gathers is one derivation asked three ways, so it is one verb
        # rather than one per aspect. The kinds and the coverage walk arrive as arguments,
        # so cli/scopes.py imports no module and no module imports it.
        *scope_commands(kinds=scopes, covered_by=_covered_tests),
        # The coverage picture is every module's Qt-free half read once and arranged;
        # assembled here, so neither the verbs nor the tab import any of them.
        *coverage_cli.commands(trace_of=_coverage_trace),
        # The asset catalog is the same shape one level down: every file-carrying module
        # exports an asset_source(), the reports live in cli/assets.py, and the browser
        # module's own writes (attach, name) stay in its cli.py — the `scope` split.
        *catalog_commands(sources=sources, titles=read_titles),
        *assets_cli.commands(sources=sources),
        *order_cli.commands(),
        # Progression reads statuses and estimates through the aspects' Qt-free readers —
        # handed over here so no cli.py imports another module's.
        *progression_cli.commands(status_for=step_status, days_for=estimated_days),
        # The timeline sort reads a step's length through estimation's Qt-free reader —
        # handed over here so neither cli.py imports the other.
        *layout_cli.commands(
            days_for=estimated_days,
            paste_policies=_paste_policies(),
            file_modules=tuple(source.id for source in sources),
        ),
        # The staffing matrix reads estimates, agent-ness and the start date through the
        # owners' Qt-free readers — handed over here so no cli.py imports another module's.
        *time_cli.commands(
            days_for=estimated_days,
            is_agent=agent_marked,
            start_of=start_of,
            milestone_label=milestone_read,
        ),
        *github_cli.commands(),
        # The journal both surfaces write, read back: the paths are the process's, handed
        # over here so a test can point the same verbs at a file of its own.
        *telemetry_commands(journal=journal_path(), crash_log=crash_log_path()),
        *aspect_commands(specs),
        # Each module exports what "missing" means for its own aspect; the list order is
        # the report order — the graph's integrity first, then authoring, then the spec.
        *lint_commands(
            checks=[
                *projects_cli.lint_checks(),
                *description_cli.lint_checks(),
                *docs_cli.lint_checks(kinds=scopes),
                # An agent step is briefed by its description unless it carries a separate
                # instruction; the description's reader arrives here, not by import.
                *agent_cli.lint_checks(described=lambda step: bool(description_read(step))),
                *estimation_cli.lint_checks(),
                *spec_cli.lint_checks(),
                *feature_cli.lint_checks(anchor=spec_cli.anchor_sources),
                *testing_cli.lint_checks(),
                # A step's *own* tests are a different question from what it gathers;
                # testing's Qt-free reader answers it, handed over rather than imported.
                *scope_lint(kinds=scopes, covered_by=_covered_tests, carries_tests=test_enabled),
            ]
        ),
    ]
    # Every verb that declared it reshapes a graph runs behind the topology gate. Wrapped
    # before the skill reads the registry, so the skill describes the gated verbs.
    commands = [gated(command, gate) for command in commands]
    # The skill describes the registry it is registered into, so the loop is closed here
    # rather than by anything going looking for a registry at run time.
    described = CliRegistry()
    described.register_all(commands)
    skill = skill_commands(specs, described)
    described.register_all(skill)
    return [*commands, *skill]


def aspect_specs() -> list["AspectSpec"]:
    """Every step aspect this build knows about.

    What ``dplanner aspect list`` prints and the generated skill describes — the entry point
    an agent uses to find out what a step can carry. Each package declares its own ``SPEC``;
    this is only the list of packages, in the order a person would read them.
    """
    from dplanner.modules.docs import aspect as docs
    from dplanner.modules.estimation import aspect as estimation
    from dplanner.modules.feature import aspect as feature
    from dplanner.modules.github import aspect as github
    from dplanner.modules.spec import aspect as spec
    from dplanner.modules.step_agent_instruction import aspect as agent
    from dplanner.modules.step_agent_run import aspect as agent_run
    from dplanner.modules.step_check import aspect as check
    from dplanner.modules.step_description import aspect as description
    from dplanner.modules.step_handoff import aspect as handoff
    from dplanner.modules.step_milestone import aspect as milestone
    from dplanner.modules.step_status import aspect as status
    from dplanner.modules.step_ticket import aspect as ticket
    from dplanner.modules.testing import aspect as testing

    return [
        agent.SPEC,
        agent_run.SPEC,
        check.SPEC,
        description.SPEC,
        docs.SPEC,
        docs.COMPILED_SPEC,
        estimation.SPEC,
        feature.SPEC,
        github.SPEC,
        handoff.SPEC,
        milestone.SPEC,
        spec.SPEC,
        status.SPEC,
        testing.SPEC,
        ticket.SPEC,
    ]


# Row phrases lead with where a step *stands* (status, agent run, milestone) before what it
# *carries*. Only a preference: an aspect not named here still appears, after these, in
# aspect_specs() order — so a new aspect reaches every step row without editing this list.
_PHRASE_ORDER = (
    "step_status",
    "step_agent_run",
    "step_milestone",
    "feature",
    "estimation",
    "step_ticket",
    "github",
    "spec",
    "step_description",
    "step_agent_instruction",
    "step_handoff",
)


def aspect_summaries(skip: "Container[str]" = ()) -> list[Callable[["Step"], str]]:
    """Each aspect's one-phrase description of a step, for whoever renders a step row.

    A projection of :func:`aspect_specs` — the ``phrase`` on each SPEC — so an aspect
    cannot exist without a row presence. ``skip`` is for a surface that already shows one
    of them in a column of its own — the order table and its Estimate column — so the
    phrase is not printed twice.
    """
    specs = {spec.id: spec for spec in aspect_specs()}
    ordered = [specs.pop(aspect_id) for aspect_id in _PHRASE_ORDER if aspect_id in specs]
    ordered += specs.values()
    return [spec.phrase for spec in ordered if spec.id not in skip]


def default_module_formats() -> list[ModuleDataFormat]:
    """Every module data format, for the CLI to migrate with.

    The GUI gets these from the module objects themselves (``AppBuilder`` reads
    ``data_format`` off anything that declares one). The CLI never builds those objects, so
    the same list has to be reachable without them — and it must stay complete, because a
    format missing here is data the CLI silently declines to bring forward.
    """
    from dplanner.domain import shelf
    from dplanner.modules.project_assets import cli as project_assets
    from dplanner.modules.project_editor import positions
    from dplanner.modules.time_estimates import schedule as time_schedule

    # The aspects, plus the module data that is not an aspect: the graph's node positions,
    # the time report's focus factor and the asset browser's display titles. Deriving this
    # list from aspect_specs() alone would silently omit them. A project's start date
    # needs no entry: it rides on the estimation aspect's format, which is the same module
    # writing under the same id on another node.
    # The shelf is the fourth: the domain's own, holding turned-off aspects' data.
    return [spec.data_format for spec in aspect_specs()] + [
        positions.DATA_FORMAT,
        time_schedule.DATA_FORMAT,
        project_assets.DATA_FORMAT,
        shelf.DATA_FORMAT,
    ]
