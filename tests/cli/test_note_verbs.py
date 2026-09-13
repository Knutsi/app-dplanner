"""``dplanner note``: the log beside a project, safe to write twice, what an agent's
briefing carries of it, and how the two retired modules reach it. No ``qapp`` fixture:
this is an agent's workflow."""

import json

import pytest

from dplanner.domain.store import LibraryStore
from dplanner.modules.notes.log import read_log
from dplanner.modules.notes.reach import INDEX_LIMIT


def data(text):
    return json.loads(text)


@pytest.fixture
def project(cli, cli_stdin):
    cli("project", "create", "Search rewrite")
    cli("step", "add", "Search rewrite", "Draft the model", "--agent")
    cli("step", "add", "Search rewrite", "Build the index", "--after", "S1")
    cli("step", "add", "Search rewrite", "Write the docs")
    cli_stdin("describe", "set", "S1", "--file", "-", stdin="Draft it.")
    cli_stdin("describe", "set", "S2", "--file", "-", stdin="Build it.")
    cli("agent", "on", "S2")
    return "Search rewrite"


def log(cli_library):
    return read_log(LibraryStore(cli_library).load().projects[0])


# -- recording ----------------------------------------------------------------------------------


def test_add_mints_ids_stamps_the_day_and_names_the_step_by_key(cli, project, cli_library):
    said = cli(
        "note",
        "add",
        project,
        "decision",
        "Keep the index in SQLite",
        "--step",
        "S1",
        "--text",
        "Postgres would need an operator.",
        "--made",
        "2026-09-05",
    )
    assert "N1: decision — Keep the index in SQLite — recorded" in said
    (record,) = log(cli_library)
    assert record.id == "N1" and record.made == "2026-09-05" and record.label == "decision"
    assert record.body == "Postgres would need an operator."
    assert record.step  # the step's id, not its key
    listed = data(cli("note", "list", project, "--json"))["notes"]
    assert listed[0]["key"] == "S1" and listed[0]["note"] == "N1"
    assert "N1   decision     Keep the index in SQLite  5 September, on S1" in cli(
        "note", "list", project
    )


def test_the_label_is_one_of_the_ontology(cli, project):
    said = cli("note", "add", project, "musing", "Hmm", expect=1)
    assert "no such label" in said and "handoff" in said and "spec-change" in said


def test_a_title_already_on_the_step_is_that_note_not_a_second(cli, project, cli_library):
    """A retry after a stale-workspace refusal, or an epilogue run twice, must not leave
    two records; the answer names the existing one and how to revise it. The same title
    on another step is another note — a step's handoff is its own."""
    cli("note", "add", project, "handoff", "Done", "--step", "S1", "--text", "first")
    said = cli("note", "add", project, "handoff", "done ", "--step", "S1", "--text", "second")
    assert "N1: already recorded" in said and "note set" in said
    cli("note", "add", project, "handoff", "Done", "--step", "S2", "--text", "third")
    first, second = log(cli_library)
    assert first.body == "first" and second.body == "third"
    assert (
        data(cli("note", "add", project, "handoff", "Done", "--step", "S1", "--json"))["outcome"]
        == "unchanged"
    )


def test_add_stamps_today_when_nobody_says_and_refuses_a_bad_day(cli, project, cli_library):
    from datetime import date

    cli("note", "add", project, "decision", "Ship weekly")
    assert log(cli_library)[0].made == date.today().isoformat()
    assert "YYYY-MM-DD" in cli("note", "add", project, "later", "Later", "--made", "soon", expect=1)


def test_a_reversal_supersedes_the_earlier_note(cli, project, cli_library):
    cli("note", "add", project, "decision", "Keep the index in SQLite")
    cli("note", "add", project, "decision", "Move the index to Postgres", "--supersedes", "n1")
    _first, second = log(cli_library)
    assert second.supersedes == "N1"
    listed = cli("note", "list", project)
    assert "N2" in listed and "N1" not in listed.split("(1 superseded")[0]
    assert "1 superseded — `--all`" in listed
    everything = cli("note", "list", project, "--all")
    assert "N1   decision     Keep the index in SQLite" in everything
    assert "superseded by N2" in everything
    assert "no note 'N9'" in cli(
        "note", "add", project, "decision", "Again", "--supersedes", "N9", expect=1
    )


