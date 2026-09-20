"""Shorthands for the repository facts a test states by hand: one code row, placed."""

from pathlib import Path

from dplanner.domain.locations import CODE, Location, Placement
from dplanner.domain.repositories import RepositoryFacts


def code_row(url: str, location_id: str = "l1") -> tuple[Location, ...]:
    """A locations table naming one code repository — what `Project.repository` was."""
    return (Location(location_id, CODE.id, url),)


def code_facts(
    *,
    plan_root: Path | None,
    plan_remote: str = "",
    repository: str = "",
    checkout: Path | None = None,
    colocation: str = "",
) -> RepositoryFacts:
    """Facts for a project with one code location — or none, the older shape."""
    placements = (Placement(code_row(repository)[0], checkout),) if repository else ()
    return RepositoryFacts(
        plan_root=plan_root, plan_remote=plan_remote, placements=placements, colocation=colocation
    )
