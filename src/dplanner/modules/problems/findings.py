"""What is wrong with a project, derived once and read by everyone who shows it.

Two surfaces say it: the Problems panel lists the findings, and the canvas draws a
squiggle under every card one is about. Running the checks twice would be two answers
that could disagree for a moment, and it would be the *expensive* thing done twice —
lint is super-linear in the size of a plan (measured on this machine: 1 ms at 40 steps,
9 ms at 120, **66 ms at 300**), which is why nothing may run it on a canvas sync or a
keystroke.

So it settles rather than answers. :meth:`Findings.of` hands back the last reading it
took — nothing, for a project it has not been asked about before — and asks for a fresh
one after a quiet spell; when the fresh one differs, :attr:`Findings.changed` says so and
the surfaces redraw. A squiggle appearing a moment after you delete a description is the
honest behaviour: the plan is what changed, and the answer is a walk of the whole thing.

It keeps every project it has been asked about, because the canvas asks for one project
and the panel may be following another; the set is small (a library's open projects) and
each entry is a tuple of findings, not a copy of the plan.
"""

from collections.abc import Callable, Sequence

from dplanner.cli.lint import LintCheck, LintFinding, repository_finding
from dplanner.core.signals import Signal
from dplanner.domain.model import Library, NodeId
from dplanner.domain.repositories import RepositoryFacts
from dplanner.domain.store import FilesFor
from dplanner.framework.debounce import Debounced, DebounceService


class Findings:
    """Every check over a project, kept fresh on a settle and shared by its readers."""

    def __init__(
        self,
        library: Library,
        files: FilesFor,
        checks: Callable[[], Sequence[LintCheck]],
        *,
        debounce: DebounceService | None = None,
        facts_of: Callable[[NodeId], RepositoryFacts] | None = None,
    ) -> None:
        self._library = library
        self._files = files
        self._checks = checks
        self._facts_of = facts_of
        self._found: dict[NodeId, tuple[LintFinding, ...]] = {}
        # Both name the project, so a view of one project hears its own changes and no
        # others — the rule `follow_project` keeps for the model. Two signals because the
        # readers ask different questions: the panel lists the findings, so *any* change
        # to them is news; the canvas draws one mark per flagged step, so renaming a step
        # changes every message about it and nothing the canvas shows. A canvas that
        # re-synced on the first would repaint after every keystroke, one settle late.
        self.changed: Signal[NodeId] = Signal("problems.changed")
        self.flagged_changed: Signal[NodeId] = Signal("problems.flagged.changed")
        # After a quiet spell, not per signal — the reason this class exists.
        self.settle = Debounced(self._reread, parent=None, service=debounce)
        self._unsubscribes = [
            signal.connect(lambda *_a: self.settle.trigger())
            for signal in (
                library.structure_changed,
                library.edges_changed,
                library.field_changed,
                library.module_data_changed,
                library.text_edited,
            )
        ]

    def of(self, project_id: NodeId) -> tuple[LintFinding, ...]:
        """This project's findings as they last read — and an ask for a fresh reading.

        A project asked about for the first time answers nothing and arrives on the next
        settle, which is what keeps the caller off the expensive path.
        """
        if project_id not in self._found:
            self._found[project_id] = ()
            self.settle.trigger()
        return self._found[project_id]

    def flagged(self, project_id: NodeId) -> frozenset[str]:
        """The ids of everything in this project a finding is about — what the canvas
        needs, which is the question and not the answers."""
        return self._subjects(self.of(project_id))

    def dispose(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        self.settle.cancel()

    # -- the reading -----------------------------------------------------------------------

    def _reread(self) -> None:
        """Re-run every check over every project anybody is showing, and say which moved."""
        moved: list[tuple[NodeId, bool]] = []
        for project_id in list(self._found):
            found = self._read(project_id)
            was = self._found[project_id]
            if found != was:
                self._found[project_id] = found
                moved.append((project_id, self._subjects(found) != self._subjects(was)))
        # Emitted after every reading is stored, so a listener that asks about a second
        # project inside the first's slot gets the new answer rather than the old one.
        for project_id, flagged_moved in moved:
            self.changed.emit(project_id)
            if flagged_moved:
                self.flagged_changed.emit(project_id)

    @staticmethod
    def _subjects(found: Sequence[LintFinding]) -> frozenset[str]:
        return frozenset(finding.subject_id for finding in found)

    def _read(self, project_id: NodeId) -> tuple[LintFinding, ...]:
        """Every check over this project, the repository question first, as lint runs them.

        Sorted by check and then by subject, so like sits with like — a list of problems is
        read a kind at a time.
        """
        if not self._library.has(project_id):
            return ()
        project = self._library.project(project_id)
        found: list[LintFinding] = []
        if self._facts_of is not None:
            # The plan's own repository question, asked before any module's — exactly as
            # `project lint` asks it. The facts arrive through a callback because they are
            # the store's, and `origin_url` is memoised on the file's mtime, so a rebuild
            # does not shell out.
            repository = repository_finding(project, self._facts_of(project.id))
            if repository is not None:
                found.append(repository)
        for check in self._checks():
            found += check(self._library, project, self._files)
        return tuple(sorted(found, key=lambda finding: (finding.check, finding.subject)))
