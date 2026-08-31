"""The Agent tab: the briefing itself, and the components it is assembled from.

Two inner tabs. **Prompt** is the thing to inspect: the exact assembled text Run Agent
will launch with — not a rendering of it — plus every image it references, in reading
order, as one gallery. Refreshed lazily: model changes mark it stale, and it recomputes
only while it is the visible page, because re-laying a multi-kilobyte document per
keystroke would fight the person typing on the other tab.

**Components** is the editing surface: four collapsible parts in the order the prompt is
assembled — the project's standing instruction (editable here and in the project panel's
Agent card — one field, one undo stack), the step's own facts rendered by the same
``prompt.section_lines`` the prompt is built with, what earlier steps handed forward
(via ``part_lines`` — the same no-drift rule), and this step's own instruction.

The buttons are not second implementations of anything — each evaluates and runs the same
``ActionSpec`` the menus do, so the tab and the menu can never disagree about when a run
or a preview is possible, and the state's reason label becomes the disabled tooltip.
"""

from collections.abc import Callable, Sequence

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QIcon, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QStackedLayout,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.core.signals import Signal
from dplanner.domain.fields import ModuleTextField
from dplanner.domain.model import Library, NodeId, StepId
from dplanner.domain.store import FilesFor
from dplanner.framework.action_registry import ActionState
from dplanner.framework.asset_gallery import AssetGallery
from dplanner.framework.prose_edit import ProseEdit
from dplanner.framework.prose_section import ProseSection
from dplanner.framework.text_binding import TextBinding
from dplanner.framework.text_dialog import ExpandedTextDialog, attach_expand
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import make_text_well, space_lines
from dplanner.modules.step_agent_instruction.aspect import MODULE_ID, separate_instruction
from dplanner.modules.step_agent_instruction.prompt import (
    AssembledPrompt,
    PromptPart,
    PromptSegment,
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
    """The assembled prompt and its four component parts; Preview and Run under both."""

    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        placeholder: str,
        prompt_parts: Callable[[StepId], Sequence[PromptPart]],
        files: FilesFor | None,
        run_state: Callable[[], ActionState],
        run: Callable[[], None],
        preview_state: Callable[[], ActionState],
        preview: Callable[[], None],
        prompt_sections: Callable[[StepId], Sequence[PromptPart]] = lambda _sid: (),
        read_asset: Callable[[str], bytes | None] | None = None,
        assembled: Callable[[StepId], AssembledPrompt] | None = None,
    ) -> None:
        super().__init__()
        self._product = library
        self._undo = undo
        self._prompt_parts = prompt_parts
        self._prompt_sections = prompt_sections
        self._read_asset = read_asset
        self._assemble = assembled
        self._assembled_now: AssembledPrompt | None = None
        self._prompt_stale = True
        self._files = files
        self._run_state = run_state
        self._preview_state = preview_state
        self._step_id: StepId | None = None
        self._project_id: NodeId | None = None
        self._step_binding: TextBinding[Library] | None = None
        self._project_binding: TextBinding[Library] | None = None

        # -- Project: the standing instruction, editable here and in the project panel.
        self.project_edit = ProseEdit(self, undo=undo)
        self.project_edit.setObjectName("InspectorNotes")
        self.project_edit.setPlaceholderText(PROJECT_PLACEHOLDER)
        self.project_edit.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.project_expand = attach_expand(self.project_edit)
        self.project_expand.clicked.connect(
            lambda: self._expand(
                self._project_id, "Project Agent Instruction", PROJECT_PLACEHOLDER
            )
        )
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
        self.edit = ProseEdit(self, undo=undo)
        self.edit.setObjectName("InspectorNotes")
        self.edit.setPlaceholderText(placeholder)
        self.edit.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.step_expand = attach_expand(self.edit)
        self.step_expand.clicked.connect(
            lambda: self._expand(self._step_id, "Agent Instruction", placeholder)
        )
        self.step_assets = AssetGallery(
            self, editable=True, attach_title="Attach to Instruction"
        )
        step_body = _body(self.edit, self.step_assets)
        self.step_part = PartRow("This step", leaf_icon, step_body, expanded=True)
        # Shown in the editor's place while the description is the instructions — most
        # agent steps carry no separate text, and an empty editor would invite writing
        # the same thing twice.
        self.step_note = QLabel(
            "The description is this step's instructions. Tick “Separate agent"
            " instruction” on the Details tab to write execution-specific guidance.",
            self,
        )
        self.step_note.setObjectName("InspectorNote")
        self.step_note.setWordWrap(True)
        self.step_note.hide()

        # -- The Prompt page: the exact text Run Agent launches with, and every image it
        # references — not a rendering, the thing itself.
        self.prompt_view = QPlainTextEdit(self)
        self.prompt_view.setObjectName("InspectorNotes")
        self.prompt_view.setReadOnly(True)
        self.prompt_view.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.prompt_view.setPlaceholderText("Select a step to see its briefing.")
        make_text_well(self.prompt_view)
        self.prompt_legend = QLabel(self)
        self.prompt_legend.setObjectName("InspectorNote")
        self.prompt_gallery = AssetGallery(self)
        self.copy_button = QPushButton("Copy Prompt", self)
        self.copy_button.clicked.connect(self._copy_prompt)
        copy_row = QHBoxLayout()
        copy_row.setSpacing(FIELD_GAP)
        copy_row.addStretch(1)
        copy_row.addWidget(self.copy_button)
        prompt_page = QWidget(self)
        prompt_column = QVBoxLayout(prompt_page)
        prompt_column.setContentsMargins(0, 0, 0, 0)
        prompt_column.setSpacing(FIELD_GAP)
        prompt_column.addWidget(self.prompt_legend)
        prompt_column.addWidget(self.prompt_view, stretch=1)
        prompt_column.addWidget(self.prompt_gallery)
        prompt_column.addLayout(copy_row)

        # -- The Components page: the four parts, exactly as before the split.
        components_page = QWidget(self)
        self._parts_column = QVBoxLayout(components_page)
        self._parts_column.setContentsMargins(0, 0, 0, 0)
        self._parts_column.setSpacing(BLOCK_GAP)
        self._parts_column.addWidget(self.project_part)
        self._parts_column.addWidget(self.context_part)
        self._parts_column.addWidget(self.inherited_part)
        self._parts_column.addWidget(self.step_part, stretch=1)
        self._parts_column.addWidget(self.step_note)

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

        # The panel's own tab idiom (step_properties/panel.py): a bare QTabBar over a
        # QStackedLayout, styled by #InspectorTabs. Prompt first — it is what a reader
        # came to inspect; Components is where the writing happens.
        self.tab_bar = QTabBar(self)
        self.tab_bar.setObjectName("InspectorTabs")
        self.tab_bar.setExpanding(False)
        self.tab_bar.setDrawBase(False)
        self.tab_bar.addTab("Prompt")
        self.tab_bar.addTab("Components")
        self._pages = QStackedLayout()
        self._pages.addWidget(prompt_page)
        self._pages.addWidget(components_page)
        self.tab_bar.currentChanged.connect(self._pages.setCurrentIndex)
        self.tab_bar.currentChanged.connect(lambda _index: self._refresh_prompt_if_shown())

        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(
            PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN
        )
        self._column.setSpacing(BLOCK_GAP)
        self._column.addWidget(self.tab_bar)
        self._column.addLayout(self._pages, stretch=1)
        # The verbs belong to the section, not to a page: one button row under both.
        self._column.addLayout(buttons)

        # A collapsed part must not keep its share of the height; the expanded ones split it.
        for part in self._parts():
            part.toggled.connect(lambda _expanded: self._restretch())
        self._restretch()

        # Typing the first instruction is what arms the buttons; the summaries follow too,
        # and the assembled prompt goes stale (the binding's origin suppresses the model
        # echo back into this view, so the local signal is the one that fires here).
        self.edit.textChanged.connect(self._refresh_buttons)
        self.edit.textChanged.connect(self._refresh_summaries)
        self.edit.textChanged.connect(self._mark_prompt_stale)
        self.project_edit.textChanged.connect(self._refresh_summaries)
        self.project_edit.textChanged.connect(self._mark_prompt_stale)

        self._unsubscribes = [
            library.text_edited.connect(lambda *_a: self._refresh_derived()),
            library.module_data_changed.connect(lambda *_a: self._refresh_derived()),
            library.edges_changed.connect(lambda *_a: self._refresh_derived()),
        ]

    # -- the panel's side of the contract ------------------------------------------------------

    @property
    def widget(self) -> QWidget:
        return self

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
        self._update_step_part()

    def dispose(self) -> None:
        self._close_bindings()
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()

    def _expand(self, node_id: NodeId | None, title: str, placeholder: str) -> None:
        """The same instruction in a big modal editor — a second binding over the same
        field, so the inline editor tracks every keystroke."""
        if node_id is None or not self._product.has(node_id):
            return
        # Whichever editor opened it, with the same powers: a build without file storage
        # gives the dialog none, exactly as _retarget_assets gives the inline editors none.
        gallery = self.step_assets if node_id == self._step_id else self.project_assets
        dialog = ExpandedTextDialog(
            ModuleTextField(self._product, node_id, MODULE_ID),
            self._undo,
            title=title,
            placeholder=placeholder,
            attach=gallery.attach_bytes if self._files is not None else None,
            parent=self.window(),
        )
        dialog.exec()
        dialog.dispose()

    # -- reading -------------------------------------------------------------------------------

    def _retarget_assets(self) -> None:
        """Both galleries and both editors' paste, aimed in one place — a step's files and
        the project's are different areas of the same module, and an editor pointed at the
        wrong one is the kind of mistake that only shows up in somebody else's diff."""
        files = self._files
        step_id, project_id = self._step_id, self._project_id
        if files is None or step_id is None or project_id is None:
            self.step_assets.set_area(None)
            self.project_assets.set_area(None)
            self.edit.set_attach(None)
            self.project_edit.set_attach(None)
            return
        self.step_assets.set_area(lambda: files(step_id, MODULE_ID))
        self.project_assets.set_area(lambda: files(project_id, MODULE_ID))
        self.edit.set_attach(self.step_assets.attach_bytes)
        self.project_edit.set_attach(self.project_assets.attach_bytes)

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
        self._update_step_part()
        self._mark_prompt_stale()

    def _mark_prompt_stale(self) -> None:
        self._prompt_stale = True
        self._refresh_prompt_if_shown()

    def _refresh_prompt_if_shown(self) -> None:
        # Gate on the tab bar, never isVisible(): the whole section reports not-visible
        # while its panel tab is offscreen — the trap PartRow's own state documents.
        if self.tab_bar.currentIndex() == 0 and self._prompt_stale:
            self._refresh_prompt()

    def _refresh_prompt(self) -> None:
        assembled: AssembledPrompt | None = None
        if (
            self._assemble is not None
            and self._step_id is not None
            and self._product.has(self._step_id)
        ):
            assembled = self._assemble(self._step_id)
        self._assembled_now = assembled
        self._prompt_stale = False
        self.copy_button.setEnabled(assembled is not None)
        if assembled is None:
            self.prompt_view.setPlainText("")
            self.prompt_legend.hide()
            self.prompt_gallery.set_files([], None)
            return
        self._render_prompt(assembled)
        self.prompt_gallery.set_files(assembled.files, self._read_asset)

    def _render_prompt(self, assembled: AssembledPrompt) -> None:
        """The text tinted by origin — the segments guarantee the characters are exactly
        the assembled text, so the colouring can never lie about what is sent."""
        colors = self._origin_colors()
        self.prompt_view.clear()
        cursor = self.prompt_view.textCursor()
        fallback = self.palette().text().color()
        segments = assembled.segments or (PromptSegment("instruction", assembled.text),)
        for segment in segments:
            style = QTextCharFormat()
            style.setForeground(colors.get(segment.origin, fallback))
            cursor.insertText(segment.text, style)
        self.prompt_view.moveCursor(QTextCursor.MoveOperation.Start)
        make_text_well(self.prompt_view)
        space_lines(self.prompt_view)
        legend = "   ".join(
            f'<span style="color:{colors[origin].name()}">■ {label}</span>'
            for origin, label in (
                ("project", "Project"),
                ("context", "Step context"),
                ("inherited", "Inherited"),
                ("instruction", "This step"),
            )
        )
        self.prompt_legend.setText(legend)
        self.prompt_legend.show()

    def _origin_colors(self) -> dict[str, QColor]:
        """Per-origin inks from the live palette, never stored — hues at the theme text's
        own lightness stay readable in light and dark alike; the protocol chrome dims to
        the sanctioned ~63 % secondary, and the step's own instruction keeps full ink."""
        ink = self.palette().text().color()
        secondary = QColor(ink)
        secondary.setAlpha(160)

        def tinted(hue: int) -> QColor:
            return QColor.fromHsl(hue, 190, ink.lightness())

        return {
            "header": secondary,
            "protocol": secondary,
            "project": tinted(215),  # blue
            "context": tinted(160),  # teal
            "inherited": tinted(275),  # violet
            "instruction": ink,
        }

    def _copy_prompt(self) -> None:
        from PySide6.QtGui import QGuiApplication

        if self._assembled_now is not None:
            QGuiApplication.clipboard().setText(self._assembled_now.text)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            # The origin inks are read from the live palette at render time; a theme
            # switch re-renders rather than re-tinting stored colours (CLAUDE.md's rule).
            self._mark_prompt_stale()

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

    def _update_step_part(self) -> None:
        """The editor appears only where the step opted into a separate instruction; the
        note holds its place everywhere else, so the page still says where the text is."""
        separate = False
        if self._step_id is not None and self._product.has(self._step_id):
            separate = separate_instruction(self._product.step(self._step_id))
        self.step_part.setVisible(separate)
        self.step_note.setVisible(not separate and self._step_id is not None)
        self._restretch()

    # -- internals -----------------------------------------------------------------------------

    def _parts(self) -> tuple[PartRow, ...]:
        return (self.project_part, self.context_part, self.inherited_part, self.step_part)

    def _restretch(self) -> None:
        for part in self._parts():
            self._parts_column.setStretchFactor(part, 1 if part.expanded() else 0)

    def _close_bindings(self) -> None:
        for binding in (self._step_binding, self._project_binding):
            if binding is not None:
                binding.close()
                # close() only disconnects; the binding is parented to the editor, which
                # outlives it, so without this every retarget would leave one behind.
                binding.setParent(None)
        self._step_binding = None
        self._project_binding = None


