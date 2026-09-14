"""The Tests tab's left pane: the features to read the roster through, and one filter.

**A tester reads the roster one feature at a time.** *What is being tested* is the
question a test roster is opened with, and the answer is a feature — so the features are
a standing list beside the table rather than an entry in a dropdown somebody has to think
to open. *All tests* leads it, because the whole roster is a real answer too.

**The filter limits the list, not the table.** A plan of any size has more features than
fit beside a table, and the way a person narrows them is by release: the funnel holds one
entry per milestone, and picking some leaves the features those milestones gather. It
narrows what there is to choose *from* — the table still shows whatever is picked — which
is why it sits over this list and not on the tab's own strip, where it would read as a
second filter on the rows.

A check is gathered by no milestone, so a milestone filter drops it; that is the honest
answer rather than a special case, and clearing the funnel brings it back.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtWidgets import QHBoxLayout, QListWidgetItem, QVBoxLayout, QWidget

from dplanner.domain.model import Library, Project, Step, StepId
from dplanner.domain.scope import ScopeKind, gatherers, kind_of
from dplanner.framework.list_rows import (
    DETAIL_ROLE,
    EMPHASIS_ROLE,
    HOST_ROLE,
    RULE_ROLE,
    TRAILING_ROLE,
    RichList,
)
from dplanner.framework.toolbar import FilterButton
from dplanner.framework.widgets import caption
from dplanner.theme.tokens import CAPTION_GAP, FIELD_GAP

COLLECTOR_ROLE = HOST_ROLE

PANE_WIDTH = 230  # A feature's name on one line, at the width a table can spare beside it.
ALL_TESTS = "All tests"
PANE_CAPTION = "Features"
FILTER_LABEL = "Milestone"
FILTER_TIP = "Which milestones' features to list — the table shows whatever is picked"


@dataclass(frozen=True)
class Collector:
    """One row: a step that stands for work, and what a reader needs to tell it apart."""

    step_id: StepId
    title: str
    kind: str  # The ScopeKind's label — "Feature", "Milestone", "Check".
    milestones: tuple[StepId, ...]  # Which milestones gather it; empty for a check.
    where: str  # The milestone's name, for the line under the title.
    tests: int


def collectors(
    library: Library,
    project: Project,
    scopes: Sequence[ScopeKind],
    count: Callable[[StepId], int],
    release_kind: str = "",
) -> list[Collector]:
    """Every collector the project has, in project order, with what gathers each.

    ``release_kind`` is the id of the kind a plan is cut into releases by — named by the
    composition root, never guessed here: which of the three that is is exactly the kind
    of fact a module may not know about another.

    Qt-free on purpose even though it lives beside a widget: what belongs in the list is a
    question about the graph, and a test that asks it should not have to build a window.
    """
    milestone = next((kind for kind in scopes if kind.id == release_kind), None)
    owners = (
        gatherers(library, project, carried_by=milestone.carried_by, stops_at=milestone.stops_at)
        if milestone is not None
        else {}
    )
    found = []
    for step in project.steps:
        kind = kind_of(scopes, step)
        if kind is None:
            continue
        own = (step.id,) if milestone is not None and milestone.carried_by(step) else ()
        held = own or tuple(owners.get(step.id, ()))
        names = [
            named.title or "Untitled step"
            for owner in held
            if (named := project.step(owner)) is not None and owner != step.id
        ]
        found.append(
            Collector(
                step_id=step.id,
                title=step.title or "Untitled step",
                kind=kind.label,
                milestones=held,
                where=" and ".join(names),
                tests=count(step.id),
            )
        )
    return found


def milestones_of(
    project: Project, scopes: Sequence[ScopeKind], release_kind: str = ""
) -> list[Step]:
    """The project's milestones in order — one funnel entry each."""
    kind = next((found for found in scopes if found.id == release_kind), None)
    if kind is None:
        return []
    return [step for step in project.steps if kind.carried_by(step)]


def listed(found: Sequence[Collector], wanted: Sequence[StepId]) -> list[Collector]:
    """``found`` limited to the collectors the picked milestones gather — all of them when
    nothing is picked, which is what an empty funnel means everywhere else."""
    if not wanted:
        return list(found)
    keep = set(wanted)
    return [one for one in found if keep & set(one.milestones)]


class CollectorPane(QWidget):
    """The caption, the funnel, and the list of features to read the roster through."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(CAPTION_GAP)

        head = QHBoxLayout()
        column.addLayout(head)  # Joined before it is filled; see CLAUDE.md's layout rule.
        head.setSpacing(FIELD_GAP)
        head.addWidget(caption(PANE_CAPTION, self))
        head.addStretch(1)
        self.filter = FilterButton(self, label=FILTER_LABEL)
        self.filter.setToolTip(FILTER_TIP)
        head.addWidget(self.filter)

        self.list = RichList(self)
        self.list.setSelectionMode(RichList.SelectionMode.SingleSelection)
        column.addWidget(self.list, 1)

    def show_collectors(self, found: Sequence[Collector], picked: StepId) -> StepId:
        """Fill the list and keep the pick; answers what is picked after the rebuild.

        A pick that is no longer listed — its milestone filtered away, its step deleted —
        falls back to *All tests* rather than to a neighbour: landing the reader on some
        other feature's tests would be a wrong answer where "all of them" is merely a
        wider one.
        """
        self.list.blockSignals(True)
        self.list.clear()
        self._add(ALL_TESTS, "", "", rule=True, emphasis=True, step_id="")
        for one in found:
            self._add(
                one.title,
                f"{one.kind}{f' · {one.where}' if one.where else ''}",
                str(one.tests) if one.tests else "",
                step_id=one.step_id,
            )
        wanted = picked if any(one.step_id == picked for one in found) else ""
        for index in range(self.list.count()):
            if str(self.list.item(index).data(COLLECTOR_ROLE)) == wanted:
                self.list.setCurrentRow(index)
                break
        self.list.blockSignals(False)
        return wanted

    def picked(self) -> StepId:
        item = self.list.currentItem()
        return str(item.data(COLLECTOR_ROLE)) if item is not None else ""

    def _add(
        self,
        title: str,
        detail: str,
        trailing: str,
        *,
        step_id: StepId,
        rule: bool = False,
        emphasis: bool = False,
    ) -> None:
        item = QListWidgetItem(title)
        item.setData(DETAIL_ROLE, detail)
        item.setData(TRAILING_ROLE, trailing)
        item.setData(COLLECTOR_ROLE, step_id)
        if rule:
            item.setData(RULE_ROLE, True)
        if emphasis:
            item.setData(EMPHASIS_ROLE, True)
        item.setToolTip(title if not detail else f"{title} — {detail}")
        self.list.addItem(item)

    def show_filters(self, steps: Sequence[Step]) -> list[StepId]:
        """One funnel entry per milestone; answers what is active afterwards."""
        self.filter.set_filters([(step.id, step.title or "Untitled milestone") for step in steps])
        return self.filter.active()
