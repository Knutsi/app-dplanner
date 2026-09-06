"""The Docs tab: a project's collectors down the side, their Fragments and Compiled beside.

**A group is a collector, and grouping is the existing walk.** ``domain/scope.gatherers()``
answers which features (or milestones) gather each step, and ``collect.sources_for`` answers
what one would read. Nothing is stored, so ``dplanner step link`` cannot leave a document
filed under a feature that no longer waits on it.

**Two tabs, because they are two documents, not two halves of one.** *Fragments* is what the
work wrote — read-only, each contribution under its step's heading. *Compiled* is the
document made of them, edited in place. A reader wants one or the other, never both at once,
which is what makes a tab right where a stacked pair would not be.

**The mark on a row is the third state of the same fact the banner states.** A filled accent
dot for a document its fragments have outgrown, a hollow ring for one nobody has written yet,
and nothing at all when it is current — because the common case should be quiet.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QModelIndex, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.model import Project, Step, StepId
from dplanner.domain.scope import gatherers, kind_of
from dplanner.domain.store import ModuleFileArea
from dplanner.framework.activity import EntityActivity, follow_project
from dplanner.framework.context import ContextNode, Uri, activity_uri, selection_uri
from dplanner.framework.debounce import Debounced
from dplanner.framework.markdown_view import MarkdownView
from dplanner.framework.module_data_section import PANEL_MARGIN
from dplanner.framework.toolbar import control_bar
from dplanner.modules.docs.aspect import MODULE_ID, read
from dplanner.modules.docs.collect import (
    Source,
    as_markdown,
    sources_for,
    word_count,
)
from dplanner.modules.docs.section import CompileBanner, CompiledSection, CompileLink
from dplanner.theme.icons import ICON_SIZE, glyph_painter

if TYPE_CHECKING:  # module.py imports this file, so the Deps arrive as a forward name.
    from dplanner.modules.docs.module import DocsDeps

DOCS_KIND = "docs"

CAPTION_GAP = 6
BLOCK_GAP = 12
CONTROL_GAP = 8
SELECTOR_WIDTH = 180
LIST_WIDTH = 260

ROW_PADDING_V = 10
ROW_PADDING_H = 12
ROW_LINE_GAP = 4
SECONDARY_ALPHA = 160  # ~63 % — DESIGN.md's opacity-derived secondary text.
MARK_DIAMETER = 8.0
MARK_GAP = 10

DETAIL_ROLE = int(Qt.ItemDataRole.UserRole) + 1
GROUP_ROLE = int(Qt.ItemDataRole.UserRole) + 2
MARK_ROLE = int(Qt.ItemDataRole.UserRole) + 3

UNGROUPED = "Every documented step"
NOTHING_YET = (
    "Nothing documented yet. Turn on Step ▸ Type ▸ Docs and write what a step adds "
    "to the product's documentation — or `dplanner docs set '<step>' --file notes.md`."
)
NOT_A_COLLECTOR = (
    "These steps reach no feature, so there is nothing for their documentation to be "
    "compiled into. `dplanner project lint` reports them as scope.ungathered."
)


@dataclass(frozen=True)
class Group:
    """One row: a collector, what it holds, and where its document stands."""

    key: StepId  # The collector's id, or "" for the pile nothing gathers.
    title: str
    detail: str
    sources: tuple[Source, ...]
    icon: str = ""  # A medallion name; "" draws none.
    mark: str = ""  # "stale" | "never" | "" — what the delegate paints at the right edge.
    collector: Step | None = None
    areas: tuple[str, ...] = field(default_factory=tuple)


class DocsActivity(EntityActivity):
    """One project's documentation, read by whichever collector the reader chose."""

    def __init__(self, deps: "DocsDeps", project_id: str, link: CompileLink) -> None:
        super().__init__(deps.context, "project", project_id)
        self.project_id = project_id
        self._deps = deps
        self._library = deps.library
        self._link = link
        self._group_kind = ""
        self._selected: StepId | None = None
        self._groups: list[Group] = []

        self.page = _DocsPage(deps, link)
        self.page.group_box.currentIndexChanged.connect(self._on_group_changed)
        self.page.list.currentRowChanged.connect(self._on_row_changed)

        # After a quiet spell, not per signal: a refresh walks a cone per collector.
        self._refresh_soon = Debounced(self._refresh, parent=self.page, service=deps.debounce)
        self._unsubscribes = [
            # Every signal, this project only — a fragment is prose, so text edits count.
            follow_project(self._library, self.project_id, self._refresh_soon.trigger),
        ]
        self._refresh()

    # -- the activity contract -------------------------------------------------------------

    @property
    def uri(self) -> Uri:
        return activity_uri(DOCS_KIND, self.project_id)

    @property
    def title(self) -> str:
        return f"{self._project().title or 'Untitled project'} — Docs"

    @property
    def widget(self) -> QWidget:
        return self.page

    def on_activated(self) -> None:
        super().on_activated()
        self._publish()

    def close(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes = []

    def show_collector(self, step_id: StepId) -> None:
        """Select the group that is ``step_id``'s — its own, when it collects, else the
        one holding its fragment — what a jump from a step or the coverage view lands on."""
        self._refresh()
        held = next(
            (group for group in self._groups if group.key == step_id),
            next((group for group in self._groups if step_id in group.areas), None),
        )
        if held is None:
            return
        self._selected = held.key
        self.page.show_groups(self._groups, keep=self._selected)
        self._show_selected()

    def _project(self) -> Project:
        return self._library.project(self.project_id)

    # -- reading -----------------------------------------------------------------------------

    def _refresh(self) -> None:
        if not self._library.has(self.project_id):
            return  # The tab is on its way out; follow_entity_tabs closes it.
        project = self._project()
        self._sync_grouping(project)
        self._groups = self._build_groups(project)
        self.page.show_groups(self._groups, keep=self._selected)
        self.page.lead(*_headline(self._groups))
        self.page.say("" if self._groups else NOTHING_YET)
        self._show_selected()

    def _sync_grouping(self, project: Project) -> None:
        """Only kinds this project actually has: a selector offering nothing teaches nothing."""
        present = [
            kind for kind in self._deps.scopes if any(kind.carried_by(s) for s in project.steps)
        ]
        # Finest grain first, so the default is the one people name and demo. `gathers` is
        # empty exactly for the finest kind — a feature is read flat, a milestone as a list
        # of features — so the sort needs no rank of its own.
        present.sort(key=lambda kind: bool(kind.gathers))
        entries = [(f"By {kind.label.lower()}", kind.id) for kind in present] or [(UNGROUPED, "")]
        box = self.page.group_box
        if [(box.itemText(i), box.itemData(i)) for i in range(box.count())] != entries:
            box.blockSignals(True)
            box.clear()
            for label, value in entries:
                box.addItem(label, value)
            index = box.findData(self._group_kind)
            box.setCurrentIndex(index if index >= 0 else 0)
            box.blockSignals(False)
        self._group_kind = str(box.currentData() or "")
        # A project with nothing to group by shows no control at all rather than one with a
        # single entry — DESIGN.md: an empty box is worse than no box.
        self.page.group_action.setVisible(len(entries) > 1)

    def _build_groups(self, project: Project) -> list[Group]:
        kind = next((k for k in self._deps.scopes if k.id == self._group_kind), None)
        if kind is None:
            # No collectors at all: the honest degenerate case is the fragments, flat.
            return [
                Group(
                    step.id,
                    step.title or "Untitled step",
                    _words(word_count(read(step))),
                    (Source(step, read(step)),),
                    areas=(step.id,),
                )
                for step in project.steps
                if read(step)
            ]

        groups: list[Group] = []
        for step in project.steps:
            if not kind.carried_by(step):
                continue
            found = sources_for(self._deps.scopes, self._library, project, step.id)
            if not found:
                continue
            standing = self._link.standing(step.id)
            groups.append(
                Group(
                    step.id,
                    f"{kind.label}: {step.title or 'Untitled step'}",
                    _group_detail(found),
                    tuple(found),
                    icon=_glyph_for(self._deps.scopes, step),
                    mark="" if standing.state == "current" else standing.state,
                    collector=step,
                    areas=tuple(source.step.id for source in found),
                )
            )

        loose = self._ungathered(project, kind)
        if loose:
            groups.append(
                Group(
                    "",
                    f"Not in any {kind.label.lower()}",
                    _group_detail(loose),
                    tuple(loose),
                    areas=tuple(source.step.id for source in loose),
                )
            )
        return groups

    def _ungathered(self, project: Project, kind: Any) -> list[Source]:
        """Documented steps this kind's collectors do not reach — lint's scope.ungathered."""
        owners = gatherers(
            self._library, project, carried_by=kind.carried_by, stops_at=kind.stops_at
        )
        return [
            Source(step, read(step))
            for step in project.steps
            if read(step) and step.id not in owners
        ]

    # -- selection ---------------------------------------------------------------------------

    def _on_group_changed(self, _index: int) -> None:
        self._group_kind = str(self.page.group_box.currentData() or "")
        self._selected = None
        self._refresh()

    def _on_row_changed(self, _row: int) -> None:
        item = self.page.list.currentItem()
        self._selected = item.data(GROUP_ROLE) if item is not None else None
        self._show_selected()
        self._publish()

    def _current(self) -> Group | None:
        found = [group for group in self._groups if group.key == self._selected]
        return found[0] if found else (self._groups[0] if self._groups else None)

    def _show_selected(self) -> None:
        group = self._current()
        if group is None:
            self.page.show_group(None, [])
            return
        self.page.show_group(group, self._areas(group))

    def _areas(self, group: Group) -> list[ModuleFileArea]:
        """Every contributing step's own file area, so a pasted image renders here too.

        Assets are content-addressed, so one name means one blob wherever it lives and
        asking each area in turn is exact rather than a guess.
        """
        files = self._deps.files
        if files is None:
            return []
        found = []
        for step_id in group.areas:
            try:
                found.append(files(step_id, MODULE_ID))
            except KeyError:
                continue  # A step the store has never flushed has no files yet.
        return found

    def _publish(self) -> None:
        """The selected group's collector, so the step panel follows this tab for free."""
        group = self._current()
        if group is None or group.collector is None:
            self.publish_selection(())
            return
        self.publish_selection((ContextNode(selection_uri("step", group.collector.id)),))


class _DocsPage(QWidget):
    """Caption, the answer, the Group by control, and the list beside its two tabs."""

    def __init__(self, deps: "DocsDeps", link: CompileLink) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(CAPTION_GAP)

        title = QLabel("Documentation", self)
        title.setObjectName("InspectorCaption")
        layout.addWidget(title)

        subtitle = QLabel("What this project's work adds up to, for whoever reads it.", self)
        subtitle.setObjectName("InspectorNote")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        layout.addSpacing(BLOCK_GAP)

        self.answer = QLabel(self)
        answer_font = self.answer.font()
        answer_font.setPointSizeF(answer_font.pointSizeF() + 2.0)
        self.answer.setFont(answer_font)
        layout.addWidget(self.answer)

        self.detail = QLabel(self)
        self.detail.setObjectName("InspectorNote")
        layout.addWidget(self.detail)
        layout.addSpacing(BLOCK_GAP)

        # A toolbar rather than a row of widgets: too narrow for its contents it grows the
        # » overflow button, where a plain row simply overlaps.
        strip = QHBoxLayout()
        strip.setSpacing(CONTROL_GAP)
        self.controls = control_bar(self)
        self.group_box = QComboBox(self.controls)
        self.group_box.setMinimumWidth(SELECTOR_WIDTH)
        # A toolbar wraps a widget in an action, and it is the *action* that carries
        # visibility — hiding the combo alone would leave its slot behind.
        self.group_action = self.controls.addWidget(self.group_box)
        strip.addWidget(self.controls, 1)
        layout.addLayout(strip)
        layout.addSpacing(CONTROL_GAP)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.list = QListWidget(self.splitter)
        self.list.setObjectName("DocsGroups")
        self.rows = _GroupDelegate(self.list)
        self.rows.set_accent(deps.theme.current.accent)
        deps.theme.changed.connect(lambda theme: self._reink(theme.accent))
        self.list.setItemDelegate(self.rows)
        self.list.setFrameShape(QListWidget.Shape.NoFrame)

        right = QWidget(self.splitter)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(CONTROL_GAP)
        self.banner = CompileBanner(link, right)
        right_layout.addWidget(self.banner)

        self.tabs = QTabWidget(right)
        self.tabs.setDocumentMode(True)
        right_layout.addWidget(self.tabs, 1)

        self.fragments = MarkdownView(self.tabs)
        self.fragments.setFrameShape(MarkdownView.Shape.NoFrame)
        self.tabs.addTab(self.fragments, "Fragments")

        compiled_page = QWidget(self.tabs)
        compiled_layout = QVBoxLayout(compiled_page)
        compiled_layout.setContentsMargins(0, CONTROL_GAP, 0, 0)
        compiled_layout.setSpacing(CONTROL_GAP)
        self.compiled = CompiledSection(deps.library, deps.undo)
        compiled_layout.addWidget(self.compiled, 1)
        self.uncompilable = QLabel(NOT_A_COLLECTOR, compiled_page)
        self.uncompilable.setObjectName("InspectorNote")
        self.uncompilable.setWordWrap(True)
        self.uncompilable.hide()
        compiled_layout.addWidget(self.uncompilable)
        self.tabs.addTab(compiled_page, "Compiled")

        self.splitter.addWidget(self.list)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([LIST_WIDTH, LIST_WIDTH * 3])
        layout.addWidget(self.splitter, 1)

        self.empty = QLabel(self)
        self.empty.setObjectName("InspectorNote")
        self.empty.setWordWrap(True)
        self.empty.hide()
        layout.addWidget(self.empty)

    def _reink(self, accent: str) -> None:
        self.rows.set_accent(accent)
        self.list.viewport().update()

    def say(self, message: str) -> None:
        """A tab cannot go off screen the way a panel does, so it says so in words."""
        self.empty.setText(message)
        self.empty.setVisible(bool(message))
        self.splitter.setVisible(not message)

    def lead(self, answer: str, detail: str) -> None:
        self.answer.setText(answer)
        self.detail.setText(detail)

    def show_groups(self, groups: Sequence[Group], *, keep: StepId | None) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for group in groups:
            item = QListWidgetItem(group.title)
            item.setData(DETAIL_ROLE, group.detail)
            item.setData(GROUP_ROLE, group.key)
            item.setData(MARK_ROLE, group.mark)
            painter = glyph_painter(group.icon) if group.icon else None
            if painter is not None:
                item.setIcon(painter(self.list.palette().text().color()))
            self.list.addItem(item)
        rows = [index for index, group in enumerate(groups) if group.key == keep]
        self.list.setCurrentRow(rows[0] if rows else (0 if groups else -1))
        self.list.blockSignals(False)

    def show_group(self, group: Group | None, areas: Sequence[ModuleFileArea]) -> None:
        if group is None:
            self.fragments.show_markdown("")
            self.compiled.show_target(None)
            return
        self.fragments.show_markdown(as_markdown(group.sources), areas)
        # A pile nothing gathers has no step to hold a document, and says so rather than
        # offering a button that could not write anywhere.
        collector = group.collector
        self.banner.setVisible(collector is not None)
        self.compiled.setVisible(collector is not None)
        self.uncompilable.setVisible(collector is None)
        self.compiled.show_target(collector.id if collector is not None else None)
        if collector is not None:
            self.banner.show_target(collector.id)


class _GroupDelegate(QStyledItemDelegate):
    """Two lines and a mark: what the group is, how much it holds, and whether it is due."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Not the palette's Highlight, which is the *selection* blue in every theme. The
        # accent is the warm "this wants you" colour, and it is set from the theme rather
        # than read off a widget, because a colour copied onto one goes stale.
        self._accent = QColor("#c98a3a")

    def set_accent(self, colour: str) -> None:
        self._accent = QColor(colour)

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | Any
    ) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        opt.icon = QIcon()  # Drawn below, so the two lines start from one left edge.
        style = opt.widget.style() if opt.widget else None
        if style is not None:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

        palette = opt.palette
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        role = palette.ColorRole.HighlightedText if selected else palette.ColorRole.Text
        primary = palette.color(role)
        secondary = QColor(primary)
        secondary.setAlpha(SECONDARY_ALPHA)

        rect = opt.rect.adjusted(ROW_PADDING_H, ROW_PADDING_V, -ROW_PADDING_H, -ROW_PADDING_V)
        metrics = opt.fontMetrics
        painter.save()

        # The icon column is reserved whether or not this row has one, so a heading with no
        # glyph — the pile nothing gathers — still lines up with the collectors above it.
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        left = rect.left()
        if isinstance(icon, QIcon) and not icon.isNull():
            icon.paint(painter, QRect(left, rect.top(), ICON_SIZE, metrics.height()))
        left += ICON_SIZE + MARK_GAP

        mark = index.data(MARK_ROLE) or ""
        width = rect.right() - left - (MARK_GAP + int(MARK_DIAMETER) if mark else 0)
        elide = Qt.TextElideMode.ElideRight
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        painter.setPen(primary)
        painter.drawText(
            QRect(left, rect.top(), width, metrics.height()),
            align,
            metrics.elidedText(index.data(Qt.ItemDataRole.DisplayRole), elide, width),
        )
        painter.setPen(secondary)
        painter.drawText(
            QRect(left, rect.top() + metrics.height() + ROW_LINE_GAP, width, metrics.height()),
            align,
            metrics.elidedText(index.data(DETAIL_ROLE) or "", elide, width),
        )
        if mark:
            self._mark(painter, opt, rect, metrics.height(), str(mark))
        painter.restore()

    def _mark(
        self, painter: QPainter, opt: QStyleOptionViewItem, rect: QRect, line: int, mark: str
    ) -> None:
        """Filled accent for out of date, a hollow ring for never written.

        The accent is DESIGN.md's "the action the user came to perform" colour, so it needs
        no new token and follows the theme with everything else.
        """
        centre = QRectF(
            rect.right() - MARK_DIAMETER,
            rect.top() + (line - MARK_DIAMETER) / 2,
            MARK_DIAMETER,
            MARK_DIAMETER,
        )
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if mark == "stale":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._accent)
        else:
            ring = QColor(opt.palette.color(opt.palette.ColorRole.Text))
            ring.setAlpha(SECONDARY_ALPHA)
            painter.setPen(ring)
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(centre)

    def sizeHint(  # noqa: N802 - Qt override
        self, option: QStyleOptionViewItem, index: QModelIndex | Any
    ) -> QSize:
        metrics = option.fontMetrics
        return QSize(0, 2 * ROW_PADDING_V + 2 * metrics.height() + ROW_LINE_GAP)


def _glyph_for(kinds: Sequence[Any], step: Step) -> str:
    """The medallion the node itself wears, so the list and the canvas agree at a glance."""
    kind = kind_of(kinds, step)
    return {"feature": "layers", "step_milestone": "tag", "step_check": "shield"}.get(
        kind.id if kind is not None else "", ""
    )


def _headline(groups: Sequence[Group]) -> tuple[str, str]:
    """Lead with the answer: the staffing matrix taught that a list with no sentence over
    it makes every reader do the arithmetic."""
    if not groups:
        return "Nothing documented yet", ""
    marks = [group.mark for group in groups if group.collector is not None]
    words = sum(word_count(source.body) for group in groups for source in group.sources)
    answer = f"{len(groups)} {_word('group', len(groups))}, {words:,} words"
    stale = sum(1 for mark in marks if mark == "stale")
    never = sum(1 for mark in marks if mark == "never")
    parts = [f"{len(marks) - stale - never} up to date"] if marks else []
    if stale:
        parts.append(f"{stale} out of date")
    if never:
        parts.append(f"{never} not written yet")
    return answer, " · ".join(parts)


def _group_detail(sources: Sequence[Source]) -> str:
    words = sum(word_count(source.body) for source in sources)
    return f"{len(sources)} {_word('source', len(sources))} · {_words(words)}"


def _words(count: int) -> str:
    return f"{count:,} {_word('word', count)}"


def _word(noun: str, count: int) -> str:
    return noun if count == 1 else f"{noun}s"
