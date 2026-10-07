"""A step's worktree, prepared by git in Python: the one path a terminal run and a headless
run share. Real repositories in a temp directory — a bare remote and its clone."""

import subprocess

import pytest

from dplanner.modules.agent_briefing.worktree import WorktreeError, prepare, ref_safe, run_name
from dplanner.planning.branches import DEFAULT_START, BranchPlan


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _identify(repo):
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")


@pytest.fixture
def cloned_repo(tmp_path):
    """A checkout of a bare remote with one commit on main — origin/HEAD set, as a clone
    has it — left on a branch of its own that the remote has never seen."""
    remote = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)
    _identify(seed)
    _git(seed, "commit", "-q", "--allow-empty", "-m", "on main")
    _git(seed, "push", "-q", str(remote), "main")
    repo = tmp_path / "repo"
    subprocess.run(["git", "clone", "-q", str(remote), str(repo)], check=True)
    _identify(repo)
    _git(repo, "checkout", "-q", "-b", "elsewhere")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "on elsewhere")
    return repo


@pytest.fixture
def pointed_repo(tmp_path):
    """A repository whose plan sits in a subfolder — so the root carries the `.dplanner`
    pointer *file* the old worktree path collided with."""
    from dplanner.core.storage.locations import init_repo
    from dplanner.domain.seed import seed_project

    repo = init_repo(tmp_path / "repo")
    seed_project(repo / "planning", "Discovery")
    assert (repo / ".dplanner").is_file()
    _identify(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


def _upstream(tree):
    found = subprocess.run(
        ["git", "-C", str(tree), "rev-parse", "--abbrev-ref", "@{u}"],
        capture_output=True,
        text=True,
    )
    return found.stdout.strip() if found.returncode == 0 else ""


def test_a_worktree_sits_beside_the_pointer_file_and_is_reused(pointed_repo):
    """The worktree lives in .dplanner-worktrees/, never .dplanner/ — the pointer *file* a
    project kept in a subfolder leaves at the root, under which the first version's
    `git worktree add` failed on every such project. Made on the first run, reused on the
    next, and kept out of git status."""
    tree = pointed_repo / ".dplanner-worktrees" / "s1-discovery"
    for _ in range(2):
        assert prepare(pointed_repo, "s1-discovery") == tree
    assert (tree / ".git").is_file()
    assert _git(tree, "branch", "--show-current") == "agent/s1-discovery"
    exclude = (pointed_repo / ".git" / "info" / "exclude").read_text()
    assert exclude.splitlines().count("/.dplanner-worktrees/") == 1
    assert not _git(pointed_repo, "status", "--porcelain")


def test_a_fresh_worktree_starts_at_the_remotes_default_branch(cloned_repo):
    """Fetched and started from the remote's default — looked up, since nothing here knows
    it — so a checkout left on another branch is nobody's base; and no upstream, so a bare
    push from the agent's branch reaches nothing shared."""
    tree = prepare(cloned_repo, "s1-x")
    assert _git(tree, "log", "-1", "--format=%s") == "on main"
    assert _upstream(tree) == ""
    assert "gh-merge-base" not in _git(cloned_repo, "config", "--list")  # gh's default is right.


def test_the_first_run_in_a_stretch_cuts_its_branch_and_starts_from_it(cloned_repo, tmp_path):
    plan = BranchPlan(
        start="origin/feature/x",
        create="feature/x",
        create_from="origin/main",
        pr_base="feature/x",
    )
    tree = prepare(cloned_repo, "s2-x", plan)
    assert _git(tree, "log", "-1", "--format=%s") == "on main"
    assert _upstream(tree) == ""
    assert _git(tmp_path / "origin.git", "branch", "--list", "feature/x")
    assert _git(cloned_repo, "config", "branch.agent/s2-x.gh-merge-base") == "feature/x"
    assert _git(cloned_repo, "branch", "--show-current") == "elsewhere"  # Never switched.


def test_a_cut_from_the_remotes_default_finds_it_on_a_checkout_that_was_never_told(
    cloned_repo, tmp_path
):
    """A checkout made by init and remote-add has no origin/HEAD: the remote is asked which
    branch is its default before anything is pushed from it."""
    _git(cloned_repo, "remote", "set-head", "origin", "-d")
    plan = BranchPlan(
        start="origin/feature/y", create="feature/y", create_from=DEFAULT_START, pr_base="feature/y"
    )
    tree = prepare(cloned_repo, "s5-x", plan)
    assert _git(tree, "log", "-1", "--format=%s") == "on main"
    assert _git(tmp_path / "origin.git", "branch", "--list", "feature/y")


def test_a_landing_works_on_the_feature_branch_and_tracks_it(cloned_repo):
    _git(cloned_repo, "push", "-q", "origin", "origin/main:refs/heads/feature/x")
    plan = BranchPlan(work_branch="feature/x", start="origin/feature/x", pr_base="main")
    tree = prepare(cloned_repo, "s3-land", plan)
    assert _git(tree, "branch", "--show-current") == "feature/x"
    assert _upstream(tree) == "origin/feature/x"


def test_a_branch_gone_from_the_remote_is_never_cut_again(cloned_repo):
    """No ``create``: the stretch has already run, so a missing branch was deleted — landed,
    most likely — and starting it afresh from main would put members' work nowhere."""
    plan = BranchPlan(start="origin/feature/gone", pr_base="feature/gone")
    with pytest.raises(WorktreeError, match="there is no origin/feature/gone"):
        prepare(cloned_repo, "s4-x", plan)
    assert not (cloned_repo / ".dplanner-worktrees" / "s4-x").exists()


def test_a_worktree_that_cannot_be_prepared_is_refused_with_why(pointed_repo):
    """Never the main checkout by accident: something in the worktree's way is a refusal
    naming it, never a run carrying on where the plan is."""
    (pointed_repo / ".dplanner-worktrees").mkdir()
    (pointed_repo / ".dplanner-worktrees" / "s2-stale").write_text("in the way")
    with pytest.raises(WorktreeError, match="s2-stale"):
        prepare(pointed_repo, "s2-stale")


def test_a_folder_that_is_not_a_repository_is_refused(tmp_path):
    with pytest.raises(WorktreeError, match="could not prepare the worktree"):
        prepare(tmp_path, "s1-x")


def test_a_branch_git_would_refuse_never_reaches_git(tmp_path):
    with pytest.raises(WorktreeError, match="not a branch"):
        prepare(tmp_path, "s7-x", BranchPlan(pr_base='x"; rm -rf ~'))


def test_a_run_name_is_the_key_the_ticket_and_the_slug_made_ref_safe():
    assert run_name("F7", "PROJ-12", "Build the modal") == "f7-PROJ-12-build-the-modal"
    assert run_name("S3", "", "Wire it (v2)!") == "s3-wire-it-v2"
    assert run_name("", "", "") == "step"
    assert ref_safe("a..b//c ~^:?*[\\") == "a-b-c"
    assert ref_safe("-.lead and trail.-") == "lead-and-trail"
    assert len(run_name("S1", "", "x" * 200)) <= 60


def test_a_worktree_git_never_finished_is_made_again(pointed_repo):
    """A checkout cut short keeps the ``initializing`` lock ``worktree add`` takes until it is
    done: the next launch removes that worktree and makes it again rather than reuse it."""
    tree = prepare(pointed_repo, "s1-discovery")
    _git(pointed_repo, "worktree", "lock", "--reason", "initializing", str(tree))
    (tree / "half-written").write_text("a checkout cut short")
    assert prepare(pointed_repo, "s1-discovery") == tree
    assert "locked" not in _git(pointed_repo, "worktree", "list", "--porcelain")
    assert not (tree / "half-written").exists()
    assert _git(tree, "branch", "--show-current") == "agent/s1-discovery"


def test_a_worktree_is_checked_out_with_the_checkout_timeout(pointed_repo, monkeypatch):
    """A large repository, or an antivirus scanning every file, takes longer than a local
    command's twenty seconds to check out."""
    from dplanner.core.storage import sparse
    from dplanner.modules.agent_briefing import worktree

    timeouts: dict[str, float] = {}

    def timed(args, *, cwd=None, timeout=sparse.LOCAL_S, **kw):
        if list(args[:2]) == ["worktree", "add"]:
            timeouts["add"] = timeout
        return sparse.run_git(args, cwd=cwd, timeout=timeout, **kw)

    monkeypatch.setattr(worktree, "run_git", timed)
    prepare(pointed_repo, "s1-discovery")
    assert timeouts == {"add": sparse.CHECKOUT_S}
