"""Qt-free shapes for the project surfaces that talk about repositories.

The Project dialog, the Repositories card, Open Projects and Move Plan all read the same
two repositories and use git and GitHub the same handful of ways. What they need is one
frozen bundle of callables the composition root fills in — :class:`RepositoryServices` —
so a dialog test hands over lambdas and never spawns ``git`` or ``gh``, and the module
never names a storage provider (architecture rule 8) or imports the github module (rule
5). Every member marked BLOCKING is run inside a task body off the GUI thread and reads
nothing but its arguments; the rest read the model and stay on the GUI thread.

The other shape here is what those surfaces *say*. A repository answers two questions —
which repository it is, and where it is on this machine — and :func:`code_lines` and
:func:`plan_lines` are the one derivation of both, so the dialog's columns and the panel's
card cannot word the same fact two ways.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from dplanner.core.signals import Signal
from dplanner.domain.relocate import Moved
from dplanner.domain.repositories import RepositoryFacts

MODULE_ID = "projects"

# Where people keep their checkouts, in the order one would guess. The first that exists
# is the suggestion, and clones — code and plan repositories alike — land in it.
CODE_FOLDER_CANDIDATES = (
    "Code",
    "code",
    "src",
    "repos",
    "repo",
    "dev",
    "Developer",
    "Projects",
    "projects",
    "git",
    "work",
    "workspace",
)

LOG_LIMIT = 30  # Commits per column in the Project dialog.

# Move Plan reads as two different offers and every surface must word them the same way: a
# plan still inside its code is being *set up* with a repository, a plan that has one is
# being *moved* to another. The verb behind both is `projects.move`.
SET_UP_PLAN = "Set up a plan repository…"
MOVE_PLAN = "Move Plan…"


def candidate_repositories_folders(home: Path) -> list[Path]:
    """The folders under ``home`` a person likely clones into — those that exist, in the
    order above; ``home/Code`` to be created when none does."""
    found = [home / name for name in CODE_FOLDER_CANDIDATES if (home / name).is_dir()]
    return found or [home / CODE_FOLDER_CANDIDATES[0]]


def github_url(repo: str) -> str:
    """The https URL of ``owner/repo`` — what a project records as its code repository."""
    return f"https://github.com/{repo}"


def shown_path(path: Path) -> str:
    """A path as a person writes it: ``~`` for the home directory."""
    try:
        return "~/" + path.relative_to(Path.home()).as_posix()
    except ValueError:
        return str(path)


@dataclass(frozen=True)
class RepoLines:
    """One repository as a surface states it: which repository it is, and where it is on
    this machine.

    Both lines always say something. Where nothing is recorded the line says what is
    missing instead of standing blank, and ``missing`` is what a reader greys — the same
    words, greyed the same way, in the Project dialog and on the Repositories card.
    """

    identity: str
    location: str
    identity_missing: bool = False
    location_missing: bool = False


def code_lines(facts: RepositoryFacts) -> RepoLines:
    """The code repository: its remote, and the checkout this machine has.

    With no code repository recorded the plan's own repository is where the code is — the
    older shape — so the location says that rather than nothing.
    """
    if not facts.repository:
        root = facts.plan_root
        return RepoLines(
            identity="no code repository recorded",
            location=shown_path(root) if root is not None else "not in a git repository",
            identity_missing=True,
            location_missing=root is None,
        )
    checkout = facts.checkout
    return RepoLines(
        identity=facts.code_label,
        location=(
            shown_path(checkout) if checkout is not None else "not checked out on this machine"
        ),
        location_missing=checkout is None,
    )


def plan_lines(facts: RepositoryFacts) -> RepoLines:
    """The plan repository: its remote or folder name, and its root on this machine."""
    root = facts.plan_root
    if root is None:
        # Nothing true to say about where a repository that is not there lives: the line
        # stays empty rather than inventing a second way to say the first one.
        return RepoLines(identity="not in a git repository", location="", identity_missing=True)
    return RepoLines(identity=facts.plan_label, location=shown_path(root))


@dataclass(frozen=True)
class LogEntry:
    id: str
    subject: str
    author: str
    when: str  # ISO-8601, as git prints it.


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    head_ref: str
    url: str


@dataclass(frozen=True)
class RepoLog:
    """What one repository has been up to: the branch it is on and its latest commits."""

    branch: str
    entries: tuple[LogEntry, ...]


@dataclass(frozen=True)
class RepositoryServices:
    """Everything the project surfaces do with the model's repositories, git and GitHub."""

    facts_of: Callable[[str], RepositoryFacts]
    project_dir: Callable[[str], Path]
    set_checkout: Callable[[str, Path | None], None]
    checkout_changed: Signal[str]
    plan_roots: Callable[[], list[Path]]
    # PR number -> "S7 Build the modal", for the steps of one project that carry a PR.
    pr_steps: Callable[[str], dict[int, str]]
    # BLOCKING: a repository root's log, over a root-relative scope ("" for the whole tree).
    history_for: Callable[[Path, str, int], RepoLog]
    # BLOCKING: why gh cannot be used — not installed, not signed in — or None when it can.
    gh_refusal: Callable[[], str | None]
    list_repositories: Callable[[], list[str]]  # BLOCKING: owner/repo, newest first.
    clone: Callable[[str, Path], None]  # BLOCKING: a URL or owner/repo into a directory.
    publish: Callable[[Path, str], str]  # BLOCKING: a root onto GitHub as name -> its origin.
    create_repository: Callable[[str, Path], str]  # BLOCKING: name on GitHub, cloned -> URL.
    open_prs: Callable[[str], list[PullRequest]]  # BLOCKING: a remote's open pull requests.
    # Synchronous on purpose: it rewrites the working tree, and the reload that follows
    # discards the build — ARCHITECTURE.md's *Storage operations that rewrite the working
    # tree are synchronous*.
    move_project: Callable[[str, Path, bool], Moved]
