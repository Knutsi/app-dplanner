"""The Problems panel, for whoever hosts it.

It is the graph tab that does — clicking a problem moves the canvas to the step it is
about, and a trip across the window is a long one for that — so this module registers no
panel and offers the widget instead, the ``step_properties`` arrangement. The host tells
it which project to show; it follows a context like any panel, and acts through the
registry like any surface.

What it shows arrives as ``checks``: the assembled ``LintCheck`` registry, the very list
``dplanner project lint`` runs. What it can hand to an agent arrives as two plain-data
callbacks over the launch profiles, wired by the composition root from the agent module —
the ``LibraryWatchDeps.hand_to_agent`` arrangement, so neither module learns the other.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtWidgets import QWidget

from dplanner.cli.lint import LintCheck, LintFinding
from dplanner.domain.model import Library, NodeId, Step
from dplanner.domain.repositories import RepositoryFacts
from dplanner.domain.store import FilesFor
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.debounce import DebounceService
from dplanner.modules.problems.findings import Findings
from dplanner.modules.problems.panel import ProblemsPanel

MODULE_ID = "problems"

# Each launch profile's name and why it cannot run here ("" when it can) — plain data, so
# the agent module's own types stay its own.
type FixProfiles = Callable[[], Sequence[tuple[str, str]]]
# (project, the problems on screen, the profile's name) → True when a shell was spawned.
type FixWithAgent = Callable[[NodeId, Sequence[LintFinding], str], bool]


@dataclass(frozen=True)
class ProblemsDeps:
    library: Library
    actions: ActionRegistry
    files: FilesFor
    # Every module's answer to "what can be wrong", assembled by the composition root and
    # shared verbatim with `dplanner project lint`.
    checks: Callable[[], Sequence[LintCheck]]
    debounce: DebounceService | None = None
    parent: QWidget | None = None
    # The plan's own repository question is the store's to answer, so it arrives as
    # a callback — the same one the agent module is handed.
    facts_of: Callable[[NodeId], RepositoryFacts] | None = None
    # The step's readable key ("F3") for a row's trailing note — the root's one rule,
    # so a problem names a step exactly as every other listing does.
    key_of: Callable[[Step], str] = lambda _step: ""
    # None in a build with no agent: the panel offers no way to fix, rather than a
    # disabled one — the capability is absent, not inapplicable.
    fix_profiles: FixProfiles | None = None
    fix: FixWithAgent | None = None


class ProblemsModule:
    id = MODULE_ID

    def __init__(self, deps: ProblemsDeps) -> None:
        self._deps = deps
        # One reading of what is wrong, settled and shared: the panel lists it, the canvas
        # draws a squiggle under every card it names. Running the checks twice would be
        # two answers that could disagree, and lint is the expensive thing — see
        # `findings.py` for the numbers.
        self.findings = Findings(
            deps.library,
            deps.files,
            deps.checks,
            debounce=deps.debounce,
            facts_of=deps.facts_of,
        )

    def flagged(self, project_id: NodeId) -> frozenset[str]:
        """Which of this project's steps a problem is about — what the canvas asks."""
        return self.findings.flagged(project_id)

    def register(self) -> None:
        """Nothing: this module owns a widget, not a surface of its own.

        The verb that shows the panel is the graph's own ``canvas.side_panel``, which
        takes its name and glyph from the panel spec the root writes.
        """

    def create_panel(self) -> ProblemsPanel:
        deps = self._deps
        return ProblemsPanel(
            deps.library,
            deps.actions,
            self.findings,
            key_of=deps.key_of,
            fix_profiles=deps.fix_profiles,
            fix=deps.fix,
        )