def test_set_revises_the_fields_and_remove_survives_a_second_run(
    cli, cli_stdin, project, cli_library
):
    cli("note", "add", project, "decision", "Keep the index in SQLite", "--step", "S1")
    cli_stdin(
        "note",
        "set",
        project,
        "N1",
        "--label",
        "spec-change",
        "--title",
        "Keep SQLite",
        "--file",
        "-",
        "--no-step",
        "--for",
        "S2",
        "S3",
        "--made",
        "2026-09-01",
        stdin="Read-mostly, one operator.",
    )
    (record,) = log(cli_library)
    assert (record.label, record.title, record.body, record.step, record.made) == (
        "spec-change",
        "Keep SQLite",
        "Read-mostly, one operator.",
        "",
        "2026-09-01",
    )
    assert len(record.for_steps) == 2
    shown = cli("note", "show", project, "sqlite")
    assert "**N1 spec-change · Keep SQLite** (1 September)" in shown
    assert "Read-mostly, one operator." in shown and "for S2, S3" in shown
    cli("note", "set", project, "N1", "--for-nobody")
    assert log(cli_library)[0].for_steps == ()
    assert "N1: Keep SQLite — removed" in cli("note", "remove", project, "N1")
    assert log(cli_library) == []
    assert "nothing to remove" in cli("note", "remove", project, "N1")


def test_removing_a_superseded_note_unlinks_its_successor(cli, project, cli_library):
    cli("note", "add", project, "decision", "One")
    cli("note", "add", project, "decision", "Two", "--supersedes", "N1")
    cli("note", "remove", project, "N1")
    (record,) = log(cli_library)
    assert record.id == "N2" and record.supersedes == ""


def test_list_filters_by_label_and_an_ambiguous_name_is_refused_with_the_ids(cli, project):
    cli("note", "add", project, "decision", "Index in SQLite")
    cli("note", "add", project, "later", "Index in memory")
    assert "N2" not in cli("note", "list", project, "--label", "decision")
    said = cli("note", "show", project, "Index", expect=1)
    assert "several notes" in said and "N1" in said and "N2" in said
    assert "note list" in cli("note", "show", project, "ghost", expect=1)
    assert "cannot supersede itself" in cli(
        "note", "set", project, "N1", "--supersedes", "N1", expect=1
    )


def test_the_log_is_one_file_beside_the_project_with_absence_for_the_defaults(
    cli, project, workspace
):
    cli("note", "add", project, "handoff", "Keys", "--made", "2026-09-05", "--step", "S1")
    entry = json.loads(next(workspace.glob("*/modules/notes.json")).read_text())
    (row,) = entry["notes"]
    assert entry["format"] == 1
    assert set(row) == {"id", "label", "title", "made", "step"}
    cli("note", "set", project, "N1", "--reach", "project")
    (row,) = json.loads(next(workspace.glob("*/modules/notes.json")).read_text())["notes"]
    assert row["reach"] == "project"
    cli("note", "remove", project, "N1")
    assert not list(workspace.glob("*/modules/notes.json"))


def test_attach_copies_the_file_in_and_links_it_from_the_body(cli, project, tmp_path, cli_library):
    diagram = tmp_path / "diagram.png"
    diagram.write_bytes(b"png-bytes")
    cli("note", "add", project, "handoff", "See the diagram", "--step", "S1")
    said = data(cli("note", "attach", project, "N1", str(diagram), "--json"))
    assert said["asset"].startswith("assets/") and said["path"].endswith(said["asset"])
    assert log(cli_library)[0].body == f"![diagram]({said['asset']})"
    # Attaching the same bytes again links nothing twice.
    cli("note", "attach", project, "N1", str(diagram))
    assert log(cli_library)[0].body.count("assets/") == 1
    assert "no such file" in cli("note", "attach", project, "N1", "nope.png", expect=1)


# -- what an agent is told ----------------------------------------------------------------------


