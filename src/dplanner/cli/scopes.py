"""``dplanner scope show`` — what one collector gathers.

Like ``aspect list`` and ``project lint``, this verb belongs to no feature: a check, a
feature and a release are one derivation asked with different stopping rules, so a verb per
aspect would be three near-copies of the same report that could drift apart. The kinds and
the coverage walk arrive as arguments — the composition root, the one place that may name
every aspect, assembles them — and nothing here imports a module.

The four lint checks live here for the same reason. Three of them exist only because the
walk can answer them: a step gathered by two features is genuinely ambiguous, a step two
releases both reach is counted whole by each of them, and a step carrying tests that no
feature gathers is work nobody planned into a release.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from dplanner.cli.command import CliCommand, CliContext, CliError
from dplanner.cli.lint import LintCheck, LintFinding
from dplanner.cli.lookup import find_step, step_arg
from dplanner.domain.model import Library, Project, Step, StepId
from dplanner.domain.scope import (
    ScopeKind,
    StepPredicate,
    cone,
    gatherers,
    kind_of,
    leaders,
    stops_for,
)
from dplanner.domain.store import FilesFor

# What a scope covers, as the module that owns tests answers it: (id, title, step title).
type CoveredTest = tuple[str, str, str]
# The same question the Covers tab asks: everything at and behind a step, optionally
# truncated at the collectors it hands off to.
type CoveredBy = Callable[[Library, Project, StepId, StepPredicate | None], Sequence[CoveredTest]]


@dataclass(frozen=True)
class _Group:
    title: str
    tests: Sequence[CoveredTest]


def commands(*, kinds: Sequence[ScopeKind], covered_by: CoveredBy) -> list[CliCommand]:
    def show(context: CliContext, args: Namespace) -> int:
        step = find_step(context.library, args.step, context.current)
        # The step names its project, so this reads the same with or without a current one.
        project = context.library.project_of(step.id)
        kind = kind_of(kinds, step)
        if kind is None:
            raise CliError(
                f"{step.title!r} is not a scope — `dplanner feature set`, "
                "`dplanner release set` or `dplanner check set` makes it one"
            )
        stops_at = None if args.cumulative else kind.stops_at
        walked = cone(context.library, project, step.id, stops_at=stops_at)
        groups = [
            _Group(
                f"{_label(kinds, leader)}: {leader.title or 'Untitled step'}",
                covered_by(context.library, project, leader.id, stops_for(kinds, leader)),
            )
            for leader in leaders(kinds, kind, walked.steps)
        ]
        claimed = {test_id for group in groups for test_id, _t, _o in group.tests}
        direct = [
            found
            for found in covered_by(context.library, project, step.id, stops_at)
            if found[0] not in claimed
        ]
        every = [found for group in groups for found in group.tests] + direct
        data = {
            "step": step.id,
            "kind": kind.id,
            "cumulative": bool(args.cumulative),
            "gathers": [
                {
                    "title": group.title,
                    "tests": [_row(found) for found in group.tests],
                }
                for group in groups
            ],
            "direct": [_row(found) for found in direct],
            "after": [
                {"id": boundary.id, "title": boundary.title} for boundary in walked.boundaries
            ],
        }
        context.report(data, _render(step.title, kind, groups, direct, every, walked.boundaries))
        return 0

    def configure(parser: ArgumentParser) -> None:
        step_arg(parser)
        parser.add_argument(
            "--cumulative",
            action="store_true",
            help="everything behind it, not only what it adds since the previous one",
        )

    return [
        CliCommand(
            path=("scope", "show"),
            summary="What a check, feature or milestone gathers: its features and tests.",
            configure=configure,
            run=show,
            examples=(
                "dplanner scope show v3",
                "dplanner scope show 'Bulk import'",
                "dplanner scope show v3 --cumulative",
            ),
        )
    ]


def lint_checks(
    *,
    kinds: Sequence[ScopeKind],
    covered_by: CoveredBy,
    carries_tests: Callable[[Step], bool],
) -> list[LintCheck]:
    """Four findings the walk can answer and nothing else can.

    ``carries_tests`` asks about *this step's own* tests, which is a different question from
    what it gathers: a release gathers plenty and carries none, and reporting it as work
    nobody planned would be nonsense. It arrives as a function so this file still imports no
    module.
    """

    def gathers_nothing(library: Library, project: Project, _files: FilesFor) -> list[LintFinding]:
        found = []
        for step in project.steps:
            kind = kind_of(kinds, step)
            if kind is None or covered_by(library, project, step.id, kind.stops_at):
                continue
            found.append(
                LintFinding(
                    check="scope.gathers-nothing",
                    subject_id=step.id,
                    subject=step.title,
                    message=f"a {kind.label.lower()} with no tests behind it — link it to "
                    f"work that carries tests, or `dplanner {_verb(kind)} clear "
                    f"'{step.title}'`",
                )
            )
        return found

    def _gathered_twice(
        library: Library, project: Project, kind: ScopeKind, check: str, remedy: str
    ) -> list[LintFinding]:
        owners = gatherers(library, project, carried_by=kind.carried_by, stops_at=kind.stops_at)
        return [
            LintFinding(
                check=check,
                subject_id=step.id,
                subject=step.title,
                message=f"gathered by {_titles(project, owners[step.id])} at once — both "
                f"wait on it, so both count it. {remedy}",
            )
            for step in project.steps
            if len(owners.get(step.id, ())) > 1 and not kind.carried_by(step)
        ]

    def shared(library: Library, project: Project, _files: FilesFor) -> list[LintFinding]:
        sub = _grouping_kind(kinds)
        if sub is None:
            return []
        return _gathered_twice(
            library,
            project,
            sub,
            "scope.shared",
            f"Link one {sub.label.lower()} behind the other if only one should.",
        )

    def crosses_milestones(
        library: Library, project: Project, _files: FilesFor
    ) -> list[LintFinding]:
        """A step two releases both reach without passing a third.

        The same question ``scope.shared`` asks of features, asked of what partitions the
        graph: releases are meant to be a chain, so a step hanging off two of them is work
        two of them each count whole. One walk, two stopping rules, one report shape.
        """
        return [
            finding
            for kind in _partitioning_kinds(kinds, project)
            for finding in _gathered_twice(
                library,
                project,
                kind,
                "scope.crosses-milestones",
                f"A {kind.label.lower()} is meant to follow the one before it; link the "
                "later one behind the earlier, or move the step into one of them.",
            )
        ]

    def ungathered(library: Library, project: Project, _files: FilesFor) -> list[LintFinding]:
        sub = _grouping_kind(kinds)
        if sub is None or not any(sub.carried_by(step) for step in project.steps):
            return []  # A project with no features has not made the claim to fall short of.
        owners = gatherers(library, project, carried_by=sub.carried_by, stops_at=sub.stops_at)
        return [
            LintFinding(
                check="scope.ungathered",
                subject_id=step.id,
                subject=step.title,
                message=f"carries tests but no {sub.label.lower()} waits on it — nothing "
                "gathers it, so no milestone counts it. Link it behind one.",
            )
            for step in project.steps
            # A collector is gathered by construction: it is what gathers.
            if step.id not in owners and kind_of(kinds, step) is None and carries_tests(step)
        ]

    return [gathers_nothing, shared, crosses_milestones, ungathered]


# -- shared shapes -------------------------------------------------------------------------


def _titles(project: Project, ids: Sequence[StepId]) -> str:
    found = [project.step(step_id) for step_id in ids]
    return " and ".join(repr(step.title) for step in found if step is not None)


def _partitioning_kinds(kinds: Sequence[ScopeKind], project: Project) -> list[ScopeKind]:
    """The kinds that cut the graph into stretches — the releases, in this build.

    Derived, not declared: a kind whose cone stops at its own carriers partitions the
    graph (a milestone does; a check, which stops at nothing and stands for everything
    behind it, does not), and the finest such kind is the grouping kind the other checks
    already speak for. Asked of the project's own steps because that is where a carrier
    exists to ask about — which also makes a project with no releases quietly answer none.
    """
    sub = _grouping_kind(kinds)
    found = []
    for kind in kinds:
        if kind is sub:
            continue
        carriers = [step for step in project.steps if kind.carried_by(step)]
        if carriers and all(kind.stops_at(step) for step in carriers):
            found.append(kind)
    return found


def _grouping_kind(kinds: Sequence[ScopeKind]) -> ScopeKind | None:
    """The kind the others are read as lists of — the feature, in this build.

    Named once here rather than spelled ``"feature"`` in three checks, so the lint
    still says something true in a build that ships a different set of collectors.
    """
    wanted = {kind.gathers for kind in kinds if kind.gathers}
    return next((kind for kind in kinds if kind.id in wanted), None)


def _label(kinds: Sequence[ScopeKind], step: Step) -> str:
    kind = kind_of(kinds, step)
    return kind.label if kind is not None else "Step"


def _verb(kind: ScopeKind) -> str:
    """The noun a kind's own verbs live under: ``step_milestone`` → ``milestone``."""
    return kind.id.removeprefix("step_")


def _row(found: CoveredTest) -> dict[str, str]:
    test_id, title, owner = found
    return {"id": test_id, "title": title, "step_title": owner}


def _render(
    title: str,
    kind: ScopeKind,
    groups: Sequence[_Group],
    direct: Sequence[CoveredTest],
    every: Sequence[CoveredTest],
    boundaries: Sequence[Step],
) -> str:
    width = max((len(test_id) for test_id, _t, _o in every), default=0)

    def rows(tests: Sequence[CoveredTest], indent: str) -> list[str]:
        return [
            f"{indent}{test_id:<{width}}  {test_title}  ({owner})"
            for test_id, test_title, owner in tests
        ]

    count = f"{len(every)} test{'' if len(every) == 1 else 's'}"
    lines = [f"{title or 'Untitled step'} ({kind.label.lower()}): {count}"]
    for group in groups:
        lines.append(f"  {group.title}")
        lines += rows(group.tests, "    ")
    if groups and direct:
        lines.append("  Directly")
    lines += rows(direct, "    " if groups else "  ")
    if boundaries:
        after = ", ".join(step.title or "Untitled step" for step in boundaries)
        lines.append(f"  (after {after} — `--cumulative` for everything behind it)")
    return "\n".join(lines)
