"""Every module's own checklist rows, asked with the machine mocked out.

Each ``checks()`` takes its ``which``, its ``run`` and its ``reach`` — or reads something a
monkeypatch can stand in for — so the whole checklist can be exercised without a subprocess,
a network request or a keychain prompt. That is the contract these tests are here to keep:
a probe with no seam is a probe the suite would have to run for real.
"""

import subprocess

import keyring
import keyring.backends.fail
import pytest

from dplanner.cli.checklist import GROUPS
from dplanner.domain.agents import AgentHarness
from dplanner.modules.checklist import checks as generic
from dplanner.modules.github import checks as github_checks
from dplanner.modules.llm import checks as llm_checks
from dplanner.modules.spec_confluence import checks as confluence_checks
from dplanner.modules.step_agent_instruction import checks as agent_checks


def read(checks, check_id):
    (one,) = [check for check in checks if check.id == check_id]
    return one, one.probe()


def ran(**answers):
    """A runner answering by the command's first two words; anything else fails."""

    def run(command):
        code = answers.get(" ".join(command[:2]), 1)
        said = "git version 2.51.0" if command[:2] == ["git", "--version"] else ""
        return subprocess.CompletedProcess(command, code, stdout=said, stderr="")

    return run


# -- the rows no feature owns ------------------------------------------------------------


def test_git_is_required_and_says_its_version():
    check, reading = read(
        generic.checks(which=lambda name: f"/usr/bin/{name}", run=ran(**{"git --version": 0})),
        "git.installed",
    )

    assert check.required and check.group == "Git and GitHub"
    assert reading.ok and reading.detail == "git version 2.51.0"


def test_git_missing_is_the_one_row_that_fails_a_machine():
    _check, reading = read(generic.checks(which=lambda _name: None), "git.installed")

    assert not reading.ok and reading.detail == "not on PATH"


def test_the_internet_row_says_what_stopped_it():
    _check, reading = read(generic.checks(reach=lambda: "URLError"), "network.internet")

    assert not reading.ok and "unreachable (URLError)" in reading.detail
    _check, well = read(generic.checks(reach=lambda: ""), "network.internet")
    assert well.ok


def test_az_says_it_is_not_dplanners_and_never_blocks():
    check, reading = read(generic.checks(which=lambda _name: None), "az.installed")

    assert not check.required and check.group == "Other tools"
    assert "only needed if your work deploys to Azure" in reading.detail
    assert "DPlanner never calls az" in (check.remedy.words if check.remedy else "")


def test_az_installed_but_signed_out_is_said_apart_from_az_missing():
    checks = generic.checks(which=lambda name: f"/usr/bin/{name}", run=ran())
    _check, reading = read(checks, "az.installed")

    assert not reading.ok and reading.detail == "installed, but not signed in"


def test_the_generic_rows_never_run_at_start_except_git():
    required = [check.id for check in generic.checks() if check.required]

    assert required == ["git.installed"]  # No network and no az on a launch.


# -- gh ----------------------------------------------------------------------------------


def test_gh_missing_advises_rather_than_blocking(monkeypatch):
    monkeypatch.setattr("dplanner.modules.github.checks.which_gh", lambda: None)

    installed, reading = read(github_checks.checks(), "github.gh")
    auth, signed = read(github_checks.checks(), "github.auth")

    assert not installed.required and not auth.required
    assert not reading.ok and reading.detail == "not on PATH"
    assert not signed.ok and signed.detail == "gh is not installed"


def test_gh_installed_but_signed_out_is_its_own_row(monkeypatch):
    monkeypatch.setattr("dplanner.modules.github.checks.which_gh", lambda: "/usr/bin/gh")
    monkeypatch.setattr(
        "dplanner.modules.github.checks.gh_refusal",
        lambda **_kwargs: "gh is not authenticated — run `gh auth login`",
    )

    check, reading = read(github_checks.checks(), "github.auth")

    assert not reading.ok and "not authenticated" in reading.detail
    assert check.remedy is not None and check.remedy.command == "gh auth login"


# -- agents ------------------------------------------------------------------------------


def harness(harness_id, binary):
    return AgentHarness(
        id=harness_id, label=harness_id.title(), command=f"{binary} --print", binary=binary
    )


