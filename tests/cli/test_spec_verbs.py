"""``dplanner spec``: documents, versions, requirements, links — over a real workspace.

**No ``qapp`` fixture anywhere in this file**: the spec workflow is an agent's workflow,
and it has to run where a graphics stack does not exist.
"""

import json
from io import StringIO
from pathlib import Path

import pytest

from dplanner.cli.command import CliRegistry
from dplanner.cli.main import run
from dplanner.core.storage.local import LocalStorage
from dplanner.domain.seed import create_product
from dplanner.modules import default_cli_commands, default_module_formats

PDF = b"%PDF-1.4 not really, but binary enough\xff\xfe\x00"


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


@pytest.fixture
def project(cli):
    cli("project", "create", "Search rewrite")
    return "Search rewrite"


def data(text):
    return json.loads(text)


def source(tmp_path, name, content):
    path = tmp_path / name
    path.write_bytes(content if isinstance(content, bytes) else content.encode())
    return str(path)


# -- importing ---------------------------------------------------------------------------------


def test_import_stores_the_document_beside_the_project(cli, project, tmp_path, workspace):
    cli("spec", "import", project, source(tmp_path, "auth spec.md", "# Auth\nRules."))
    listed = data(cli("spec", "list", project, "--json"))
    assert [doc["name"] for doc in listed["documents"]] == ["auth-spec"]
    assert listed["documents"][0]["kind"] == "markdown"
    blobs = list((workspace / "projects").glob("*/modules/spec/documents/*.md"))
    assert len(blobs) == 1


def test_import_accepts_a_pdf_and_refuses_other_binary(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "spec.pdf", PDF))
    out = cli("spec", "import", project, source(tmp_path, "junk.bin", PDF), expect=1)
    assert "neither a PDF nor UTF-8 text" in out


def test_reimporting_the_same_bytes_is_a_noop(cli, project, tmp_path):
    path = source(tmp_path, "spec.md", "same")
    assert "added" in cli("spec", "import", project, path)
    assert "unchanged" in cli("spec", "import", project, path)
    assert not data(cli("spec", "list", project, "--json"))["documents"][0]["has_previous"]


def test_replacing_keeps_the_previous_version(cli, project, tmp_path, workspace):
    cli("spec", "import", project, source(tmp_path, "spec.md", "one"), "--name", "spec")
    cli("spec", "import", project, source(tmp_path, "spec2.md", "two"), "--name", "spec")
    assert data(cli("spec", "list", project, "--json"))["documents"][0]["has_previous"]
    # Both blobs stay on disk: the index edit is undoable, the blob write is not.
    blobs = list((workspace / "projects").glob("*/modules/spec/documents/*.md"))
    assert len(blobs) == 2


# -- reading -----------------------------------------------------------------------------------


def test_show_prints_text_and_previous(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "spec.md", "one"), "--name", "spec")
    cli("spec", "import", project, source(tmp_path, "spec2.md", "two"), "--name", "spec")
    assert cli("spec", "show", project, "spec").strip() == "two"
    assert cli("spec", "show", project, "spec", "--previous").strip() == "one"


def test_show_refuses_a_pdf_and_points_at_path(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "spec.pdf", PDF))
    out = cli("spec", "show", project, "spec", expect=1)
    assert "spec path" in out


def test_path_is_absolute_and_exists(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "spec.pdf", PDF))
    path = Path(data(cli("spec", "path", project, "spec", "--json"))["path"])
    assert path.is_absolute() and path.is_file()


def test_previous_without_a_replace_is_refused(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "spec.md", "one"))
    out = cli("spec", "show", project, "spec", "--previous", expect=1)
    assert "no previous version" in out


# -- diffing -----------------------------------------------------------------------------------


def test_diff_reports_hunks_between_versions(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "s.md", "a\nkeep\n"), "--name", "s")
    cli("spec", "import", project, source(tmp_path, "s2.md", "b\nkeep\n"), "--name", "s")
    hunks = data(cli("spec", "diff", project, "s", "--json"))["hunks"]
    assert hunks and hunks[0]["removed"] == "a" and hunks[0]["added"] == "b"


def test_diff_on_a_pdf_hands_over_both_paths(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "s.pdf", PDF), "--name", "s")
    cli("spec", "import", project, source(tmp_path, "s2.pdf", PDF + b"x"), "--name", "s")
    report = data(cli("spec", "diff", project, "s", "--json"))
    assert Path(report["previous"]).is_file() and Path(report["current"]).is_file()


