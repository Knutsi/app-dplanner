"""Where a step's run works: its name, its checkout, its worktree and its mainline.

The launch prepares exactly what the briefing tells the agent — the worktree by this name,
under this checkout — so both read these functions rather than each composing the name.
Headless, like the rest of the package: a daemon names a run the way the window does.

**The worktree is prepared here, in Python, for every kind of run** (:func:`prepare`): a
headless run has no shell script to do it in, and one implementation for both is what keeps
a terminal run and a headless one on the same branch from the same start. A new branch
starts from the remote, never from whatever the checkout has checked out: fetch, then start
from the :class:`BranchPlan`'s ``start`` — a stretch's feature branch, the code location's
own mainline, else the remote's default branch — with no upstream, so a bare push from the
agent's branch reaches nothing shared. A landing's worktree is on the feature branch itself,
tracking it. **A worktree that cannot be prepared stops the run with git's reason** — the
first version swallowed the error, and two agents launched into "fresh worktrees" did their
work on the same branch of the main checkout. The directory is excluded through
``.git/info/exclude`` (local, never versioned) and is deliberately not ``.dplanner/``: that
name is the pointer *file* a project kept in a subfolder leaves at the repository root.
"""

import re
from contextlib import suppress
from pathlib import Path

from dplanner.core.fsio import slugify

# Where a step's worktree lives, under the repository root: a sibling of the `.dplanner`
# index file, never inside it. Declared beside that file, since the plan repository scan
# has to know to skip it.
from dplanner.core.storage.pointer import WORKTREES_DIR
from dplanner.core.storage.sparse import (
    CHECKOUT_S,
    LOCAL_S,
    REMOTE_S,
    GitError,
    run_git,
    valid_ref,
)
from dplanner.domain.locations import Placement
from dplanner.domain.model import Step
from dplanner.domain.repositories import RepositoryFacts
from dplanner.modules.step_ticket.aspect import read as ticket_read
from dplanner.planning.agent import workplace
from dplanner.planning.branches import DEFAULT_BRANCHES, DEFAULT_START, BranchPlan
from dplanner.planning.kinds import key_of

# A run name is a branch name's last component, so it keeps to what git's ref rules allow
# everywhere: letters, digits, `.`, `_` and `-`, none of them doubled up or at an end.
RUN_NAME_MAX = 60