def test_index_prints_what_the_briefing_carries(cli, cli_stdin, project):
    cli("note", "add", project, "decision", "Keep SQLite", "--text", "One operator.")
    cli_stdin(
        "note",
        "add",
        project,
        "handoff",
        "Keys in vault",
        "--step",
        "S1",
        "--for",
        "S2",
        "--file",
        "-",
        stdin="Under ci/.",
    )
    cli("note", "add", project, "handoff", "Docs draft", "--step", "S3")
    shown = cli("note", "index", "S2")
    assert "## Notes for this step" in shown and "Under ci/." in shown
    assert "## Notes so far" in shown and "- N1 · Keep SQLite" in shown
    assert "Docs draft" not in shown  # S3 is not behind S2.
    assert "One operator." not in shown  # Indexed, not carried.
    as_json = data(cli("note", "index", "S2", "--json"))
    assert [n["note"] for n in as_json["for_this_step"]] == ["N2"]
    assert [n["note"] for n in as_json["index"]] == ["N1"]
    # S3 sees the decision and its own handoff — a re-run is a pick-up — and nothing of S1's.
    own = cli("note", "index", "S3")
    assert "- N1 · Keep SQLite" in own and "- N3 · Docs draft" in own and "Keys" not in own
    cli("note", "remove", project, "N1")
    cli("note", "remove", project, "N2")
    cli("note", "remove", project, "N3")
    assert "No notes reach this step yet." in cli("note", "index", "S3")


def test_a_decision_stays_on_its_branch_until_reach_project_lifts_it(cli, project):
    """The rule the narrowed reach turns on: a choice made on a branch binds the work after
    it, and a choice that binds the whole plan says so."""
    cli("note", "add", project, "decision", "Vite for the bundler", "--step", "S3")
    lift = ("--step", "S3", "--reach", "project")
    cli("note", "add", project, "decision", "Tabs, not spaces", *lift)
    shown = cli("note", "index", "S2")
    assert "Tabs, not spaces" in shown and "Vite for the bundler" not in shown
    own = cli("note", "index", "S3")
    assert "Tabs, not spaces" in own and "Vite for the bundler" in own


def test_index_caps_each_label_and_all_lifts_the_cap(cli, project):
    """What the briefing carries is capped and says so; --all is how to read everything that
    reaches the step."""
    for n in range(1, INDEX_LIMIT + 4):
        cli("note", "add", project, "decision", f"Choice {n}")
    shown = cli("note", "index", "S1")
    assert f"Decisions standing ({INDEX_LIMIT} of {INDEX_LIMIT + 3}):" in shown
    assert "Choice 3" not in shown and f"Choice {INDEX_LIMIT + 3}" in shown
    # The ref is quoted exactly as every other verb in the briefing quotes it.
    assert "…and 3 earlier: `dplanner note list 'Search rewrite' --label decision`" in shown
    assert len(data(cli("note", "index", "S1", "--json"))["index"]) == INDEX_LIMIT
    whole = cli("note", "index", "S1", "--all")
    assert f"Decisions standing ({INDEX_LIMIT + 3}):" in whole
    assert "Choice 3" in whole and "earlier:" not in whole
    assert len(data(cli("note", "index", "S1", "--all", "--json"))["index"]) == INDEX_LIMIT + 3


def test_the_briefing_carries_the_addressed_notes_in_full_and_indexes_the_rest(
    cli, cli_stdin, project, tmp_path
):
    cli("note", "add", project, "decision", "Ship weekly", "--made", "2026-09-06")
    cli(
        "note",
        "add",
        project,
        "decision",
        "Ship daily",
        "--supersedes",
        "N1",
        "--made",
        "2026-09-07",
    )
    cli_stdin(
        "note",
        "add",
        project,
        "handoff",
        "Keys in vault",
        "--step",
        "S1",
        "--for",
        "S2",
        "--file",
        "-",
        stdin="Under ci/.",
    )
    diagram = tmp_path / "diagram.png"
    diagram.write_bytes(b"png-bytes")
    asset = data(cli("note", "attach", project, "N3", str(diagram), "--json"))["path"]
    shown = data(cli("agent", "prompt", "S2", "--json"))
    prompt = shown["prompt"]
    assert "## Notes for this step" in prompt and "Under ci/." in prompt
    assert prompt.index("## Instructions") < prompt.index("## Notes for this step")
    assert prompt.index("## Notes for this step") < prompt.index("## Notes so far")
    assert "- N2 · Ship daily (7 September)" in prompt
    assert "Ship weekly" not in prompt and "Decisions so far" not in prompt
    assert asset in shown["files"] and f"- {asset}" in prompt
    assert "dplanner note add 'Search rewrite' handoff" in prompt


