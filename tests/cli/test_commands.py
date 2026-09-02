"""The CLI, over a real library.

**No ``qapp`` fixture anywhere in this file.** That it can run at all — parse, open, mutate,
flush — without a QApplication is the real proof the layering holds; the architecture test
checks the imports, this checks the behaviour.
"""

import json
from io import StringIO

import pytest

from dplanner.cli.command import CliError
from dplanner.cli.discovery import find_current_project, find_library
from dplanner.core.storage.locations import init_repo
from dplanner.domain.library_file import LIBRARY_ENV, write_library_file
from dplanner.domain.seed import create_library, seed_project
from dplanner.domain.store import LibraryStore


def data(text):
    return json.loads(text)


# -- finding the library -----------------------------------------------------------------------


@pytest.fixture
def libraries(tmp_path):
    """Two real library files, so precedence has something to choose between."""
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    create_library(first)
    create_library(second)
    return first, second


def test_an_explicit_library_beats_the_environment(libraries, monkeypatch):
    first, second = libraries
    monkeypatch.setenv(LIBRARY_ENV, str(second))
    assert find_library(str(first)) == first


def test_the_environment_beats_the_default(libraries, monkeypatch):
    _first, second = libraries
    monkeypatch.setenv(LIBRARY_ENV, str(second))
    assert find_library() == second


def test_nothing_named_means_the_per_user_default(libraries, monkeypatch):
    first, _second = libraries
    monkeypatch.delenv(LIBRARY_ENV, raising=False)
    monkeypatch.setattr("dplanner.domain.library_file.default_library_path", lambda: first)
    assert find_library() == first


def test_a_missing_library_is_a_refusal_that_names_the_fixes(tmp_path, monkeypatch):
    monkeypatch.delenv(LIBRARY_ENV, raising=False)
    with pytest.raises(CliError, match="no project library at"):
        find_library(str(tmp_path / "nowhere.json"))


# -- finding the current project ---------------------------------------------------------------


def open_library_of(tmp_path, *project_dirs):
    """A loaded library listing exactly these project directories."""
    path = tmp_path / "resolve-library.json"
    write_library_file(path, list(project_dirs))
    store = LibraryStore(path)
    return store.load(), store


@pytest.fixture
def repo(tmp_path):
    return init_repo(tmp_path / "checkout")


def test_the_project_is_found_by_walking_up(repo, tmp_path):
    """The whole point: an agent already sitting in the project needs no configuration."""
    directory = seed_project(repo / "planning", "Widget")
    library, store = open_library_of(tmp_path, directory)
    deep = directory / "notes"
    deep.mkdir()
    found = find_current_project(library, store, start=deep)
    assert found is not None and found.title == "Widget"


def test_a_pointer_file_reaches_a_project_the_walk_never_enters(repo, tmp_path):
    """A plan in `planning/` under a repo root is invisible to an upward walk; the one-line
    `.dplanner` seed_project leaves at the root is how the repo says where it is."""
    directory = seed_project(repo / "planning", "Widget")
    library, store = open_library_of(tmp_path, directory)
    deep = repo / "src" / "somewhere"
    deep.mkdir(parents=True)
    assert (repo / ".dplanner").read_text().strip() == "planning"
    found = find_current_project(library, store, start=deep)
    assert found is not None and found.title == "Widget"


def test_a_real_project_wins_over_a_pointer_beside_it(repo, tmp_path):
    directory = seed_project(repo / "planning", "Widget")
    library, store = open_library_of(tmp_path, directory)
    (directory / ".dplanner").write_text(str(tmp_path / "elsewhere"))
    found = find_current_project(library, store, start=directory)
    assert found is not None and found.title == "Widget"


def test_a_dangling_pointer_is_an_error_not_a_fallthrough(tmp_path):
    library, store = open_library_of(tmp_path)
    stray = tmp_path / "stray"
    stray.mkdir()
    (stray / ".dplanner").write_text("nowhere")
    with pytest.raises(CliError, match="points at"):
        find_current_project(library, store, start=stray)


