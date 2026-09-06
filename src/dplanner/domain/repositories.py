"""Which repository is which: the plan's, the code's, and whether they are one.

A project answers two questions, and they want different storage. *Where does the plan
live?* — the **plan repository** — is derived: the git repository enclosing the project
directory, exactly as it always was. *Which code does it plan?* — the **code repository** —
is a stored fact, its remote URL in ``project.dproj``, shared with everyone who opens the
plan. *Where is that code on this machine?* is the library file's row, per user, per
machine. This module is the one derivation over the three, and every reader — ``project
show``, lint, the Run Agent seams, the Repositories card, the Project dialog, the agent
briefing — asks it rather than comparing paths of its own.

Three states. **Separated** is the shape the application wants. **Colocated** is a plan
kept inside the code it plans: the same remote, or either checkout inside the other. And
**legacy** is a project with no code repository recorded at all — the shape every project
had before the fact existed — read as colocated by every derivation (Run Agent opens in the
plan's own repository, GitHub refs read its origin), so nothing breaks on the day the build
updates, and warned about until it is moved or the colocation is accepted.
"""

from dataclasses import dataclass
from pathlib import Path

from dplanner.core.storage.locations import (
    canonical_remote,
    find_repo_root,
    origin_url,
    remote_label,
)
from dplanner.domain.model import Project

LEGACY = "legacy"
COLOCATED = "colocated"
SEPARATED = "separated"

# The value of Project.colocation that says the people on this project decided the plan
# stays inside its code repository. Absent means warn.
ACCEPTED = "accepted"


@dataclass(frozen=True)
class RepositoryFacts:
    """Both repositories as this machine sees them for one project."""

    plan_root: Path | None  # The plan repository's root; None when the folder left git.
    plan_remote: str  # Its origin as git prints it; "" for a local-only plan repository.
    repository: str  # The code repository as stored on the project.
    checkout: Path | None  # Where this machine has the code; None while nothing said.
    colocation: str  # "" or ACCEPTED.

    @property
    def state(self) -> str:
        if not self.repository:
            return LEGACY
        if colocated(self.plan_root, self.plan_remote, self.repository, self.checkout):
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


def repository_facts(project: Project, project_dir: Path, checkout: Path | None) -> RepositoryFacts:
    """The facts for one project: its directory's repository, and what the project stores."""
    plan_root = find_repo_root(project_dir)
    return RepositoryFacts(
        plan_root=plan_root,
        plan_remote=origin_url(project_dir) if plan_root is not None else "",
        repository=project.repository,
        checkout=checkout,
        colocation=project.colocation,
    )
