"""The Agent tab: the whole briefing, part by part, with the trigger under it.

Four collapsible parts, in the order the prompt is assembled: the project's standing
instruction (editable here and in the project panel's Agent card — one field, one undo
stack), the step's own facts — description, requirements, figures — rendered by the same
``prompt.section_lines`` the prompt is built with and showing each section's files as a
gallery of real thumbnails, what earlier steps handed forward (read-only, via
``part_lines`` — the same no-drift rule), and this step's own instruction. Expanding
everything *is* the whole prompt in reading order; Preview Prompt shows the exact
assembled text.

The buttons are not second implementations of anything — each evaluates and runs the same
``ActionSpec`` the menus do, so the tab and the menu can never disagree about when a run
or a preview is possible, and the state's reason label becomes the disabled tooltip.
"""

from collections.abc import Callable, Sequence

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.core.signals import Signal
from dplanner.domain.fields import ModuleTextField
from dplanner.domain.model import NodeId, Product, StepId
from dplanner.domain.store import ModuleFileArea
from dplanner.framework.action_registry import ActionState
from dplanner.framework.asset_gallery import AssetGallery
from dplanner.framework.text_binding import TextBinding
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import make_text_well, space_lines
from dplanner.modules.step_agent_instruction.aspect import MODULE_ID
from dplanner.modules.step_agent_instruction.prompt import (
    PromptPart,
    part_lines,
    section_lines,
)
from dplanner.theme.icons import ICON_SIZE, graph_icon, leaf_icon, project_icon, read_icon

PANEL_MARGIN = 16
BLOCK_GAP = 12  # DESIGN.md: between blocks; FIELD_GAP is within one.
FIELD_GAP = 6
LEAD_WIDTH = 22  # The chevron column, fixed so part titles align (the task-centre idiom).

PROJECT_PLACEHOLDER = "Standing instructions for every step in this project."


class PartRow(QWidget):
    """One collapsible part: chevron, glyph, caption and summary over a body."""

    def __init__(
        self,
        title: str,
        icon: Callable[[str], QIcon],
        body: QWidget,
        expanded: bool = False,
    ) -> None:
        super().__init__()
        self._icon = icon
        self._expanded = False  # Own state: isVisible() is false while the tab is offscreen.
        self.toggled: Signal[bool] = Signal()

        self.chevron = QToolButton(self)
        self.chevron.setAutoRaise(True)
        self.chevron.setFixedWidth(LEAD_WIDTH)
        self.chevron.clicked.connect(lambda: self.set_expanded(not self.expanded()))

        self.glyph = QLabel(self)
        self.glyph.setFixedSize(ICON_SIZE, ICON_SIZE)

        caption = QLabel(title, self)
        caption.setObjectName("InspectorCaption")

        self.summary = QLabel("", self)
        self.summary.setObjectName("InspectorNote")

        header = QHBoxLayout()
        header.setSpacing(FIELD_GAP)
        header.addWidget(self.chevron)
        header.addWidget(self.glyph)
        header.addWidget(caption)
        header.addStretch(1)
        header.addWidget(self.summary)

        self.body = body
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(FIELD_GAP)
        column.addLayout(header)
        # The body keeps the chevron column's width so it aligns under the caption.
        indented = QHBoxLayout()
        indented.setContentsMargins(LEAD_WIDTH, 0, 0, 0)
        indented.addWidget(body)
        column.addLayout(indented, stretch=1)

        self._paint_glyph()
        self.set_expanded(expanded)

    def expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self.body.setVisible(expanded)
        self.chevron.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self.toggled.emit(expanded)

    def set_summary(self, text: str) -> None:
        self.summary.setText(text)

    def _paint_glyph(self) -> None:
        # DESIGN.md's sanctioned exception: secondary is the palette's text at ~63 % alpha.
        # Painted from the live palette and repainted on PaletteChange, never stored.
        ink = QColor(self.palette().text().color())
        ink.setAlpha(160)
        icon = self._icon(ink.name(QColor.NameFormat.HexArgb))
        self.glyph.setPixmap(icon.pixmap(ICON_SIZE, ICON_SIZE))

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            self._paint_glyph()