def test_a_project_outside_the_library_is_refused_not_half_served(repo, tmp_path):
    directory = seed_project(repo / "planning", "Widget")
    library, store = open_library_of(tmp_path)  # the library has never heard of it
    with pytest.raises(CliError, match="not in your library"):
        find_current_project(library, store, start=directory)


def test_the_repository_resolves_the_project_when_the_walk_finds_nothing(repo, tmp_path):
    """Anywhere in the checkout — not just under the plan — is inside the project."""
    directory = seed_project(repo / "planning", "Widget")
    (repo / ".dplanner").unlink()  # leave only the repo itself to say so
    library, store = open_library_of(tmp_path, directory)
    deep = repo / "src" / "somewhere"
    deep.mkdir(parents=True)
    found = find_current_project(library, store, start=deep)
    assert found is not None and found.title == "Widget"


def test_a_repository_with_several_projects_asks_rather_than_guessing(repo, tmp_path):
    one = seed_project(repo / "one", "Widget")
    two = seed_project(repo / "two", "Gadget")
    (repo / ".dplanner").unlink()
    library, store = open_library_of(tmp_path, one, two)
    deep = repo / "src"
    deep.mkdir()
    with pytest.raises(CliError, match="pass --project") as refusal:
        find_current_project(library, store, start=deep)
    assert "Widget" in str(refusal.value) and "Gadget" in str(refusal.value)


def test_nowhere_at_all_means_no_current_project(tmp_path):
    library, store = open_library_of(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    assert find_current_project(library, store, start=outside) is None


def test_an_explicit_name_wins_over_any_working_directory(repo, tmp_path):
    directory = seed_project(repo / "planning", "Widget")
    library, store = open_library_of(tmp_path, directory)
    outside = tmp_path / "outside"
    outside.mkdir()
    found = find_current_project(library, store, explicit="Widget", start=outside)
    assert found is not None and found.title == "Widget"


# -- reading -----------------------------------------------------------------------------------


def test_an_empty_library_says_so_rather_than_printing_nothing(cli):
    assert "No projects yet" in cli("project", "list")


def test_json_works_after_the_verb_as_well_as_before(cli):
    """Argparse wants global options first; nobody types them that way."""
    assert data(cli("project", "list", "--json"))["projects"] == []
    assert data(cli("--json", "project", "list"))["projects"] == []


# -- writing -----------------------------------------------------------------------------------


def test_a_verb_writes_to_disk_and_the_next_run_sees_it(cli, workspace):
    cli("project", "create", "Search rewrite", "--summary", "Replace the index")
    assert (workspace / "search-rewrite" / "project.dproj").is_file()
    rows = data(cli("project", "list", "--json"))["projects"]
    assert [row["title"] for row in rows] == ["Search rewrite"]


def test_project_delete_takes_the_directory_with_it(cli, workspace):
    """`library remove` keeps the files; delete is the verb that really deletes."""
    cli("project", "create", "Discovery")
    assert (workspace / "discovery" / "project.dproj").is_file()
    said = cli("project", "delete", "Discovery")
    assert str(workspace / "discovery") in said
    assert not (workspace / "discovery").exists()
    assert data(cli("project", "list", "--json"))["projects"] == []


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
    before = (workspace / "discovery" / "project.dproj").read_bytes()
    cli("project", "rename", "Discovery", expect=1)
    assert (workspace / "discovery" / "project.dproj").read_bytes() == before


def test_an_ambiguous_name_asks_rather_than_guessing(cli):
    cli("project", "create", "Discovery one")
    cli("project", "create", "Discovery two")
    message = cli("project", "show", "Discovery", expect=1)
    assert "matches several" in message
    # The message has to say what to type next, so it names the ids.
    ids = [row["id"][:8] for row in data(cli("project", "list", "--json"))["projects"]]
    assert all(short in message for short in ids)
    # And what it says to type has to work: the short id it printed resolves.
    shown = data(cli("project", "show", ids[0], "--json"))
    assert shown["id"].startswith(ids[0])


def test_a_short_id_prefix_finds_a_step(cli):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Deploy")
    full = data(cli("step", "show", "Deploy", "--json"))["id"]
    assert data(cli("step", "show", full[:8], "--json"))["id"] == full


def test_unlink_removes_only_that_edge(cli):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "A")
    cli("step", "add", "Discovery", "B")
    cli("step", "add", "Discovery", "C", "--after", "A", "--after", "B")
    cli("step", "unlink", "C", "A")
    assert len(data(cli("step", "show", "C", "--json"))["requires"]) == 1


