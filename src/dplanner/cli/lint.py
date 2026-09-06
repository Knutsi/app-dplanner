"""``dplanner project lint`` — is this plan complete enough to hand to an agent?

Like ``aspect list``, this command belongs to no feature: it asks a question about all of
them. The checks arrive as arguments — each owning module's ``cli.py`` exports its own, so
what "missing" looks like and which verb closes the gap stay with the owner — and the
composition root assembles the list. Nothing here imports a module.

The run exits 1 when there are findings, so an agent gates a handover on it the way it
gates on a test suite: hand over clean.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from dplanner.cli.command import CliCommand, CliContext
from dplanner.cli.lookup import find_project
from dplanner.domain.model import Library, Project
from dplanner.domain.repositories import LEGACY, RepositoryFacts, repository_facts
from dplanner.domain.store import FilesFor


@dataclass(frozen=True)
class LintFinding:
    """One gap in a plan. ``message`` always names the verb that closes it."""

    check: str  # A stable id, e.g. "description.missing" — what --json output filters on.
    subject_id: str  # The step's — or for a project-scoped finding, the project's — id.
    subject: str  # Its title.
    message: str


# One shape for both scopes: a step-scoped check loops over ``project.steps`` itself.
LintCheck = Callable[[Library, Project, FilesFor], Sequence[LintFinding]]


def repository_finding(project: Project, facts: RepositoryFacts) -> LintFinding | None:
    """The plan's own repository question, asked before any module's: a plan kept inside
    the code it plans is what drifts, and the finding names the way out — or the way to
    keep it there on purpose, which silences it. ``project show`` prints the same line."""
    if not facts.warns:
        return None
    title = project.title or project.folder_name
    if facts.state == LEGACY:
        check = "repo.unset"
        what = (
            "no code repository is recorded, so the plan reads as living inside the code it plans"
        )
    else:
        check = "repo.colocated"
        what = "the plan lives inside the code it plans"
    return LintFinding(
        check=check,
        subject_id=project.id,
        subject=title,
        message=(
            f"{what} — `dplanner project move '{title}' --into PLAN_REPO`, or "
            f"`dplanner project set '{title}' --accept-colocation`"
        ),
    )


def commands(checks: Sequence[LintCheck]) -> list[CliCommand]:
    def _lint(context: CliContext, args: Namespace) -> int:
        library = context.library
        store = context.store
        projects = [find_project(library, args.project)] if args.project else list(library.projects)
        found: list[tuple[Project, LintFinding]] = []
        for project in projects:
            facts = repository_facts(
                project, store.project_dir(project.id), store.checkout_of(project.id)
            )
            finding = repository_finding(project, facts)
            if finding is not None:
                found.append((project, finding))
            for check in checks:
                found += [
                    (project, finding) for finding in check(library, project, context.store.files)
                ]
        rows = [
            {
                "project": project.id,
                "check": finding.check,
                "subject": finding.subject_id,
                "title": finding.subject,
                "message": finding.message,
            }
            for project, finding in found
        ]
        lines = []
        for project in projects:
            own = [finding for owner, finding in found if owner is project]
            if not own:
                continue
            lines.append(project.title or project.id)
            lines += [f"  {finding.subject}: {finding.message}" for finding in own]
        lines.append(f"{len(found)} findings" if found else "Clean.")
        context.report({"findings": rows, "count": len(found)}, "\n".join(lines))
        return 1 if found else 0

    def _configure(parser: ArgumentParser) -> None:
        parser.add_argument(
            "project",
            nargs="?",
            help="project id, folder name, or part of its title; omitted lints them all",
        )

    return [
        CliCommand(
            path=("project", "lint"),
            summary="Report what a plan is missing before handover — undescribed, "
            "uninstructed or unestimated steps, unimplemented requirements, dangling "
            "links. Exits 1 when there are findings.",
            configure=_configure,
            run=_lint,
            examples=("dplanner project lint", "dplanner project lint discovery --json"),
        )
    ]
