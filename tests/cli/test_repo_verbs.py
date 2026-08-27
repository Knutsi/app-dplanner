"""``dplanner repo``: a project's repository association, over a real workspace.

No ``qapp`` fixture: agents set and read the association headless, and the resolution the
verbs print is the same function Run Agent is wired through.
"""

import json
from io import StringIO

import pytest

from dplanner.cli.command import CliRegistry
from dplanner.cli.main import run
from dplanner.core.storage.local import LocalStorage
from dplanner.domain.seed import create_product
from dplanner.modules import default_cli_commands, default_module_formats


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "widget"
    create_product(LocalStorage(root))
    return root


@pytest.fixture
def cli(workspace):
    registry = CliRegistry()
    registry.register_all(default_cli_commands())

    def invoke(*argv, expect=0):
        out, err = StringIO(), StringIO()
        code = run(
            registry, default_module_formats(), ["--workspace", str(workspace), *argv], out, err
        )
        assert code == expect, f"exit {code}: {err.getvalue()}{out.getvalue()}"
        return out.getvalue() + err.getvalue()

    invoke("project", "create", "Discovery")
    return invoke


def entry_path(workspace):
    return workspace / "projects" / "discovery" / "modules" / "project_repo.json"


def test_set_writes_and_a_second_run_reads_it_back(cli, workspace):
    cli("repo", "set", "Discovery", "--checkout", "~/Code/widget")
    written = json.loads(entry_path(workspace).read_text())
    assert written["checkout"] == "~/Code/widget"
    shown = json.loads(cli("repo", "show", "Discovery", "--json"))
    assert shown["checkout"] == "~/Code/widget"
    assert shown["effective_checkout"] == "~/Code/widget"


def test_setting_one_flag_keeps_the_other(cli, workspace):
    cli("repo", "set", "Discovery", "--checkout", "~/Code/widget")
    cli("repo", "set", "Discovery", "--repository", "https://github.com/owner/widget")
    written = json.loads(entry_path(workspace).read_text())
    assert written["checkout"] == "~/Code/widget"
    assert written["repository"] == "https://github.com/owner/widget"


def test_show_marks_the_product_fallback(cli):
    cli("product", "set", "--checkout", "~/Code/mono")
    text = cli("repo", "show", "Discovery")
    assert "~/Code/mono (from the product)" in text
    shown = json.loads(cli("repo", "show", "Discovery", "--json"))
    assert shown["checkout"] == ""
    assert shown["effective_checkout"] == "~/Code/mono"


def test_the_project_overrides_the_product(cli):
    cli("product", "set", "--checkout", "~/Code/mono")
    cli("repo", "set", "Discovery", "--checkout", "~/Code/widget")
    shown = json.loads(cli("repo", "show", "Discovery", "--json"))
    assert shown["effective_checkout"] == "~/Code/widget"


def test_clear_leaves_no_file(cli, workspace):
    cli("repo", "set", "Discovery", "--checkout", "~/Code/widget")
    cli("repo", "clear", "Discovery")
    assert not entry_path(workspace).exists()


def test_set_with_no_flags_is_refused(cli):
    assert "nothing to set" in cli("repo", "set", "Discovery", expect=1)


def test_setting_a_flag_empty_clears_that_half(cli, workspace):
    cli(
        "repo", "set", "Discovery",
        "--checkout", "~/Code/widget",
        "--repository", "https://github.com/owner/widget",
    )
    cli("repo", "set", "Discovery", "--repository", "")
    written = json.loads(entry_path(workspace).read_text())
    assert "repository" not in written
    assert written["checkout"] == "~/Code/widget"