def test_disconnect_cuts_the_links_that_cross_the_set_and_keeps_the_rest(cli):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "A")
    cli("step", "add", "Discovery", "B", "--after", "A")
    cli("step", "add", "Discovery", "C", "--after", "B")
    cli("step", "add", "Discovery", "D", "--after", "C")
    ids = {title: data(cli("step", "show", title, "--json"))["id"] for title in "ABCD"}
    report = data(cli("step", "disconnect", "B", "C", "--json"))
    assert [(edge["waiter"], edge["source"]) for edge in report["removed"]] == [
        (ids["B"], ids["A"]),
        (ids["D"], ids["C"]),
    ]
    assert data(cli("step", "show", "B", "--json"))["requires"] == []
    assert len(data(cli("step", "show", "C", "--json"))["requires"]) == 1  # B → C stays.
    assert data(cli("step", "show", "D", "--json"))["requires"] == []


def test_disconnecting_a_step_with_no_links_is_already_done(cli):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "A")
    assert "Nothing links" in cli("step", "disconnect", "A")


# -- the agent instruction at both levels ------------------------------------------------------


def test_agent_set_and_show_take_a_project(cli, cli_stdin, workspace):
    cli("project", "create", "Discovery")
    cli_stdin("agent", "set", "--for-project", "Discovery", "--file", "-", stdin="House rules.")
    assert (
        workspace / "discovery" / "modules" / "step_agent_instruction.md"
    ).is_file()
    shown = data(cli("agent", "show", "--for-project", "Discovery", "--json"))
    assert shown["markdown"] == "House rules."
    assert "project" in shown


def test_a_bare_for_project_flag_means_the_current_project(cli, cli_stdin):
    """`--for-project` with no name reads the invocation's project scope."""
    cli("project", "create", "Discovery")
    cli_stdin(
        "agent", "set", "--for-project", "--file", "-", "--project", "Discovery",
        stdin="House rules.",
    )
    shown = data(cli("agent", "show", "--for-project", "--project", "Discovery", "--json"))
    assert shown["markdown"] == "House rules."
    # And with no scope anywhere, the refusal says what to do.
    assert "pass --project" in cli("agent", "show", "--for-project", expect=1)


def test_agent_show_needs_exactly_one_target(cli):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Deploy")
    message = cli("agent", "show", expect=1)
    assert "but not both" in message
    message = cli("agent", "show", "Deploy", "--for-project", "Discovery", expect=1)
    assert "but not both" in message


def test_agent_prompt_opens_with_the_project_instruction(cli, cli_stdin):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Deploy")
    cli_stdin("agent", "set", "Deploy", "--file", "-", stdin="Ship it.")
    cli_stdin("agent", "set", "--for-project", "Discovery", "--file", "-", stdin="House rules.")
    shown = data(cli("agent", "prompt", "Deploy", "--json"))
    assert "## Project instructions" in shown["prompt"]
    assert shown["prompt"].index("House rules.") < shown["prompt"].index("Ship it.")


