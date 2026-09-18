"""Which repository is which: the plan's, the locations a project names, and where each
is on this machine.

A project answers two questions, and they want different storage. *Where does the plan
live?* — the **plan repository** — is derived: the git repository enclosing the project
directory, exactly as it always was. *Which places is it about?* — its **locations**,
each a role, a repository and a position — is a stored fact, the table in
``project.dproj``, shared with everyone who opens the plan. *Where is each of those on
this machine?* is the library file's checkouts map, per user, per machine, and
:func:`dplanner.domain.locations.place` answers it row by row. This module is the one
derivation over all three, and every reader — ``project show``, lint, the Run Agent seams,
the Repositories card, the Project dialog, the agent briefing — asks it rather than
comparing paths of its own.

Three states, read off the code rows. **Separated** is the shape the application wants.
**Colocated** is a plan kept inside the code it plans: the same remote, or either checkout
inside the other. And **legacy** is a project with no code location at all — the shape
every project had before the fact existed — read as colocated by every derivation (Run
Agent opens in the plan's own repository, GitHub refs read its origin), so nothing breaks
on the day the build updates, and warned about until it is moved or the colocation is
accepted.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dplanner.core.storage.locations import (
    canonical_remote,
    find_repo_root,
    origin_url,
    remote_label,
)
from dplanner.domain.locations import CODE, ManagedFor, Placement, place
from dplanner.domain.model import Project

LEGACY = "legacy"
COLOCATED = "colocated"
SEPARATED = "separated"

# The value of Project.colocation that says the people on this project decided the plan
# stays inside its code repository. Absent means warn.
ACCEPTED = "accepted"


@dataclass(frozen=True)
class RepositoryFacts:
    """The plan repository and every location's placement, as this machine sees them."""

    plan_root: Path | None  # The plan repository's root; None when the folder left git.
    plan_remote: str  # Its origin as git prints it; "" for a local-only plan repository.
    placements: tuple[Placement, ...]  # One per location, in the table's order.
    colocation: str  # "" or ACCEPTED.

    @property
    def code(self) -> Placement | None:
        """The primary code location — the first ``code`` row — placed."""
        return next((found for found in self.placements if found.location.role == CODE.id), None)

    @property
    def repository(self) -> str:
        """The code repository as the older readers mean it: the primary code row's."""
        code = self.code
        return code.location.repository if code is not None else ""

    @property
    def checkout(self) -> Path | None:
        """Where this machine has the primary code — a checkout a person can work in."""
        code = self.code
        return code.root if code is not None and code.here else None

    @property
    def state(self) -> str:
        if not self.repository:
            return LEGACY
        if any(
            colocated(self.plan_root, self.plan_remote, found.location.repository, found.root)
            for found in self.placements
            if found.location.role == CODE.id and not found.managed
        ):
            return COLOCATED
        return SEPARATED

    @property
    def warns(self) -> bool:
        """Whether a person, lint and the briefing should say the plan lives in its code."""
        return self.state != SEPARATED and self.colocation != ACCEPTED

    @property
    def plan_label(self) -> str:
        """The plan repository as a person knows it: ``acme/plans``, else the folder."""
        if self.plan_remote:
            return remote_label(self.plan_remote)
        return self.plan_root.name if self.plan_root is not None else ""

    @property
    def code_label(self) -> str:
        return remote_label(self.repository) if self.repository else ""

    def placement(self, location_id: str) -> Placement | None:
        return next((found for found in self.placements if found.location.id == location_id), None)


def colocated(
    plan_root: Path | None, plan_remote: str, repository: str, checkout: Path | None
) -> bool:
    """Whether the code repository is the plan repository: the same remote, spelt however,
    or either checkout inside the other — a plan kept in ``planning/`` of the code, or code
    checked out into the plan repository."""
    if not repository:
        return False
    code = canonical_remote(repository)
    if plan_remote and canonical_remote(plan_remote) == code:
        return True
    if plan_root is None:
        return False
    roots = [checkout] if checkout is not None else []
    if Path(code).is_absolute():  # A remote-less code repository, stored as its path.
        roots.append(Path(code))
    return any(_nested(plan_root, root) for root in roots)


def _nested(one: Path, other: Path) -> bool:
    first, second = one.expanduser().resolve(), other.expanduser().resolve()
    return first.is_relative_to(second) or second.is_relative_to(first)


def repository_facts(
    project: Project,
    project_dir: Path,
    checkouts: Mapping[str, Path],
    *,
    managed: ManagedFor | None = None,
    kept_root: Path | None = None,
) -> RepositoryFacts:
    """The facts for one project: its directory's repository, and every location placed
    against this machine's checkouts. ``managed`` says where a read-only location's clone
    stands; the composition root builds it from the roles, and a reader that has no roles
    to ask (the CLI's read verbs) leaves such a row unplaced. ``kept_root`` is the
    configuration directory, under which a checkout the application keeps is told apart
    from the person's own."""
    plan_root = find_repo_root(project_dir)
    plan_remote = origin_url(project_dir) if plan_root is not None else ""
    return RepositoryFacts(
        plan_root=plan_root,
        plan_remote=plan_remote,
        placements=tuple(
            place(
                location,
                checkouts=checkouts,
                plan_root=plan_root,
                plan_remote=plan_remote,
                managed=managed,
                kept_root=kept_root,
            )
            for location in project.locations
        ),
        colocation=project.colocation,
    )
