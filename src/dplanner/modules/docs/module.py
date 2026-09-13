"""The docs aspects in the running application: the fragment tab, the Documentation view,
and *Compile with Agent…*.

**Compiling launches a peer, and this module writes no document.** The briefing is built here
(:mod:`dplanner.modules.docs.prompt`) and handed to Run Agent's launcher through two typed
callbacks on :class:`DocsDeps`; the agent reads the fragments and lands the document with
``dplanner compiled set``, which arrives in the window as any other outside change. Three
things follow, and each is a rule rather than an accident:

- **nothing lands on the undo stack.** The write comes from another process minutes later, so
  Ctrl+Z cannot put back a document the agent replaced — which is why the one gesture that
  would overwrite an existing document asks first.
- **the launch is one act with no result seam.** No ``TaskRunner``, no signal home, no
  cancellation: a terminal the person owns promises none of those honestly.
- **who compiled it is remembered here**, per user, because only this module knows which of
  the runs on a collector was *its* launch.

**Any collector compiles.** There is no step kind for it: a feature and a milestone already
are the collectors the graph defines, so compiling is a verb on them and nothing has to be
created. What one reads is :mod:`dplanner.modules.docs.collect`, never stored.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtWidgets import QMenu, QTreeWidgetItem, QWidget

from dplanner.domain.model import Library, NodeId, Step, StepId
from dplanner.domain.scope import ScopeKind, kind_of
from dplanner.domain.store import FilesFor
from dplanner.framework.action_menu import append_action
from dplanner.framework.action_registry import (
    ActionRegistry,
    ActionSpec,
    ActionState,
    DataMenuSpec,
)
from dplanner.framework.activity import follow_entity_tabs
from dplanner.framework.aspect_toggle import aspect_toggle
from dplanner.framework.context import Context, ContextService
from dplanner.framework.debounce import DebounceService
from dplanner.framework.index_panel import IndexSegment, IndexSegmentRegistry
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.mime_files import Payload
from dplanner.framework.project_list_segment import ChildRow, ProjectListSegment
from dplanner.framework.tabs import TabHost
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.framework.user_config import get_global, set_global
from dplanner.framework.widgets import confirm
from dplanner.modules.docs.activity import DOCS_CAPTION, DOCS_KIND, DocsActivity
from dplanner.modules.docs.aspect import (
    COMPILED_FORMAT,
    COMPILED_ID,
    DATA_FORMAT,
    MODULE_ID,
    SPEC,
    enabled,
    read,
    read_compiled,
    read_stamp,
    write_state,
)
from dplanner.modules.docs.collect import Source, sources_for, state_of, sub_collectors
from dplanner.modules.docs.prompt import compile_body
from dplanner.modules.docs.section import (
    CompileLink,
    DocsSection,
    InstructionsCard,
    Standing,
)
from dplanner.theme.icons import read_icon, refresh_icon, spark_icon

COMPILE_ACTION = "docs.compile"
COMPILE_MENU_ID = "docs.compile_with"
COMPILE_MENU_TITLE = "Compile with Agent"
STALE_ACTION = "docs.compile_stale"
NOTHING_REASON = "Nothing to compile — no step behind this one carries a documentation fragment"
NOT_COLLECTOR_REASON = "Compile with Agent — only a feature, milestone or check compiles one"
NOTHING_STALE_REASON = "Compile Out of Date — every document in this project is up to date"
WAITING_REASON = "waiting for a feature's document to be compiled first"
OPEN_STEP_ACTION = "docs.open_step"
NO_DOCS_REASON = "Show Documentation — this step has no documentation and gathers none"
# Which agent this module launched on a collector, per user and per machine: a fact about
# one desk's runs, never the plan (*Attribution comes from the run*). Keyed by step id.
LAUNCHES_KEY = "compiled_by"
# The step panel's tab; SPEC.label is the aspect's full name, which that strip has no room
# for. Two words for one thing is a cost, and a tab bar that elides every label is worse.
TAB_LABEL = "Fragment"


@dataclass(frozen=True)
class DocsDeps:
    library: Library
    undo: UndoService[Library]
    actions: ActionRegistry
    sections: InspectorSectionRegistry
    context: ContextService
    debounce: DebounceService
    tabs: TabHost
    segments: IndexSegmentRegistry
    theme: ThemeService
    # Every collector this build knows — read, never added to: what a feature or a milestone
    # gathers is the same walk the Tests surfaces make.
    scopes: tuple[ScopeKind, ...] = ()
    # Where a step's documentation images live — the store's `files`, so this module
    # never names a store.
    files: FilesFor | None = None
    # The project panel's card stack. None in a build without a project panel.
    cards: InspectorSectionRegistry | None = None
    # What a collector says about itself — its description. Context in the briefing, not a
    # writing brief: which prose that is is a cross-module fact, so the root decides it.
    instructions: Callable[[Step], str] = lambda _step: ""
    # The step's key (F5, M21) — what the briefing's verbs and the list's rows name it by.
    step_key: Callable[[Step], str] = lambda _step: ""
    # Every launch profile this machine offers, with why it cannot compile *these*
    # collectors right now ("" when it can); the default is first. Run Agent's module
    # answers, through the root — this one never learns what a terminal is.
    compile_profiles: Callable[[Sequence[StepId]], Sequence[tuple[str, str]]] = lambda _ids: ()
    # Launch one agent per (collector, briefing body) through the named profile; the
    # launches that opened a shell, each with the words naming what is working on it.
    # None in a build with no launcher, where compiling is simply not offered.
    compile_with_agent: (
        Callable[[Sequence[tuple[StepId, str]], str], Sequence[tuple[StepId, str]]] | None
    ) = None
    # Whether an agent run is live on this step, in the agent-run aspect's own words. Not
    # "is a compile running" — the window cannot tell one run on a step from another — but
    # enough to stop a second launch.
    run_state: Callable[[StepId], str] = lambda _step_id: ""
    # A milestone collector's own shade of the project's colour map, "" for anything else —
    # what its group's medallion is painted in. Wired by the composition root.
    milestone_color: Callable[[str], str] = lambda _step_id: ""
    parent: QWidget | None = None  # What confirm() and the launcher's fallback open over.
    # Insert from Assets…: a modal picker over the node's project's catalog, composed by
    # the root. Node id in, picked payloads out; None is a build without the browser.
    pick_assets: Callable[[str], "list[Payload]"] | None = None
    # Rows other modules put under each project in the index's Docs folder, beside
    # *Documentation* — the notes module's *Implementation notes*, opening its own tab.
    more_rows: tuple[ChildRow, ...] = ()


class DocsCompiledModule:
    """Declares the compiled-document format only.

    ``builder.py`` collects one ``data_format`` per module and migrates them before any
    ``register()`` runs, so a second format needs a second declarer. ``StepAgentRunModule``
    is the same shape for the same reason: nothing to install.
    """

    id = COMPILED_ID
    data_format = COMPILED_FORMAT

    def register(self) -> None:
        return None


class DocsModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: DocsDeps) -> None:
        self._deps = deps

    # -- registration ----------------------------------------------------------------------

    def register(self) -> None:
        deps = self._deps
        deps.sections.register(
            InspectorSection(
                id=f"{MODULE_ID}.tab",
                # Short, where SPEC.label is the full "Documentation fragment": the panel's
                # strip already holds nine tabs and elides. `testing` differs the same way.
                label=TAB_LABEL,
                order=25,
                factory=self._section,
                shown_for=lambda step_id: (
                    step_id is not None
                    and deps.library.has(step_id)
                    and (enabled(deps.library.step(step_id)) or self._collects(step_id))
                ),
            )
        )
        if deps.cards is not None:
            deps.cards.register(
                InspectorSection(
                    id=f"{MODULE_ID}.card",
                    label="Compilation instructions",
                    order=30,
                    factory=lambda: InstructionsCard(
                        deps.library, deps.undo, deps.files, deps.pick_assets
                    ),
                    icon=read_icon,
                    hint="Prepended to every document an agent compiles in this project.",
                )
            )
        deps.tabs.register_factory(DOCS_KIND, self._activity)
        follow_entity_tabs(
            deps.tabs,
            DocsActivity,
            deps.library.has,
            closes_on=deps.library.structure_changed,
            retitles_on=deps.library.field_changed,
        )
        deps.segments.register(
            IndexSegment(id="docs", label="Docs", order=30, factory=self._segment, icon=read_icon)
        )
        for spec in self._action_specs():
            deps.actions.register(spec)
        # Compiling's seat: the profiles, as Run Agent's child menu does it, so picking one
        # is the same gesture in both places and neither is a copy of the other's list.
        deps.actions.register_data_menu(
            DataMenuSpec(
                id=COMPILE_MENU_ID,
                menu="Step",
                group="agent",
                title=COMPILE_MENU_TITLE,
                order=20,  # After Run Agent's child menu (10), in the same band.
                fill=self._fill_profiles,
            )
        )

    def open(self, project_id: NodeId, *, preview: bool = False) -> None:
        self._deps.tabs.open(DOCS_KIND, project_id, preview=preview)

    def open_collector(self, project_id: NodeId, step_id: StepId) -> None:
        """The Docs tab, on the group that is ``step_id``'s."""
        activity = self._deps.tabs.open(DOCS_KIND, project_id)
        if isinstance(activity, DocsActivity):
            activity.show_collector(step_id)

    def has_docs(self, step_id: StepId) -> bool:
        """Whether the Docs tab has anything to show for this step: a document of its
        own to compile or compiled, or a fragment some collector gathers."""
        library = self._deps.library
        if not library.has(step_id):
            return False
        step = library.step(step_id)
        if self._collects(step_id):
            return bool(self._sources(step_id)) or bool(read_compiled(step))
        return enabled(step)

    def _activity(self, target: str | None) -> DocsActivity:
        assert target is not None
        return DocsActivity(self._deps, target, self._link())

    def _section(self) -> DocsSection:
        deps = self._deps
        return DocsSection(deps.library, deps.undo, deps.files, self._link(), deps.pick_assets)

    def _link(self) -> CompileLink:
        """Where a collector's document stands, in the vocabulary a view uses, so no surface
        re-derives it. No ``run``: a view asks for the *verb* through the registry, where its
        state and its profile menu already live."""
        return CompileLink(
            collects=self._collects,
            standing=self.standing_of,
            # The project-wide verb first, then the one on the picked collector — DESIGN.md's
            # strip order — and the profiles under the second one's arrow.
            verbs=(STALE_ACTION, COMPILE_ACTION),
            profile_menu=(COMPILE_ACTION, COMPILE_MENU_ID),
        )

    def _segment(self, root: QTreeWidgetItem) -> ProjectListSegment:
        """One row per project, with the project's documents under it: *Documentation*
        (this tab) and whatever rows other modules add. No *All Projects* row:
        documentation is a project's, and there is no cross-project reading of it worth
        a row."""
        deps = self._deps

        def open_docs(project_id: NodeId, preview: bool) -> None:
            self.open(project_id, preview=preview)

        return ProjectListSegment(
            root,
            deps.library,
            deps.context,
            deps.actions,
            deps.theme,
            key_prefix="docs",
            menu="Project",
            project_icon=read_icon,
            open_project=open_docs,
            children=(ChildRow(DOCS_CAPTION, read_icon, open_docs), *deps.more_rows),
        )

    def _action_specs(self) -> list[ActionSpec]:
        return [
            aspect_toggle(
                id="docs.toggle",
                label=SPEC.label,
                order=85,  # Among the facets, beside Description (80).
                module_id=MODULE_ID,
                library=self._deps.library,
                undo=self._deps.undo,
                enabled=enabled,
                fresh=lambda _step, _project: write_state(True),
                icon=read_icon,
                tip="Give this step prose saying what it adds to the product's documentation",
            ),
            ActionSpec(
                id=COMPILE_ACTION,
                label="Compile with &Agent…",
                menu="Step",
                group="agent",
                order=20,
                submenu=COMPILE_MENU_TITLE,
                in_menus=False,  # Its seat is the child menu of profiles, as Run Agent's is.
                icon=spark_icon,
                tip="Launch an agent to write this collector's document from what it gathers",
                state=self._action_state,
                run=lambda context: self.compile(self._focused_id(context)),
            ),
            ActionSpec(
                id=STALE_ACTION,
                label="Compile &Out of Date…",
                menu="Project",
                group="docs",
                order=10,
                # Not the launch glyph: two verbs a strip shows side by side need two
                # glyphs, and what this one does is bring a set back up to date.
                icon=refresh_icon,
                tip="Launch an agent for every document in this project that is out of date",
                state=self._stale_state,
                run=self._compile_stale,
            ),
            ActionSpec(
                id=OPEN_STEP_ACTION,
                label="Show &Documentation",
                menu="Step",
                group="open",
                order=80,
                tip="Open the Documentation tab on this step's document, or the one"
                " gathering its fragment",
                state=self._open_step_state,
                run=self._open_step,
            ),
        ]

    def _open_step_state(self, context: Context) -> ActionState:
        step_id = self._focused_id(context)
        if not step_id or not self.has_docs(step_id):
            return ActionState(enabled=False, label=NO_DOCS_REASON)
        return ActionState()

    def _open_step(self, context: Context) -> None:
        step_id = self._focused_id(context)
        if step_id and self._deps.library.has(step_id):
            project = self._deps.library.project_of(step_id)
            self.open_collector(project.id, step_id)

    # -- compiling -------------------------------------------------------------------------

    def _collects(self, step_id: StepId) -> bool:
        library = self._deps.library
        if not library.has(step_id):
            return False
        return kind_of(self._deps.scopes, library.step(step_id)) is not None

    def _action_state(self, context: Context) -> ActionState:
        step_id = self._focused_id(context)
        if not step_id or not self._collects(step_id):
            # Not hidden: the verb exists, it just does not apply to a step that gathers
            # nothing. Step ▸ Type ▸ Feature is how it comes to.
            return ActionState(enabled=False, label=NOT_COLLECTOR_REASON)
        reason = self.compile_refusal([step_id])
        return ActionState() if not reason else ActionState(enabled=False, label=reason)

    def compile_refusal(self, step_ids: Sequence[StepId]) -> str:
        """Why these collectors cannot be compiled right now, in the words a greyed control
        shows; "" when they can.

        One function, every presenter — the menu entry, the child menu's default and the
        activity's strip — so the two can never disagree about why the verb is off. What this
        module owns is *is there anything to read*; whether a terminal can open is the
        launcher's answer, asked through ``compile_profiles``. **Up to date is not a
        refusal**: recompiling on purpose is legitimate.
        """
        deps = self._deps
        if deps.compile_with_agent is None:
            return "Compile with Agent — this build has no agent launcher"
        for step_id in step_ids:
            if not self._sources(step_id):
                return NOTHING_REASON
        offers = list(deps.compile_profiles(step_ids))
        return offers[0][1] if offers else "Compile with Agent — no launch profile"

    def standing_of(self, step_id: StepId) -> Standing:
        """Where this collector's document stands, what it would read, what it read, who
        this desk last launched on it and whether an agent is working there now."""
        library = self._deps.library
        if not library.has(step_id):
            return Standing("never", 0, {})
        project = library.project_of(step_id)
        return Standing(
            state_of(self._deps.scopes, library, project, step_id),
            len(self._sources(step_id)),
            read_stamp(library.step(step_id)),
            by=self._launched_by(step_id),
            working=bool(self._deps.run_state(step_id)),
        )

    def _sources(self, step_id: StepId) -> list[Source]:
        library = self._deps.library
        if not library.has(step_id):
            return []
        project = library.project_of(step_id)
        return list(sources_for(self._deps.scopes, library, project, step_id))

    # -- launching a compile -------------------------------------------------------------------

    def compile(self, step_id: StepId, profile: str = "") -> None:
        """Launch an agent to compile one collector's documentation."""
        if step_id and self._collects(step_id):
            self._launch([step_id], profile)

    def _stale_state(self, context: Context) -> ActionState:
        project_id = context.focus_entity("project")
        if not project_id or not self._deps.library.has(project_id):
            return ActionState(enabled=False, label="Compile Out of Date — no project is open")
        ready, waiting = self._stale(project_id)
        count = len(ready)
        verb = "Compile Out of Date" if count <= 1 else f"Compile {count} Out of Date"
        if not ready:
            reason = WAITING_REASON if waiting else NOTHING_STALE_REASON
            return ActionState(enabled=False, label=f"{verb} — {reason}")
        if refusal := self.compile_refusal(ready):
            # The count past the desk's limit refuses here, exactly as it does for a
            # selection of agent steps: the way past it is the setting, not a confirmation.
            named = refusal.partition(" — ")[2] or refusal
            return ActionState(enabled=False, label=f"{verb} — {named}")
        # What waits is on the label, not hidden: the next gesture takes it, and a person
        # who sees "2 waiting" knows why one press did not compile everything.
        waited = f" ({len(waiting)} waiting)" if waiting else ""
        return ActionState(label=f"{verb.replace('Out of', '&Out of')}…{waited}")

    def _compile_stale(self, context: Context) -> None:
        project_id = context.focus_entity("project")
        if project_id and self._deps.library.has(project_id):
            ready, _waiting = self._stale(project_id)
            self._launch(ready, "")

    def _stale(self, project_id: NodeId) -> tuple[list[StepId], list[StepId]]:
        """Which of this project's documents want compiling, and which must wait.

        **A collector whose own sub-collectors are out of date waits**, because a milestone
        reads its features' *compiled* documents: launching both at once would have the
        milestone read a document that is about to change, and ``docs status``'s advice says
        as much to an agent. So one gesture takes the frontier and the next takes what it
        unblocked — which is also why the verb says how many are waiting.
        """
        deps = self._deps
        library = deps.library
        project = library.project(project_id)
        due = {
            step.id
            for step in project.steps
            if self._collects(step.id)
            and state_of(deps.scopes, library, project, step.id) != "current"
            and self._sources(step.id)
        }
        ready: list[StepId] = []
        waiting: list[StepId] = []
        for step in project.steps:
            if step.id not in due:
                continue
            behind = {sub.id for sub in sub_collectors(deps.scopes, library, project, step.id)}
            (waiting if behind & due else ready).append(step.id)
        return ready, waiting

    def _launch(self, step_ids: Sequence[StepId], profile: str) -> None:
        """Hand one briefing per collector to the launcher, after asking about the documents
        this would replace.

        The question is asked **once for the whole gesture** and only about documents that
        already have text: the agent's write arrives from another process, so Ctrl+Z is not
        the safety net it is everywhere else in this application.
        """
        deps = self._deps
        launch = deps.compile_with_agent
        if launch is None or not step_ids or self.compile_refusal(step_ids):
            return
        written = [
            deps.library.step(step_id)
            for step_id in step_ids
            if deps.library.has(step_id) and read_compiled(deps.library.step(step_id))
        ]
        if written and not confirm(
            deps.parent,
            "Compile with Agent",
            self._replacing(written),
            verb="Compile",
        ):
            return
        requests = [(step_id, self._briefing(step_id)) for step_id in step_ids]
        for step_id, words in launch(requests, profile):
            self._remember(step_id, words)

    def _replacing(self, written: Sequence[Step]) -> str:
        """The question, naming what the agent will replace."""
        if len(written) == 1:
            return (
                f"The agent will replace the document on “{written[0].title or 'this step'}”"
                " when it reports back. There is no undo for that — it is written by another"
                " process, minutes from now. Compile anyway?"
            )
        names = "\n".join(f"• {step.title or 'Untitled step'}" for step in written)
        return (
            f"The agents will replace {len(written)} documents that already have text, and"
            " there is no undo for that — each is written by another process, minutes from"
            f" now:\n\n{names}\n\nCompile anyway?"
        )

    def _briefing(self, step_id: StepId) -> str:
        """What the agent is handed for one collector: this module's words, wrapped by the
        launcher's own header and preflight."""
        deps = self._deps
        step = deps.library.step(step_id)
        project = deps.library.project_of(step_id)
        kind = kind_of(deps.scopes, step)
        return compile_body(
            key=deps.step_key(step) or (step.title or "this step"),
            kind=kind.label.lower() if kind is not None else "",
            instructions=read(project),
            about=deps.instructions(step),
            sources=self._sources(step_id),
        )

    # -- who compiled it -----------------------------------------------------------------------

    def _remember(self, step_id: StepId, words: str) -> None:
        """Record which agent this desk launched on a collector.

        Per user and per machine, because that is what it is: the plan's stamp says *when* a
        document was compiled and from what, and only the window that launched the run knows
        *which* of the runs on that step was the compile. Reading the step's newest run back
        instead would credit a feature's document to whoever happened to be working on that
        feature.
        """
        if not words:
            return
        launches = dict(self._launches())
        launches[step_id] = words
        set_global(MODULE_ID, LAUNCHES_KEY, launches)

    def _launches(self) -> dict[str, str]:
        stored = get_global(MODULE_ID, LAUNCHES_KEY, {})
        if not isinstance(stored, dict):
            return {}
        return {str(key): str(value) for key, value in stored.items()}

    def _launched_by(self, step_id: StepId) -> str:
        return self._launches().get(step_id, "")

    def _fill_profiles(self, menu: QMenu) -> None:
        """Step ▸ Compile with Agent: one entry per profile, the default first and marked,
        each greyed with its own reason — Run Agent's child menu, over this verb.
        """
        deps = self._deps
        step_id = self._focused_id(deps.context.current())
        if not step_id or not self._collects(step_id):
            entry = menu.addAction(NOT_COLLECTOR_REASON)
            entry.setEnabled(False)
            return
        shared = self.compile_refusal([step_id])
        for index, (name, refusal) in enumerate(deps.compile_profiles([step_id])):
            reason = refusal or (shared if shared != refusal else "")
            titled = f"{name} (default)" if index == 0 else name
            entry = menu.addAction(f"{titled} — {reason}" if reason else titled)
            entry.setEnabled(not reason)
            entry.triggered.connect(
                lambda _checked=False, picked=name: self.compile(
                    self._focused_id(deps.context.current()), picked
                )
            )
        menu.addSeparator()
        append_action(menu, deps.actions, deps.context, "agent.profiles")

    # -- context ---------------------------------------------------------------------------

    def _focused_id(self, context: Context) -> StepId:
        step_id = context.focus_entity("step")
        return step_id if step_id and self._deps.library.has(step_id) else ""

    def _focused(self, context: Context) -> Step | None:
        step_id = self._focused_id(context)
        return self._deps.library.step(step_id) if step_id else None