def test_agent_prompt_works_from_the_standing_instruction_alone(cli, cli_stdin):
    """The standing instruction is "prepended to every briefing" — so an agent step with
    no prose of its own still has a briefing, exactly as the GUI's Preview shows."""
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Deploy", "--agent")
    cli_stdin("agent", "set", "--for-project", "Discovery", "--file", "-", stdin="House rules.")
    shown = data(cli("agent", "prompt", "Deploy", "--json"))
    assert "House rules." in shown["prompt"]
    # No empty section for the instruction the step does not have.
    assert "## Instructions" not in shown["prompt"]


def test_agent_prompt_briefs_with_the_description(cli, cli_stdin):
    """The description is the instructions: on an agent step with no separate instruction
    it renders once, under ## Instructions, not as a ## Description section too."""
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Deploy", "--agent")
    cli_stdin("describe", "set", "Deploy", "--file", "-", stdin="The release step.")
    prompt = data(cli("agent", "prompt", "Deploy", "--json"))["prompt"]
    assert "## Instructions" in prompt and "The release step." in prompt
    assert "## Description" not in prompt
    assert prompt.count("The release step.") == 1


def test_agent_prompt_is_a_self_contained_briefing(cli, cli_stdin, tmp_path):
    """One read gives an executing agent everything: description, the requirements the
    step answers to (titles AND quotes), where the work lands, then the instructions."""
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Deploy")
    cli_stdin("agent", "set", "Deploy", "--file", "-", stdin="Ship it.")
    cli_stdin("describe", "set", "Deploy", "--file", "-", stdin="The release step.")
    spec = tmp_path / "spec.txt"
    spec.write_text("The system must deploy on tag.\n")
    cli("spec", "import", "Discovery", str(spec))
    cli(
        "spec", "mark", "Discovery", "spec",
        "--title", "Deploy on tag", "--quote", "must deploy on tag",
    )
    cli("spec", "link", "Deploy", "r1")
    cli("github", "set", "Deploy", "--branch", "deploy-work")

    prompt = data(cli("agent", "prompt", "Deploy", "--json"))["prompt"]
    assert "## Description" in prompt and "The release step." in prompt
    assert "**Deploy on tag** (r1, in spec)" in prompt
    assert "> must deploy on tag" in prompt
    assert "Branch: deploy-work" in prompt
    # What the step is, before why it exists, before how to carry it out.
    assert prompt.index("## Description") < prompt.index("## Requirements")
    assert prompt.index("## Requirements") < prompt.index("## Instructions")
    assert prompt.index("## Instructions") < prompt.index("Ship it.")


def test_agent_prompt_says_when_a_requirement_link_dangles(cli, cli_stdin, tmp_path):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Deploy")
    cli_stdin("agent", "set", "Deploy", "--file", "-", stdin="Ship it.")
    spec = tmp_path / "spec.txt"
    spec.write_text("The system must deploy on tag.\n")
    cli("spec", "import", "Discovery", str(spec))
    cli("spec", "mark", "Discovery", "spec", "--title", "Deploy on tag")
    cli("spec", "link", "Deploy", "r1")
    cli("spec", "unmark", "Discovery", "r1")
    prompt = data(cli("agent", "prompt", "Deploy", "--json"))["prompt"]
    assert "r1 (no longer in the spec index)" in prompt


def test_agent_prompt_lists_description_figures_as_files(cli, cli_stdin, tmp_path):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Deploy")
    cli_stdin("agent", "set", "Deploy", "--file", "-", stdin="Ship it.")
    figure = tmp_path / "diagram.png"
    figure.write_bytes(b"png bytes")
    cli("describe", "attach", "Deploy", str(figure))
    shown = data(cli("agent", "prompt", "Deploy", "--json"))
    attached = [path for path in shown["files"] if "step_description" in path]
    assert len(attached) == 1 and attached[0].endswith(".png")
    assert attached[0] in shown["prompt"]


def test_agent_prompt_refuses_a_step_that_is_not_an_agent_step(cli):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Deploy")
    message = cli("agent", "prompt", "Deploy", expect=1)
    assert "not an agent step" in message
    assert "agent on 'Deploy'" in message