def test_a_project_with_no_notes_briefs_none(cli, project):
    prompt = data(cli("agent", "prompt", "S1", "--json"))["prompt"]
    assert "Notes" not in prompt.split("## When you are done")[0]


# -- the two retired modules --------------------------------------------------------------------


def test_an_old_decision_log_is_taken_over_as_decision_notes(cli, project, workspace, cli_library):
    modules = workspace / "search-rewrite" / "modules"
    modules.mkdir(exist_ok=True)
    (modules / "decisions.json").write_text(
        json.dumps(
            {
                "format": 1,
                "decisions": [
                    {"id": "D1", "title": "Keep SQLite", "body": "Why.", "made": "2026-09-05"},
                    {"id": "D3", "title": "Ship daily", "supersedes": "D1"},
                ],
            }
        )
    )
    listed = cli("note", "list", project, "--all")
    assert "N1   decision     Keep SQLite  5 September  — superseded by N2" in listed
    first, second = log(cli_library)
    assert (first.id, first.label, first.body) == ("N1", "decision", "Why.")
    assert second.supersedes == "N1"
    assert not (modules / "decisions.json").exists()
    assert (modules / "notes.json").exists()


def test_an_old_handoff_is_absorbed_as_a_handoff_note_with_its_files(
    cli, project, workspace, cli_library
):
    step_modules = workspace / "search-rewrite" / "steps" / "draft-the-model" / "modules"
    step_modules.mkdir(parents=True, exist_ok=True)
    (step_modules / "step_handoff.md").write_text("# Keys live in the vault\n\nAsk ops.\n")
    (step_modules / "step_handoff.json").write_text(json.dumps({"scope": "project", "format": 1}))
    assets = step_modules / "step_handoff" / "assets"
    assets.mkdir(parents=True)
    (assets / "0123456789abcdef.png").write_bytes(b"png-bytes")
    other = workspace / "search-rewrite" / "steps" / "build-the-index" / "modules"
    other.mkdir(parents=True, exist_ok=True)
    (other / "step_handoff.json").write_text(json.dumps({"on": True, "format": 1}))

    listed = cli("note", "list", project)
    assert "N1   handoff      Keys live in the vault  on S1" in listed
    (note,) = log(cli_library)
    assert note.reach == "project" and note.step
    assert note.body.startswith("# Keys live in the vault\n\nAsk ops.")
    assert "![" in note.body and "](assets/" in note.body
    shown = data(cli("note", "show", project, "N1", "--json"))
    assert shown["reach"] == "project"
    # The step's entries and files are gone; the project's notes area holds the file.
    assert not (step_modules / "step_handoff.md").exists()
    assert not (step_modules / "step_handoff.json").exists()
    assert not (other / "step_handoff.json").exists()
    assert not list(assets.glob("*"))
    moved = list((workspace / "search-rewrite" / "modules" / "notes" / "assets").glob("*.png"))
    assert len(moved) == 1 and moved[0].read_bytes() == b"png-bytes"
    # Every step after S1 sees it; a second open finds nothing left to absorb.
    assert "N1 · Keys live in the vault" in cli("note", "index", "S2")
    assert len(log(cli_library)) == 1


def test_a_long_handoff_titles_itself_from_its_first_line(cli, project, workspace, cli_library):
    step_modules = workspace / "search-rewrite" / "steps" / "draft-the-model" / "modules"
    step_modules.mkdir(parents=True, exist_ok=True)
    words = " ".join(["word"] * 30)
    (step_modules / "step_handoff.md").write_text(f"\n- {words}\nmore\n")
    cli("note", "list", project)
    (note,) = log(cli_library)
    assert note.title.endswith("…") and len(note.title) <= 81 and note.title.startswith("word")
    assert note.reach == ""
