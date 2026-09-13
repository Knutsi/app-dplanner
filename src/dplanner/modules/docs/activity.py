"""The Documentation tab: a project's collectors down the side, their documents beside.

**A group is a collector, and grouping is the existing walk.** ``domain/scope.gatherers()``
answers which features (or milestones) gather each step, and ``collect.sources_for`` answers
what one would read. Nothing is stored, so ``dplanner step link`` cannot leave a document
filed under a feature that no longer waits on it.

**Three tabs, because they are three documents.** *Fragments* is what the work wrote —
read-only, each contribution under its step's heading. *Documentation* is what a collector
makes of them, edited in place. *Compilation instructions* is the project's, a second binding
over the field the project panel's card edits, because this is the page where somebody decides
how every document here should read.

**The row says where a document stands in words, and the strip carries the verb.** The state
sits in the row's trailing slot — nothing at all when it is current, because the common case
should be quiet — and what a compile *was* is on the second line: how much it read, when it
landed and which agent this desk handed it to.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
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
from dplanner.framework.list_rows import (
    DETAIL_ROLE,
    HOST_ROLE,
    TRAILING_ROLE,
    TwoLineDelegate,
    rich_row_height,
)
from dplanner.framework.markdown_view import MarkdownView
from dplanner.framework.module_data_section import PANEL_MARGIN
from dplanner.framework.signalling import UpdatingIndicator
from dplanner.framework.toolbar import Toolbar
from dplanner.framework.widgets import EmptyState, caption, note
from dplanner.modules.docs.aspect import MODULE_ID, read
from dplanner.modules.docs.collect import (
    Source,
    as_markdown,
    sources_for,
    word_count,
)
from dplanner.modules.docs.section import (
    CompiledSection,
    CompileLink,
    DocumentStanding,
    InstructionsCard,
    Standing,
    ago,
)
from dplanner.theme.icons import glyph_painter, read_icon
from dplanner.theme.tokens import CAPTION_GAP, CONTROL_GAP, SECTION_GAP

if TYPE_CHECKING:  # module.py imports this file, so the Deps arrive as a forward name.
    from dplanner.modules.docs.module import DocsDeps

DOCS_KIND = "docs"

SELECTOR_WIDTH = 180
LIST_WIDTH = 300  # Three facts a row, on two lines.

DOCS_CAPTION = "Documentation"

FRAGMENTS_TAB = "Fragments"
DOCUMENT_TAB = "Documentation"
INSTRUCTIONS_TAB = "Compilation instructions"

# The lead sentence over the list: the page's one answer, a size up from its own detail.
LEAD_POINTS = 2.0

GROUP_ROLE = HOST_ROLE  # Where a host's own roles start; the delegates never read past it.

# What the trailing slot says: the state, or — for a document nobody needs to act on — when
# it landed. DESIGN.md's *Lists of rich items*: a date, a count, a fact about the row.
MARKS = {"stale": "out of date", "never": "not compiled yet"}

UNGROUPED = "Every documented step"
# Under the headline, which already says "Nothing documented yet".
NOTHING_YET = (
    "Turn on Step ▸ Type ▸ Documentation fragment and write what a step adds to the"
    " product's documentation — or `dplanner docs set '<step>' --file notes.md`."
)
NOT_A_COLLECTOR = (
    "These steps reach no feature, so there is nothing for their fragments to be compiled"
    " into. `dplanner project lint` reports them as scope.ungathered."
)


@dataclass(frozen=True)
class Group:
    """One row: a collector, what it holds, and where its document stands."""

    key: StepId  # The collector's id, or "" for the pile nothing gathers.
    title: str
    detail: str
    sources: tuple[Source, ...]
    icon: str = ""  # A medallion name; "" draws the list's own.
    # A milestone collector's own shade of the project's colour map; "" paints the
    # glyph in the list's ink, which is what a feature and a check take.
    color: str = ""
    state: str = ""  # "current" | "stale" | "never" — what the headline counts.
    mark: str = ""  # The trailing slot: the state in words, or when a current one landed.
    tip: str = ""  # The row's tooltip: the session of the run that compiled it.
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
        self.page.updating.follow(self._refresh_soon)
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
        return f"{self._project().title or 'Untitled project'} — {DOCS_CAPTION}"

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
        self.page.controls.dispose()

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
        self.page.instructions.show_target(self.project_id)
        self._groups = self._build_groups(project)
        self.page.show_groups(self._groups, keep=self._selected)
        self.page.lead(*_headline(self._groups))
        self.page.say("" if self._groups else NOTHING_YET)
        self._show_selected()
        # What a compile *can* read has just changed, and a strip restates on the context
        # rather than on the model — the theme toggles' path, and coalesced like theirs, so
        # deleting the last fragment greys the verb where it stands.
        self._deps.context.refresh()

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
        self.page.offer_grouping(len(entries) > 1)

    def _build_groups(self, project: Project) -> list[Group]:
        kind = next((k for k in self._deps.scopes if k.id == self._group_kind), None)
        if kind is None:
            # No collectors at all: the honest degenerate case is the fragments, flat.
            return [
                Group(
                    step.id,
                    " ".join(
                        part
                        for part in (self._deps.step_key(step), step.title or "Untitled step")
                        if part
                    ),
                    _words(word_count(read(step))),
                    (Source(step, read(step)),),
                    icon="loose",
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
            key = self._deps.step_key(step)
            groups.append(
                Group(
                    step.id,
                    # The key leads, and the kind is the medallion's to say: a row that
                    # spelled "Feature:" said twice what the glyph beside it already showed.
                    " · ".join(part for part in (key, step.title or "Untitled step") if part),
                    _group_detail(found, standing),
                    tuple(found),
                    icon=_glyph_for(self._deps.scopes, step),
                    color=self._deps.milestone_color(step.id),
                    state=standing.state,
                    mark=MARKS.get(standing.state) or _when(standing),
                    tip=standing.by,
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
                    # A glyph of its own, because ``TwoLineDelegate`` reserves the icon
                    # column per row: without one this heading would start where the
                    # collectors' titles do not.
                    icon="loose",
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

        # No sentence under the caption saying what documentation is: DESIGN.md's *Words* —
        # a standing definition is chrome that never stops being read, and the answer under
        # it changes with the plan, which is what a reader came for.
        self.caption = caption(DOCS_CAPTION, self)
        layout.addWidget(self.caption)
        layout.addSpacing(SECTION_GAP)

        self.answer = QLabel(self)
        answer_font = self.answer.font()
        answer_font.setPointSizeF(answer_font.pointSizeF() + LEAD_POINTS)
        self.answer.setFont(answer_font)
        layout.addWidget(self.answer)

        self.detail = note("", self)
        layout.addWidget(self.detail)
        layout.addSpacing(SECTION_GAP)

        # The strip carries the page's verbs and its one selector: a `Toolbar`, so a narrow
        # dock folds what does not fit into its … menu instead of squeezing every button.
        strip = QHBoxLayout()
        strip.setSpacing(CONTROL_GAP)
        self.controls = Toolbar(self)
        # Creation before the verbs on the selection — DESIGN.md's strip order — and the
        # arrow drops the profiles, which is the *same* child menu the Step menu offers.
        # Registry-fed: the glyph, the words and the reason are the spec's and its state's,
        # restated on every context change, so this strip cannot disagree with the menu about
        # whether a compile can run. The arrow drops the launch profiles — the Step menu's own
        # child menu, never a copy of its list.
        dropped, menu_id = link.profile_menu
        self.verbs = {
            action_id: self.controls.add_action(
                deps.actions,
                deps.context,
                action_id,
                data_menu=menu_id if action_id == dropped else None,
            )
            for action_id in link.verbs
        }
        self.controls.add_divider()
        self.group_box = QComboBox(self.controls)
        self.group_box.setMinimumWidth(SELECTOR_WIDTH)
        self.controls.add_widget(self.group_box)
        strip.addWidget(self.controls, 1)
        self.updating = UpdatingIndicator(self)
        strip.addWidget(self.updating)
        layout.addLayout(strip)
        layout.addSpacing(CONTROL_GAP)

        self._collector: StepId = ""
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.list = QListWidget(self.splitter)
        self.list.setObjectName("DocsGroups")
        self.rows = TwoLineDelegate(self.list)
        self.list.setItemDelegate(self.rows)
        self.list.setFrameShape(QListWidget.Shape.NoFrame)
        self._ink = deps.theme.current.text_secondary
        deps.theme.changed.connect(lambda theme: self._reink(theme.text_secondary))

        right = QWidget(self.splitter)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(CONTROL_GAP)
        self.standing = DocumentStanding(link, right)
        right_layout.addWidget(self.standing)

        self.tabs = QTabWidget(right)
        self.tabs.setDocumentMode(True)
        # Where the picked collector's document stands is nothing to say over the *project's*
        # instructions, so the line steps aside for that tab rather than contradicting it.
        self.tabs.currentChanged.connect(lambda _index: self._show_standing())
        right_layout.addWidget(self.tabs, 1)

        self.fragments = MarkdownView(self.tabs)
        self.fragments.setFrameShape(MarkdownView.Shape.NoFrame)
        self.tabs.addTab(self.fragments, FRAGMENTS_TAB)

        compiled_page = QWidget(self.tabs)
        compiled_layout = QVBoxLayout(compiled_page)
        compiled_layout.setContentsMargins(0, CONTROL_GAP, 0, 0)
        compiled_layout.setSpacing(CONTROL_GAP)
        self.compiled = CompiledSection(deps.library, deps.undo, dictation=deps.dictation)
        compiled_layout.addWidget(self.compiled, 1)
        self.uncompilable = QLabel(NOT_A_COLLECTOR, compiled_page)
        self.uncompilable.setObjectName("InspectorNote")
        self.uncompilable.setWordWrap(True)
        self.uncompilable.hide()
        compiled_layout.addWidget(self.uncompilable)
        self.tabs.addTab(compiled_page, DOCUMENT_TAB)

        # The project's own document, in the page where somebody decides how every document
        # here should read: a second binding over the field the project panel's card edits,
        # which is the standing agent instruction's shape for the same reason.
        instructions_page = QWidget(self.tabs)
        instructions_layout = QVBoxLayout(instructions_page)
        instructions_layout.setContentsMargins(0, CONTROL_GAP, 0, 0)
        instructions_layout.setSpacing(CAPTION_GAP)
        # No caption: the tab names it and the editor's placeholder says what it is for, so a
        # heading here would be the same words a third time.
        self.instructions = InstructionsCard(
            deps.library, deps.undo, deps.files, deps.pick_assets, deps.dictation
        )
        # The card's height is a card's; here it has the page, so it takes what is left.
        self.instructions.edit.setMaximumHeight(16_777_215)
        instructions_layout.addWidget(self.instructions, 1)
        self.tabs.addTab(instructions_page, INSTRUCTIONS_TAB)

        self.splitter.addWidget(self.list)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([LIST_WIDTH, LIST_WIDTH * 3])

        layout.addWidget(self.splitter, 1)
        self.empty = EmptyState(parent=self, stands_in_for=self.splitter)
        layout.addWidget(self.empty, 1)

    def offer_grouping(self, offered: bool) -> None:
        """Whether Group by has a choice to offer."""
        self.controls.set_shown(self.group_box, offered)

    def _reink(self, ink: str) -> None:
        """A colour copied out of the palette onto a widget goes stale, so the rows' glyphs
        are repainted on a theme change — the same hook `TabHost` owes its titles."""
        self._ink = ink
        self.list.viewport().update()

    def say(self, message: str) -> None:
        """A tab cannot go off screen the way a panel does, so it says so in words."""
        self.empty.say(message)

    def lead(self, answer: str, detail: str) -> None:
        self.answer.setText(answer)
        self.detail.setText(detail)

    def show_groups(self, groups: Sequence[Group], *, keep: StepId | None) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        ink = QColor(self._ink)
        for group in groups:
            item = QListWidgetItem(group.title)
            item.setData(DETAIL_ROLE, group.detail)
            item.setData(GROUP_ROLE, group.key)
            item.setData(TRAILING_ROLE, group.mark)
            item.setIcon(_row_icon(group.icon, ink, group.color))
            if group.tip:
                item.setToolTip(group.tip)
            self.list.addItem(item)
        # The row's height is the font's, not a pixel: a two-line row and a two-line table
        # cell take it from the one formula (DESIGN.md's *Lists of rich items*).
        for index in range(self.list.count()):
            item = self.list.item(index)
            item.setSizeHint(QSize(0, rich_row_height(self.list.font())))
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
        # offering an editor that could not write anywhere.
        collector = group.collector
        self._collector = collector.id if collector is not None else ""
        self.compiled.setVisible(collector is not None)
        self.uncompilable.setVisible(collector is None)
        self.compiled.show_target(self._collector or None)
        if collector is not None:
            self.standing.show_target(collector.id)
        self._show_standing()

    def _show_standing(self) -> None:
        on_instructions = self.tabs.currentIndex() == self.tabs.count() - 1
        self.standing.setVisible(bool(self._collector) and not on_instructions)


def _glyph_for(kinds: Sequence[Any], step: Step) -> str:
    """The medallion the node itself wears, so the list and the canvas agree at a glance."""
    kind = kind_of(kinds, step)
    return {"feature": "layers", "step_milestone": "tag", "step_check": "shield"}.get(
        kind.id if kind is not None else "", ""
    )


def _row_icon(name: str, ink: QColor, tone: str) -> QIcon:
    """A row's glyph: the collector's medallion in its own shade, or the page's own mark for
    a row that is not a collector — so every row's text starts at one left edge."""
    if name == "loose":
        return read_icon(ink)
    painter = glyph_painter(name)
    return painter(QColor(tone) if tone else ink) if painter is not None else read_icon(ink)