def test_agent_prompt_with_nothing_to_brief_names_both_fixes(cli):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Deploy", "--agent")
    message = cli("agent", "prompt", "Deploy", expect=1)
    assert "describe set 'Deploy'" in message
    assert "agent set --for-project" in message


def test_agent_on_and_off_bracket_the_aspect(cli, cli_stdin):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Deploy")
    shown = data(cli("agent", "show", "Deploy", "--json"))
    assert shown["agent"] is False

    cli("agent", "on", "Deploy")
    shown = data(cli("agent", "show", "Deploy", "--json"))
    assert shown["agent"] is True and shown["separate"] is False
    assert "already an agent step" in cli("agent", "on", "Deploy")

    # A separate instruction implies the aspect; `off` drops both.
    cli_stdin("agent", "set", "Deploy", "--file", "-", stdin="Ship it.")
    shown = data(cli("agent", "show", "Deploy", "--json"))
    assert shown["separate"] is True
    cli("agent", "off", "Deploy")
    shown = data(cli("agent", "show", "Deploy", "--json"))
    assert shown["agent"] is False and shown["markdown"] == ""
    # Already in the target state is success, so a batch of offs survives.
    assert "already not an agent step" in cli("agent", "off", "Deploy")


def test_agent_set_clear_drops_the_instruction_but_keeps_the_mark(cli, cli_stdin):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Deploy")
    # The mark here is implied by the text alone — clearing must still leave an agent step.
    cli_stdin("agent", "set", "Deploy", "--file", "-", stdin="Ship it.")
    assert data(cli("agent", "show", "Deploy", "--json"))["separate"] is True

    said = cli("agent", "set", "Deploy", "--clear")
    assert "description is the briefing" in said
    shown = data(cli("agent", "show", "Deploy", "--json"))
    assert shown["agent"] is True and shown["separate"] is False and shown["markdown"] == ""

    # Idempotent: clearing again is success, and still does not unmark.
    cli("agent", "set", "Deploy", "--clear")
    assert data(cli("agent", "show", "Deploy", "--json"))["agent"] is True


def test_agent_set_clear_on_a_plain_step_does_not_mark_it(cli):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Deploy")
    assert "no separate instruction" in cli("agent", "set", "Deploy", "--clear")
    assert data(cli("agent", "show", "Deploy", "--json"))["agent"] is False


def test_agent_set_needs_exactly_one_of_file_and_clear(cli, tmp_path):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Deploy")
    assert "give --file or --clear" in cli("agent", "set", "Deploy", expect=1)
    notes = tmp_path / "notes.md"
    notes.write_text("Ship it.")
    said = cli("agent", "set", "Deploy", "--file", str(notes), "--clear", expect=1)
    assert "give --file or --clear" in said


def test_agent_set_clear_for_project_empties_the_standing_instruction(cli, cli_stdin):
    cli("project", "create", "Discovery")
    cli_stdin("agent", "set", "--for-project", "Discovery", "--file", "-", stdin="House rules.")
    assert "House rules." in cli("agent", "show", "--for-project", "Discovery")
    assert "no standing instruction" in cli("agent", "set", "--for-project", "Discovery", "--clear")
    assert "(no instruction)" in cli("agent", "show", "--for-project", "Discovery")


def test_state_clearing_verbs_treat_already_clear_as_success(cli):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Deploy")
    assert "not a milestone" in cli("milestone", "clear", "Deploy")
    assert "no ticket" in cli("ticket", "clear", "Deploy")
    assert "no GitHub refs" in cli("github", "clear", "Deploy")
    # The two aspects whose default is *on* clear to an opt-out rather than to absence, so
    # "already clear" means "already opted out" — still success, and still idempotent.
    assert "no estimate" in cli("estimate", "clear", "Deploy")
    assert "no estimate" in cli("estimate", "clear", "Deploy")
    assert "no description" in cli("describe", "clear", "Deploy")
    assert "no description" in cli("describe", "clear", "Deploy")


