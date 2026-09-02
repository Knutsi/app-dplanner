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
    from dplanner.domain.aspects import AspectSpec
    from dplanner.domain.assets import AssetSource
    from dplanner.domain.model import Library, Project, Step
    from dplanner.domain.ordering import Placed
    from dplanner.domain.schedule import Scheduled
    from dplanner.domain.scope import ScopeKind
    from dplanner.domain.store import ModuleFileArea
    from dplanner.framework.mime_files import Payload
    from dplanner.framework.module import Module
    from dplanner.framework.services import AppServices
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
    from dplanner.domain.store import LibraryStore
    from dplanner.modules.agent_skill.module import AgentSkillDeps, AgentSkillModule
    from dplanner.modules.appshell.module import AppShellDeps, AppShellModule
    from dplanner.modules.debug.module import DebugDeps, DebugModule
    from dplanner.modules.docs.module import DocsCompiledModule, DocsDeps, DocsModule
    from dplanner.modules.estimation.aspect import MODULE_ID as ESTIMATION_ID
    from dplanner.modules.estimation.aspect import read as estimated_days
    from dplanner.modules.estimation.module import EstimationDeps, EstimationModule
    from dplanner.modules.estimation.schedule import start_of, write_start
    from dplanner.modules.github.aspect import MODULE_ID as GITHUB_ID
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
    from dplanner.modules.project_editor.kinds import StepKind
    from dplanner.modules.project_editor.module import ProjectEditorDeps, ProjectEditorModule
    from dplanner.modules.project_editor.renderers import NodeAccent
    from dplanner.modules.projects.module import ProjectEntry, ProjectsDeps, ProjectsModule
    from dplanner.modules.reopen_tabs.module import ReopenTabsDeps, ReopenTabsModule
    from dplanner.modules.settings.module import SettingsDeps, SettingsModule
    from dplanner.modules.spec.aspect import MODULE_ID as SPEC_ID
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
    from dplanner.modules.step_agent_run.aspect import MODULE_ID as AGENT_RUN_ID
    from dplanner.modules.step_agent_run.aspect import read as agent_run_state
    from dplanner.modules.step_agent_run.aspect import record_launch as agent_run_launch
    from dplanner.modules.step_agent_run.module import StepAgentRunModule
    from dplanner.modules.step_check.aspect import read as check_read
    from dplanner.modules.step_check.aspect import write as check_write
    from dplanner.modules.step_check.module import StepCheckDeps, StepCheckModule
    from dplanner.modules.step_description.aspect import read as description_read
    from dplanner.modules.step_description.aspect import summary as description_summary
    from dplanner.modules.step_description.module import (
        StepDescriptionDeps,
        StepDescriptionModule,
    )
    from dplanner.modules.step_description.section import SeparateInstructionLink
    from dplanner.modules.step_feature.aspect import read as feature_read
    from dplanner.modules.step_feature.aspect import write as feature_write
    from dplanner.modules.step_feature.module import StepFeatureDeps, StepFeatureModule
    from dplanner.modules.step_handoff.module import StepHandoffDeps, StepHandoffModule
    from dplanner.modules.step_milestone.aspect import MODULE_ID as MILESTONE_ID
    from dplanner.modules.step_milestone.aspect import next_milestone_label
    from dplanner.modules.step_milestone.aspect import project_labels as milestone_labels
    from dplanner.modules.step_milestone.aspect import read as milestone_read
    from dplanner.modules.step_milestone.aspect import write as milestone_write
    from dplanner.modules.step_milestone.module import StepMilestoneDeps, StepMilestoneModule
    from dplanner.modules.step_order.module import StepOrderDeps, StepOrderModule
    from dplanner.modules.step_properties.module import (
        StepPropertiesDeps,
        StepPropertiesModule,
    )
    from dplanner.modules.step_status.aspect import MODULE_ID as STATUS_ID
    from dplanner.modules.step_status.aspect import read as step_status
    from dplanner.modules.step_status.module import StepStatusDeps, StepStatusModule
    from dplanner.modules.step_ticket.module import StepTicketDeps, StepTicketModule
    from dplanner.modules.sync.module import SyncDeps, SyncModule
    from dplanner.modules.taskcenter.module import TaskCenterDeps, TaskCenterModule
    from dplanner.modules.testing.aspect import enabled as test_enabled
    from dplanner.modules.testing.module import TestsDeps, TestsModule
    from dplanner.modules.time_estimates.module import TimeEstimatesDeps, TimeEstimatesModule
    from dplanner.theme.icons import (
        clock_icon,
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

    def milestone_stat(step: "Step") -> str:
        """What a milestone answers with: the schedule's accumulated days and landing date.

        A milestone closes the block of work above it, so its number is the walk's total at
        that row — the same pair the order table's milestone row highlights. Falls back to
        nothing when the project carries no estimates at all.
        """
        project = library.project_of(step.id)
        order = placed(library, project)
        for scheduled in step_schedule(project.id, order):
            if scheduled.place.step.id == step.id:
                if scheduled.finish is not None:
                    return f"{format_days(scheduled.accumulated)} · {format_date(scheduled.finish)}"
                if scheduled.accumulated:
                    return format_days(scheduled.accumulated)
                break
        return ""

    def step_type_icons(step: "Step") -> tuple[str, ...]:
        """What kind of thing a step is, in the medallion vocabulary the canvas painted
        first: "tag" a milestone, "layers" a feature, "spark" an agent step, "beaker" one
        carrying tests, "shield" a check. The order table's title column reads the same
        answer, so a step is the same kind everywhere."""
        return (
            *(("tag",) if milestone_read(step) else ()),
            *(("layers",) if feature_read(step) else ()),
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

    def step_accent(step_id: str) -> "NodeAccent":
        """How a step looks on the canvas, translated from aspects the canvas never learns.

        A done step is muted with a green body — finished work recedes into a colour the
        eye can skip; in-progress and blocked wear busy and bad bars; a milestone is a
        purple-highlighted node wearing its label as a badge, a tag medallion and the
        schedule's accumulated days and date as its stat (done outranks it on the body —
        a shipped milestone reads finished, and the tag still says what it was); an agent
        instruction is the spark medallion; a PR is a pill with its state as a tone and a
        branch the fork glyph; a live agent run is the chip on the bottom edge; a plain
        step's stat is its own estimate. Everything worn here is skipped from the canvas
        subtitle below, so nothing is said twice.
        """
        step = library.step(step_id)
        refs = github_read(step)
        pill = ""
        if refs is not None and refs.has_pr():
            pill = pr_label(refs)
        chip_text, chip_tone = {
            "launched": ("launched", "info"),
            "working": ("working", "info"),
            "plan-for-review": ("plan ready", "attention"),
            "pending-approval": ("needs approval", "attention"),
        }.get(agent_run_state(step), ("", ""))
        status = step_status(step)
        milestone = milestone_read(step)
        if milestone:
            stat = milestone_stat(step)
        else:
            days = estimated_days(step)
            stat = format_days(days) if days is not None else ""
        return NodeAccent(
            muted=status == "done",
            badge=milestone,
            pill_text=pill,
            pill_tone={"merged": "good", "closed": "bad"}.get(refs.pr_state, "") if refs else "",
            branch=bool(refs is not None and refs.branch),
            # Done colours the whole body, so its bar would only repeat the same green.
            bar_tone={"in-progress": "busy", "blocked": "bad"}.get(status, ""),
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
                if feature_read(step)
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
    project_editor = ProjectEditorModule(
        ProjectEditorDeps(
            library=library,
            actions=services.actions,
            context=services.context,
            tabs=services.tabs,
            undo=services.undo,
            status=services.window,
            parent=services.window,
            panels=services.panels,
            theme=services.theme,
            # A node's second line: whatever the aspects have to say about that step. The
            # milestone and GitHub phrases are skipped because the accent already wears them
            # — the badge the label, the pill and glyph the PR and branch.
            # The accent wears all of these, so the subtitle must not say them again.
            step_aspects=lambda step_id: step_aspects(
                step_id,
                skip={
                    MILESTONE_ID,
                    GITHUB_ID,
                    STATUS_ID,
                    AGENT_INSTRUCTION_ID,
                    AGENT_RUN_ID,
                    ESTIMATION_ID,
                },
            ),
            step_accent=step_accent,
            # The timeline sort reads a step's length through this seam; estimation owns it.
            days_for=estimated_days,
            # The project panel renders whatever registered a card here — the project-level
            # counterpart of the step panel's inspector_sections.
            cards=services.detail_cards,
            # What Step ▸ New offers. A *kind* is what a node is — it wears a body colour
            # and the graph reads differently for it; a *facet* is what a step carries, and
            # "New ▸ Description" would be nonsense, which is why this is a named list
            # rather than the Type submenu. Ticket and Test are one line away if they ever
            # earn a place. The tuple order is the order the menu shows.
            # The glyph on each is the medallion its node will wear, from the same
            # vocabulary ``step_type_icons`` answers in — named once, here.
            step_kinds=(
                StepKind(
                    "step_feature", "Feature", lambda _project: feature_write(True), icon="layers"
                ),
                StepKind(
                    "step_milestone",
                    "Milestone",
                    # A fresh milestone generates its label from the ones already there,
                    # exactly as the Type toggle does — one function, two ways in.
                    lambda project: milestone_write(
                        next_milestone_label(milestone_labels(project))
                    ),
                    icon="tag",
                ),
                StepKind(
                    "step_agent_instruction",
                    "Agent Step",
                    lambda _project: agent_write_state(True),
                    icon="spark",
                ),
                StepKind(
                    "step_check", "Check", lambda _project: check_write(True), icon="shield"
                ),
            ),
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
        )
    )
    # Constructed before the list because the projects index opens the board through it.
    # Run Agent arrives as the real action's state and verb, resolved lazily so the agent
    # module's registration order does not matter; neither module knows the other's name.
    progression = ProgressionModule(
        ProgressionDeps(
            library=library,
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
            parent=services.window,
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
                    detail=", ".join(
                        dict.fromkeys(source.label for source, _l in entry.locations)
                    ),
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
            # trailing aspects column, which is why MILESTONE_ID is not skipped here.
            milestone_label=lambda step_id: milestone_read(library.step(step_id)),
            # The same kind vocabulary the canvas medallions wear, one translation.
            step_icons=lambda step_id: step_type_icons(library.step(step_id)),
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
        # After sync, so a reload notice lands to the right of the library path.
        LibraryWatchModule(
            LibraryWatchDeps(
                # The narrowed store from above: the watcher needs changed_underneath(),
                # which the Repository protocol deliberately does not promise.
                repo=store,
                autosave=services.autosave,
                actions=services.actions,
                switcher=services.switcher,
                status=services.window,
                parent=services.window,
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
                actions=services.actions,
                tabs=services.tabs,
                context=services.context,
            )
        ),
        # -- the planner ------------------------------------------------------------------
        ProjectsModule(
            ProjectsDeps(
                library=library,
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
                parent=services.window,
            )
        ),
        StepDescriptionModule(
            StepDescriptionDeps(
                actions=services.actions,
                parent=services.window,
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
        StepAgentInstructionModule(
            StepAgentInstructionDeps(
                library=library,
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
                # The launch stamp: written directly, off the undo stack — Ctrl+Z cannot
                # un-launch a shell.
                record_launch=lambda step_id: agent_run_launch(library, step_id),
                pick_assets=pick_assets,
            )
        ),
        # Declares the agent-run format only; Run Agent and the CLI write it, the canvas
        # reads it through step_accent above.
        StepAgentRunModule(),
        DocsModule(
            DocsDeps(
                library=library,
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
                scopes=_scope_kinds(check_read, feature_read, milestone_read),
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
                parent=services.window,
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
                parent=services.window,
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
        # A feature is the same shape one rank down: it gathers the work behind it, stopping
        # at the previous feature. Also no tab of its own, for the same reason.
        StepFeatureModule(
            StepFeatureDeps(library=library, undo=services.undo, actions=services.actions)
        ),
        TestsModule(
            TestsDeps(
                library=library,
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
                scopes=_scope_kinds(check_read, feature_read, milestone_read),
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


def _briefing_sections(
    library: "Library", step: "Step", files: "Callable[[str, str], ModuleFileArea]"
) -> "list[PromptPart]":
    """The step's own facts as briefing sections: what it is, why it exists, where the
    work lands. Cross-module prose, so it is worded here in the one file allowed to know
    every module's vocabulary — the agent module renders the blocks without learning what
    a description, a requirement or a PR is. An empty fact contributes no section.
    """
    from dplanner.modules.github.aspect import pr_label
    from dplanner.modules.github.aspect import read as github_read
    from dplanner.modules.spec.aspect import attachment_paths, read_links
    from dplanner.modules.spec.documents import read_index
    from dplanner.modules.step_agent_instruction.aspect import read as instruction_read
    from dplanner.modules.step_agent_instruction.prompt import PromptPart
    from dplanner.modules.step_description.aspect import MODULE_ID as DESCRIPTION_ID
    from dplanner.modules.step_description.aspect import read as description_read

    sections: list[PromptPart] = []
    # Without a separate instruction the description IS the ## Instructions block (see
    # _briefing_instruction), so a Description section here would say everything twice.
    description = description_read(step)
    description_files = _module_asset_paths(files, step.id, DESCRIPTION_ID)
    if instruction_read(step) and (description or description_files):
        sections.append(
            PromptPart(heading="Description", body=description, files=description_files)
        )
    links = read_links(step)
    if links:
        requirements = read_index(library.project_of(step.id)).requirements
        by_id = {requirement.id: requirement for requirement in requirements}
        lines: list[str] = []
        for link in links:
            requirement = by_id.get(link)
            if requirement is None:
                # Links dangle by design (unmark warns, it does not rewrite steps);
                # the briefing says so instead of pretending the link never existed.
                lines.append(f"- {link} (no longer in the spec index)")
                continue
            where = f", in {requirement.document}" if requirement.document else ""
            lines.append(f"- **{requirement.title}** ({requirement.id}{where})")
            lines += [f"  > {quoted}" for quoted in requirement.quote.splitlines()]
        sections.append(
            PromptPart(heading="Requirements this step implements", body="\n".join(lines))
        )
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
        epilogue=lambda step: _agent_epilogue(step.title),
        preamble=_agent_preamble(),
        instruction=_briefing_instruction,
    )


def _agent_preamble() -> str:
    """The briefing's preflight: the agent proves it can report back before it starts.

    An agent without the DPlanner skill would do the work and leave the plan blind — no
    status, no handoff — so the briefing makes the check the first move and stopping the
    honest fallback. Root prose for the same reason as the epilogue: it names another
    module's verbs.
    """
    return (
        "First, confirm you can drive DPlanner: run `dplanner skill status`. If the"
        " command is missing or the skill is not installed, STOP — do not carry out the"
        " step — and tell the developer this step needs the DPlanner skill"
        " (`dplanner skill install`)."
    )


def _agent_epilogue(step_title: str) -> str:
    """The briefing's closing words: how the agent reports back through the CLI.

    Cross-module prose — it names the status and handoff verbs — so it is written here, in
    the one file allowed to know every module's vocabulary, and handed to the agent module
    as a callback on both surfaces.
    """
    title = step_title or "Untitled step"
    return (
        "As you work, keep the run state current:\n"
        f"- `dplanner agent-state set '{title}' plan-for-review` when your plan is ready"
        " to review\n"
        f"- `dplanner agent-state set '{title}' working` while implementing\n"
        f"- `dplanner agent-state set '{title}' pending-approval` while waiting on an"
        " approval\n"
        "When the work is finished, record it in DPlanner:\n"
        f"- `dplanner status set '{title}' done` and `dplanner agent-state clear '{title}'`\n"
        f"- `dplanner handoff set '{title}' --file -` with anything later steps should"
        " know (add `--scope project` to reach the whole project;"
        f" `dplanner handoff attach '{title}' <file>` for files).\n"
        f"If you cannot finish, `dplanner status set '{title}' blocked` and say why in the"
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
        ScopeKind(
            "step_milestone", "Milestone", is_milestone, is_milestone, gathers="step_feature"
        ),
        ScopeKind(
            "step_feature",
            "Feature",
            is_feature,
            lambda step: is_feature(step) or is_milestone(step),
        ),
        ScopeKind("step_check", "Check", is_check, lambda _step: False, gathers="step_feature"),
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


def _asset_sources() -> tuple["AssetSource", ...]:
    """Every module's slice of the asset catalog, in reading order.

    The tuple both surfaces read — ``asset list``/``uses``/``prune`` and the Assets tab —
    assembled here because each ``asset_source()`` lives in its owner's Qt-free half and
    no module may import another's. The order is the report order: the prose surfaces a
    person writes first, then what rides along to agents, then the spec's figures, then
    the pool.
    """
    from dplanner.modules.docs.aspect import asset_source as documentation
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
        pool(),
    )


def default_cli_commands() -> list["CliCommand"]:
    """Every ``dplanner <noun> <verb>``, from the same modules the window is built from.

    The headless half of the composition root. It imports each module's ``cli.py`` and
    nothing else — no ``module.py``, no Qt — which is what lets ``dplanner project list``
    start in milliseconds and run where a graphics stack does not exist.
    """
    from dplanner.cli.aspects import commands as aspect_commands
    from dplanner.cli.assets import catalog_commands
    from dplanner.cli.command import CliRegistry
    from dplanner.cli.lint import commands as lint_commands
    from dplanner.cli.scopes import commands as scope_commands
    from dplanner.cli.scopes import lint_checks as scope_lint
    from dplanner.cli.skill import commands as skill_commands
    from dplanner.modules.docs import cli as docs_cli
    from dplanner.modules.estimation import cli as estimation_cli
    from dplanner.modules.estimation.aspect import read as estimated_days
    from dplanner.modules.estimation.schedule import start_of
    from dplanner.modules.github import cli as github_cli
    from dplanner.modules.library import cli as library_cli
    from dplanner.modules.progression import cli as progression_cli
    from dplanner.modules.project_assets import cli as assets_cli
    from dplanner.modules.project_assets.cli import read_titles
    from dplanner.modules.project_editor import cli as layout_cli
    from dplanner.modules.projects import cli as projects_cli
    from dplanner.modules.spec import cli as spec_cli
    from dplanner.modules.step_agent_instruction import cli as agent_cli
    from dplanner.modules.step_agent_instruction.aspect import enabled as agent_marked
    from dplanner.modules.step_agent_run import cli as agent_state_cli
    from dplanner.modules.step_check import cli as check_cli
    from dplanner.modules.step_check.aspect import read as check_read
    from dplanner.modules.step_description import cli as description_cli
    from dplanner.modules.step_description.aspect import read as description_read
    from dplanner.modules.step_feature import cli as feature_cli
    from dplanner.modules.step_feature.aspect import read as feature_read
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
    scopes = _scope_kinds(check_read, feature_read, milestone_read)
    sources = _asset_sources()
    commands = [
        *library_cli.commands(),
        # The step authors let `step add` author the step in the same call; the list
        # order is the report order — the same order the skill teaches authoring in.
        *projects_cli.commands(
            step_authors=[
                description_cli.step_author(),
                agent_cli.step_author(),
                estimation_cli.step_author(),
                spec_cli.step_author(),
                testing_cli.step_author(),
            ]
        ),
        *spec_cli.commands(),
        *estimation_cli.commands(),
        *ticket_cli.commands(),
        *description_cli.commands(),
        *docs_cli.commands(kinds=scopes),
        *agent_cli.commands(briefing=_default_briefing()),
        *agent_state_cli.commands(),
        *status_cli.commands(),
        *milestone_cli.commands(),
        *feature_cli.commands(),
        *handoff_cli.commands(),
        *testing_cli.commands(),
        *check_cli.commands(),
        # What any collector gathers is one derivation asked three ways, so it is one verb
        # rather than one per aspect. The kinds and the coverage walk arrive as arguments,
        # so cli/scopes.py imports no module and no module imports it.
        *scope_commands(kinds=scopes, covered_by=_covered_tests),
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
        *layout_cli.commands(days_for=estimated_days),
        # The staffing matrix reads estimates, agent-ness and the start date through the
        # owners' Qt-free readers — handed over here so no cli.py imports another module's.
        *time_cli.commands(
            days_for=estimated_days,
            is_agent=agent_marked,
            start_of=start_of,
            milestone_label=milestone_read,
        ),
        *github_cli.commands(),
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
                *testing_cli.lint_checks(),
                # A step's *own* tests are a different question from what it gathers;
                # testing's Qt-free reader answers it, handed over rather than imported.
                *scope_lint(kinds=scopes, covered_by=_covered_tests, carries_tests=test_enabled),
            ]
        ),
    ]
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
    from dplanner.modules.github import aspect as github
    from dplanner.modules.spec import aspect as spec
    from dplanner.modules.step_agent_instruction import aspect as agent
    from dplanner.modules.step_agent_run import aspect as agent_run
    from dplanner.modules.step_check import aspect as check
    from dplanner.modules.step_description import aspect as description
    from dplanner.modules.step_feature import aspect as feature
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
    "step_feature",
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
    from dplanner.modules.project_assets import cli as project_assets
    from dplanner.modules.project_editor import positions
    from dplanner.modules.time_estimates import schedule as time_schedule

    # The aspects, plus the module data that is not an aspect: the graph's node positions,
    # the time report's focus factor and the asset browser's display titles. Deriving this
    # list from aspect_specs() alone would silently omit them. A project's start date
    # needs no entry: it rides on the estimation aspect's format, which is the same module
    # writing under the same id on another node.
    return [spec.data_format for spec in aspect_specs()] + [
        positions.DATA_FORMAT,
        time_schedule.DATA_FORMAT,
        project_assets.DATA_FORMAT,
    ]
