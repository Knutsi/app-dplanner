"""The docs aspects, what a collector compiles from, and when that goes out of date.

No ``qapp`` fixture: ``aspect.py``, ``collect.py`` and ``cli.py`` are Qt-free by rule, and
this file exercising them without one is what proves it beyond the import check.
"""

import json

import pytest

from dplanner.domain.commands import SetEdgesCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.scope import ScopeKind
from dplanner.domain.store import LibraryStore
from dplanner.modules.docs.aspect import (
    COMPILED_ID,
    MODULE_ID,
    enabled,
    read,
    read_compiled,
    read_digest,
    summary,
    write_stamp,
    write_state,
)
from dplanner.modules.docs.collect import (
    as_markdown,
    digest,
    fragments,
    sources_for,
    state_of,
    user_prompt,
)


@pytest.fixture
def cli(cli):
    """The shared CLI over a seeded project — the conftest fixture, pre-populated."""
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Write the parser")
    return cli


@pytest.fixture
def reload(cli_library):
    return lambda: LibraryStore(cli_library).load()


def first_step(library):
    return library.projects[0].steps[0]


# -- the two aspects ---------------------------------------------------------------------------


def test_a_step_documents_nothing_until_it_says_so():
    assert enabled(Step(title="A")) is False
    assert summary(Step(title="A")) == ""


def test_prose_alone_reads_as_on_so_the_cli_needs_no_toggle():
    """Documentation written before anybody touched the toggle still shows its tab."""
    step = Step(title="A")
    step.module_text[MODULE_ID] = "You can now sign in."
    assert enabled(step) is True
    assert summary(step) == "documented"


def test_off_writes_nothing_so_the_file_disappears():
    assert write_state(False) == {}


def test_the_two_aspects_keep_separate_documents():
    """A feature legitimately has both: its own note, and what it compiled."""
    step = Step(title="Auth")
    step.module_text[MODULE_ID] = "A note."
    step.module_text[COMPILED_ID] = "# Signing in"
    assert read(step) == "A note."
    assert read_compiled(step) == "# Signing in"


def test_the_stamp_writes_its_numbers_as_floats():
    """FORMAT.md: a file's bytes must not depend on whether the project was reopened."""
    stamp = write_stamp("abc", 1756000000, "OpenAI", "gpt-5", 4)
    assert isinstance(stamp["at"], float)
    assert isinstance(stamp["sources"], float)
    assert stamp["digest"] == "abc"


# -- the graph ---------------------------------------------------------------------------------


def graph(*titles):
    """A chain: each step requires the one before it."""
    library = Library()
    project = Project(title="Discovery")
    library.add_child(library.id, project)
    previous = ""
    for title in titles:
        step = Step(title=title)
        library.add_child(project.id, step)
        if previous:
            SetEdgesCommand(step.id, "requires", [previous]).redo(library)
        previous = step.id
    return library, project


def is_feature(step):
    return bool(step.module_data.get("feature"))


def is_milestone(step):
    return bool(step.module_data.get("step_milestone"))


# The kinds, written as the composition root writes them.
KINDS = (
    ScopeKind("step_milestone", "Milestone", is_milestone, is_milestone, gathers="feature"),
    ScopeKind(
        "feature",
        "Feature",
        is_feature,
        lambda step: is_feature(step) or is_milestone(step),
    ),
)


def document(step, body):
    step.module_text[MODULE_ID] = body


def compile_it(library, project, step, body):
    """Stand in for a run of the LLM: store a document and stamp what it read."""
    stamp = write_stamp(digest(sources_for(KINDS, library, project, step.id)), 1.0, "F", "m", 1)
    step.module_text[COMPILED_ID] = body
    step.module_data[COMPILED_ID] = stamp


def titles(sources):
    return [source.step.title for source in sources]


# -- what a collector reads --------------------------------------------------------------------


def test_a_feature_reads_the_fragments_behind_it_and_its_own():
    library, project = graph("A", "B", "Auth")
    a, _b, auth = project.steps
    auth.module_data["feature"] = {"feature": "f1"}
    document(a, "About A")
    document(auth, "About the feature")
    assert titles(sources_for(KINDS, library, project, auth.id)) == ["A", "Auth"]
    assert "## A" in as_markdown(sources_for(KINDS, library, project, auth.id))


def test_a_feature_stops_at_the_feature_before_it():
    library, project = graph("A", "First", "B", "Second")
    a, first, b, second = project.steps
    for step in (first, second):
        step.module_data["feature"] = {"feature": "f1"}
    document(a, "About A")
    document(b, "About B")
    assert titles(sources_for(KINDS, library, project, second.id)) == ["B"]