def _headline(groups: Sequence[Group]) -> tuple[str, str]:
    """Lead with the answer: the staffing matrix taught that a list with no sentence over
    it makes every reader do the arithmetic."""
    if not groups:
        return "Nothing documented yet", ""
    states = [group.state for group in groups if group.collector is not None]
    words = sum(word_count(source.body) for group in groups for source in group.sources)
    answer = f"{len(groups)} {_word('group', len(groups))}, {words:,} words"
    counted = [
        (sum(1 for state in states if state == "current"), "up to date"),
        (sum(1 for state in states if state == "stale"), "out of date"),
        (sum(1 for state in states if state == "never"), "not compiled yet"),
    ]
    return answer, " · ".join(f"{count} {words}" for count, words in counted if count)


def _when(standing: Standing) -> str:
    """When a document that is up to date landed — the trailing slot's quiet fact."""
    return ago(float(standing.stamp.get("at", 0.0) or 0.0))


def _group_detail(sources: Sequence[Source], standing: Standing | None = None) -> str:
    """A row's second line: what there is to read, and who last compiled it.

    *When* is the trailing slot's, and *who* is here, because a row answers "is this due" at
    a glance and "who has been at it" on the line under.
    """
    words = sum(word_count(source.body) for source in sources)
    parts = [f"{len(sources)} {_word('fragment', len(sources))}", _words(words)]
    if standing is not None and standing.working:
        parts.append("an agent is working here")
    elif standing is not None and standing.by and standing.state != "never":
        parts.append(standing.by.partition(" · ")[0])  # The session is the row's tooltip.
    return " · ".join(parts)


def _words(count: int) -> str:
    return f"{count:,} {_word('word', count)}"


def _word(noun: str, count: int) -> str:
    return noun if count == 1 else f"{noun}s"
