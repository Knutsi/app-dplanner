"""One Type toggle, declared once: the ``ActionSpec`` an aspect module registers.

Eleven aspects each carried the same three functions — *is a step focused*, *is the aspect
on*, *flip it* — differing only in what a fresh entry holds. This is that shape written
once. A module hands over its ``enabled`` predicate and a ``fresh`` entry, and gets back a
checkable Step ▸ Type verb whose off is :func:`~dplanner.domain.shelf.turn_off` and whose
on is :func:`~dplanner.domain.shelf.turn_on` — so nothing is lost on the way out, no
confirmation is needed, and the CLI's ``clear`` builds the very same command.
"""

from collections.abc import Callable, Mapping
from typing import Any

from PySide6.QtGui import QColor, QIcon

from dplanner.domain.model import Library, Project, Step
from dplanner.domain.shelf import turn_off, turn_on
from dplanner.framework.action_registry import DISABLED, ActionSpec, ActionState
from dplanner.framework.context import Context
from dplanner.framework.step_selection import focused_step
from dplanner.framework.undo import UndoService


def aspect_toggle(
    *,
    id: str,  # noqa: A002 — the spec field it fills.
    label: str,
    order: int,
    module_id: str,
    library: Library,
    undo: UndoService[Library],
    enabled: Callable[[Step], bool],
    fresh: Callable[[Step, Project], Mapping[str, Any]],
    leaving: Mapping[str, Any] | None = None,
    icon: Callable[[QColor], QIcon] | None = None,
    tip: str = "",
    refusal: Callable[[Step], str] | None = None,
) -> ActionSpec:
    """A Step ▸ Type toggle for one aspect.

    ``fresh`` is what turning on writes when the shelf holds nothing — a marker, or a
    generated milestone label. ``leaving`` is what turning off leaves in the entry's place:
    nothing for a marker aspect, the opt-out for one whose default is on. ``refusal`` says why
    a step cannot carry the aspect at all — "" when it can — and the toggle is then greyed
    with the reason in its words, never hidden.
    """

    def refused(step: Step) -> str:
        return refusal(step) if refusal is not None else ""

    def state(context: Context) -> ActionState:
        step = focused_step(context, library)
        if step is None:
            return DISABLED
        why = refused(step)
        if why:
            return ActionState(enabled=False, checked=enabled(step), label=f"{label} — {why}")
        return ActionState(checked=enabled(step))

    def run(context: Context) -> None:
        step = focused_step(context, library)
        if step is None or refused(step):
            return
        if enabled(step):
            undo.push(
                turn_off(step.id, module_id, leaving=dict(leaving or {}), label=f"Remove {label}")
            )
        else:
            project = library.project_of(step.id)
            undo.push(
                turn_on(step, module_id, fresh=dict(fresh(step, project)), label=f"Add {label}")
            )

    return ActionSpec(
        id=id,
        label=label,
        menu="Step",
        group="classify",
        submenu="Type",
        order=order,
        icon=icon,
        tip=tip,
        state=state,
        run=run,
    )