def test_one_agent_row_reads_every_harnesss_own_binary():
    harnesses = (harness("claude", "claude"), harness("codex", "codex"))

    _check, found = read(
        agent_checks.checks(
            harnesses=harnesses, which=lambda name: f"/usr/bin/{name}" if name == "codex" else None
        ),
        "agents.cli",
    )
    _check, none = read(
        agent_checks.checks(harnesses=harnesses, which=lambda _name: None), "agents.cli"
    )

    assert found.ok and found.detail == "Codex on PATH"
    assert not none.ok and none.detail == "none of Claude, Codex is on PATH"


def test_a_terminal_is_judged_by_the_launchers_own_rule():
    checks = agent_checks.checks(
        harnesses=(),
        which=lambda name: f"/usr/bin/{name}" if name in ("ghostty", "tmux") else None,
        env={},
        platform="linux",
    )

    _check, terminal = read(checks, "agents.terminal")
    _check, multiplexer = read(checks, "agents.multiplexer")

    assert terminal.ok and "Ghostty" in terminal.detail
    # tmux is on PATH and the row's probe is env:TMUX — outside a session it is not usable,
    # and the checklist must not offer a terminal Run Agent would refuse.
    assert not multiplexer.ok


def test_tmux_counts_from_inside_a_tmux_session():
    checks = agent_checks.checks(
        harnesses=(),
        which=lambda name: f"/usr/bin/{name}" if name == "tmux" else None,
        env={"TMUX": "/tmp/tmux-1000/default,1,0"},
        platform="linux",
    )

    _check, multiplexer = read(checks, "agents.multiplexer")

    assert multiplexer.ok and "tmux" in multiplexer.detail


def test_no_agent_row_ever_blocks():
    assert not any(check.required for check in agent_checks.checks(harnesses=()))


# -- the keychain and the AI key ---------------------------------------------------------


class _Native:
    __module__ = "keyring.backends.macOS"


def test_the_keychain_row_says_why_it_cannot_keep_a_secret(monkeypatch):
    monkeypatch.setattr(keyring, "get_keyring", lambda: keyring.backends.fail.Keyring())

    check, reading = read(confluence_checks.checks(), "secrets.keychain")

    assert not check.required and not reading.ok and "keychain" in reading.detail


def test_a_native_keychain_is_well(monkeypatch):
    monkeypatch.setattr(keyring, "get_keyring", lambda: _Native())

    _check, reading = read(confluence_checks.checks(), "secrets.keychain")

    assert reading.ok and reading.detail == "usable"


def test_one_ai_row_names_whichever_provider_holds_a_key(monkeypatch):
    stored = {"llm_openai.api_key": "sk-test"}
    monkeypatch.setattr(keyring, "get_password", lambda _service, user: stored.get(user))
    providers = (("llm_openai", "OpenAI"), ("llm_anthropic", "Anthropic"))

    _check, reading = read(llm_checks.checks(providers=providers), "llm.key")

    assert reading.ok and reading.detail == "OpenAI configured"


def test_no_key_anywhere_names_every_provider_it_asked(monkeypatch):
    monkeypatch.setattr(keyring, "get_password", lambda _service, _user: None)
    providers = (("llm_openai", "OpenAI"), ("llm_anthropic", "Anthropic"))

    check, reading = read(llm_checks.checks(providers=providers), "llm.key")

    assert not check.required
    assert not reading.ok and reading.detail == "no key stored for OpenAI, Anthropic"


# -- the assembly ------------------------------------------------------------------------


def test_the_root_names_each_provider_by_its_own_module_id():
    """The composition root writes the provider ids literally — reaching for each module's
    MODULE_ID would load its SDK adapter, and Qt with it, in a CLI run. This is the guard."""
    from dplanner.modules import _llm_providers
    from dplanner.modules.anthropic.provider import MODULE_ID as ANTHROPIC
    from dplanner.modules.openai.provider import MODULE_ID as OPENAI

    assert {module_id for module_id, _label in _llm_providers()} == {OPENAI, ANTHROPIC}


def test_every_contributed_row_names_a_group_the_table_holds():
    from dplanner.modules import _machine_checks

    checks = _machine_checks(files=dict)

    assert {check.group for check in checks} <= set(GROUPS)
    assert len({check.id for check in checks}) == len(checks)  # No two rows share an id.
    assert [check.id for check in checks if check.required] == [
        "install.command",
        "install.skill",
        "git.installed",
    ]


@pytest.mark.parametrize("group", GROUPS)
def test_every_group_in_the_table_has_a_row(group):
    """A group nothing registers into is vocabulary that lies — menus.py's rule."""
    from dplanner.modules import _machine_checks

    assert any(check.group == group for check in _machine_checks(files=dict))
