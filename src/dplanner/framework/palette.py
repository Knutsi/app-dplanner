"""The command palette: every currently-runnable action, one fuzzy search away.

Reads the same registry as the menu bar, filtered through the same context, so the palette
can never offer something the menus would refuse. It is a :class:`PickerDialog` carrying
rows built from the registry — the field, the ranking, the rows and the keyboard are the
primitive's, and this is the half that knows what a verb is.

**A row says where the verb lives.** Two entries called *Vertical* and *Horizontal* are two
riddles; *Graph ▸ Divide ▸ Vertical* is a verb you can act on. So the row is the two-line
one every rich list here uses (``list_rows.TwoLineDelegate``): the label, the menu path
under it, the shortcut at the right, and the verb's glyph where it has one — the same
glyph the pop-up menus paint, because a palette is built fresh on every open and a colour
baked into it cannot go stale.

**And the path is searchable.** A label match still wins — typing "vertical" puts *Vertical*
first — but "divide vertical" matches through the path, which is the way somebody who
remembers the submenu and not the entry would look for it.
"""

from PySide6.QtGui import QKeySequence, QPalette
from PySide6.QtWidgets import QWidget

from dplanner.framework.action_registry import (
    PATH_SEPARATOR,
    ActionRegistry,
    ActionSpec,
    key_sequences,
)
from dplanner.framework.context import ContextService
from dplanner.framework.picker import PickerDialog, PickerRow


def menu_path(spec: ActionSpec) -> str:
    """Where the verb sits in the menu bar: ``Graph ▸ Divide``, or just ``Step``.

    The group is left out on purpose — it is a module's word for a band of entries, not a
    heading anybody sees, so printing it would name something the menus never show.
    """
    return spec.menu if spec.submenu is None else spec.menu + PATH_SEPARATOR + spec.submenu


def _plain_label(spec: ActionSpec, label: str | None) -> str:
    return (label if label is not None else spec.label).replace("&", "")


class CommandPalette(PickerDialog):
    def __init__(self, registry: ActionRegistry, context: ContextService, parent: QWidget) -> None:
        ink = parent.palette().color(QPalette.ColorRole.Text)
        rows = []
        for spec, state in registry.runnable(context.current()):
            if not spec.palette:
                continue
            sequences = key_sequences(spec.shortcut)
            path = menu_path(spec)
            rows.append(
                PickerRow(
                    id=spec.id,
                    label=_plain_label(spec, state.label),
                    detail=path,
                    trailing=(
                        sequences[0].toString(QKeySequence.SequenceFormat.NativeText)
                        if sequences
                        else ""
                    ),
                    icon=None if spec.icon is None else spec.icon(ink),
                    also=path,
                )
            )
        super().__init__(rows, self._run, parent, placeholder="Type a command…")
        self._registry = registry
        self._context = context

    def _run(self, action_id: str) -> None:
        self._registry.run(action_id, self._context.current())
