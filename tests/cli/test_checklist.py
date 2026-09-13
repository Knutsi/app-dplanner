"""``dplanner checklist show``: the rows, the order, the words and the exit code.

Every check here is a fake probe. Nothing in this file asks the machine anything — which is
the point of the seam: a check is a record with a callable, so the report can be tested
without a subprocess, a network or a keychain.
"""

import json
from io import StringIO

import pytest

from dplanner.cli.checklist import (
    GROUPS,
    Machine,
    MachineCheck,
    Reading,
    Remedy,
    command_for,
    commands,
    install_line,
    ordered,
    os_release_families,
    summary,
    this_machine,
)
from dplanner.cli.command import CliRegistry
from dplanner.cli.main import run


def check(check_id, group="Services", *, ok=True, detail="", required=False, remedy=None):
    return MachineCheck(
        id=check_id,
        group=group,
        label=check_id,
        probe=lambda: Reading(ok=ok, detail=detail),
        remedy=remedy,
        required=required,
    )


@pytest.fixture
def checklist_cli():
    def invoke(checks, *argv, expect=0):
        registry = CliRegistry()
        registry.register_all(commands(checks))
        out, err = StringIO(), StringIO()
        code = run(registry, [], ["checklist", "show", *argv], out, err)
        assert code == expect, f"exit {code}: {err.getvalue()}{out.getvalue()}"
        return out.getvalue()

    return invoke


def test_the_rows_are_grouped_in_the_tables_order_with_the_required_first():
    read = ordered(
        [
            check("advice", "Agents"),
            check("later", "Other tools"),
            check("needed", "Agents", required=True),
            check("first", "DPlanner", required=True),
        ]
    )

    assert [one.id for one in read] == ["first", "needed", "advice", "later"]
    assert [one.group for one in read] == ["DPlanner", "Agents", "Agents", "Other tools"]


def test_a_group_the_table_does_not_name_is_refused():
    with pytest.raises(ValueError, match="Wishes"):
        ordered([check("stray", "Wishes")])


def test_every_group_in_the_table_is_spelled_the_same_way_twice():
    assert len(set(GROUPS)) == len(GROUPS)


def test_a_required_row_that_fails_is_the_exit_code(checklist_cli):
    said = checklist_cli(
        [check("git.installed", "Git and GitHub", ok=False, detail="not on PATH", required=True)],
        expect=1,
    )

    assert "problem" in said
    assert "1 required item needs attention" in said


def test_a_failing_recommendation_is_advice_and_exits_zero(checklist_cli):
    said = checklist_cli([check("github.gh", "Git and GitHub", ok=False, detail="not on PATH")])

    assert "advice" in said and "problem" not in said
    assert "Everything required is in place — 1 suggestion." in said


def test_a_machine_with_everything_says_so(checklist_cli):
    said = checklist_cli([check("git.installed", "Git and GitHub", ok=True, detail="git 2.51.0")])

    assert "This machine has everything." in said
    assert "git 2.51.0" in said


def test_a_failing_rows_remedy_is_printed_with_the_command_to_type(checklist_cli):
    remedy = Remedy(
        words="Install or update DPlanner on this machine.",
        command="dplanner install all",
        action="install.dplanner",
        verb="Install…",
    )
    said = checklist_cli(
        [check("install.skill", "DPlanner", ok=False, required=True, remedy=remedy)], expect=1
    )

    assert "Install or update DPlanner on this machine." in said
    assert "$ dplanner install all" in said


def test_a_row_that_is_well_keeps_its_remedy_to_itself(checklist_cli):
    remedy = Remedy(words="Install or update DPlanner on this machine.")
    said = checklist_cli([check("install.skill", "DPlanner", ok=True, remedy=remedy)])

    assert "Install or update" not in said


def test_json_carries_every_row_with_its_remedy_and_the_two_counts(checklist_cli):
    remedy = Remedy(words="Sign in.", command="gh auth login")
    said = checklist_cli(
        [
            check("git.installed", "Git and GitHub", ok=True, detail="git 2.51.0", required=True),
            check("github.auth", "Git and GitHub", ok=False, remedy=remedy),
        ],
        "--json",
    )
    data = json.loads(said)

    assert data["failing"] == 1
    assert data["required_failing"] == 0
    assert [row["check"] for row in data["checks"]] == ["git.installed", "github.auth"]
    assert data["checks"][0]["remedy"] is None
    assert data["checks"][1]["remedy"] == {
        "words": "Sign in.",
        "command": "gh auth login",
        "action": "",
        "url": "",
    }
    assert data["summary"] == summary(
        [(check("github.auth", ok=False), Reading(ok=False))],
    )


