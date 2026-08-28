"""``dplanner spec``: documents, versions, requirements, links — over a real workspace.

**No ``qapp`` fixture anywhere in this file**: the spec workflow is an agent's workflow,
and it has to run where a graphics stack does not exist.
"""

import json
from pathlib import Path

import pytest

PDF = b"%PDF-1.4 not really, but binary enough\xff\xfe\x00"


def tiny_pdf(*page_texts: str) -> bytes:
    """A minimal but real PDF, one page per string — built by hand so these tests need
    no Qt and no PDF writer, only the reader under test."""
    objects: list[bytes] = []
    page_ids = [4 + 2 * i for i in range(len(page_texts))]
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_texts)} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for page_id, text in zip(page_ids, page_texts, strict=True):
        content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objects.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {page_id + 1} 0 R >>"
            ).encode()
        )
        objects.append(
            b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content)
        )
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


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


# -- quote validation and pages ----------------------------------------------------------------


def test_mark_finds_the_quote_and_records_its_page(cli, project, tmp_path):
    pdf = tiny_pdf("Nothing here.", "All credentials MUST be hashed.")
    cli("spec", "import", project, source(tmp_path, "s.pdf", pdf))
    quote = "MUST be hashed"
    report = data(
        cli("spec", "mark", project, "s", "--title", "Hashing", "--quote", quote, "--json")
    )
    assert report["quote_found"] is True and report["page"] == 2
    listed = data(cli("spec", "requirements", project, "--json"))["requirements"]
    assert listed[0]["page"] == 2


def test_an_absent_quote_warns_but_still_marks(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "s.pdf", tiny_pdf("Nothing here.")))
    out = cli("spec", "mark", project, "s", "--title", "Ghost", "--quote", "does not appear")
    assert "warning" in out and "not found" in out
    assert data(cli("spec", "requirements", project, "--json"))["requirements"]


def test_a_page_that_disagrees_with_the_quote_warns_but_is_kept(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "s.pdf", tiny_pdf("Nothing.", "The rule.")))
    out = cli("spec", "mark", project, "s", "--title", "Rule", "--quote", "The rule", "--page", "1")
    assert "found on page 2" in out
    assert data(cli("spec", "requirements", project, "--json"))["requirements"][0]["page"] == 1


def test_strict_refuses_a_quote_that_does_not_anchor(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "s.pdf", tiny_pdf("Nothing here.")))
    out = cli(
        "spec", "mark", project, "s", "--title", "Ghost",
        "--quote", "does not appear", "--strict", expect=1,
    )
    assert "--strict" in out
    assert data(cli("spec", "requirements", project, "--json"))["requirements"] == []
    # An anchoring quote passes strict; no quote at all passes too (nothing to refute).
    cli("spec", "mark", project, "s", "--title", "Real", "--quote", "Nothing here", "--strict")
    cli("spec", "mark", project, "s", "--title", "Quoteless", "--strict")
    listed = data(cli("spec", "requirements", project, "--json"))["requirements"]
    assert [req["title"] for req in listed] == ["Real", "Quoteless"]


def test_quotes_are_validated_against_prose_documents_too(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "s.md", "The rule\nis here."))
    report = data(
        cli("spec", "mark", project, "s", "--title", "Rule", "--quote", "rule is here", "--json")
    )
    assert report["quote_found"] is True and report["page"] is None


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
            "file": report["path"].split("modules/spec/")[-1],
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


def test_linking_does_not_erase_attachments(cli, project, tmp_path):
    """write_step_entry exists because write_links rewrote the whole entry from the links
    alone — this is the regression that must never come back."""
    cli("spec", "import", project, source(tmp_path, "s.pdf", tiny_pdf("A rule.")))
    cli("spec", "render", project, "s", "--page", "1")
    cli("spec", "mark", project, "s", "--title", "Rule")
    cli("step", "add", project, "Hash passwords")
    cli("spec", "attach-to-step", "Hash passwords", "a1")
    cli("spec", "link", "Hash passwords", "r1")
    shown = data(cli("step", "show", "Hash passwords", "--json"))
    assert shown["aspects"]["spec"]["requirements"] == ["r1"]
    assert shown["aspects"]["spec"]["attachments"][0]["asset"] == "a1"


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
    figures = [path for path in shown["files"] if "modules/spec/assets/" in path]
    assert len(figures) == 1 and figures[0] in shown["prompt"]


def test_link_takes_several_requirements_in_one_call(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "s.md", "# Spec"))
    for title in ("One", "Two", "Three"):
        cli("spec", "mark", project, "s", "--title", title)
    cli("step", "add", project, "Hash passwords")
    cli("spec", "link", "Hash passwords", "r1", "r2", "r3")
    shown = data(cli("step", "show", "Hash passwords", "--json"))
    assert shown["aspects"]["spec"]["requirements"] == ["r1", "r2", "r3"]
    cli("spec", "link", "Hash passwords", "r1", "r3", "--remove")
    shown = data(cli("step", "show", "Hash passwords", "--json"))
    assert shown["aspects"]["spec"]["requirements"] == ["r2"]


def test_one_unknown_id_refuses_the_whole_batch(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "s.md", "# Spec"))
    cli("spec", "mark", project, "s", "--title", "One")
    cli("step", "add", project, "Hash passwords")
    out = cli("spec", "link", "Hash passwords", "r1", "r9", expect=1)
    assert "'r9'" in out
    # Nothing was written — not even the id that existed.
    shown = data(cli("step", "show", "Hash passwords", "--json"))
    assert "spec" not in shown["aspects"]


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


def test_the_index_is_stamped_format_2(cli, project, tmp_path, workspace):
    cli("spec", "import", project, source(tmp_path, "s.md", "# Spec"))
    entry = json.loads(next(workspace.glob("*/modules/spec.json")).read_text())
    assert entry["format"] == 2


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
    blobs = list(workspace.glob("*/modules/spec/documents/*.md"))
    assert len(blobs) == 2


def test_remove_reports_the_steps_left_dangling(cli, marked):
    cli("step", "add", marked, "Hash passwords")
    cli("spec", "link", "Hash passwords", "r1")
    out = cli("spec", "remove", marked, "spec")
    assert "still linked" in out and "Hash passwords" in out


def test_removing_the_last_document_removes_the_index_file(cli, marked, workspace):
    cli("spec", "remove", marked, "spec")
    assert list(workspace.glob("*/modules/spec.json")) == []


# -- refusals leave nothing behind -------------------------------------------------------------


def test_a_failing_verb_writes_no_index(cli, project, tmp_path):
    cli("spec", "mark", project, "nowhere", "--title", "x", expect=1)
    assert data(cli("spec", "list", project, "--json"))["documents"] == []


def test_an_unknown_document_is_refused_with_guidance(cli, project):
    out = cli("spec", "show", project, "ghost", expect=1)
    assert "no spec document" in out
