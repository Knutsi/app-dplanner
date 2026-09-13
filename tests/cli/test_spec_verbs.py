"""``dplanner spec`` and ``dplanner topology``: documents, versions, figures and the
project's own account of its shape — over a real library.

**No ``qapp`` fixture anywhere in this file**: the spec workflow is an agent's workflow,
and it has to run where a graphics stack does not exist.
"""

import json
from pathlib import Path

import pytest
from tests.cli.spec_helpers import source, tiny_pdf

PDF = b"%PDF-1.4 not really, but binary enough\xff\xfe\x00"


@pytest.fixture
def project(cli):
    cli("project", "create", "Search rewrite")
    return "Search rewrite"


def data(text):
    return json.loads(text)


# -- importing ---------------------------------------------------------------------------------


def test_import_stores_the_document_beside_the_project(cli, project, tmp_path, workspace):
    cli("spec", "import", project, source(tmp_path, "auth spec.md", "# Auth\nRules."))
    listed = data(cli("spec", "list", project, "--json"))
    assert [doc["name"] for doc in listed["documents"]] == ["auth-spec"]
    assert listed["documents"][0]["kind"] == "markdown"
    blobs = list(workspace.glob("*/modules/spec/documents/*.md"))
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
    blobs = list(workspace.glob("*/modules/spec/documents/*.md"))
    assert len(blobs) == 2


# -- reading -----------------------------------------------------------------------------------


def test_show_prints_text_and_previous(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "spec.md", "one"), "--name", "spec")
    cli("spec", "import", project, source(tmp_path, "spec2.md", "two"), "--name", "spec")
    assert cli("spec", "show", project, "spec").strip() == "two"
    assert cli("spec", "show", project, "spec", "--previous").strip() == "one"


def test_show_prints_a_pdfs_text_layer_with_page_markers(cli, project, tmp_path):
    pdf = tiny_pdf("First rule.", "Second rule.")
    cli("spec", "import", project, source(tmp_path, "spec.pdf", pdf))
    out = cli("spec", "show", project, "spec")
    assert "--- page 1 ---" in out and "First rule." in out and "Second rule." in out
    only = cli("spec", "show", project, "spec", "--page", "2")
    assert "Second rule." in only and "First rule." not in only
    assert "no page 9" in cli("spec", "show", project, "spec", "--page", "9", expect=1)


def test_import_writes_the_text_layer_beside_the_documents(cli, project, tmp_path, workspace):
    cli("spec", "import", project, source(tmp_path, "spec.pdf", tiny_pdf("A rule.")))
    layers = list(workspace.glob("*/modules/spec/text/*.txt"))
    assert len(layers) == 1 and "A rule." in layers[0].read_text()


def test_a_pdf_imported_before_text_layers_still_shows(cli, project, tmp_path, workspace):
    """Read verbs extract in memory and never write — no lazy backfill."""
    cli("spec", "import", project, source(tmp_path, "spec.pdf", tiny_pdf("A rule.")))
    for layer in workspace.glob("*/modules/spec/text/*.txt"):
        layer.unlink()
    assert "A rule." in cli("spec", "show", project, "spec")
    assert list(workspace.glob("*/modules/spec/text/*.txt")) == []


def test_pages_are_a_pdf_thing(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "spec.md", "# Spec"))
    assert "pages are a PDF thing" in cli("spec", "show", project, "spec", "--page", "1", expect=1)


def test_show_on_an_unparseable_pdf_points_at_path(cli, project, tmp_path):
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


def test_diff_on_a_pdf_diffs_the_text_layers(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "s.pdf", tiny_pdf("Old rule.")), "--name", "s")
    cli("spec", "import", project, source(tmp_path, "s2.pdf", tiny_pdf("New rule.")), "--name", "s")
    report = data(cli("spec", "diff", project, "s", "--json"))
    assert report["hunks"], "a changed PDF should produce text hunks"
    joined = json.dumps(report["hunks"])
    assert "Old" in joined and "New" in joined
    # The original files stay on offer for an agent that wants them.
    assert Path(report["previous"]).is_file() and Path(report["current"]).is_file()


# -- the topology ------------------------------------------------------------------------------


def test_topology_set_and_show(cli, cli_stdin, project, workspace):
    out = cli_stdin("topology", "set", project, "--file", "-", stdin="Views are features.\n")
    assert "topology set" in out and "topology show" in out
    assert (next(workspace.glob("*/modules/spec.md"))).read_text() == "Views are features.\n"
    shown = data(cli("topology", "show", project, "--json"))
    assert shown["topology"] == "Views are features.\n" and len(shown["digest"]) == 16
    assert "Views are features." in cli("topology", "show", project)


