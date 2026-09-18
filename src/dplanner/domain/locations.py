"""A project's locations: the repositories it is about, each with a role and a position.

A project sits in its **plan repository** — the git repository enclosing its directory,
derived and never stored — and names the places it is *about* in a table of locations
shared in ``project.dproj``. A location is a **role** (``code``, ``specs``, ``docs``,
``tests``…), a **repository** (the remote URL as git prints it, a resolved path for one
with no remote) and a **position** — a directory inside it. The roles are a registry: the
domain declares :data:`CODE`, because the CLI must find a project from a code checkout
without loading a module, and every other role is declared by the module that acts on it
in a Qt-free ``roles.py`` the composition root gathers.

Where a location *is on this machine* is the second question, and :func:`place` is the one
answer to it, in a fixed order: the checkout this machine recorded for the repository (the
library file's per-machine map), the plan repository itself when the location's repository
is the plan's, a managed clone for a role that only reads, or nowhere yet. Whether a role
needs a checkout the person can see follows from whether it *writes*: a place an agent
commits in is asked about once per repository per machine; a place that is only read is
fetched on demand and never asks. ``ARCHITECTURE.md``'s *A project names its locations*
has the reasoning.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from dplanner.core.storage.locations import canonical_remote, remote_label

ID_PREFIX = "l"


@dataclass(frozen=True)
class LocationRole:
    """One kind of place a project can name. ``writes`` is the property with consequences:
    a role that writes needs a working checkout the person owns; one that only reads may be
    served from a managed clone nobody has to pick a folder for."""

    id: str  # "specs" — the row's ``role`` in project.dproj.
    label: str  # "Specs" — how a row is captioned.
    summary: str  # One line for the Add menu and `dplanner location roles`.
    writes: bool
    several: bool = False  # May a project name more than one row of this role?
    default_path: str = ""  # Offered when a row is added: "docs", "tests".


CODE = LocationRole(
    id="code",
    label="Code",
    summary="The code this project changes — where an agent works and commits.",
    writes=True,
    several=True,
)


@dataclass(frozen=True)
class Location:
    """One row of the table. The id is what a spec source, a step's workplace and a CLI
    call name a row by, minted per project and kept while the row is edited — the same
    reason a step's folder name is frozen and its id is its identity."""

    id: str
    role: str
    repository: str
    path: str = ""  # POSIX, relative, inside the repository; "" is the root.
    ref: str = ""  # A branch or tag; "" is the repository's default branch.
    label: str = ""  # Tells two rows of one role apart: "UI", "backend".

    @property
    def canonical(self) -> str:
        return canonical_remote(self.repository)

    @property
    def repository_label(self) -> str:
        """The repository as a person knows it: ``acme/widget``."""
        return remote_label(self.repository)

    def name(self, roles: Mapping[str, LocationRole]) -> str:
        """``Code``, ``Code — UI``, or the raw role id for one this build does not know."""
        role = roles.get(self.role)
        word = role.label if role is not None else self.role
        return f"{word} — {self.label}" if self.label else word


@dataclass(frozen=True)
class Placement:
    """Where one location is on this machine, or that it is nowhere yet."""

    location: Location
    root: Path | None  # The repository's root here; None while nothing has it.
    managed: bool = False  # A clone the application keeps under config_dir, never written.

    @property
    def directory(self) -> Path | None:
        """The position on disk: the root joined with the path."""
        if self.root is None:
            return None
        return self.root / self.location.path if self.location.path else self.root

    @property
    def here(self) -> bool:
        """Whether a person could open a shell there: a checkout, not a managed clone."""
        return self.root is not None and not self.managed


def roles_by_id(roles: Iterable[LocationRole]) -> dict[str, LocationRole]:
    return {role.id: role for role in roles}


def next_id(locations: Iterable[Location]) -> str:
    """The next row id: past every ``l<n>`` the table already holds."""
    highest = 0
    for location in locations:
        suffix = location.id.removeprefix(ID_PREFIX)
        if location.id.startswith(ID_PREFIX) and suffix.isdigit():
            highest = max(highest, int(suffix))
    return f"{ID_PREFIX}{highest + 1}"


def problem(location: Location) -> str:
    """Why a row cannot stand, in words a person can act on; "" when it can. A plan is
    shared and a colleague's row is input, so this is checked on every read."""
    if not location.repository.strip():
        return "names no repository"
    if location.repository.startswith("-"):
        return f"this is not a repository address: {location.repository}"
    if location.path:
        # Read by Windows rules, which take both separators and see a drive as well as
        # a root — the project link's rule, for the same reason.
        parts = PureWindowsPath(location.path)
        if parts.anchor or ".." in parts.parts or "\\" in location.path:
            return f"the position leaves its repository: {location.path}"
    if location.ref and (
        location.ref.startswith("-")
        or ".." in location.ref
        or "@{" in location.ref
        or location.ref.endswith((".lock", "/"))
        or any(char.isspace() or char in "~^:?*[\\" for char in location.ref)
    ):
        return f"this is not a git ref: {location.ref}"
    return ""


def normalise_path(text: str) -> str:
    """A position as the table stores it: POSIX, no leading or trailing slash, "" for the
    root — so ``./docs/``, ``docs`` and ``docs/`` are one row."""
    parts = [part for part in PurePosixPath(text.strip().replace("\\", "/")).parts if part != "."]
    return "/".join(parts).strip("/")