class AgentSection(QWidget):
    """The four prompt parts, stacked; Preview and Run under them."""

    def __init__(
        self,
        product: Product,
        undo: UndoService[Product],
        placeholder: str,
        prompt_parts: Callable[[StepId], Sequence[PromptPart]],
        files: Callable[[NodeId, str], ModuleFileArea] | None,
        run_state: Callable[[], ActionState],
        run: Callable[[], None],
        preview_state: Callable[[], ActionState],
        preview: Callable[[], None],
        prompt_sections: Callable[[StepId], Sequence[PromptPart]] = lambda _sid: (),
        read_asset: Callable[[str], bytes | None] | None = None,
    ) -> None:
        super().__init__()
        self._product = product
        self._undo = undo
        self._prompt_parts = prompt_parts
        self._prompt_sections = prompt_sections
        self._read_asset = read_asset
        self._files = files
        self._run_state = run_state
        self._preview_state = preview_state
        self._step_id: StepId | None = None
        self._project_id: NodeId | None = None
        self._step_binding: TextBinding[Product] | None = None
        self._project_binding: TextBinding[Product] | None = None
        self.tab_visibility_changed: Signal[bool] = Signal()

        # -- Project: the standing instruction, editable here and in the project panel.
        self.project_edit = QPlainTextEdit(self)
        self.project_edit.setObjectName("InspectorNotes")
        self.project_edit.setPlaceholderText(PROJECT_PLACEHOLDER)
        self.project_edit.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.project_assets = AssetGallery(
            self, editable=True, attach_title="Attach to Instruction"
        )
        project_body = _body(self.project_edit, self.project_assets)
        self.project_part = PartRow("Project", project_icon, project_body)

        # -- Step context: the step's own facts, exactly as the briefing carries them —
        # rendered text from section_lines, and each section's files as real thumbnails.
        self.context_view = QPlainTextEdit(self)
        self.context_view.setObjectName("InspectorNotes")
        self.context_view.setReadOnly(True)
        self.context_view.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.context_view.setPlaceholderText("Nothing recorded about this step yet.")
        make_text_well(self.context_view)
        self._context_galleries = QWidget(self)
        self._galleries_column = QVBoxLayout(self._context_galleries)
        self._galleries_column.setContentsMargins(0, 0, 0, 0)
        self._galleries_column.setSpacing(FIELD_GAP)
        context_body = QWidget(self)
        context_column = QVBoxLayout(context_body)
        context_column.setContentsMargins(0, 0, 0, 0)
        context_column.setSpacing(FIELD_GAP)
        context_column.addWidget(self.context_view, stretch=1)
        context_column.addWidget(self._context_galleries)
        self.context_part = PartRow("Step context", read_icon, context_body)

        # -- Inherited: read-only, derived on every relevant change, never stored.
        self.inherited_view = QPlainTextEdit(self)
        self.inherited_view.setObjectName("InspectorNotes")
        self.inherited_view.setReadOnly(True)
        self.inherited_view.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.inherited_view.setPlaceholderText("Nothing handed forward to this step yet.")
        make_text_well(self.inherited_view)
        self.inherited_part = PartRow("Inherited", graph_icon, self.inherited_view)

        # -- This step: the instruction itself, expanded by default — it is why you came.
        self.edit = QPlainTextEdit(self)
        self.edit.setObjectName("InspectorNotes")
        self.edit.setPlaceholderText(placeholder)
        self.edit.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.step_assets = AssetGallery(
            self, editable=True, attach_title="Attach to Instruction"
        )
        step_body = _body(self.edit, self.step_assets)
        self.step_part = PartRow("This step", leaf_icon, step_body, expanded=True)

        self.preview_button = QPushButton("Preview Prompt…", self)
        self.preview_button.clicked.connect(lambda: preview())
        self.run_button = QPushButton("Run Agent…", self)
        self.run_button.setObjectName("AgentRunButton")
        self.run_button.clicked.connect(lambda: run())
        buttons = QHBoxLayout()
        buttons.setSpacing(FIELD_GAP)
        buttons.addStretch(1)
        buttons.addWidget(self.preview_button)
        buttons.addWidget(self.run_button)

        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(
            PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN
        )
        self._column.setSpacing(BLOCK_GAP)
        self._column.addWidget(self.project_part)
        self._column.addWidget(self.context_part)
        self._column.addWidget(self.inherited_part)
        self._column.addWidget(self.step_part, stretch=1)
        self._column.addLayout(buttons)

        # A collapsed part must not keep its share of the height; the expanded ones split it.
        for part in self._parts():
            part.toggled.connect(lambda _expanded: self._restretch())
        self._restretch()

        # Typing the first instruction is what arms the buttons; the summaries follow too.
        self.edit.textChanged.connect(self._refresh_buttons)
        self.edit.textChanged.connect(self._refresh_summaries)
        self.project_edit.textChanged.connect(self._refresh_summaries)

        self._unsubscribes = [
            product.text_edited.connect(lambda *_a: self._refresh_derived()),
            product.module_data_changed.connect(lambda *_a: self._refresh_derived()),
            product.edges_changed.connect(lambda *_a: self._refresh_derived()),
        ]

    # -- the panel's side of the contract ------------------------------------------------------

    @property
    def widget(self) -> QWidget:
        return self

    def tab_visible(self) -> bool:
        return True

    def show_target(self, target_id: str | None) -> None:
        self._close_bindings()
        self._step_id = target_id if target_id and self._product.has(target_id) else None
        self._project_id = None
        self.setEnabled(self._step_id is not None)
        if self._step_id is not None:
            self._project_id = self._product.project_of(self._step_id).id
            self._step_binding = TextBinding(
                self.edit, ModuleTextField(self._product, self._step_id, MODULE_ID), self._undo
            )
            self._project_binding = TextBinding(
                self.project_edit,
                ModuleTextField(self._product, self._project_id, MODULE_ID),
                self._undo,
            )
        else:
            self.edit.setPlainText("")
            self.project_edit.setPlainText("")
        self._retarget_assets()
        self._refresh_derived()
        self._refresh_buttons()

    def dispose(self) -> None:
        self._close_bindings()
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()

    # -- reading -------------------------------------------------------------------------------

    def _retarget_assets(self) -> None:
        files = self._files
        step_id, project_id = self._step_id, self._project_id
        if files is None or step_id is None or project_id is None:
            self.step_assets.set_area(None)
            self.project_assets.set_area(None)
            return
        self.step_assets.set_area(lambda: files(step_id, MODULE_ID))
        self.project_assets.set_area(lambda: files(project_id, MODULE_ID))

    def _refresh_derived(self) -> None:
        """Everything this tab computes rather than edits: inherited context and the
        step's own facts. One entry point, so no model change can refresh one pane and
        leave the other describing an older step."""
        parts: Sequence[PromptPart] = ()
        if self._step_id is not None and self._product.has(self._step_id):
            parts = self._prompt_parts(self._step_id)
        lines = [line for part in parts for line in part_lines(part)]
        self.inherited_view.setPlainText("\n".join(lines).strip())
        make_text_well(self.inherited_view)
        space_lines(self.inherited_view)
        self._refresh_context()
        self._refresh_summaries()

    def _refresh_context(self) -> None:
        sections: Sequence[PromptPart] = ()
        if self._step_id is not None and self._product.has(self._step_id):
            sections = self._prompt_sections(self._step_id)
        lines = [line for section in sections for line in section_lines(section)]
        self.context_view.setPlainText("\n".join(lines).strip())
        make_text_well(self.context_view)
        space_lines(self.context_view)

        while (item := self._galleries_column.takeAt(0)) is not None:
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        read = self._read_asset
        if read is not None:
            for section in sections:
                if not section.files:
                    continue
                heading = QLabel(section.heading, self._context_galleries)
                heading.setObjectName("InspectorNote")
                gallery = AssetGallery(self._context_galleries)
                gallery.set_files(section.files, read)
                self._galleries_column.addWidget(heading)
                self._galleries_column.addWidget(gallery)

    def _refresh_summaries(self) -> None:
        self.project_part.set_summary(_prose_summary(self.project_edit.toPlainText()))
        self.step_part.set_summary(_prose_summary(self.edit.toPlainText()))
        parts, sections = 0, 0
        if self._step_id is not None and self._product.has(self._step_id):
            parts = len(self._prompt_parts(self._step_id))
            sections = len(self._prompt_sections(self._step_id))
        self.inherited_part.set_summary(
            "nothing yet" if parts == 0 else f"{parts} block{'s' if parts != 1 else ''}"
        )
        self.context_part.set_summary(
            "nothing yet"
            if sections == 0
            else f"{sections} section{'s' if sections != 1 else ''}"
        )

    def _refresh_buttons(self) -> None:
        state = self._run_state()
        self.run_button.setEnabled(state.enabled)
        self.run_button.setToolTip(
            state.label or "Open a terminal with the agent briefed on this step"
        )
        preview = self._preview_state()
        self.preview_button.setEnabled(preview.enabled)
        self.preview_button.setToolTip(
            preview.label or "See the exact briefing Run Agent will launch with"
        )

    # -- internals -----------------------------------------------------------------------------

    def _parts(self) -> tuple[PartRow, ...]:
        return (self.project_part, self.context_part, self.inherited_part, self.step_part)

    def _restretch(self) -> None:
        for part in self._parts():
            self._column.setStretchFactor(part, 1 if part.expanded() else 0)

    def _close_bindings(self) -> None:
        for binding in (self._step_binding, self._project_binding):
            if binding is not None:
                binding.close()
                # close() only disconnects; the binding is parented to the editor, which
                # outlives it, so without this every retarget would leave one behind.
                binding.setParent(None)
        self._step_binding = None
        self._project_binding = None