# -- requirements ------------------------------------------------------------------------------


@pytest.fixture
def marked(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "spec.md", "# Spec"), "--name", "spec")
    cli("spec", "mark", project, "spec", "--title", "Hash with argon2id", "--quote", "MUST")
    return project


def test_mark_generates_ids_and_updates_by_id(cli, marked):
    cli("spec", "mark", marked, "spec", "--title", "Second rule")
    listed = data(cli("spec", "requirements", marked, "--json"))["requirements"]
    assert [req["id"] for req in listed] == ["r1", "r2"]
    cli("spec", "mark", marked, "spec", "--title", "Hash with scrypt", "--id", "r1")
    listed = data(cli("spec", "requirements", marked, "--json"))["requirements"]
    assert listed[0]["title"] == "Hash with scrypt"


def test_link_ties_a_step_to_a_requirement(cli, marked):
    cli("step", "add", marked, "Hash passwords")
    cli("spec", "link", "Hash passwords", "r1")
    listed = data(cli("spec", "requirements", marked, "--json"))["requirements"]
    assert [step["title"] for step in listed[0]["steps"]] == ["Hash passwords"]
    cli("spec", "link", "Hash passwords", "r1", "--remove")
    listed = data(cli("spec", "requirements", marked, "--json"))["requirements"]
    assert listed[0]["steps"] == []


def test_linking_an_unknown_requirement_is_refused(cli, marked):
    cli("step", "add", marked, "Hash passwords")
    out = cli("spec", "link", "Hash passwords", "r9", expect=1)
    assert "no requirement" in out


def test_unmark_reports_the_steps_left_dangling(cli, marked):
    cli("step", "add", marked, "Hash passwords")
    cli("spec", "link", "Hash passwords", "r1")
    out = cli("spec", "unmark", marked, "r1")
    assert "still linked" in out and "Hash passwords" in out
    # The step keeps its (now dangling) link — undo must be able to restore either side.
    report = data(cli("spec", "requirements", marked, "--json"))
    assert report["requirements"] == []


def test_requirements_filter_by_document(cli, marked, tmp_path):
    cli("spec", "import", marked, source(tmp_path, "other.md", "# Other"))
    cli("spec", "mark", marked, "other", "--title", "Elsewhere")
    ids = [
        req["id"]
        for req in data(cli("spec", "requirements", marked, "--document", "spec", "--json"))[
            "requirements"
        ]
    ]
    assert ids == ["r1"]


# -- removing ----------------------------------------------------------------------------------


def test_remove_takes_the_document_and_its_requirements(cli, marked, tmp_path, workspace):
    cli("spec", "import", marked, source(tmp_path, "other.md", "# Other"))
    cli("spec", "mark", marked, "other", "--title", "Elsewhere")
    report = data(cli("spec", "remove", marked, "spec", "--json"))
    assert report["document"] == "spec"
    assert report["requirements_removed"] == ["r1"]
    listed = data(cli("spec", "list", marked, "--json"))
    assert [doc["name"] for doc in listed["documents"]] == ["other"]
    remaining = data(cli("spec", "requirements", marked, "--json"))["requirements"]
    assert [req["id"] for req in remaining] == ["r2"]
    # The blob outlives the index entry — an orphan is recoverable, a dangling pointer is not.
    blobs = list((workspace / "projects").glob("*/modules/spec/documents/*.md"))
    assert len(blobs) == 2


def test_remove_reports_the_steps_left_dangling(cli, marked):
    cli("step", "add", marked, "Hash passwords")
    cli("spec", "link", "Hash passwords", "r1")
    out = cli("spec", "remove", marked, "spec")
    assert "still linked" in out and "Hash passwords" in out


def test_removing_the_last_document_removes_the_index_file(cli, marked, workspace):
    cli("spec", "remove", marked, "spec")
    assert list((workspace / "projects").glob("*/modules/spec.json")) == []


# -- refusals leave nothing behind -------------------------------------------------------------


def test_a_failing_verb_writes_no_index(cli, project, tmp_path):
    cli("spec", "mark", project, "nowhere", "--title", "x", expect=1)
    assert data(cli("spec", "list", project, "--json"))["documents"] == []


def test_an_unknown_document_is_refused_with_guidance(cli, project):
    out = cli("spec", "show", project, "ghost", expect=1)
    assert "no spec document" in out
