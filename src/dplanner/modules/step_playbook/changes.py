"""What a pass changed: its branch against the branch it started from, read from git.

A run records only where it worked (``LedgerRecord.directory``), so the rest is asked of the
worktree itself: the branch checked out there, its base — what ``agent_briefing/worktree``
recorded for ``gh`` as ``branch.<b>.gh-merge-base``, else the PR's base — and the commits and
the diff stat between them. Only the machine that launched the run has its worktree; anywhere
else the answer is why there is nothing to read. Every call is git, so a window reads this off
the GUI thread.
"""

from dataclasses import dataclass, replace
from pathlib import Path

from dplanner.core.storage.sparse import GitError, run_git
from dplanner.domain import ledger
from dplanner.domain.ledger import LedgerRecord
from dplanner.modules.github.aspect import GithubRefs

SHOWN_COMMITS = 10  # The commits listed; the rest are counted.
_SEP = "\x1f"


@dataclass(frozen=True)
class Work:
    directory: str
    branch: str = ""
    base: str = ""  # The ref the branch is compared against: "origin/main", "feature/x".
    commits: tuple[tuple[str, str], ...] = ()  # (short sha, subject), newest first.
    more: int = 0  # Commits beyond those listed.
    stat: str = ""  # "3 files changed, 40 insertions(+), 2 deletions(-)"
    pr_url: str = ""
    pr_label: str = ""  # "#255 · open"
    refusal: str = ""  # Why the worktree cannot be read here, "" when it was.

    @property
    def compared(self) -> bool:
        return bool(self.branch and self.base and not self.refusal)


def read_work(
    run: LedgerRecord | None, refs: GithubRefs | None, config: Path | None = None
) -> Work:
    """What the work of ``run`` — a pass's latest — changed, as its worktree says now."""
    work = _compared(run, refs, config)
    if refs is None or not refs.has_pr():
        return work
    label = f"#{refs.pr_number}" + (f" · {refs.pr_state}" if refs.pr_state else "")
    return replace(work, pr_url=refs.pr_url, pr_label=label)


def _compared(run: LedgerRecord | None, refs: GithubRefs | None, config: Path | None) -> Work:
    if run is None or not run.directory:
        return Work("", refusal="no run of the pass recorded where it worked")
    directory = Path(run.directory)
    if run.machine and run.machine != ledger.machine_id(config):
        return Work(run.directory, refusal=f"its worktree is on {run.host or 'another machine'}")
    if not directory.is_dir():
        return Work(run.directory, refusal="its worktree is gone from this machine")
    try:
        branch = _git(directory, "branch", "--show-current") or (refs.branch if refs else "")
        base = _base(directory, branch, refs)
        if not (branch and base):
            return Work(run.directory, branch, refusal="no base branch to compare it with")
        logged = _git(directory, "log", f"--format=%h{_SEP}%s", f"{base}..{branch}")
        stat = _git(directory, "diff", "--shortstat", f"{base}...{branch}")
    except GitError as error:
        return Work(run.directory, refusal=f"git could not read it: {error}")
    commits = tuple(
        (sha, subject)
        for sha, _, subject in (line.partition(_SEP) for line in logged.splitlines() if line)
    )
    shown = commits[:SHOWN_COMMITS]
    return Work(run.directory, branch, base, shown, len(commits) - len(shown), stat)


def diff_argv(work: Work, difftool: bool) -> list[str]:
    """What a terminal in the worktree runs to show the change: the person's own difftool
    over the whole tree when they set one, else git's diff in its pager."""
    span = f"{work.base}...{work.branch}"
    return ["git", "difftool", "--dir-diff", span] if difftool else ["git", "diff", span]


def has_difftool(directory: Path) -> bool:
    try:
        return bool(_git(directory, "config", "--get", "diff.tool"))
    except GitError:
        return False


def _base(directory: Path, branch: str, refs: GithubRefs | None) -> str:
    """The ref ``branch`` started from: the remote's copy where there is one, which a merge
    of it brought in, else the local branch."""
    named = _git(directory, "config", "--get", f"branch.{branch}.gh-merge-base") if branch else ""
    named = named or (refs.pr_base if refs else "")
    if not named:
        head = _git(directory, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
        return head
    for ref in (f"origin/{named}", named):
        if _git(directory, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"):
            return ref
    return ""


def _git(directory: Path, *args: str) -> str:
    """What git printed, or "" when it answered no (a missing config key, an unknown ref)."""
    try:
        return run_git(args, cwd=directory).out.strip()
    except GitError as error:
        if error.timed_out:
            raise
        return ""