# -- authoring a step at birth -----------------------------------------------------------------


def test_step_add_authors_the_whole_step_in_one_call(cli, cli_stdin, tmp_path):
    cli("project", "create", "Discovery")
    spec = tmp_path / "spec.md"
    spec.write_text("The rule is argon2id.")
    cli("spec", "import", "Discovery", str(spec))
    cli("spec", "mark", "Discovery", "spec", "--title", "Hashing", "--quote", "argon2id")
    figure = tmp_path / "fig.png"
    figure.write_bytes(b"png bytes")
    cli("spec", "attach", "Discovery", str(figure))
    describe = tmp_path / "what.md"
    describe.write_text("An offline-first store.")

    cli_stdin(
        "step", "add", "Discovery", "Hash passwords",
        "--describe-file", str(describe), "--agent-file", "-",
        "--days", "3", "--link", "r1", "--attach", "a1",
        stdin="Use argon2id.",
    )

    assert data(cli("describe", "show", "Hash passwords", "--json"))["markdown"].startswith(
        "An offline-first"
    )
    assert data(cli("agent", "show", "Hash passwords", "--json"))["markdown"] == "Use argon2id."
    shown = data(cli("step", "show", "Hash passwords", "--json"))
    assert shown["aspects"]["estimation"]["days"] == 3.0
    assert shown["aspects"]["spec"]["requirements"] == ["r1"]
    assert shown["aspects"]["spec"]["attachments"][0]["asset"] == "a1"
    # One call, and the authoring lint checks have nothing left to say about this step.
    report = data(cli("project", "lint", "Discovery", "--json", expect=1))
    complaints = {row["check"] for row in report["findings"] if row["title"] == "Hash passwords"}
    assert complaints == set()


def test_a_failing_author_leaves_no_step_behind(cli, tmp_path):
    """The transaction is the rollback: a refused flag aborts the whole add."""
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Doomed", "--days", "-1", expect=1)
    assert data(cli("step", "list", "Discovery", "--json"))["steps"] == []
    cli("step", "add", "Discovery", "Doomed", "--link", "r9", expect=1)
    assert data(cli("step", "list", "Discovery", "--json"))["steps"] == []


def test_two_stdin_flags_are_refused_before_either_reads(cli):
    cli("project", "create", "Discovery")
    out = cli(
        "step", "add", "Discovery", "Deploy",
        "--describe-file", "-", "--agent-file", "-", expect=1,
    )
    assert "one flag may read stdin" in out
    assert data(cli("step", "list", "Discovery", "--json"))["steps"] == []


def test_clear_steps_keeps_the_project_and_what_it_owns(cli, tmp_path):
    cli("project", "create", "Discovery")
    for title in ("A", "B", "C"):
        cli("step", "add", "Discovery", title)
    cli("schedule", "start", "Discovery", "--date", "2026-09-01")
    spec = tmp_path / "spec.md"
    spec.write_text("# Spec")
    cli("spec", "import", "Discovery", str(spec))
    cli("spec", "mark", "Discovery", "spec", "--title", "A rule")

    report = data(cli("project", "clear-steps", "Discovery", "--json"))
    assert len(report["removed"]) == 3
    assert data(cli("step", "list", "Discovery", "--json"))["steps"] == []
    # The re-plan keeps everything the steps did not own.
    assert data(cli("schedule", "show", "Discovery", "--json"))["start"] == "2026-09-01"
    listed = data(cli("spec", "requirements", "Discovery", "--json"))["requirements"]
    assert [req["id"] for req in listed] == ["r1"]


def test_clear_steps_on_an_empty_project_is_a_calm_zero(cli):
    cli("project", "create", "Discovery")
    out = cli("project", "clear-steps", "Discovery")
    assert "all 0 steps" in out


# -- the schedule's two assumptions ------------------------------------------------------------


