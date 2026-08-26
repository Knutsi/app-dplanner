"""The CLI, over a real workspace.

**No ``qapp`` fixture anywhere in this file.** That it can run at all — parse, open, mutate,
flush — without a QApplication is the real proof the layering holds; the architecture test
checks the imports, this checks the behaviour.
"""

import json
from io import StringIO

import pytest

from dplanner.cli.command import CliRegistry
from dplanner.cli.main import run
from dplanner.cli.workspace import find_workspace
from dplanner.core.storage.local import LocalStorage
from dplanner.domain.seed import create_product
from dplanner.modules import default_cli_commands, default_module_formats


@pytest.fixture
def registry():
    registry = CliRegistry()
    registry.register_all(default_cli_commands())
    return registry


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "widget"
    create_product(LocalStorage(root))
    return root


@pytest.fixture
def cli(registry, workspace):
    def invoke(*argv, expect=0):
        out, err = StringIO(), StringIO()
        code = run(
            registry, default_module_formats(), ["--workspace", str(workspace), *argv], out, err
        )
        assert code == expect, f"exit {code}: {err.getvalue()}{out.getvalue()}"
        return out.getvalue() + err.getvalue()

    return invoke


def data(text):
    return json.loads(text)


# -- finding the product -----------------------------------------------------------------------


def test_the_product_is_found_by_walking_up(workspace):
    """The whole point: an agent already sitting in the checkout needs no configuration."""
    deep = workspace / "projects" / "somewhere"
    deep.mkdir(parents=True, exist_ok=True)
    assert find_workspace(start=deep).path == workspace


def test_no_product_anywhere_is_an_error_not_a_guess(tmp_path):
    from dplanner.cli.command import CliError

    with pytest.raises(CliError, match="no product found here"):
        find_workspace(start=tmp_path)


def test_an_explicit_workspace_wins(workspace, tmp_path):
    assert find_workspace(str(workspace), start=tmp_path).path == workspace


# -- reading -----------------------------------------------------------------------------------


def test_product_show_reports_an_empty_product(cli):
    assert data(cli("product", "show", "--json"))["projects"] == 0


def test_an_empty_product_says_so_rather_than_printing_nothing(cli):
    assert "No projects yet" in cli("project", "list")


def test_json_works_after_the_verb_as_well_as_before(cli):
    """Argparse wants global options first; nobody types them that way."""
    assert data(cli("product", "show", "--json"))["name"]
    assert data(cli("--json", "product", "show"))["name"]


# -- writing -----------------------------------------------------------------------------------


def test_a_verb_writes_to_disk_and_the_next_run_sees_it(cli, workspace):
    cli("project", "create", "Search rewrite", "--summary", "Replace the index")
    assert (workspace / "projects" / "search-rewrite" / "project.json").is_file()
    rows = data(cli("project", "list", "--json"))["projects"]
    assert [row["title"] for row in rows] == ["Search rewrite"]


def test_product_set_needs_something_to_set(cli):
    assert "nothing to set" in cli("product", "set", expect=1)


def test_steps_and_links(cli):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Read the spec")
    cli("step", "add", "Discovery", "Draft the model", "--after", "Read the spec")
    shown = data(cli("step", "show", "Draft the model", "--json"))
    assert len(shown["requires"]) == 1
    assert shown["title"] == "Draft the model"


def test_a_cycle_is_refused_as_a_message_not_a_traceback(cli):
    """A model refusal is the user's to fix; only a bug deserves a traceback."""
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "A")
    cli("step", "add", "Discovery", "B", "--after", "A")
    assert "that is a cycle" in cli("step", "link", "A", "B", expect=1)


def test_nothing_is_written_when_a_verb_fails(cli, workspace):
    cli("project", "create", "Discovery")
    before = (workspace / "projects" / "discovery" / "project.json").read_bytes()
    cli("project", "rename", "Discovery", expect=1)
    assert (workspace / "projects" / "discovery" / "project.json").read_bytes() == before


def test_an_ambiguous_name_asks_rather_than_guessing(cli):
    cli("project", "create", "Discovery one")
    cli("project", "create", "Discovery two")
    message = cli("project", "show", "Discovery", expect=1)
    assert "matches several" in message
    # The message has to say what to type next, so it names the ids.
    ids = [row["id"][:8] for row in data(cli("project", "list", "--json"))["projects"]]
    assert all(short in message for short in ids)


def test_unlink_removes_only_that_edge(cli):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "A")
    cli("step", "add", "Discovery", "B")
    cli("step", "add", "Discovery", "C", "--after", "A", "--after", "B")
    cli("step", "unlink", "C", "A")
    assert len(data(cli("step", "show", "C", "--json"))["requires"]) == 1


# -- export and import -------------------------------------------------------------------------


def test_export_and_import_round_trip_with_fresh_ids(cli, monkeypatch):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "A")
    cli("step", "add", "Discovery", "B", "--after", "A")
    document = data(cli("project", "export", "Discovery"))

    monkeypatch.setattr("sys.stdin", StringIO(json.dumps(document)))
    cli("project", "import", "--title", "Copy")

    copied = data(cli("project", "show", "Copy", "--json"))
    original = data(cli("project", "show", "Discovery", "--json"))
    assert [s["title"] for s in copied["steps"]] == [s["title"] for s in original["steps"]]
    # The links survived, pointing at the copy's own steps rather than the original's.
    assert copied["steps"][1]["requires"] == [copied["steps"][0]["id"]]
    assert copied["steps"][0]["id"] != original["steps"][0]["id"]


def test_a_projects_own_module_data_survives_the_round_trip(cli, monkeypatch):
    """A project owns data too — its start date — and a document that dropped it would make
    export-then-import a quietly lossy operation."""
    cli("project", "create", "Discovery")
    cli("schedule", "start", "Discovery", "--date", "2026-09-01")
    document = data(cli("project", "export", "Discovery"))
    assert document["aspects"]["estimation"]["start"] == "2026-09-01"

    monkeypatch.setattr("sys.stdin", StringIO(json.dumps(document)))
    cli("project", "import", "--title", "Copy")
    assert data(cli("schedule", "show", "Copy", "--json"))["start"] == "2026-09-01"


def test_import_refuses_something_that_is_not_a_document(cli, monkeypatch):
    monkeypatch.setattr("sys.stdin", StringIO("not json"))
    assert "not valid JSON" in cli("project", "import", expect=1)
