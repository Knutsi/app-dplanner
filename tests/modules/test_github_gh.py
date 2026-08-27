"""The github module's own ``gh`` door: parsing, refusals, and subprocess handling.

No ``qapp`` fixture: ``gh.py`` is Qt-free by rule (it is in ``HEADLESS_FILES``), and every
subprocess is faked — these tests must pass on a machine with no ``gh`` and no network.
"""

import shutil
import subprocess
from types import SimpleNamespace

import pytest

from dplanner.modules.github import gh


def fake_run(monkeypatch, *, stdout="", stderr="", returncode=0):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/gh")
    return calls


# -- parse_repo --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/acme/widget",
        "https://github.com/acme/widget.git",
        "https://github.com/acme/widget/",
        "git@github.com:acme/widget.git",
        "ssh://git@github.com/acme/widget",
    ],
)
def test_both_url_forms_parse_to_owner_repo(url):
    assert gh.parse_repo(url) == "acme/widget"


@pytest.mark.parametrize(
    "url",
    ["", "https://gitlab.com/acme/widget", "https://github.com/acme", "github.com", "not a url"],
)
def test_anything_else_parses_to_none(url):
    assert gh.parse_repo(url) is None


# -- pr_number_from ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ref",
    ["12", "#12", " 12 ", "https://github.com/acme/widget/pull/12", ".../pull/12/files"],
)
def test_a_pr_number_is_found_in_every_shape_people_paste(ref):
    assert gh.pr_number_from(ref) == 12


@pytest.mark.parametrize("ref", ["", "twelve", "https://github.com/acme/widget", "#"])
def test_no_number_reads_as_none(ref):
    assert gh.pr_number_from(ref) is None


# -- refusals ----------------------------------------------------------------------------------


def test_missing_gh_is_refused_with_the_install_hint(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    refusal = gh.gh_refusal()
    assert refusal is not None and "not found" in refusal


def test_unauthenticated_gh_is_refused_only_when_asked(monkeypatch):
    fake_run(monkeypatch, returncode=1)
    assert gh.gh_refusal() is None  # No probe unless requested: one spawn, not two.
    refusal = gh.gh_refusal(check_auth=True)
    assert refusal is not None and "gh auth login" in refusal


def test_a_working_gh_is_not_refused(monkeypatch):
    fake_run(monkeypatch, returncode=0)
    assert gh.gh_refusal(check_auth=True) is None


# -- listing and viewing -----------------------------------------------------------------------

PR_ROW = (
    '{"number": 12, "title": "Add login flow", "state": "MERGED",'
    ' "url": "u", "headRefName": "feat/login"}'
)


def test_pr_states_are_lowercased_at_the_boundary(monkeypatch):
    fake_run(monkeypatch, stdout=f"[{PR_ROW}]")
    (pr,) = gh.list_prs("acme/widget")
    assert pr == gh.PrInfo(
        number=12, title="Add login flow", state="merged", url="u", head_ref="feat/login"
    )


def test_view_pr_returns_none_for_a_number_the_repo_does_not_have(monkeypatch):
    fake_run(monkeypatch, returncode=1, stderr="GraphQL: Could not resolve to a PullRequest")
    assert gh.view_pr("acme/widget", 999) is None


def test_view_pr_reads_one_pr(monkeypatch):
    fake_run(monkeypatch, stdout=PR_ROW)
    pr = gh.view_pr("acme/widget", 12)
    assert pr is not None and pr.number == 12 and pr.state == "merged"


def test_any_other_gh_failure_carries_ghs_own_words(monkeypatch):
    fake_run(monkeypatch, returncode=1, stderr="HTTP 502: Bad gateway\nsecond line")
    with pytest.raises(gh.GhError, match="HTTP 502"):
        gh.list_prs("acme/widget")


def test_branches_come_one_per_line(monkeypatch):
    fake_run(monkeypatch, stdout="main\nfeat/login\n\n")
    assert gh.list_branches("acme/widget") == ["main", "feat/login"]


def test_a_timeout_is_a_gh_error_not_a_traceback(monkeypatch):
    def run(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, gh.GH_TIMEOUT)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/gh")
    with pytest.raises(gh.GhError, match="timed out"):
        gh.list_branches("acme/widget")