def test_schedule_show_names_both_assumptions(cli):
    """A diamond graph: serial totals every step, the critical path takes the heavier
    branch — and each line says which assumption produced it."""
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "A")
    cli("step", "add", "Discovery", "B", "--after", "A")
    cli("step", "add", "Discovery", "C", "--after", "A")
    cli("step", "add", "Discovery", "D", "--after", "B", "--after", "C")
    for title, days in (("A", "1"), ("B", "2"), ("C", "10"), ("D", "1")):
        cli("estimate", "set", title, "--days", days)
    cli("schedule", "start", "Discovery", "--date", "2026-09-07")

    shown = data(cli("schedule", "show", "Discovery", "--json"))
    assert shown["days"] == 14 and shown["assumption"] == "serial"
    path = shown["critical_path"]
    assert path["days"] == 12
    assert [step["title"] for step in path["steps"]] == ["A", "C", "D"]

    text = cli("schedule", "show", "Discovery")
    assert "(serial: one worker, steps end to end)" in text
    assert "critical path:" in text and "unlimited workers" in text
    assert "A → C → D" in text


# -- the graph as text -------------------------------------------------------------------------


def test_project_graph_draws_waves_and_edges(cli):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Read the spec")
    cli("step", "add", "Discovery", "Draft the model", "--after", "Read the spec")
    cli("step", "add", "Discovery", "Interview users")
    chart = data(cli("project", "graph", "Discovery", "--json"))["mermaid"]
    assert chart.startswith("flowchart TD")
    # Both independent steps sit in wave 1, the dependent one in wave 2.
    assert 'subgraph wave1["Wave 1"]' in chart and 'subgraph wave2["Wave 2"]' in chart
    read = data(cli("step", "show", "Read the spec", "--json"))["id"][:12]
    draft = data(cli("step", "show", "Draft the model", "--json"))["id"][:12]
    assert f"s{read} --> s{draft}" in chart


def test_project_graph_quotes_awkward_titles(cli):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", 'Say "hello" [loudly]')
    chart = cli("project", "graph", "Discovery")
    assert '"Say #quot;hello#quot; [loudly]"' in chart


def test_project_graph_short_uses_positional_ids_and_cut_titles(cli):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "A step with a very long descriptive title indeed")
    cli("step", "add", "Discovery", "B", "--after", "A step")
    chart = cli("project", "graph", "Discovery", "--short")
    assert 's1["1: A step with a very long…"]' in chart
    assert 's2["2: B"]' in chart
    assert "s1 --> s2" in chart


def test_project_graph_of_an_empty_project_is_still_a_chart(cli):
    cli("project", "create", "Discovery")
    assert "no steps yet" in cli("project", "graph", "Discovery")


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


def test_the_standing_instruction_survives_the_round_trip(cli, cli_stdin, monkeypatch):
    """The project's prose — its standing agent instruction — is as much the plan as its
    start date; a document without it made export-then-import quietly lossy."""
    cli("project", "create", "Discovery")
    cli_stdin("agent", "set", "--for-project", "Discovery", "--file", "-", stdin="House rules.")
    document = data(cli("project", "export", "Discovery"))
    assert document["text"]["step_agent_instruction"] == "House rules."

    monkeypatch.setattr("sys.stdin", StringIO(json.dumps(document)))
    cli("project", "import", "--title", "Copy")
    shown = data(cli("agent", "show", "--for-project", "Copy", "--json"))
    assert shown["markdown"] == "House rules."


def test_a_document_from_before_text_existed_still_imports(cli, monkeypatch):
    monkeypatch.setattr("sys.stdin", StringIO(json.dumps({"title": "Old", "steps": []})))
    cli("project", "import")
    assert "Old" in cli("project", "list")


def test_import_refuses_something_that_is_not_a_document(cli, monkeypatch):
    monkeypatch.setattr("sys.stdin", StringIO("not json"))
    assert "not valid JSON" in cli("project", "import", expect=1)
