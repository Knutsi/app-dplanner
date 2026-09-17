"""The prose editors, and the line every surface shows over a collector's document.

All three editors are :class:`~dplanner.framework.prose_section.ProseSection` — the editor,
its image gallery, paste-and-drop, markdown highlighting and the expand-to-modal button all
come from it. Nothing here hand-rolls an Attach button.

**Where a document stands is one `StatusLine`**, shared by the step panel's Fragment tab and
the Documentation view, so it is worded once and toned once. It carries no button: compiling
launches an agent, and that verb's seats are the Step menu, the palette and the activity's
strip — a surface that only *says* where a document stands cannot disagree with the verb
about whether it can run.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from PySide6.QtWidgets import QVBoxLayout, QWidget

from dplanner.domain.fields import ModuleTextField
from dplanner.domain.model import Library, StepId
from dplanner.domain.store import FilesFor
from dplanner.framework.activity import follow_target
from dplanner.framework.dictation import DictationService
from dplanner.framework.mime_files import Payload
from dplanner.framework.prose_section import FIELD_GAP, ProseSection
from dplanner.framework.signalling import StatusLine
from dplanner.framework.undo import UndoService
from dplanner.modules.docs.aspect import COMPILED_ID, MODULE_ID
from dplanner.modules.docs.collect import CompiledState

STEP_PLACEHOLDER = (
    "What this step adds to the product's documentation, for someone using it. A collector"
    " compiles these. Markdown; paste or drop an image straight in."
)
COMPILED_PLACEHOLDER = (
    "The documentation compiled from every fragment this collector gathers. Edit it freely —"
    " the next compile replaces it."
)
PROJECT_PLACEHOLDER = (
    "How this project's documentation should read — voice, audience, anything every"
    " document compiled here should follow. It opens every compile briefing."
)
# A card grows down the stack, not with its content; six lines is what the standing agent
# instruction's card settled on and this sits beside it.
CARD_LINES = 6


@dataclass(frozen=True)
class Standing:
    """Where one collector's document stands: the state, what it would read, what it read,
    who this desk last launched on it, and whether an agent is working there now.

    ``by`` is the module's own record of the launch it made (*"Claude Code · session 3f2a1c"*)
    rather than anything in the plan: the stamp says when a document was compiled and from
    what, and who compiled it is a fact about one desk's runs.
    """

    state: CompiledState
    sources: int
    stamp: dict[str, Any]
    by: str = ""
    working: bool = False


@dataclass(frozen=True)
class CompileLink:
    """What a view needs in order to say where a collector's document stands.

    No verb: compiling is an ``ActionSpec``, so a view runs it through the registry and
    renders the registry's own state. A link that carried its own ``run`` and ``state`` was
    how the button came to exist in three places.
    """

    collects: Callable[[StepId], bool]
    standing: Callable[[StepId], Standing]
    # What a strip renders: the compile verbs' action ids, in the order they sit. Ids rather
    # than callables, because a presenter runs a verb through the registry and renders the
    # registry's own state — a second path is how the button came to exist in three places.
    verbs: tuple[str, ...] = ()
    # (the verb that carries an arrow, the data child menu the arrow drops): the launch
    # profiles, which are the Step menu's own child menu and never a copy of its list.
    profile_menu: tuple[str, str] = ("", "")


class DocumentStanding(StatusLine):
    """Where a collector's document stands, in one toned line.

    A ``StatusLine`` and nothing more — DESIGN.md's *Signalling*: the glyph carries the mood,
    the words carry the fact. Four states in the four tones and no fifth: busy while an agent
    is working on the step, ok when the document is up to date, and the line's own ink for
    *out of date* and *not compiled yet*, which are facts rather than faults.
    """

    def __init__(self, link: CompileLink, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._link = link
        self._target: StepId = ""
        self.setWordWrap(True)

    def show_target(self, step_id: StepId) -> None:
        self._target = step_id
        self.refresh()

    def refresh(self) -> None:
        if not self._target:
            self.clear()
            return
        standing = self._link.standing(self._target)
        if standing.working:
            # Not "compiling this now": the window cannot tell one run on a step from
            # another, and what the reader needs to know is that somebody is already here.
            self.say(f"An agent is working on this step. {state_line(standing)}", "busy")
            return
        self.say(state_line(standing), "ok" if standing.state == "current" else "info")


class DocsSection(ProseSection):
    """One step's documentation fragment — and, on a collector, where its document stands."""

    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        files: FilesFor | None = None,
        compile_link: CompileLink | None = None,
        pick_assets: Callable[[str], list[Payload]] | None = None,
        dictation: DictationService | None = None,
    ) -> None:
        def field_for(target_id: str) -> ModuleTextField | None:
            if not library.has(target_id):
                return None
            return ModuleTextField(library, target_id, MODULE_ID)

        super().__init__(
            field_for,
            undo,
            STEP_PLACEHOLDER,
            expand_title="Documentation Fragment",
            attach_title="Attach to Documentation Fragment",
            dictation=dictation,
        )
        self._library = library
        self._files = files
        self._pick_assets = pick_assets
        self._link = compile_link
        self._target_id: str | None = None

        self.standing: DocumentStanding | None = None
        self._unsubscribes: list[Callable[[], None]] = []
        if compile_link is not None:
            self.standing = DocumentStanding(compile_link, self)
            layout = self.layout()
            if isinstance(layout, QVBoxLayout):
                layout.insertWidget(0, self.standing)
                layout.insertSpacing(1, FIELD_GAP)
            self.standing.hide()
            # Where a document stands changes with a fragment nobody here is editing — a
            # relink, another writer's `compiled set`, an agent's run ending. The panel
            # re-asks `shown_for` on a model change but does not re-show a section, so the
            # line follows the model itself, as the Agent tab's derived part does.
            self._unsubscribes.append(
                follow_target(library, lambda: self._target_id, self._refresh_standing)
            )

    def show_target(self, target_id: str | None) -> None:
        super().show_target(target_id)
        self._target_id = target_id
        files = self._files
        pick = self._pick_assets
        if target_id is not None and files is not None and self.isEnabled():
            self.set_area(lambda: files(target_id, MODULE_ID))
            if pick is not None:
                self.set_picker(lambda: pick(target_id))
        self._refresh_standing()

    def dispose(self) -> None:
        """A core signal has no widget lifetime to ride on, so the subscription is dropped
        here: a section outliving its build would hand the collector a wrapper whose C++ side
        Qt had already freed."""
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes = []
        super().dispose()

    def _refresh_standing(self) -> None:
        """A plain step has no document to be out of date; the line is a collector's."""
        line, target, link = self.standing, self._target_id, self._link
        if line is None or link is None:
            return
        if target is None or not self._library.has(target) or not link.collects(target):
            line.hide()
            return
        line.show_target(target)
        line.show()