def test_the_verb_needs_no_library():
    (command,) = commands([])

    assert command.needs_library is False
    assert command.edits_graph is None  # It reshapes nothing; the topology gate is not its.


# -- what this machine calls its packages ---------------------------------------------------

OMARCHY = 'NAME="Omarchy"\nID=omarchy\nID_LIKE=arch\nVERSION_ID="4.0.2"\n'
UBUNTU = 'NAME="Ubuntu"\nID=ubuntu\nID_LIKE=debian\n'
GH = {"": "gh", "arch": "github-cli", "windows": "GitHub.cli"}


def test_a_derivative_is_read_as_its_parent_and_needs_no_row_of_its_own(tmp_path):
    """Omarchy is the case this exists for: ID names itself, ID_LIKE names Arch."""
    assert os_release_families(OMARCHY) == ["omarchy", "arch"]
    release = tmp_path / "os-release"
    release.write_text(OMARCHY)

    found = this_machine(
        platform="linux", which=lambda name: f"/usr/bin/{name}", os_release=release
    )

    assert found == Machine("arch", "yay")
    assert install_line(GH, found) == "yay -S github-cli"


def test_the_manager_has_to_be_on_path_before_it_is_offered(tmp_path):
    """Suggesting `yay -S` on a machine without yay is a second thing to go and install,
    said as if it were the answer."""
    release = tmp_path / "os-release"
    release.write_text(OMARCHY)
    only_pacman = lambda name: "/usr/bin/pacman" if name == "pacman" else None  # noqa: E731

    found = this_machine(platform="linux", which=only_pacman, os_release=release)

    assert found == Machine("arch", "pacman")
    assert install_line(GH, found) == "sudo pacman -S github-cli"


def test_a_family_with_no_name_of_its_own_takes_the_one_most_of_them_use(tmp_path):
    release = tmp_path / "os-release"
    release.write_text(UBUNTU)

    found = this_machine(
        platform="linux", which=lambda name: f"/usr/bin/{name}", os_release=release
    )

    assert found == Machine("ubuntu", "apt")
    assert install_line(GH, found) == "sudo apt install gh"


def test_a_mac_and_a_windows_box_name_themselves(tmp_path):
    missing = tmp_path / "nothing"
    mac = this_machine(
        platform="darwin", which=lambda _n: "/opt/homebrew/bin/brew", os_release=missing
    )
    windows = this_machine(platform="win32", which=lambda _n: "C:/winget.exe", os_release=missing)

    assert install_line(GH, mac) == "brew install gh"
    assert install_line(GH, windows) == "winget install GitHub.cli"


def test_a_machine_nothing_is_known_about_suggests_nothing(tmp_path):
    nowhere = this_machine(platform="linux", which=lambda _n: None, os_release=tmp_path / "nothing")

    assert nowhere == Machine()
    assert install_line(GH, nowhere) == ""


def test_a_remedys_own_command_beats_whatever_packages_would_make():
    remedy = Remedy(words="Sign in.", command="gh auth login", packages=GH)

    assert command_for(remedy, Machine("arch", "yay")) == "gh auth login"
    assert command_for(Remedy(words="", packages=GH), Machine("arch", "yay")) == "yay -S github-cli"


def test_the_report_says_the_line_this_machine_would_run_and_where_to_read(checklist_cli):
    remedy = Remedy(words="Needed to pick branches.", url="https://cli.github.com", packages=GH)
    said = checklist_cli(
        [check("github.gh", "Git and GitHub", ok=False, detail="not on PATH", remedy=remedy)]
    )

    assert "https://cli.github.com" in said
    # The machine running the suite decides the line, so assert only that it named one of
    # this machine's own — the table itself is tested above over fixed files.
    machine = this_machine()
    if machine.manager:
        assert f"$ {install_line(GH, machine)}" in said


def test_json_carries_the_url_and_the_line_this_machine_would_run(checklist_cli):
    remedy = Remedy(words="Needed.", url="https://cli.github.com", packages=GH)
    said = checklist_cli([check("github.gh", "Git and GitHub", ok=False, remedy=remedy)], "--json")
    row = json.loads(said)["checks"][0]

    assert row["remedy"]["url"] == "https://cli.github.com"
    assert row["remedy"]["command"] == install_line(GH, this_machine())