class ProjectInstructionCard(ProseSection):
    """The project panel's Agent card: the standing instruction, the tab's same field.

    Two editors over one ``ModuleTextField`` — the binding's per-view origin keeps them
    from echoing each other, and one undo stack serves both. The editor, its gallery and
    its paste all come from :class:`ProseSection`; this subclass only aims them at the
    project and pins the card's height — a card grows down the stack, not with its
    content, and the inner scroller is DESIGN.md's accepted trade.
    """

    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        files: FilesFor | None,
    ) -> None:
        def field_for(target_id: str) -> ModuleTextField | None:
            if not library.has(target_id):
                return None
            return ModuleTextField(library, target_id, MODULE_ID)

        super().__init__(
            field_for,
            undo,
            PROJECT_PLACEHOLDER,
            expand_title="Project Agent Instruction",
            attach_title="Attach to Instruction",
        )
        self._files = files
        self.edit.setFixedHeight(self.edit.fontMetrics().lineSpacing() * 6 + 16)
        layout = self.layout()
        if layout is not None:
            layout.setContentsMargins(0, 0, 0, 0)  # The hosting card carries the margins.

    def show_target(self, target_id: str | None) -> None:
        super().show_target(target_id)
        files = self._files
        if target_id is not None and files is not None and self.isEnabled():
            self.set_area(lambda: files(target_id, MODULE_ID))


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