class CompiledSection(ProseSection):
    """A collector's compiled document, edited in place.

    Editable on purpose: a model's output always wants a tweak, and the digest is over what
    the compile *read*, so a hand edit never makes the document read as out of date.
    """

    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        margin: int = 0,
        dictation: DictationService | None = None,
    ) -> None:
        def field_for(target_id: str) -> ModuleTextField | None:
            if not library.has(target_id):
                return None
            return ModuleTextField(library, target_id, COMPILED_ID)

        super().__init__(
            field_for,
            undo,
            COMPILED_PLACEHOLDER,
            margin=margin,
            expand_title="Documentation",
            dictation=dictation,
        )


class InstructionsCard(ProseSection):
    """The project's compilation instructions: what every document compiled here follows.

    The same seam and the same reasoning as the standing agent instruction — written once
    beats the same three sentences repeated in three collectors, and it opens every compile
    briefing. A project does no work, so its ``docs.md`` collides with no fragment of its own.
    """

    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        files: FilesFor | None,
        pick_assets: Callable[[str], list[Payload]] | None = None,
        dictation: DictationService | None = None,
    ) -> None:
        def field_for(target_id: str) -> ModuleTextField | None:
            if not library.has(target_id):
                return None
            return ModuleTextField(library, target_id, MODULE_ID)

        super().__init__(
            field_for,
            undo,
            PROJECT_PLACEHOLDER,
            expand_title="Compilation Instructions",
            attach_title="Attach to Compilation Instructions",
            dictation=dictation,
        )
        self._files = files
        self._pick_assets = pick_assets
        # At least CARD_LINES; the page the card is on gives it more when it has more.
        self.edit.setMinimumHeight(self.edit.fontMetrics().lineSpacing() * CARD_LINES + 16)
        layout = self.layout()
        if layout is not None:
            layout.setContentsMargins(0, 0, 0, 0)  # The hosting card carries the margins.

    def show_target(self, target_id: str | None) -> None:
        super().show_target(target_id)
        files = self._files
        pick = self._pick_assets
        if target_id is not None and files is not None and self.isEnabled():
            self.set_area(lambda: files(target_id, MODULE_ID))
            if pick is not None:
                self.set_picker(lambda: pick(target_id))


def state_line(standing: Standing) -> str:
    """The line's sentence, one per state — what a compile recorded, never a definition."""
    fragments = f"{standing.sources} fragment{'' if standing.sources == 1 else 's'}"
    if standing.state == "never":
        return f"Not compiled yet — {fragments} to read."
    when = ago(float(standing.stamp.get("at", 0.0) or 0.0))
    by = f" by {standing.by}" if standing.by else ""
    if standing.state == "stale":
        return f"Out of date — compiled {when}{by}, and what it reads has changed since."
    read = int(float(standing.stamp.get("sources", 0.0) or 0.0))
    return f"Up to date — compiled {when}{by} from {read} fragment{'' if read == 1 else 's'}."


def ago(at: float) -> str:
    if at <= 0:
        return "at some point"
    seconds = max(0.0, datetime.now().timestamp() - at)
    minutes = int(seconds // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} minute{'' if minutes == 1 else 's'} ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'' if hours == 1 else 's'} ago"
    days = hours // 24
    return f"{days} day{'' if days == 1 else 's'} ago"