def test_a_milestone_reads_its_features_compiled_documents():
    """Milestones collect from their features, not from the notes all over again."""
    library, project = graph("A", "Auth", "B", "Search", "v1")
    a, auth, b, search, v1 = project.steps
    for step in (auth, search):
        step.module_data["feature"] = {"feature": "f1"}
    v1.module_data["step_milestone"] = {"label": "v1"}
    document(a, "About A")
    document(b, "About B")
    compile_it(library, project, auth, "# Signing in")
    compile_it(library, project, search, "# Searching")

    sources = sources_for(KINDS, library, project, v1.id)
    assert titles(sources) == ["Auth", "Search"]
    assert [source.compiled for source in sources] == [True, True]
    assert "# Signing in" in as_markdown(sources)
    # Never the notes those documents were made of: that would say everything twice.
    assert "About A" not in as_markdown(sources)


def test_a_milestone_falls_back_to_a_features_notes_when_it_has_no_document():
    """A half-compiled project still produces something honest."""
    library, project = graph("A", "Auth", "v1")
    a, auth, v1 = project.steps
    auth.module_data["feature"] = {"feature": "f1"}
    v1.module_data["step_milestone"] = {"label": "v1"}
    document(a, "About A")
    assert titles(sources_for(KINDS, library, project, v1.id)) == ["A"]


def test_a_milestone_also_reads_the_loose_steps_it_depends_on():
    """A step no feature gathers still reaches the release it is behind."""
    library, project = graph("A", "Auth", "Loose", "v1")
    a, auth, loose, v1 = project.steps
    auth.module_data["feature"] = {"feature": "f1"}
    v1.module_data["step_milestone"] = {"label": "v1"}
    document(a, "About A")
    document(loose, "About the loose step")
    compile_it(library, project, auth, "# Signing in")
    assert titles(sources_for(KINDS, library, project, v1.id)) == ["Auth", "Loose"]


def test_undocumented_steps_contribute_nothing():
    library, project = graph("A", "B")
    a, b = project.steps
    document(a, "About A")
    assert titles(fragments(library, project, b.id)) == ["A"]


# -- staleness ---------------------------------------------------------------------------------


def test_a_collector_nobody_compiled_reads_as_never():
    library, project = graph("A", "Auth")
    a, auth = project.steps
    auth.module_data["feature"] = {"feature": "f1"}
    document(a, "About A")
    assert state_of(KINDS, library, project, auth.id) == "never"


def test_a_fresh_compile_reads_as_current():
    library, project = graph("A", "Auth")
    a, auth = project.steps
    auth.module_data["feature"] = {"feature": "f1"}
    document(a, "About A")
    compile_it(library, project, auth, "# Signing in")
    assert state_of(KINDS, library, project, auth.id) == "current"


def test_editing_a_fragment_makes_its_feature_stale():
    library, project = graph("A", "Auth")
    a, auth = project.steps
    auth.module_data["feature"] = {"feature": "f1"}
    document(a, "About A")
    compile_it(library, project, auth, "# Signing in")
    document(a, "About A, revised")
    assert state_of(KINDS, library, project, auth.id) == "stale"


def test_hand_editing_the_document_does_not_make_it_stale():
    """The digest is over what was read, not over what was written — so a tweak stands."""
    library, project = graph("A", "Auth")
    a, auth = project.steps
    auth.module_data["feature"] = {"feature": "f1"}
    document(a, "About A")
    compile_it(library, project, auth, "# Signing in")
    auth.module_text[COMPILED_ID] = "# Signing in\n\nWith a one-time link."
    assert state_of(KINDS, library, project, auth.id) == "current"


def test_recompiling_a_feature_makes_its_milestone_stale():
    """The cascade, and it costs no notification plumbing: the milestone's sources changed."""
    library, project = graph("A", "Auth", "v1")
    a, auth, v1 = project.steps
    auth.module_data["feature"] = {"feature": "f1"}
    v1.module_data["step_milestone"] = {"label": "v1"}
    document(a, "About A")
    compile_it(library, project, auth, "# Signing in")
    compile_it(library, project, v1, "# Release v1")
    assert state_of(KINDS, library, project, v1.id) == "current"

    compile_it(library, project, auth, "# Signing in, rewritten")
    assert state_of(KINDS, library, project, v1.id) == "stale"


def test_relinking_the_graph_makes_a_document_stale():
    """What a collector gathers is derived, so a link changes the answer — and says so."""
    library, project = graph("A", "Auth")
    a, auth = project.steps
    auth.module_data["feature"] = {"feature": "f1"}
    document(a, "About A")
    compile_it(library, project, auth, "# Signing in")

    extra = Step(title="Later")
    library.add_child(project.id, extra)
    document(extra, "About later")
    SetEdgesCommand(auth.id, "requires", [a.id, extra.id]).redo(library)
    assert state_of(KINDS, library, project, auth.id) == "stale"


def test_the_prompt_drops_a_block_it_has_nothing_for():
    """A project with no house style must not be told there isn't one."""
    assert "House style" not in user_prompt("", "Be brief", "notes")
    assert "House style" in user_prompt("Second person", "Be brief", "notes")
    assert "(nothing yet)" in user_prompt("", "", "")


# -- the fragment verbs ------------------------------------------------------------------------