def ref_safe(text: str) -> str:
    """``text`` as one component of a git ref: nothing a ref rule refuses, and nothing a
    shell would quote — the run name is written into three script dialects verbatim."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", text)
    safe = re.sub(r"[-.]{2,}", "-", safe).strip("-.")
    return safe[:RUN_NAME_MAX].rstrip("-.")


def run_name(step_key: str, ticket_key: str, title: str) -> str:
    """What a step's worktree and branch are called: ``<key>-<ticket>-<slug>``.

    The key first, so ``git branch`` and the worktrees directory sort by step; the ticket
    beside it when the step has one, so the branch answers the tracker too; the title's
    slug last, for the person reading the list. Every part is optional, and a step with
    none of them is still a run — ``step`` — rather than an empty name.
    """
    parts = [step_key.lower(), ref_safe(ticket_key), slugify(title, fallback="")]
    return ref_safe("-".join(part for part in parts if part)) or "step"


def workdir(facts: RepositoryFacts, step: Step | None = None) -> Path | None:
    """Where an agent on this project works — a step's, or one opened with nothing to do:
    the checkout of the code location the step names (its ``workplace``, else the
    project's primary code row) when the project records one, else where the facts read
    the code as being — the plan's own repository for the older shape of a plan kept
    beside its code, nowhere for a project whose code is not set. None when it is not
    here."""
    placement = code_placement(facts, step)
    if placement is not None:
        return placement.root if placement.here else None
    return facts.code_root


def code_placement(facts: RepositoryFacts, step: Step | None) -> Placement | None:
    """The code location a step works in, placed: the row its workplace names, else the
    primary. A named row that is gone falls back to the primary — lint says so."""
    named = facts.placement(workplace(step)) if step is not None else None
    return named if named is not None else facts.code


def worktree_path(workdir: Path, name: str) -> Path:
    return workdir / WORKTREES_DIR / name


def mainline(facts: RepositoryFacts | None, step: Step | None = None) -> str:
    """The branch a step's work lands on when no stretch holds it: the ref its code location
    names, "" for the repository's default branch."""
    placement = code_placement(facts, step) if facts is not None else None
    return placement.location.ref if placement is not None else ""


def run_name_of(step: Step) -> str:
    """What a step's agent run is called — its worktree, its branch, its terminal's title —
    from its key and its ticket, so the briefing names the worktree the script prepared."""
    ticket = ticket_read(step)
    return run_name(key_of(step), ticket.key if ticket is not None else "", step.title)


class WorktreeError(Exception):
    """The worktree could not be prepared; the message says why, in git's words."""


def prepare(workdir: Path, name: str, branches: BranchPlan = DEFAULT_BRANCHES) -> Path:
    """The worktree ``name`` under the checkout ``workdir``, on the branch ``branches``
    names: created on the first run, reused on the next. Raises :class:`WorktreeError`.

    A failed fetch is no stop — the run starts from what was fetched last — but a start
    that is gone is: with no ``create`` the stretch has run before, so a missing branch was
    deleted (landed, most likely), and cutting it afresh would put members' work nowhere.
    """
    named = (
        branches.work_branch,
        branches.start,
        branches.create,
        branches.create_from,
        branches.pr_base,
    )
    if refused := next((ref for ref in named if ref and not valid_ref(ref)), ""):
        raise WorktreeError(f"not a branch git accepts: {refused!r}")
    tree = worktree_path(workdir, name)
    branch = branches.branch_for(name)
    repo = _Repo(workdir)
    git, holds = repo.git, repo.holds
    try:
        # A registration whose directory is gone would refuse the add; prune is safe.
        with suppress(GitError):
            git("worktree", "prune")
        _exclude(Path(git("rev-parse", "--git-common-dir")), workdir)
        if (tree / ".git").is_file() and _unfinished(repo, tree):
            # A checkout cut short — a timeout, a killed process — leaves the `.git` file of a
            # worktree git never finished: removed, so it is made again rather than reused.
            git("worktree", "remove", "--force", "--force", str(tree))
            with suppress(GitError):
                git("worktree", "prune")
        if not tree.exists():
            if holds("remote", "get-url", "origin"):
                with suppress(GitError):
                    git("fetch", "--quiet", "origin", timeout=REMOTE_S)
            if branches.create:
                _cut(repo, branches)
            start = branches.start or _remote_default(repo)
            if holds("show-ref", "--verify", "--quiet", f"refs/heads/{branch}"):
                git("worktree", "add", str(tree), branch, timeout=CHECKOUT_S)
            elif holds("rev-parse", "--verify", "--quiet", f"{start}^{{commit}}"):
                git(
                    "worktree",
                    "add",
                    _track(branch, branches.start),
                    "-b",
                    branch,
                    str(tree),
                    start,
                    timeout=CHECKOUT_S,
                )
            else:
                raise WorktreeError(
                    f"there is no {start} to start {branch} from — a branch deleted after it"
                    " landed can be restored from its pull request"
                )
        # A linked worktree is marked by a `.git` file; anything else is not one.
        if not (tree / ".git").is_file():
            raise WorktreeError(f"{tree} is in the way and is not a worktree")
        if branches.pr_base:
            # gh reads it when no --base is given: the briefing says it, this holds it.
            git("config", f"branch.{branch}.gh-merge-base", branches.pr_base)
    except (GitError, OSError) as error:
        raise WorktreeError(f"could not prepare the worktree {tree} on {branch}: {error}") from None
    return tree


class _Repo:
    """git in one checkout: what it printed, or whether it agreed."""

    def __init__(self, workdir: Path) -> None:
        self.workdir = workdir

    def git(self, *args: str, timeout: float = LOCAL_S) -> str:
        return run_git(args, cwd=self.workdir, timeout=timeout).out.strip()

    def holds(self, *args: str) -> bool:
        try:
            self.git(*args)
        except GitError:
            return False
        return True


def _unfinished(repo: _Repo, tree: Path) -> bool:
    """Whether git left the worktree at ``tree`` half made: still under the ``initializing``
    lock ``worktree add`` holds until its checkout is done, or with no commit checked out."""
    listed = repo.git("worktree", "list", "--porcelain").split("\n\n")
    mine = next(
        (
            entry
            for entry in listed
            if Path(entry.splitlines()[0][len("worktree ") :]).resolve() == tree.resolve()
        ),
        "",
    )
    if "\nlocked initializing" in mine:
        return True
    try:
        run_git(["rev-parse", "--verify", "--quiet", "HEAD"], cwd=tree)
    except GitError:
        return True
    return False


def _exclude(common: Path, workdir: Path) -> None:
    """List the worktrees directory in the repository's own ``info/exclude``, once."""
    path = (common if common.is_absolute() else workdir / common) / "info" / "exclude"
    line = f"/{WORKTREES_DIR}/"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    if line in text.splitlines():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as exclude:
        exclude.write(("" if not text or text.endswith("\n") else "\n") + line + "\n")


def _cut(repo: _Repo, branches: BranchPlan) -> None:
    """The first run in a stretch cuts its branch on the remote: a push of a ref, never a
    checkout, so a plan kept inside this checkout is not switched under. A cut from the
    remote's default pushes from ``origin/HEAD``, which a checkout that was not cloned may
    never have been told."""
    if branches.create_from == DEFAULT_START and not repo.holds(
        "symbolic-ref", "-q", f"refs/remotes/{DEFAULT_START}"
    ):
        with suppress(GitError):
            repo.git("remote", "set-head", "origin", "--auto", timeout=REMOTE_S)
    if not repo.holds("show-ref", "--verify", "--quiet", f"refs/remotes/origin/{branches.create}"):
        repo.git(
            "push",
            "--quiet",
            "origin",
            f"{branches.create_from}:refs/heads/{branches.create}",
            timeout=REMOTE_S,
        )
        repo.git("fetch", "--quiet", "origin", timeout=REMOTE_S)


def _remote_default(repo: _Repo) -> str:
    """The remote's default branch, looked up — asked of the remote when the checkout was
    never told — else ``HEAD``: a repository with no remote default has only its own."""
    ref = f"refs/remotes/{DEFAULT_START}"
    for ask in (False, True):
        if ask and not repo.holds("remote", "set-head", "origin", "--auto"):
            break
        with suppress(GitError):
            if found := repo.git("symbolic-ref", "--quiet", "--short", ref):
                return found
    return "HEAD"


def _track(branch: str, start: str) -> str:
    """How a new branch relates to where it starts: a branch that *is* its remote one — a
    landing on the feature branch — tracks it, so a plain push lands there; any other never
    does, so a bare push from an agent's own branch can reach nothing shared."""
    return "--track" if start == f"origin/{branch}" else "--no-track"
