"""Auto-progress, in the running application: one checkable verb over the picked arrows.

*Graph ▸ Auto-progress* sits in the links band beside Remove Link and Redirect, so the
arrow's right-click and the mixed pick's *Links* child render it with no word from the
canvas. It acts on every picked link as one undo step. How such a link looks is the
composition root's translation (``edge_accents``), since the canvas never learns what an
aspect means; which arrows are picked is the canvas's answer, handed over as
``picked_links`` because modules never import each other.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from dplanner.domain.commands import Command, CompositeCommand, SetModuleDataCommand
from dplanner.domain.model import Edge, Library, Step, StepId
from dplanner.framework.action_registry import ActionRegistry, ActionSpec, ActionState
from dplanner.framework.context import Context
from dplanner.framework.undo import UndoService
from dplanner.modules.auto_progress.aspect import (
    DATA_FORMAT,
    MODULE_ID,
    flagged,
    with_sources,
)

LABEL = "&Auto-progress"


@dataclass(frozen=True)
class AutoProgressDeps:
    library: Library
    undo: UndoService[Library]
    actions: ActionRegistry
    # The arrows picked on the canvas, as (waiter, kind, source) — the graph editor's own
    # reading of the selection, handed over by the root.
    picked_links: Callable[[Context], Sequence[Edge]]
    # Only an agent reads the briefing that says what to collect, so only an agent step
    # may collect; the composition root knows what marks one.
    is_agent: Callable[[Step], bool]
    key_of: Callable[[Step], str]


class AutoProgressModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: AutoProgressDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        self._deps.actions.register(
            ActionSpec(
                id="links.auto_progress",
                label=LABEL,
                menu="Graph",
                group="links",
                order=15,  # After Remove Link (10), before the Redirect child (20).
                # No glyph: a checked entry wearing one shows no tick in this theme's menus,
                # and whether a link auto-progresses is what this entry has to say.
                tip="The waiting step may start once these links' sources are ready for "
                "review, and lands their work itself",
                state=self._state,
                run=self._run,
            )
        )

    def _state(self, context: Context) -> ActionState:
        links = self._deps.picked_links(context)
        if not links:
            return ActionState(enabled=False, checked=False, label=f"{LABEL} — pick links first")
        if any(kind != "requires" for _waiter, kind, _source in links):
            return ActionState(
                enabled=False, checked=False, label=f"{LABEL} — only a requires link can"
            )
        for waiter in self._waiters(links):
            if not self._deps.is_agent(waiter):
                name = self._deps.key_of(waiter) or f"“{waiter.title}”"
                return ActionState(
                    enabled=False, checked=False, label=f"{LABEL} — {name} is not an agent step"
                )
        return ActionState(checked=self._all_on(links))

    def _run(self, context: Context) -> None:
        links = self._deps.picked_links(context)
        if not self._state(context).enabled:
            return
        on = not self._all_on(links)
        label = "Set Auto-progress" if on else "Clear Auto-progress"
        commands: list[Command] = []
        for waiter in self._waiters(links):
            picked = [source for step_id, _kind, source in links if step_id == waiter.id]
            entry = with_sources(waiter, picked, on)
            commands.append(SetModuleDataCommand(waiter.id, MODULE_ID, entry, label=label))
        self._deps.undo.push(CompositeCommand(label, commands))

    def _waiters(self, links: Sequence[Edge]) -> list[Step]:
        ids: dict[StepId, None] = dict.fromkeys(waiter for waiter, _kind, _source in links)
        return [self._deps.library.step(step_id) for step_id in ids]

    def _all_on(self, links: Sequence[Edge]) -> bool:
        library = self._deps.library
        return all(source in flagged(library.step(waiter)) for waiter, _kind, source in links)