def test_topology_show_says_when_there_is_none(cli, project):
    out = cli("topology", "show", project)
    assert "no topology yet" in out and "topology set" in out
    assert data(cli("topology", "show", project, "--json"))["topology"] == ""


# -- rendered pages and assets -----------------------------------------------------------------


def test_render_makes_an_indexed_png_asset(cli, project, tmp_path, workspace):
    cli("spec", "import", project, source(tmp_path, "s.pdf", tiny_pdf("A rule.")))
    report = data(cli("spec", "render", project, "s", "--page", "1", "--json"))
    assert report["asset"] == "a1" and report["outcome"] == "added"
    path = Path(report["path"])
    assert path.is_file() and path.read_bytes().startswith(b"\x89PNG")
    listed = data(cli("spec", "assets", project, "--json"))["assets"]
    assert listed == [
        {
            "id": "a1",
            "file": Path(report["path"]).as_posix().split("modules/spec/")[-1],
            "document": "s",
            "page": 1,
            "imported": listed[0]["imported"],
            "path": report["path"],
        }
    ]


def test_rendering_the_same_page_again_is_the_same_asset(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "s.pdf", tiny_pdf("A rule.")))
    first = data(cli("spec", "render", project, "s", "--page", "1", "--json"))
    again = data(cli("spec", "render", project, "s", "--page", "1", "--json"))
    assert again["asset"] == first["asset"] and again["outcome"] == "unchanged"


def test_rendering_a_missing_page_is_refused(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "s.pdf", tiny_pdf("A rule.")))
    assert "no page 9" in cli("spec", "render", project, "s", "--page", "9", expect=1)


def test_attach_now_records_an_asset_id(cli, project, tmp_path):
    cli("spec", "attach", project, source(tmp_path, "dot.png", b"png bytes"))
    listed = data(cli("spec", "assets", project, "--json"))["assets"]
    assert listed[0]["id"] == "a1" and listed[0]["document"] == ""


def test_attach_to_step_copies_the_figure_beside_the_step(cli, project, tmp_path, workspace):
    cli("spec", "import", project, source(tmp_path, "s.pdf", tiny_pdf("A rule.")))
    cli("spec", "render", project, "s", "--page", "1")
    cli("step", "add", project, "Hash passwords")
    report = data(cli("spec", "attach-to-step", "Hash passwords", "a1", "--json"))
    copies = list(workspace.glob("*/steps/*/modules/spec/assets/*.png"))
    assert len(copies) == 1 and report["files"][0].endswith(".png")

    shown = data(cli("step", "show", "Hash passwords", "--json"))
    attachment = shown["aspects"]["spec"]["attachments"][0]
    assert attachment["document"] == "s" and attachment["page"] == 1 and attachment["asset"] == "a1"

    cli("spec", "attach-to-step", "Hash passwords", "a1", "--remove")
    shown = data(cli("step", "show", "Hash passwords", "--json"))
    assert "attachments" not in shown["aspects"].get("spec", {})
    # The copied blob stays — content-addressed files are cheap and undo may want it.
    assert list(workspace.glob("*/steps/*/modules/spec/assets/*.png"))


def test_attaching_again_keeps_earlier_attachments(cli, project, tmp_path):
    """write_step_entry rewrites the whole entry from what it is handed — a second attach
    must read the first back rather than erase it."""
    cli("spec", "import", project, source(tmp_path, "s.pdf", tiny_pdf("One.", "Two.")))
    cli("spec", "render", project, "s", "--page", "1")
    cli("spec", "render", project, "s", "--page", "2")
    cli("step", "add", project, "Hash passwords")
    cli("spec", "attach-to-step", "Hash passwords", "a1")
    cli("spec", "attach-to-step", "Hash passwords", "a2")
    shown = data(cli("step", "show", "Hash passwords", "--json"))
    assert [a["asset"] for a in shown["aspects"]["spec"]["attachments"]] == ["a1", "a2"]


def test_an_attached_figure_reaches_the_agent_briefing(cli, project, tmp_path):
    import sys
    from io import StringIO as StdinIO

    cli("spec", "import", project, source(tmp_path, "s.pdf", tiny_pdf("A rule.")))
    cli("spec", "render", project, "s", "--page", "1")
    cli("step", "add", project, "Hash passwords")
    cli("spec", "attach-to-step", "Hash passwords", "a1")
    real = sys.stdin
    sys.stdin = StdinIO("Ship it.")
    try:
        cli("agent", "set", "Hash passwords", "--file", "-")
    finally:
        sys.stdin = real
    shown = data(cli("agent", "prompt", "Hash passwords", "--json"))
    figures = [p for p in shown["files"] if "modules/spec/assets/" in Path(p).as_posix()]
    assert len(figures) == 1 and figures[0] in shown["prompt"]


