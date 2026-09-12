"""The docs aspects in the running application: the fragment tab, the Docs view, and Compile.

**Compile is the first consumer of ``framework/llm_service.py``.** Three rules the service's
docstring lays down and this module obeys:

- ``complete()`` is blocking network I/O, so it runs inside a ``TaskRunner`` body and the
  result comes back on this module's own Qt signal. The runner has no result seam of its
  own, which is why the signal is here rather than there.
- an AI-gated control is **disabled, never hidden**, and carries ``status().message`` as its
  reason. The service re-reads its provider on every call, so the view re-asks on
  ``config_changed`` and configuring one in Settings ungreys the button where it stands.
- nothing logs the call: every one is already in the service's ring buffer, which is what
  *Debug ▸ LLM Calls* reads.

**Any collector compiles.** There is no step kind for it: a feature and a milestone already
are the collectors the graph defines, so Compile is a verb on them and nothing has to be
created. What one reads is :mod:`dplanner.modules.docs.collect`, never stored.

The compiled document lands **on the undo stack**, unlike ``github/refresh.py``'s background
sync: a person pressed a button, and undoing has to put back what was there.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QTreeWidgetItem, QWidget

from dplanner.domain.commands import (
    CompositeCommand,
    EditTextCommand,
    SetModuleDataCommand,
)
from dplanner.domain.model import Library, NodeId, Step, StepId, TextEdit
from dplanner.domain.scope import ScopeKind, kind_of
from dplanner.domain.store import FilesFor
from dplanner.framework.action_registry import (
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.activity import follow_entity_tabs
from dplanner.framework.aspect_toggle import aspect_toggle
from dplanner.framework.context import Context, ContextService
from dplanner.framework.debounce import DebounceService
from dplanner.framework.index_panel import IndexSegment, IndexSegmentRegistry
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.llm import LLMMessage, LLMTimeoutError
from dplanner.framework.llm_service import LLMService
from dplanner.framework.mime_files import Payload
from dplanner.framework.project_list_segment import ChildRow, ProjectListSegment
from dplanner.framework.tabs import TabHost
from dplanner.framework.task_runner import TaskRunner, TaskTimeoutError
from dplanner.framework.tasks import TaskService
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
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
    write_stamp,
    write_state,
)
from dplanner.modules.docs.collect import (
    SYSTEM_PROMPT,
    Source,
    as_markdown,
    digest,
    sources_for,
    state_of,
    user_prompt,
)
from dplanner.modules.docs.section import (
    CompileLink,
    DocsSection,
    ProjectDocsCard,
    Standing,
)
from dplanner.theme.icons import read_icon

COMPILE_ACTION = "docs.compile"
BUSY_REASON = "Another job is running — wait for it to finish"
NOTHING_REASON = "Nothing to compile — no step behind this one carries documentation"
NOT_COLLECTOR_REASON = "Compile Docs — only a feature, milestone or check compiles one"
OPEN_STEP_ACTION = "docs.open_step"
NO_DOCS_REASON = "Show Docs — this step carries no documentation and gathers none"


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
    llm: LLMService
    tasks: TaskService
    # Every collector this build knows — read, never added to: what a feature or a milestone
    # gathers is the same walk the Tests surfaces make.
    scopes: tuple[ScopeKind, ...] = ()
    # Where a step's documentation images live — the store's `files`, so this module
    # never names a store.
    files: FilesFor | None = None
    # The project panel's card stack. None in a build without a project panel.
    cards: InspectorSectionRegistry | None = None
    # A collector's own note, used as the brief for its document. Which prose briefs a
    # compile is a cross-module fact, so the root decides it.
    instructions: Callable[[Step], str] = lambda _step: ""
    parent: QWidget | None = None  # The compiler's QObject parent and confirm()'s.
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


class _Compiler(QObject):
    """The worker thread's way back to the GUI thread, and the runner that owns it.

    A separate QObject rather than a QObject module, and **parented to the window**: a
    parentless QObject holding a self-connected signal is a reference cycle that Python
    frees whenever the collector next runs, which may be in the middle of somebody else's
    event loop. Parented, it dies with the build like everything else ``discard_build()``
    reaches, and every other module in this application stays a plain object.
    """

    # (step id, the compiled markdown, provider label, model). Queued: emitted off-thread.
    compiled = Signal(str, str, str, str)
    # What an open Docs view re-reads: a compile starting or finishing, and a provider being
    # configured in Settings while the view is open. **A Qt signal, not a core one**, because
    # its subscribers are QWidgets: Qt drops the connection when the widget is destroyed,
    # where a plain Python signal would hold the widget's bound method and hand its wrapper
    # to the garbage collector long after Qt had freed the C++ object underneath it.
    changed = Signal()

    def __init__(self, tasks: TaskService, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.runner = TaskRunner(tasks, parent=self)


class DocsModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: DocsDeps) -> None:
        self._deps = deps
        self._compiler = _Compiler(deps.tasks, deps.parent)
        self._runner = self._compiler.runner
        self._compiler.compiled.connect(self._on_compiled)
        self._runner.busy_changed.connect(lambda _busy: self._compiler.changed.emit())
        deps.llm.config_changed.connect(self._compiler.changed.emit)

    # -- registration ----------------------------------------------------------------------

    def register(self) -> None:
        deps = self._deps
        deps.sections.register(
            InspectorSection(
                id=f"{MODULE_ID}.tab",
                label=SPEC.label,
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
                    label="Docs",
                    order=30,
                    factory=lambda: ProjectDocsCard(
                        deps.library, deps.undo, deps.files, deps.pick_assets
                    ),
                    icon=read_icon,
                    hint="Prepended to every document compiled in this project.",
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
        """The compile verb in the vocabulary a view uses, so no surface re-derives it."""
        return CompileLink(
            collects=self._collects,
            state=self.compile_state,
            standing=self.standing_of,
            run=self.compile_step,
            changed=self._compiler.changed,
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
                tip="Give this step prose saying what it adds to the documentation",
            ),
            ActionSpec(
                id=COMPILE_ACTION,
                label="Compile Docs",
                menu="Step",
                group="docs",
                order=10,
                tip="Write this collector's document from the documentation it gathers",
                state=self._action_state,
                run=lambda context: self.compile_step(self._focused_id(context)),
            ),
            ActionSpec(
                id=OPEN_STEP_ACTION,
                label="Show &Docs",
                menu="Step",
                group="open",
                order=80,
                tip="Open the Docs tab on this step's document, or the one gathering its note",
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
        runnable, reason = self.compile_state(step_id)
        return ActionState() if runnable else ActionState(enabled=False, label=reason)

    def compile_state(self, step_id: StepId) -> tuple[bool, str]:
        """Whether Compile can run, and the sentence a greyed control shows when it cannot.

        One function, two presenters — the menu entry's label and the view's banner — so the
        two can never disagree about why the button is off. Note that *up to date* is not a
        refusal: recompiling on purpose is legitimate.
        """
        if self._runner.is_busy():
            return False, BUSY_REASON
        status = self._deps.llm.status()
        if not status.configured:
            return False, status.message
        if not self._sources(step_id):
            return False, NOTHING_REASON
        return True, ""

    def standing_of(self, step_id: StepId) -> Standing:
        """Where this collector's document stands, what it would read, and what it read."""
        library = self._deps.library
        if not library.has(step_id):
            return Standing("never", 0, {})
        project = library.project_of(step_id)
        return Standing(
            state_of(self._deps.scopes, library, project, step_id),
            len(self._sources(step_id)),
            read_stamp(library.step(step_id)),
        )

    def _sources(self, step_id: StepId) -> list[Source]:
        library = self._deps.library
        if not library.has(step_id):
            return []
        project = library.project_of(step_id)
        return list(sources_for(self._deps.scopes, library, project, step_id))

    def compile_step(self, step_id: StepId) -> None:
        deps = self._deps
        if not step_id or not deps.library.has(step_id) or not self._collects(step_id):
            return
        step = deps.library.step(step_id)
        runnable, _reason = self.compile_state(step_id)
        if not runnable:
            return
        if read_compiled(step) and not confirm(
            deps.parent,
            "Compile Docs",
            f"Replace the document on {step.title or 'this step'!r}? Any edits are not kept.",
        ):
            return

        project = deps.library.project_of(step_id)
        # Everything the worker needs is read here, on the GUI thread, and travels as plain
        # strings: a body that reached into the model would be reading from a thread that
        # may not.
        sources = sources_for(deps.scopes, deps.library, project, step_id)
        prompt = user_prompt(
            standing=read(project),
            instructions=deps.instructions(step),
            sources=as_markdown(sources),
        )
        messages = [
            LLMMessage(role="system", content=SYSTEM_PROMPT),
            LLMMessage(role="user", content=prompt),
        ]

        def body() -> None:
            if self._runner.cancel_requested():
                return
            try:
                result = deps.llm.complete(messages)
            except LLMTimeoutError as error:
                # A distinct terminal state in the task centre, not a generic failure.
                raise TaskTimeoutError(str(error)) from error
            if self._runner.cancel_requested():
                # A blocking SDK call cannot be torn down, so dropping the answer is the
                # honest cancellation — the runner's docstring says as much.
                return
            status = deps.llm.status()
            self._compiler.compiled.emit(
                step_id, result.text, status.provider_label or "", status.model or ""
            )

        self._runner.run(
            "Compiling documentation",
            body,
            key=COMPILE_ACTION,
            cancellable=True,
            cancel_prompt="Stop compiling? The answer will be discarded.",
            keep_finished=True,
        )
        self._compiler.changed.emit()

    def _on_compiled(self, step_id: str, text: str, provider: str, model: str) -> None:
        """Back on the GUI thread: land the document and its stamp as one undo entry."""
        library = self._deps.library
        # A delivery for a step that has gone, or has stopped collecting while the model was
        # thinking, is dropped — github/section.py's guard, for the same reason.
        if not library.has(step_id) or not self._collects(step_id):
            return
        step = library.step(step_id)
        project = library.project_of(step_id)
        sources = sources_for(self._deps.scopes, library, project, step_id)
        body = text.strip() + "\n" if text.strip() else ""
        self._deps.undo.push(
            CompositeCommand(
                "Compile Docs",
                [
                    EditTextCommand(
                        TextEdit(step.id, COMPILED_ID, 0, read_compiled(step), body),
                        label="Compile Docs",
                    ),
                    SetModuleDataCommand(
                        step.id,
                        COMPILED_ID,
                        write_stamp(digest(sources), time.time(), provider, model, len(sources)),
                        label="Compile Docs",
                    ),
                ],
            )
        )
        self._compiler.changed.emit()

    # -- context ---------------------------------------------------------------------------

    def _focused_id(self, context: Context) -> StepId:
        step_id = context.focus_entity("step")
        return step_id if step_id and self._deps.library.has(step_id) else ""

    def _focused(self, context: Context) -> Step | None:
        step_id = self._focused_id(context)
        return self._deps.library.step(step_id) if step_id else None
