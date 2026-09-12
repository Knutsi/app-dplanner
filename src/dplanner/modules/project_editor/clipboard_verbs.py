"""Cut, Copy, Paste and Duplicate: the Edit menu's verbs on the step graph.

These are ordinary ``ActionSpec``s registered by the graph editor, not a dispatching layer
the "current" surface plugs into. The context already says what is selected and whether a
canvas is in front of the user, the state gate greys a verb that cannot run, and a greyed
menu-bar action's shortcut does not fire — so one registrant gets the "takes over when
active" behaviour for free. ``ARCHITECTURE.md``'s *Edit verbs belong to the surface whose
things they act on* says when that stops being enough.

**What they act on is what Delete acts on** —
:func:`~dplanner.framework.step_selection.chosen_steps`, so Cut and Copy work wherever
Delete does, a table's right-click included. Only Paste needs a current canvas:
it is the target. Its state never reads the clipboard; :class:`ClipboardWatch` counts what
the clipboard holds when the clipboard changes, and re-emits the context so the label
("Paste 3 Steps") follows — the app shell's undo-label idiom.

**Duplicate is a paste that never touches the clipboard.** A clip of the chosen steps pasted
straight back into their project, one row below, so what the user had copied stays copied.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QByteArray, QMimeData, QObject
from PySide6.QtGui import QGuiApplication, QKeySequence

from dplanner.domain.commands import remove_steps_command
from dplanner.domain.model import Library, NodeId, StepId
from dplanner.domain.store import FilesFor
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.context import Context, ContextService
from dplanner.framework.step_selection import chosen_steps
from dplanner.framework.undo import UndoService
from dplanner.modules.project_editor.clipboard import (
    MIME_TYPE,
    PastePolicy,
    StepClip,
    clip,
    from_json,
    paste,
    titles,
    to_json,
    write_files,
)


def held_clips() -> list[StepClip]:
    """What the clipboard holds of ours right now — empty for anything else."""
    data = QGuiApplication.clipboard().mimeData()
    if data is None or not data.hasFormat(MIME_TYPE):
        return []
    return from_json(bytes(data.data(MIME_TYPE).data()))


class ClipboardWatch(QObject):
    """How many steps the clipboard holds, kept current so no action state has to ask.

    A child of the window on purpose: ``QClipboard`` is process-global and outlives every
    build, so a slot on a bare object would keep a discarded build reachable — and answer a
    ``dataChanged`` after its actions were gone. Parenting to the window is what disconnects
    it when the build is discarded.
    """

    def __init__(self, parent: QObject, context: ContextService) -> None:
        super().__init__(parent)
        self._context = context
        self._count = len(held_clips())
        QGuiApplication.clipboard().dataChanged.connect(self._on_changed)

    def count(self) -> int:
        return self._count

    def _on_changed(self) -> None:
        self._count = len(held_clips())
        self._context.refresh()


@dataclass(frozen=True)
class ClipboardVerbs:
    library: Library
    undo: UndoService[Library]
    files: FilesFor
    # Which modules keep files beside a step — the asset catalog's sources, so a copy
    # carries every attachment the Assets tab would list.
    file_modules: tuple[str, ...]
    # What the clipboard holds, as ClipboardWatch counts it. A callable so the verbs are
    # a pure function of the context plus this one fact, and a test can hand in a lambda.
    held: Callable[[], int]
    # Paste's target: the project the current tab shows.
    current_project: Callable[[], NodeId | None]
    # Where a paste lands — the canvas's last click, centred, the same point New uses.
    new_position: Callable[[], tuple[float, float] | None]
    # The arrivals: select them and step the remembered point on, as New does.
    placed: Callable[[list[StepId]], None]
    policies: tuple[PastePolicy, ...] = ()

    def register_into(self, actions: ActionRegistry) -> None:
        for spec in self._specs():
            actions.register(spec)

    def _specs(self) -> list[ActionSpec]:
        return [
            ActionSpec(
                id="steps.cut",
                label="Cu&t Step",
                menu="Edit",
                group="clipboard",
                order=10,
                shortcut=QKeySequence.StandardKey.Cut,
                tip="Copy these steps to the clipboard and remove them",
                state=self._on_chosen("Cu&t"),
                run=self._cut,
            ),
            ActionSpec(
                id="steps.copy",
                label="&Copy Step",
                menu="Edit",
                group="clipboard",
                order=20,
                shortcut=QKeySequence.StandardKey.Copy,
                tip="Copy these steps — aspects, prose and attachments — to the clipboard",
                state=self._on_chosen("&Copy"),
                run=self._copy,
            ),
            ActionSpec(
                id="steps.paste",
                label="&Paste",
                menu="Edit",
                group="clipboard",
                order=30,
                shortcut=QKeySequence.StandardKey.Paste,
                tip="Add copies of the clipboard's steps to the project in this tab",
                state=self._can_paste,
                run=self._paste,
            ),
            ActionSpec(
                id="steps.duplicate",
                label="D&uplicate Step",
                menu="Edit",
                group="clipboard",
                order=40,
                # Not StandardKey.Delete's Ctrl+D: that binding also means Del, which is
                # every list's own key. A literal, so Duplicate is Ctrl+D everywhere.
                shortcut="Ctrl+D",
                tip="Add a copy of these steps one row below, linked among themselves only",
                state=self._on_chosen("D&uplicate"),
                run=self._duplicate,
            ),
        ]

    # -- state ---------------------------------------------------------------------------------

    def _on_chosen(self, word: str) -> Callable[[Context], ActionState]:
        def state(context: Context) -> ActionState:
            chosen = chosen_steps(context, self.library)
            if not chosen:
                return DISABLED
            if len(chosen) == 1:
                return ENABLED
            return ActionState(label=f"{word} {len(chosen)} Steps")

        return state

    def _can_paste(self, _context: Context) -> ActionState:
        if self.current_project() is None:
            return DISABLED
        count = self.held()
        if count == 0:
            return DISABLED
        return ENABLED if count == 1 else ActionState(label=f"&Paste {count} Steps")

    # -- run -----------------------------------------------------------------------------------

    def _clips_of(self, step_ids: list[StepId]) -> list[StepClip]:
        return clip(self.library, self.files, self.file_modules, step_ids)

    def _copy(self, context: Context) -> None:
        chosen = chosen_steps(context, self.library)
        if not chosen:
            return
        clips = self._clips_of(chosen)
        data = QMimeData()
        data.setData(MIME_TYPE, QByteArray(to_json(clips)))
        data.setText(titles(clips))
        QGuiApplication.clipboard().setMimeData(data)

    def _cut(self, context: Context) -> None:
        chosen = chosen_steps(context, self.library)
        if not chosen:
            return
        self._copy(context)
        self.undo.push(remove_steps_command(self.library, chosen, "Cut"))
        self.undo.break_coalescing()

    def _paste(self, _context: Context) -> None:
        project_id = self.current_project()
        clips = held_clips()
        if project_id is None or not clips:
            return
        self._arrive(project_id, clips, anchor=self.new_position(), verb="Paste")

    def _duplicate(self, context: Context) -> None:
        chosen = chosen_steps(context, self.library)
        if not chosen:
            return
        project = self.library.project_of(chosen[0])
        within = [s for s in chosen if self.library.project_of(s).id == project.id]
        self._arrive(project.id, self._clips_of(within), anchor=None, verb="Duplicate")

    def _arrive(
        self,
        project_id: NodeId,
        clips: list[StepClip],
        *,
        anchor: tuple[float, float] | None,
        verb: str,
    ) -> None:
        command, clones = paste(
            self.library, project_id, clips, anchor=anchor, policies=self.policies, verb=verb
        )
        self.undo.push(command)
        # Files before the selection: the panel that opens on the arrivals reads them.
        write_files(self.files, list(zip(clones, clips, strict=True)))
        self.undo.break_coalescing()
        self.placed([clone.id for clone in clones])