def test_attach_to_step_takes_several_assets(cli, project, tmp_path, workspace):
    cli("spec", "import", project, source(tmp_path, "s.pdf", tiny_pdf("One.", "Two.")))
    cli("spec", "render", project, "s", "--page", "1")
    cli("spec", "render", project, "s", "--page", "2")
    cli("step", "add", project, "Hash passwords")
    report = data(cli("spec", "attach-to-step", "Hash passwords", "a1", "a2", "--json"))
    assert report["assets"] == ["a1", "a2"] and len(report["files"]) == 2
    copies = list(workspace.glob("*/steps/*/modules/spec/assets/*.png"))
    assert len(copies) == 2

    out = cli("spec", "attach-to-step", "Hash passwords", "a1", "a9", expect=1)
    assert "'a9'" in out


def test_the_index_is_stamped_format_4(cli, project, tmp_path, workspace):
    cli("spec", "import", project, source(tmp_path, "s.md", "# Spec"))
    entry = json.loads(next(workspace.glob("*/modules/spec.json")).read_text())
    assert entry["format"] == 5


def test_an_older_index_drops_its_requirements_at_open(cli, project, tmp_path, workspace):
    """Format 2 carried requirements; format 3 does not. The key goes, the rest stays —
    for the project's index and a step's entry alike."""
    cli("spec", "import", project, source(tmp_path, "s.md", "# Spec"))
    cli("step", "add", project, "Hash passwords")
    index = next(workspace.glob("*/modules/spec.json"))
    entry = json.loads(index.read_text())
    entry["requirements"] = [{"id": "r1", "document": "s", "title": "Old"}]
    entry["format"] = 2
    index.write_text(json.dumps(entry))
    step_modules = next(workspace.glob("*/steps/hash-passwords")) / "modules"
    step_modules.mkdir(exist_ok=True)
    step_entry = step_modules / "spec.json"
    step_entry.write_text(json.dumps({"requirements": ["r1"], "format": 2}))
    cli("spec", "list", project)  # Any run migrates.
    assert "requirements" not in json.loads(index.read_text())
    assert json.loads(index.read_text())["format"] == 5
    assert not step_entry.exists()  # Nothing left to keep: the entry is removed.


# -- removing ----------------------------------------------------------------------------------


@pytest.fixture
def marked(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "spec.md", "# Spec"), "--name", "spec")
    return project


def test_remove_takes_the_document_and_keeps_the_blob(cli, marked, tmp_path, workspace):
    cli("spec", "import", marked, source(tmp_path, "other.md", "# Other"))
    report = data(cli("spec", "remove", marked, "spec", "--json"))
    assert report["document"] == "spec"
    listed = data(cli("spec", "list", marked, "--json"))
    assert [doc["name"] for doc in listed["documents"]] == ["other"]
    # The blob outlives the index entry — an orphan is recoverable, a dangling pointer is not.
    blobs = list(workspace.glob("*/modules/spec/documents/*.md"))
    assert len(blobs) == 2


def test_removing_the_last_document_removes_the_index_file(cli, marked, workspace):
    cli("spec", "remove", marked, "spec")
    assert list(workspace.glob("*/modules/spec.json")) == []


# -- refusals leave nothing behind -------------------------------------------------------------


def test_a_failing_verb_writes_no_index(cli, project, tmp_path):
    cli("spec", "attach", project, str(tmp_path / "nowhere.png"), expect=1)
    assert data(cli("spec", "list", project, "--json"))["documents"] == []


def test_an_unknown_document_is_refused_with_guidance(cli, project):
    out = cli("spec", "show", project, "ghost", expect=1)
    assert "no spec document" in out


# -- creating in place -------------------------------------------------------------------------


def test_new_creates_a_seeded_markdown_document(cli, project, workspace):
    out = cli("spec", "new", project, "Auth flow")
    assert "auth-flow: created" in out
    listed = data(cli("spec", "list", project, "--json"))
    assert [doc["name"] for doc in listed["documents"]] == ["auth-flow"]
    assert listed["documents"][0]["kind"] == "markdown"
    assert cli("spec", "show", project, "auth-flow").strip() == "# Auth flow"
    blobs = list(workspace.glob("*/modules/spec/documents/*.md"))
    assert len(blobs) == 1


