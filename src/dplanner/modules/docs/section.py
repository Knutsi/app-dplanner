"""The prose editors and the banner every surface shows over a collector's document.

All three editors are :class:`~dplanner.framework.prose_section.ProseSection` — the editor,
its image gallery, paste-and-drop, markdown highlighting and the expand-to-modal button all
come from it. Nothing here hand-rolls an Attach button.

**The banner is one widget with three sentences**, shared by the step panel's Docs tab and
the Docs view, so "this needs recompiling" is worded once and greyed for one reason. It is
``#InspectorNote`` over a primary button, which is DESIGN.md's sanctioned pairing: a remark
that changes with the data, above the one action the surface exists for.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from PySide6.QtCore import SignalInstance
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from dplanner.domain.fields import ModuleTextField
from dplanner.domain.model import Library, StepId
from dplanner.domain.store import FilesFor
from dplanner.framework.mime_files import Payload
from dplanner.framework.prose_section import FIELD_GAP, ProseSection
from dplanner.framework.undo import UndoService
from dplanner.modules.docs.aspect import COMPILED_ID, MODULE_ID
from dplanner.modules.docs.collect import CompiledState

STEP_PLACEHOLDER = (
    "What this step adds to the product's documentation, for someone using it."
    " Markdown; paste or drop an image straight in."
)
COMPILED_PLACEHOLDER = (
    "The document compiled from everything this collector gathers. Edit it freely —"
    " compiling again replaces it."
)
PROJECT_PLACEHOLDER = (
    "How this project's documentation should read — voice, audience, anything every"
    " compiled document should follow."
)
# A card grows down the stack, not with its content; six lines is what the standing agent
# instruction's card settled on and this sits beside it.
CARD_LINES = 6


@dataclass(frozen=True)
class Standing:
    """Where one collector's document stands: the state, what it would read, what it read."""

    state: CompiledState
    sources: int
    stamp: dict[str, Any]


@dataclass(frozen=True)
class CompileLink:
    """What a view needs from the compile verb, in the view's own vocabulary.

    ``state`` answers the two questions a disabled button owes an explanation for — can this
    run, and if not, why — so every surface renders the action's own reason rather than
    inventing preconditions that could disagree with it. ``changed`` is a **Qt** signal, so
    the connection dies with the widget; a plain Python signal would keep a section's bound
    method — and so the section — alive past the build that made it, leaving the collector to
    free a QWidget Qt had already destroyed.
    """

    collects: Callable[[StepId], bool]
    state: Callable[[StepId], tuple[bool, str]]
    standing: Callable[[StepId], Standing]
    run: Callable[[StepId], None]
    changed: SignalInstance


class CompileBanner(QWidget):
    """Where a collector's document stands, and the button that moves it on."""

    def __init__(self, link: CompileLink, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._link = link
        self._target: StepId = ""

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(FIELD_GAP)

        self.note = QLabel(self)
        self.note.setObjectName("InspectorNote")
        self.note.setWordWrap(True)
        column.addWidget(self.note)

        # One primary action per surface, and here it is the reason to be looking.
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.button = QPushButton("Compile", self)
        self.button.setObjectName("PrimaryButton")
        self.button.clicked.connect(self._on_clicked)
        row.addWidget(self.button)
        row.addStretch(1)
        column.addLayout(row)

        link.changed.connect(self.refresh)

    def show_target(self, step_id: StepId) -> None:
        self._target = step_id
        self.refresh()

    def refresh(self) -> None:
        if not self._target:
            return
        standing = self._link.standing(self._target)
        runnable, reason = self._link.state(self._target)
        self.button.setText("Compile" if standing.state == "never" else "Recompile")
        self.button.setEnabled(runnable)
        self.button.setToolTip(reason)
        # Where it stands, and — when the button is off — what is in the way. A reason only
        # in a tooltip is a reason most readers never find.
        self.note.setText(" ".join(part for part in (state_line(standing), reason) if part))

    def _on_clicked(self) -> None:
        if self._target:
            self._link.run(self._target)


class DocsSection(ProseSection):
    """One step's fragment — and, on a collector, the banner for its compiled document."""

    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        files: FilesFor | None = None,
        compile_link: CompileLink | None = None,
        pick_assets: Callable[[str], list[Payload]] | None = None,
    ) -> None:
        def field_for(target_id: str) -> ModuleTextField | None:
            if not library.has(target_id):
                return None
            return ModuleTextField(library, target_id, MODULE_ID)

        super().__init__(
            field_for,
            undo,
            STEP_PLACEHOLDER,
            expand_title="Docs",
            attach_title="Attach to Docs",
        )
        self._library = library
        self._files = files
        self._pick_assets = pick_assets
        self._link = compile_link
        self._target_id: str | None = None

        self.banner: CompileBanner | None = None
        if compile_link is not None:
            self.banner = CompileBanner(compile_link, self)
            layout = self.layout()
            if isinstance(layout, QVBoxLayout):
                layout.insertWidget(0, self.banner)
                layout.insertSpacing(1, FIELD_GAP)
            self.banner.hide()

    def show_target(self, target_id: str | None) -> None:
        super().show_target(target_id)
        self._target_id = target_id
        files = self._files
        pick = self._pick_assets
        if target_id is not None and files is not None and self.isEnabled():
            self.set_area(lambda: files(target_id, MODULE_ID))
            if pick is not None:
                self.set_picker(lambda: pick(target_id))
        self._refresh_banner()

    def _refresh_banner(self) -> None:
        """A plain step has no document to be out of date; the banner is a collector's."""
        banner, target, link = self.banner, self._target_id, self._link
        if banner is None or link is None:
            return
        if target is None or not self._library.has(target) or not link.collects(target):
            banner.hide()
            return
        banner.show_target(target)
        banner.show()


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
            expand_title="Compiled Docs",
        )

    def show_target(self, target_id: str | None) -> None:
        super().show_target(target_id)


class ProjectDocsCard(ProseSection):
    """The project panel's Docs card: the standing style every compile is given.

    The same seam and the same reasoning as the standing agent instruction — a style written
    once beats the same three sentences repeated in three collectors. A project does no work,
    so its ``docs.md`` collides with no documentation of its own.
    """

    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        files: FilesFor | None,
        pick_assets: Callable[[str], list[Payload]] | None = None,
    ) -> None:
        def field_for(target_id: str) -> ModuleTextField | None:
            if not library.has(target_id):
                return None
            return ModuleTextField(library, target_id, MODULE_ID)

        super().__init__(
            field_for,
            undo,
            PROJECT_PLACEHOLDER,
            expand_title="Documentation Style",
            attach_title="Attach to Documentation Style",
        )
        self._files = files
        self._pick_assets = pick_assets
        self.edit.setFixedHeight(self.edit.fontMetrics().lineSpacing() * CARD_LINES + 16)
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
    """The banner's sentence, one per state — what a run recorded, never a definition."""
    sources = f"{standing.sources} source{'' if standing.sources == 1 else 's'}"
    if standing.state == "never":
        return f"Not compiled yet — {sources} to read."
    when = ago(float(standing.stamp.get("at", 0.0) or 0.0))
    if standing.state == "stale":
        return f"Out of date — compiled {when}, and what it reads has changed since."
    model = str(standing.stamp.get("model") or "")
    read = int(float(standing.stamp.get("sources", 0.0) or 0.0))
    tail = f" · {model}" if model else ""
    return f"Compiled {when} from {read} source{'' if read == 1 else 's'}{tail}."


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