def test_set_writes_the_prose_and_the_mark_together(cli, cli_stdin, workspace, reload):
    cli_stdin("docs", "set", "Write the parser", "--file", "-", stdin="## Query syntax\n")
    folder = workspace / "discovery" / "steps" / "write-the-parser" / "modules"
    assert (folder / "docs.md").read_text() == "## Query syntax\n"
    assert json.loads((folder / "docs.json").read_text())["on"] is True
    assert enabled(first_step(reload())) is True


def test_show_says_so_when_a_step_documents_nothing(cli):
    assert "documents nothing" in cli("docs", "show", "Write the parser")


def test_clear_drops_the_prose_and_the_mark_in_one_go(cli, cli_stdin, workspace, reload):
    cli_stdin("docs", "set", "Write the parser", "--file", "-", stdin="Something\n")
    cli("docs", "clear", "Write the parser")
    folder = workspace / "discovery" / "steps" / "write-the-parser" / "modules"
    assert not (folder / "docs.md").exists()
    assert not (folder / "docs.json").exists()
    assert read(first_step(reload())) == ""


def test_clearing_twice_is_success_and_writes_nothing(cli):
    cli("docs", "clear", "Write the parser")
    cli("docs", "clear", "Write the parser")


def test_collect_says_so_when_there_is_nothing_behind(cli):
    assert "nothing behind it" in cli("docs", "collect", "Write the parser")


# -- the agent's loop --------------------------------------------------------------------------


@pytest.fixture
def documented(cli, cli_stdin):
    """A project with one documented step and one feature over it."""
    cli("step", "add", "Discovery", "Auth", "--after", "Write the parser")
    cli("feature", "set", "Auth")
    cli_stdin("docs", "set", "Write the parser", "--file", "-", stdin="Parses queries.\n")
    return cli


def status_rows(cli):
    return json.loads(cli("docs", "status", "--json"))["collectors"]


def test_collect_assembles_what_a_collector_would_read(documented):
    report = json.loads(documented("docs", "collect", "Auth", "--json"))
    assert [row["title"] for row in report["steps"]] == ["Write the parser"]
    assert report["markdown"] == "## Write the parser\n\nParses queries."


def test_status_names_every_collector_and_what_it_needs(documented):
    (row,) = status_rows(documented)
    assert (row["title"], row["state"], row["sources"]) == ("Auth", "never", 1)
    assert "compiled set" in row["message"]


def test_compiled_set_lands_the_document_and_stamps_it_current(documented, cli_stdin, workspace):
    cli_stdin("compiled", "set", "Auth", "--file", "-", stdin="# Signing in\n")
    folder = workspace / "discovery" / "steps" / "auth" / "modules"
    assert (folder / "docs_compiled.md").read_text() == "# Signing in\n"
    assert json.loads((folder / "docs_compiled.json").read_text())["digest"]
    assert status_rows(documented)[0]["state"] == "current"


def test_editing_a_fragment_afterwards_shows_up_in_status(documented, cli_stdin):
    cli_stdin("compiled", "set", "Auth", "--file", "-", stdin="# Signing in\n")
    cli_stdin("docs", "set", "Write the parser", "--file", "-", stdin="Parses queries, fast.\n")
    assert status_rows(documented)[0]["state"] == "stale"


def test_compiled_show_prints_it_and_clear_takes_it_away(documented, cli_stdin, workspace):
    cli_stdin("compiled", "set", "Auth", "--file", "-", stdin="# Signing in\n")
    assert "Signing in" in documented("compiled", "show", "Auth")
    documented("compiled", "clear", "Auth")
    folder = workspace / "discovery" / "steps" / "auth" / "modules"
    assert not (folder / "docs_compiled.md").exists()
    assert not (folder / "docs_compiled.json").exists()


def test_lint_reports_a_document_its_fragments_have_outgrown(documented, cli_stdin):
    cli_stdin("compiled", "set", "Auth", "--file", "-", stdin="# Signing in\n")
    cli_stdin("docs", "set", "Write the parser", "--file", "-", stdin="Parses queries, fast.\n")
    report = json.loads(documented("project", "lint", "--json", expect=1))
    stale = [f for f in report["findings"] if f["check"] == "docs.compiled-stale"]
    assert [f["title"] for f in stale] == ["Auth"]


def test_lint_is_quiet_once_it_has_been_recompiled(documented, cli_stdin):
    cli_stdin("compiled", "set", "Auth", "--file", "-", stdin="# Signing in\n")
    report = json.loads(documented("project", "lint", "--json", expect=1))
    assert not [f for f in report["findings"] if f["check"] == "docs.compiled-stale"]


def test_a_stored_digest_survives_a_reload(documented, cli_stdin, reload):
    cli_stdin("compiled", "set", "Auth", "--file", "-", stdin="# Signing in\n")
    auth = next(s for s in reload().projects[0].steps if s.title == "Auth")
    assert read_digest(auth)
