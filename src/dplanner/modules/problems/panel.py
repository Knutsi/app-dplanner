"""The Problems list: what is wrong with this project's plan, and the way to each one.

One row per lint finding, newest question first: the subject in primary ink with its step
key at the right, and the finding's message under it — which always names the verb that
closes it, because that is what a ``LintFinding`` promises. Clicking a row runs
``steps.reveal`` against a context naming exactly that step, so the canvas selects it and
moves to it at the zoom the person left; double-clicking opens its details.

A finding whose subject is the *project* — no code repository recorded, no topology read,
no start date — has no step to land on, and the row simply does not travel. That is a
lookup, not a new field on the finding.

**The count is the panel's, read by the strip.** The panel is built with the tab whether
or not the frame is shown, so it keeps answering while it is hidden and the toolbar button
reads the last answer rather than running a lint pass in an action state.
"""

from collections.abc import Callable, Sequence
from functools import partial

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.cli.lint import LintFinding
from dplanner.domain.model import Library, NodeId, Step
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.context import SCOPE_SELECTION, Context, ContextNode, selection_uri
from dplanner.framework.list_rows import (
    DETAIL_ROLE,
    HOST_ROLE,
    TRAILING_ROLE,
    TwoLineDelegate,
)
from dplanner.framework.signalling import UpdatingIndicator
from dplanner.framework.widgets import EmptyState
from dplanner.modules.problems.findings import Findings
from dplanner.theme.icons import ICON_SIZE, problem_icon
from dplanner.theme.tokens import CONTROL_HEIGHT, PANEL_MARGIN, SECTION_GAP

# The step a row is about, when it is about one — numbered from ``HOST_ROLE``, where a
# host's own roles start and nothing the framework's delegates read can collide with it.
SUBJECT_ROLE = HOST_ROLE

NOTHING_WRONG = "No problems found."
NO_AGENT_YET = "Nothing to fix"


