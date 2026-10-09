"""What a pass changed, read from its worktree: ``changes.read_work`` over a throwaway repo."""

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from tests.modules.step_playbook.test_passes import run

from dplanner.domain import ledger
from dplanner.modules.github.aspect import PR_OPEN, GithubRefs
from dplanner.modules.step_playbook.changes import diff_argv, read_work


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=T", "-c", "user.email=t@e", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path) -> Path:
    """A checkout on ``agent/s1``, started from ``main`` as a worktree's prepare records it."""
    checkout = tmp_path / "code"
    checkout.mkdir()
    git(checkout, "init", "-q", "-b", "main")
    (checkout / "a.txt").write_text("one\n", encoding="utf-8")
    git(checkout, "add", "a.txt")
    git(checkout, "commit", "-q", "-m", "Start")
    git(checkout, "switch", "-q", "-c", "agent/s1")
    git(checkout, "config", "branch.agent/s1.gh-merge-base", "main")
    return checkout


def worked_in(directory: Path, config: Path) -> ledger.LedgerRecord:
    return replace(run("execute"), directory=str(directory), machine=ledger.machine_id(config))


def test_the_commits_and_the_stat_against_the_branch_it_started_from(repo, tmp_path):
    config = tmp_path / "config"
    (repo / "a.txt").write_text("one\ntwo\n", encoding="utf-8")
    git(repo, "commit", "-q", "-am", "Add two")
    (repo / "b.txt").write_text("new\n", encoding="utf-8")
    git(repo, "add", "b.txt")
    git(repo, "commit", "-q", "-m", "Add b")
    refs = GithubRefs(branch="agent/s1", pr_number=12, pr_url="https://x/12", pr_state=PR_OPEN)
    work = read_work(worked_in(repo, config), refs, config)
    assert (work.branch, work.base, work.refusal) == ("agent/s1", "main", "")
    assert [subject for _sha, subject in work.commits] == ["Add b", "Add two"]
    assert work.stat.startswith("2 files changed")
    assert (work.pr_url, work.pr_label) == ("https://x/12", "#12 · open")
    assert diff_argv(work, difftool=False) == ["git", "diff", "main...agent/s1"]
    assert diff_argv(work, difftool=True) == ["git", "difftool", "--dir-diff", "main...agent/s1"]


def test_work_that_left_no_commits_is_compared_and_found_empty(repo, tmp_path):
    config = tmp_path / "config"
    work = read_work(worked_in(repo, config), None, config)
    assert work.compared and work.commits == () and work.stat == ""


def test_a_worktree_this_machine_does_not_have_says_why(repo, tmp_path):
    config = tmp_path / "config"
    elsewhere = replace(worked_in(repo, config), machine="another", host="laptop")
    assert read_work(elsewhere, None, config).refusal == "its worktree is on laptop"
    gone = worked_in(tmp_path / "gone", config)
    assert read_work(gone, None, config).refusal == "its worktree is gone from this machine"
    assert not read_work(gone, None, config).compared
