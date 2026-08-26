"""The order view's tree: a wave per row, the steps that can start together beneath it.

A ``QTreeWidget`` rather than a delegate-drawn list because the shape *is* a tree — waves
hold steps — and because the wave headings are what make the view readable at a glance:
everything under the first one can be started today.
"""

from collections.abc import Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QWidget

from dplanner.domain.model import Step, StepId

# The step id on a row, so a click can say which step it means. Wave rows carry none.
STEP_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class OrderTree(QTreeWidget):
    """The waves, rebuilt whenever the graph changes. A project holds tens of steps, so a
    whole redraw is cheaper to read than a diff and cannot go stale."""

    def __init__(
        self,
        wave_label: Callable[[int], str],
        step_aspects: Callable[[StepId], list[str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("OrderTree")
        self.setHeaderHidden(True)
        self.setUniformRowHeights(True)
        self.setColumnCount(2)
        self._wave_label = wave_label
        self._step_aspects = step_aspects

    def show_waves(self, waves: Sequence[Sequence[Step]]) -> None:
        open_waves = {
            item.text(0)
            for i in range(self.topLevelItemCount())
            if (item := self.topLevelItem(i)) is not None and item.isExpanded()
        }
        # Headings carry their step count, so match on the label before the dash.
        self.clear()
        for index, wave in enumerate(waves):
            label = self._wave_label(index)
            # The count belongs in the heading, so the second column is only ever the
            # aspects — one column, one meaning.
            plural = "step" if len(wave) == 1 else "steps"
            header = QTreeWidgetItem([f"{label} — {len(wave)} {plural}", ""])
            header.setFlags(header.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.addTopLevelItem(header)
            for step in wave:
                row = QTreeWidgetItem(
                    [step.title or "Untitled step", " · ".join(self._step_aspects(step.id))]
                )
                row.setData(0, STEP_ROLE, step.id)
                header.addChild(row)
            # Everything open on the first build; after that, whatever the user left open.
            header.setExpanded(not open_waves or any(was.startswith(label) for was in open_waves))
        self.resizeColumnToContents(0)

    def step_at(self, item: QTreeWidgetItem | None) -> StepId | None:
        if item is None:
            return None
        found = item.data(0, STEP_ROLE)
        return found if isinstance(found, str) else None

    def selected_step(self) -> StepId | None:
        return self.step_at(self.currentItem())