class ProblemsPanel(QWidget):
    """This project's lint findings, and the agent that can be sent at them."""

    # The strip's reading: "(4)", or "" when the plan is clean. The graph tab's panel
    # button follows this — one string, so the editor never learns what a problem is.
    reading_changed = Signal(str)

    def __init__(
        self,
        library: Library,
        actions: ActionRegistry,
        findings: Findings,
        parent: QWidget | None = None,
        *,
        key_of: Callable[[Step], str] = lambda _step: "",
        fix_profiles: Callable[[], Sequence[tuple[str, str]]] | None = None,
        fix: Callable[[NodeId, Sequence[LintFinding], str], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("InspectorPanel")
        self._library = library
        self._actions = actions
        self._found_by = findings
        self._key_of = key_of
        self._fix_profiles = fix_profiles
        self._fix = fix
        self._project_id: NodeId | None = None
        self._findings: tuple[LintFinding, ...] = ()
        self._reading = ""

        # The reading is the shared one's; this only redraws when it says something moved.
        # The settle it follows is that one's too, so the indicator still turns from the
        # first change to the answer landing.
        self._refresh_soon = self._found_by.settle

        self.list = QListWidget(self)
        self.list.setObjectName("PanelList")
        self.list.setFrameShape(QFrame.Shape.NoFrame)
        self.list.setItemDelegate(TwoLineDelegate(self.list))
        self.list.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.currentItemChanged.connect(lambda *_a: self._reveal())
        self.list.itemActivated.connect(lambda _item: self._details())

        # The strip: one face naming what it would act on, and the indicator at its right,
        # outside anything that could fold, as DESIGN.md's *Signalling* asks.
        self.fix_button: QToolButton | None = None
        strip = QHBoxLayout()
        if fix_profiles is not None and fix is not None:
            self.fix_button = QToolButton(self)
            self.fix_button.setObjectName("ToolbarButton")
            self.fix_button.setProperty("hasMenu", True)
            self.fix_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            self.fix_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.fix_button.setFixedHeight(CONTROL_HEIGHT)
            self.fix_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            popup = QMenu(self.fix_button)
            popup.aboutToShow.connect(lambda: self._fill_fix_menu(popup))
            self.fix_button.setMenu(popup)
            strip.addWidget(self.fix_button)
        strip.addStretch(1)
        self.updating = UpdatingIndicator(self)
        self.updating.follow(self._refresh_soon)
        strip.addWidget(self.updating)

        self.empty = EmptyState(parent=self, stands_in_for=self.list)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(SECTION_GAP)
        layout.addLayout(strip)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.empty, 1)

        # Every way a plan can change: its shape, its links, a title, and any aspect's
        # One subscription: the shared reading says when it has a new answer.
        self._unsubscribes = [
            self._found_by.changed.connect(self._on_found),
        ]
        self._refresh()

    # -- the ContextPanel contract -------------------------------------------------------------

    def show_context(self, context: Context) -> bool:
        """The focused project — the graph tab's, or the selected step's."""
        project_id = context.focus_entity("project")
        if project_id is None:
            step_id = context.focus_entity("step")
            if step_id is not None and self._library.has(step_id):
                project_id = self._library.project_of(step_id).id
        if project_id is None or not self._library.has(project_id):
            self._set_project(None)
            return False
        self._set_project(project_id)
        return True

    def dispose(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()

    # -- the ReadingPanel contract -------------------------------------------------------------

    def reading(self) -> str:
        """What the strip's button shows beside its glyph: "(4)", or "" when clean."""
        return self._reading

    # -- what is shown -------------------------------------------------------------------------

    def findings(self) -> tuple[LintFinding, ...]:
        """The problems on screen, in the order they are listed."""
        return self._findings

    def fix_menu(self) -> QMenu | None:
        """The Fix dropdown as it would open right now — a test's way in."""
        popup = self.fix_button.menu() if self.fix_button is not None else None
        if popup is not None:
            self._fill_fix_menu(popup)
        return popup

    def _set_project(self, project_id: NodeId | None) -> None:
        if project_id == self._project_id:
            return
        self._project_id = project_id
        self._refresh()

    def _on_found(self, project_id: NodeId, *_rest: object) -> None:
        """A fresh reading landed. Only this panel's project can change what it lists."""
        if project_id == self._project_id:
            self._refresh()

    def _refresh(self) -> None:
        self._findings = self._found_by.of(self._project_id) if self._project_id is not None else ()
        self.list.blockSignals(True)
        self.list.clear()
        ink = self.palette().text().color()
        for finding in self._findings:
            item = QListWidgetItem(finding.subject or finding.check)
            item.setIcon(problem_icon(ink))
            item.setData(DETAIL_ROLE, finding.message)
            item.setData(TRAILING_ROLE, self._key(finding.subject_id))
            item.setToolTip(f"{finding.check}\n\n{finding.message}")
            if self._library.has(finding.subject_id):
                item.setData(SUBJECT_ROLE, finding.subject_id)
            self.list.addItem(item)
        self.list.blockSignals(False)
        self.empty.say("" if self._findings else NOTHING_WRONG)
        self._refresh_fix()
        self._say_reading(f"({len(self._findings)})" if self._findings else "")

    def _key(self, subject_id: str) -> str:
        """The step's readable key at the row's right — short, and the one every other
        listing prints. The check's id is a fact for a filter, not for a column, so it is
        in the tooltip where `--json` users can still see what to say."""
        if not self._library.has(subject_id):
            return ""
        node = self._library.node(subject_id)
        return self._key_of(node) if isinstance(node, Step) else ""

    def _say_reading(self, reading: str) -> None:
        if reading != self._reading:
            self._reading = reading
            self.reading_changed.emit(reading)

    # -- landing on a problem ------------------------------------------------------------------

    def _subject(self) -> str | None:
        item = self.list.currentItem()
        subject = item.data(SUBJECT_ROLE) if item is not None else None
        return subject if isinstance(subject, str) else None

    def _reveal(self) -> None:
        """Select the step and put the canvas on it — the step's own verb, against a
        context naming exactly it, the way a table row reveals itself."""
        subject = self._subject()
        if subject is not None:
            self._actions.run("steps.reveal", _naming(subject))

    def _details(self) -> None:
        subject = self._subject()
        if subject is not None:
            self._actions.run("steps.details", _naming(subject))

    # -- handing it to an agent ----------------------------------------------------------------

    def _refresh_fix(self) -> None:
        if self.fix_button is None:
            return
        count = len(self._findings)
        self.fix_button.setText(
            f"Fix {count} Problem{'' if count == 1 else 's'}" if count else "Fix Problems"
        )
        self.fix_button.setEnabled(bool(count))
        self.fix_button.setToolTip("Open an agent on these problems" if count else NO_AGENT_YET)

    def _fill_fix_menu(self, popup: QMenu) -> None:
        """One entry per launch profile, greyed with its own reason — a profile's terminal
        may be missing where another's is not. Rebuilt every time it opens."""
        popup.clear()
        if self._fix_profiles is None:
            return
        for index, (name, refusal) in enumerate(self._fix_profiles()):
            label = f"{name} (default)" if index == 0 else name
            entry = popup.addAction(f"{label} — {refusal}" if refusal else label)
            entry.setEnabled(not refusal)
            entry.triggered.connect(partial(self._run_fix, name))

    def _run_fix(self, profile: str, _checked: bool = False) -> None:
        if self._fix is None or self._project_id is None or not self._findings:
            return
        self._fix(self._project_id, self._findings, profile)


def _naming(step_id: str) -> Context:
    return Context({SCOPE_SELECTION: (ContextNode(selection_uri("step", step_id)),)})
