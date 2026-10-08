"""The window's half of the squad claims: who holds which step, read from each project's
``claims/`` and said on the canvas and in the Control Centre.

Nothing watches that directory, and nothing in the model changes when a claim does — a
coordinator's ``claim take`` writes beside the plan, and a lease lapses with no write at all —
so this module **polls**: every :data:`POLL_MS` a fingerprint of each project's claims and
questions (the questions say whether a quiet squad is parked), and a full re-read once a
minute for the clock alone. When what it holds for a project moves, :attr:`changed` names
the project and every view of it re-reads. Who holds a step is ``claims.read_holdings``,
the same reading every verb makes.

The one write is a person's: *End Squad Claim* ends the claim holding the focused step and
stops its workers — the window's *Clear*, the same act as ``dplanner claim end``
(``ownership.end``). Not a plan edit and not undoable:
the claim is not in the model, as the at-work banner's *Clear* is not.
"""

import getpass
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from dplanner.core.signals import Signal
from dplanner.domain import claims, questions
from dplanner.domain.claims import Holding
from dplanner.domain.model import Library, ProjectId, Step, StepId, now_stamp
from dplanner.framework.action_registry import ENABLED, ActionRegistry, ActionSpec, ActionState
from dplanner.framework.context import Context
from dplanner.modules.agent_claims import ownership

MODULE_ID = "agent_claims"
POLL_MS = 2000
# A lease runs out with nothing written, so the clock alone is reason to look again.
CLOCK_S = 60.0

END_LABEL = "End S&quad Claim"


@dataclass(frozen=True)
class AgentClaimsDeps:
    library: Library  # Which projects there are.
    project_dir: Callable[[ProjectId], Path]
    actions: ActionRegistry
    parent: QWidget  # Owns the timer: a discarded build stops polling.


class AgentClaimsModule:
    id = MODULE_ID

    def __init__(self, deps: AgentClaimsDeps) -> None:
        self._deps = deps
        self._seen: dict[ProjectId, tuple[object, ...]] = {}
        self._held: dict[ProjectId, dict[StepId, Holding]] = {}
        self._read_at = 0.0
        self.changed: Signal[str] = Signal("agent_claims.changed")
        self._timer = QTimer(deps.parent)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self.refresh)

    def register(self) -> None:
        self._deps.actions.register(
            ActionSpec(
                id="agent.end_claim",
                label=END_LABEL,
                menu="Step",
                group="agent",
                order=45,
                tip="Take the step's squad off all of its steps — the squad's coordinator"
                " stands down at its next check",
                state=self._can_end,
                run=self._end,
            )
        )
        self._timer.start()
        self.refresh()

    # -- what the window reads -------------------------------------------------------------

    def holding(self, project_id: ProjectId) -> Mapping[StepId, Holding]:
        return self._held.get(project_id, {})

    def held_by(self, step: Step) -> str:
        """Who holds the step, in words — ``kettle``, ``kettle · parked`` — or ""."""
        held = self.holding(self._deps.library.project_of(step.id).id).get(step.id)
        return "" if held is None else claims.holder_words(held)

    def chip(self, project_id: ProjectId, step_id: StepId) -> tuple[str, str]:
        """The squad chip a card wears — its words and tone: parked is still owned and
        quiet, abandoned is amber — or ("", "") for a step nobody holds."""
        held = self.holding(project_id).get(step_id)
        if held is None:
            return "", ""
        return claims.holder_words(held), "attention" if held.state == claims.ABANDONED else ""

    def refresh(self) -> None:
        """Re-read each project whose claims or questions moved on disk — every project once
        a minute, since a lease lapses with no write — and say which changed."""
        clock = time.monotonic() - self._read_at >= CLOCK_S
        if clock:
            self._read_at = time.monotonic()
        now = now_stamp()
        for project in self._deps.library.projects:
            directory = self._deps.project_dir(project.id)
            stamp = (claims.fingerprint(directory), questions.fingerprint(directory))
            if stamp == self._seen.get(project.id) and not clock:
                continue
            self._seen[project.id] = stamp
            held = claims.read_holdings(directory, now) if stamp[0] else {}
            if held != self._held.get(project.id, {}):
                self._held[project.id] = held
                self.changed.emit(project.id)

    # -- End Squad Claim -------------------------------------------------------------------

    def _focused(self, context: Context) -> Holding | None:
        step_id = context.focus_entity("step")
        library = self._deps.library
        if step_id is None or not library.has(step_id):
            return None
        return self.holding(library.project_of(step_id).id).get(step_id)

    def _can_end(self, context: Context) -> ActionState:
        if self._focused(context) is None:
            return ActionState(enabled=False, label="End Squad Claim — no squad holds this step")
        return ENABLED

    def _end(self, context: Context) -> None:
        held = self._focused(context)
        if held is None:
            return
        directory = self._deps.project_dir(held.claim.project)
        by = {"kind": questions.PERSON, "name": getpass.getuser()}
        with suppress(LookupError, ValueError):  # Ended meanwhile: the refresh shows it.
            ownership.end(directory, held.claim.id, by, "cleared")
        self.refresh()