def read_locations(raw: object) -> tuple[Location, ...]:
    """The rows as ``project.dproj`` holds them. Tolerant: a row that is not a dict, or
    names no role or repository, is skipped; a row this build cannot otherwise read is
    kept as it is, because a role is a module's word and a colleague's build may have a
    module this one lacks. A row with no id is dealt one past the others."""
    if not isinstance(raw, list):
        return ()
    found: list[Location] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        role, repository = row.get("role"), row.get("repository")
        if not (isinstance(role, str) and role and isinstance(repository, str) and repository):
            continue
        found.append(
            Location(
                id=_text(row.get("id")),
                role=role,
                repository=repository,
                path=normalise_path(_text(row.get("path"))),
                ref=_text(row.get("ref")),
                label=_text(row.get("label")),
            )
        )
    dealt: list[Location] = []
    for location in found:
        if not location.id or any(other.id == location.id for other in dealt):
            location = Location(
                next_id(dealt + found),
                location.role,
                location.repository,
                location.path,
                location.ref,
                location.label,
            )
        dealt.append(location)
    return tuple(dealt)


def write_locations(locations: Iterable[Location]) -> list[dict[str, Any]]:
    """The rows as they go to disk. Absence encodes the default: no ``path`` is the root,
    no ``ref`` the default branch, no ``label`` the only row of its role."""
    rows: list[dict[str, Any]] = []
    for location in locations:
        row: dict[str, Any] = {
            "id": location.id,
            "role": location.role,
            "repository": location.repository,
        }
        if location.path:
            row["path"] = location.path
        if location.ref:
            row["ref"] = location.ref
        if location.label:
            row["label"] = location.label
        rows.append(row)
    return rows


def as_locator(location: Location) -> dict[str, str]:
    """A location as the address a repository-reading kind takes — the git spec source's
    ``url``, ``ref`` and ``path``. One spelling, here, so a source that names a row and a
    managed clone placed for the same row land in one cache directory."""
    return {"url": location.repository, "ref": location.ref or "HEAD", "path": location.path}


def of_role(locations: Iterable[Location], role: str) -> tuple[Location, ...]:
    return tuple(location for location in locations if location.role == role)


def primary_code(locations: Iterable[Location]) -> Location | None:
    """The project's first code row — what every reader of "the code repository" means."""
    return next((location for location in locations if location.role == CODE.id), None)


def matching(locations: Iterable[Location], said: str) -> tuple[Location, ...]:
    """The rows ``said`` names: by id, or by ``role`` / ``role:label`` — an agent reading
    ``location list`` should not have to copy an id."""
    said = said.strip()
    by_id = tuple(location for location in locations if location.id == said)
    if by_id:
        return by_id
    role, _, label = said.partition(":")
    return tuple(
        location
        for location in locations
        if location.role.lower() == role.lower()
        and (not label or location.label.lower() == label.lower())
    )


def find_location(locations: Sequence[Location], said: str) -> Location:
    """One row, or :class:`LookupError` saying why not — for a verb that names one."""
    found = matching(locations, said)
    if len(found) == 1:
        return found[0]
    if not found:
        raise LookupError(f"no location {said!r} — `dplanner location list` names them")
    names = ", ".join(f"{location.id} ({location.repository_label})" for location in found)
    raise LookupError(f"{said!r} names several locations — say which by id: {names}")


def replaced(locations: Sequence[Location], location: Location) -> tuple[Location, ...]:
    """The table with the row of ``location.id`` replaced, or appended when it is new."""
    if any(existing.id == location.id for existing in locations):
        return tuple(location if existing.id == location.id else existing for existing in locations)
    return (*locations, location)


def without(locations: Sequence[Location], location_id: str) -> tuple[Location, ...]:
    return tuple(location for location in locations if location.id != location_id)


def duplicates(locations: Iterable[Location], roles: Mapping[str, LocationRole]) -> tuple[str, ...]:
    """The roles named more than once that say a project names them once."""
    counts: dict[str, int] = {}
    for location in locations:
        counts[location.role] = counts.get(location.role, 0) + 1
    return tuple(
        role
        for role, count in counts.items()
        if count > 1 and role in roles and not roles[role].several
    )


# Where a read-only location's managed clone would stand, or None for one that has no
# such place — the composition root builds it from the roles and the cache root, so this
# module never learns which roles write.
type ManagedFor = Callable[[Location], Path | None]


def place(
    location: Location,
    *,
    checkouts: Mapping[str, Path],
    plan_root: Path | None,
    plan_remote: str,
    managed: ManagedFor | None = None,
) -> Placement:
    """Where ``location`` is on this machine, in the order the module docstring gives."""
    canonical = location.canonical
    checkout = checkouts.get(canonical)
    if checkout is not None:
        return Placement(location, checkout)
    if plan_root is not None and plan_remote and canonical_remote(plan_remote) == canonical:
        return Placement(location, plan_root)
    if Path(canonical).is_absolute():
        # A repository with no remote is stored as its path: on the machine that recorded
        # it, that path is where it is.
        if plan_root is not None and _nested(plan_root, Path(canonical)):
            return Placement(location, plan_root)
        if Path(canonical).is_dir():
            return Placement(location, Path(canonical))
    if managed is not None:
        cache = managed(location)
        if cache is not None:
            return Placement(location, cache, managed=True)
    return Placement(location, None)


def _nested(one: Path, other: Path) -> bool:
    first, second = one.expanduser().resolve(), other.expanduser().resolve()
    return first.is_relative_to(second) or second.is_relative_to(first)


def _text(raw: object) -> str:
    return raw if isinstance(raw, str) else ""