class ProjectInstructionCard(QWidget):
    """The project panel's Agent card: the standing instruction, the tab's same field.

    Two editors over one ``ModuleTextField`` — the binding's per-view origin keeps them
    from echoing each other, and one undo stack serves both.
    """

    def __init__(
        self,
        product: Product,
        undo: UndoService[Product],
        files: Callable[[NodeId, str], ModuleFileArea] | None,
    ) -> None:
        super().__init__()
        self._product = product
        self._undo = undo
        self._files = files
        self._binding: TextBinding[Product] | None = None
        self.tab_visibility_changed: Signal[bool] = Signal()

        self.edit = QPlainTextEdit(self)
        self.edit.setObjectName("InspectorNotes")
        self.edit.setPlaceholderText(PROJECT_PLACEHOLDER)
        self.edit.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        # A card grows down the stack, not with its content: a few lines here, the Agent
        # tab for serious writing. The inner scroller is DESIGN.md's accepted trade.
        self.edit.setFixedHeight(self.edit.fontMetrics().lineSpacing() * 6 + 16)
        self.assets = AssetGallery(
            self, editable=True, attach_title="Attach to Instruction"
        )

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(FIELD_GAP)
        column.addWidget(self.edit)
        column.addWidget(self.assets)

    @property
    def widget(self) -> QWidget:
        return self

    def tab_visible(self) -> bool:
        # Always: a card that hid itself while the instruction was empty would be a card
        # you could never use to write one.
        return True

    def show_target(self, target_id: str | None) -> None:
        self._close_binding()
        project_id = target_id if target_id and self._product.has(target_id) else None
        self.setEnabled(project_id is not None)
        if project_id is not None:
            self._binding = TextBinding(
                self.edit, ModuleTextField(self._product, project_id, MODULE_ID), self._undo
            )
            files, pid = self._files, project_id
            self.assets.set_area(
                (lambda: files(pid, MODULE_ID)) if files is not None else None
            )
        else:
            self.edit.setPlainText("")
            self.assets.set_area(None)

    def dispose(self) -> None:
        self._close_binding()

    def _close_binding(self) -> None:
        if self._binding is not None:
            self._binding.close()
            self._binding.setParent(None)
            self._binding = None


def _body(edit: QPlainTextEdit, assets: AssetGallery) -> QWidget:
    """An editor with its asset gallery under it, as one collapsible body."""
    body = QWidget()
    column = QVBoxLayout(body)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(FIELD_GAP)
    column.addWidget(edit, stretch=1)
    column.addWidget(assets)
    return body


def _prose_summary(text: str) -> str:
    return "empty" if not text.strip() else f"{len(text)} chars"