def test_new_refuses_a_taken_name(cli, project):
    cli("spec", "new", project, "Auth flow")
    out = cli("spec", "new", project, "Auth flow", expect=1)
    assert "already exists" in out


def test_new_respects_an_explicit_name(cli, project):
    payload = data(cli("spec", "new", project, "Auth flow", "--name", "auth", "--json"))
    assert payload["document"] == "auth" and payload["outcome"] == "added"


# -- an editing session is one replace ---------------------------------------------------------
# `save_body` and `prune_blob` are the Specs tab's flush core; Qt-free like everything
# in documents.py, so they are pinned here where no graphics stack exists.


def session_area(tmp_path):
    from dplanner.core.storage.local import LocalStorage
    from dplanner.domain.store import ModuleFileArea

    return ModuleFileArea(LocalStorage(tmp_path / "ws"), "modules/spec", lambda _path: None)


def seeded(area):
    from dplanner.modules.spec.documents import import_document

    docs, document, _outcome = import_document(
        area, [], "auth", b"# Auth\n", "auth.md", "2026-08-27"
    )
    return docs, document


def test_save_body_pins_previous_to_the_session_base(tmp_path):
    from dplanner.modules.spec.documents import save_body

    area = session_area(tmp_path)
    docs, base = seeded(area)
    docs, first, outcome, superseded = save_body(area, docs, base, b"# Auth\nOne", "2026-08-28")
    assert outcome == "saved" and superseded is None and first.previous == base.file
    docs, second, outcome, superseded = save_body(area, docs, base, b"# Auth\nTwo", "2026-08-28")
    # A later flush still diffs against the session base; the intermediate is handed back.
    assert outcome == "saved" and second.previous == base.file and superseded == first.file
    assert area.read_bytes(second.file) == b"# Auth\nTwo"


def test_save_body_with_unchanged_bytes_writes_nothing(tmp_path):
    from dplanner.modules.spec.documents import save_body

    area = session_area(tmp_path)
    docs, base = seeded(area)
    docs, document, outcome, superseded = save_body(area, docs, base, b"# Auth\n", "2026-08-28")
    assert outcome == "unchanged" and superseded is None and document == base


def test_save_body_typed_back_to_base_restores_the_record(tmp_path):
    from dplanner.modules.spec.documents import save_body

    area = session_area(tmp_path)
    docs, base = seeded(area)
    docs, first, _outcome, _superseded = save_body(area, docs, base, b"changed", "2026-08-28")
    docs, restored, outcome, superseded = save_body(area, docs, base, b"# Auth\n", "2026-08-28")
    assert outcome == "saved" and restored == base and superseded == first.file


def test_save_body_refuses_a_document_no_longer_indexed(tmp_path):
    import pytest as _pytest

    from dplanner.cli.command import CliError
    from dplanner.modules.spec.documents import save_body

    area = session_area(tmp_path)
    _docs, base = seeded(area)
    with _pytest.raises(CliError, match="no longer in the spec index"):
        save_body(area, [], base, b"changed", "2026-08-28")


def test_prune_blob_removes_only_what_nothing_references(tmp_path):
    from dplanner.modules.spec.documents import prune_blob, save_body

    area = session_area(tmp_path)
    docs, base = seeded(area)
    docs, first, _outcome, _superseded = save_body(area, docs, base, b"one", "2026-08-28")
    docs, _second, _outcome, superseded = save_body(area, docs, base, b"two", "2026-08-28")
    assert superseded == first.file
    prune_blob(area, docs, superseded)
    assert area.read_bytes(superseded) is None
    # A referenced blob is refused — `file` and `previous` alike, across every document.
    prune_blob(area, docs, base.file)
    assert area.read_bytes(base.file) is not None


def test_referenced_assets_records_only_the_unrecorded(tmp_path):
    from dplanner.modules.spec.documents import SpecAsset, referenced_assets

    existing = [SpecAsset(id="a1", file="assets/aa.png", imported="2026-08-27")]
    body = "![image](assets/aa.png)\n![image](assets/bb.png)\ntext (assets/bb.png) again"
    updated = referenced_assets(existing, body, "2026-08-28")
    assert [asset.file for asset in updated] == ["assets/aa.png", "assets/bb.png"]
    assert updated[1].id == "a2"
    # Recording is idempotent: a second pass changes nothing.
    assert referenced_assets(updated, body, "2026-08-28") == updated
