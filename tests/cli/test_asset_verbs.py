"""``dplanner asset``: the project-wide catalog, names, and the sweep — over a real library.

No ``qapp`` fixture: browsing and sweeping assets is an agent's workflow as much as a
person's, and it has to run where a graphics stack does not exist.
"""

import json
from pathlib import Path

import pytest

PNG = b"\x89PNG-pretend"


@pytest.fixture
def project(cli):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Deploy")
    return "Discovery"


def data(text):
    return json.loads(text)


def source(tmp_path, name, content=PNG):
    path = tmp_path / name
    path.write_bytes(content)
    return str(path)


def attach_description_image(cli, cli_stdin, tmp_path, *, referenced):
    name = data(cli("describe", "attach", "Deploy", source(tmp_path, "shot.png"), "--json"))[
        "asset"
    ]
    if referenced:
        cli_stdin("describe", "set", "Deploy", "--file", "-", stdin=f"See ![]({name}).")
    return name


def test_asset_list_names_every_location_and_its_uses(cli, cli_stdin, tmp_path, project, workspace):
    described = attach_description_image(cli, cli_stdin, tmp_path, referenced=True)
    cli("note", "add", project, "handoff", "Keys", "--step", "Deploy")
    carried = data(
        cli("note", "attach", project, "N1", source(tmp_path, "notes.txt", b"bytes"), "--json")
    )["asset"]

    report = data(cli("asset", "list", project, "--json"))

    by_name = {row["name"]: row for row in report["assets"]}
    assert set(by_name) == {described, carried}
    assert not by_name[described]["unused"]
    (location,) = by_name[described]["locations"]
    assert location["module"] == "step_description"
    where = Path(location["path"]).as_posix()  # Reported native; the suffix is spelled POSIX.
    assert where.endswith(f"steps/deploy/modules/step_description/{described}")
    assert (workspace / "discovery" / where.split("discovery/")[1]).exists()
    assert [use["where"] for use in location["uses"]] == ["description"]
    assert [use["title"] for use in location["uses"]] == ["Deploy"]
    assert [use["where"] for use in by_name[carried]["locations"][0]["uses"]] == ["note N1 — Keys"]


def test_asset_list_filters_to_the_unused(cli, cli_stdin, tmp_path, project):
    attach_description_image(cli, cli_stdin, tmp_path, referenced=False)
    cli("note", "add", project, "handoff", "Keys", "--step", "Deploy")
    cli("note", "attach", project, "N1", source(tmp_path, "notes.txt", b"bytes"))

    report = data(cli("asset", "list", project, "--unused", "--json"))

    assert [row["unused"] for row in report["assets"]] == [True]
    printed = cli("asset", "list", project, "--unused")
    assert "unused" in printed and "notes" not in printed


def test_asset_uses_resolves_a_sha_prefix_and_a_display_name(cli, cli_stdin, tmp_path, project):
    name = attach_description_image(cli, cli_stdin, tmp_path, referenced=True)
    basename = name.removeprefix("assets/")

    by_prefix = data(cli("asset", "uses", project, basename[:8], "--json"))
    assert by_prefix["asset"]["name"] == name

    cli("asset", "name", project, basename[:8], "Login mock")
    by_title = data(cli("asset", "uses", project, "Login mock", "--json"))
    assert by_title["asset"]["title"] == "Login mock"
    assert "used by Deploy — description" in cli("asset", "uses", project, "Login mock")


def test_asset_name_writes_the_title_and_clear_removes_it(
    cli, cli_stdin, tmp_path, project, workspace
):
    name = attach_description_image(cli, cli_stdin, tmp_path, referenced=True)
    cli("asset", "name", project, name, "Login mock")

    entry = workspace / "discovery" / "modules" / "project_assets.json"
    assert json.loads(entry.read_text())["titles"] == {name: "Login mock"}

    cli("asset", "name", project, "Login mock", "--clear")
    assert not entry.exists()  # Writing nothing leaves nothing behind.


def test_asset_prune_dry_run_deletes_nothing(cli, cli_stdin, tmp_path, project, workspace):
    name = attach_description_image(cli, cli_stdin, tmp_path, referenced=False)
    blob = workspace / "discovery" / "steps" / "deploy" / "modules" / "step_description" / name

    printed = cli("asset", "prune", project)

    assert "--apply" in printed and blob.exists()
    report = data(cli("asset", "prune", project, "--json"))
    assert report["applied"] is False
    assert [row["name"] for row in report["pruned"]] == [name]


def test_asset_prune_apply_removes_only_unused_copies_and_says_so(
    cli, cli_stdin, tmp_path, project, workspace
):
    kept = attach_description_image(cli, cli_stdin, tmp_path, referenced=True)
    stray = data(
        cli(
            "describe",
            "attach",
            "Deploy",
            source(tmp_path, "other.png", b"\x89PNG-other"),
            "--json",
        )
    )["asset"]
    area = workspace / "discovery" / "steps" / "deploy" / "modules" / "step_description"

    printed = cli("asset", "prune", project, "--apply")

    assert "not undoable" in printed
    assert not (area / stray).exists() and (area / kept).exists()
    assert data(cli("asset", "prune", project, "--json"))["pruned"] == []


def test_asset_prune_never_touches_spec_documents_or_unknown_module_dirs(
    cli, cli_stdin, tmp_path, project, workspace
):
    cli("spec", "import", project, source(tmp_path, "auth.md", b"# Auth\nRules."))
    unknown = workspace / "discovery" / "steps" / "deploy" / "modules" / "mystery"
    unknown.mkdir(parents=True)
    (unknown / "assets").mkdir()
    (unknown / "assets" / "keep.bin").write_bytes(b"not ours")
    attach_description_image(cli, cli_stdin, tmp_path, referenced=False)

    cli("asset", "prune", project, "--apply")

    documents = workspace / "discovery" / "modules" / "spec" / "documents"
    assert list(documents.iterdir())  # The spec blob is not an asset and stays.
    assert (unknown / "assets" / "keep.bin").exists()


def test_a_detached_spec_figure_is_prunable_while_an_attached_one_is_not(cli, tmp_path, project):
    cli("spec", "attach", project, source(tmp_path, "figure.png"))
    cli("spec", "attach-to-step", "Deploy", "a1")

    assert data(cli("asset", "prune", project, "--json"))["pruned"] == []

    cli("spec", "attach-to-step", "Deploy", "a1", "--remove")
    report = data(cli("asset", "prune", project, "--json"))
    # The step's detached copy is sweepable; the indexed project figure is a use and stays.
    assert [row["module"] for row in report["pruned"]] == ["spec"]
    assert {row["node"] for row in report["pruned"]} != {
        data(cli("project", "list", "--json"))["projects"][0]["id"]
    }


def test_the_pool_stages_an_image_and_the_sweep_leaves_it_alone(cli, tmp_path, project, workspace):
    report = data(cli("asset", "attach", project, source(tmp_path, "mock.png"), "--json"))

    assert report["asset"].startswith("assets/")
    pool = workspace / "discovery" / "modules" / "project_assets" / report["asset"]
    assert pool.exists() and Path(report["path"]).as_posix().endswith(report["asset"])

    assert cli("asset", "prune", project).strip() == "Nothing to sweep."
    assert pool.exists()
    listed = data(cli("asset", "list", project, "--json"))
    assert [row["locations"][0]["source"] for row in listed["assets"]] == ["Pool"]
