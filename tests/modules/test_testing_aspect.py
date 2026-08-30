"""The test aspect and the run records, with no application at all.

Both halves are plain functions over the model — the whole reason they live in Qt-free files
the CLI can reach without a graphics stack.
"""

import pytest

from dplanner.domain.commands import SetEdgesCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.modules.step_check import aspect as check
from dplanner.modules.testing import runs
from dplanner.modules.testing.aspect import (
    Test,
    covered,
    enabled,
    find,
    mint_ids,
    next_test_id,
    project_tests,
    read,
    replace,
    summary,
    write,
)


def build(*titles):
    library = Library()
    project = Project(title="Widget")
    library.add_child(library.id, project)
    for title in titles:
        library.add_child(project.id, Step(title=title))
    return library, project


def by_title(project, title):
    return next(step for step in project.steps if step.title == title)


def link(library, project, waiter, source):
    step = by_title(project, waiter)
    waiting = [*step.edges.get("requires", []), by_title(project, source).id]
    SetEdgesCommand(step.id, "requires", waiting).redo(library)


def give(step, *tests):
    step.module_data["testing"] = write(tests)


# -- the tests a step carries -------------------------------------------------------


def test_a_step_with_no_entry_carries_nothing():
    step = Step(title="A")
    assert read(step) == []
    assert not enabled(step)
    assert summary(step) == ""


def test_a_test_round_trips_through_the_entry():
    step = Step(title="A")
    give(step, Test("t1", "No flicker", "1. Open the list\n2. It must not flicker"))
    assert read(step) == [Test("t1", "No flicker", "1. Open the list\n2. It must not flicker")]
    assert enabled(step)


def test_an_empty_list_removes_the_file():
    assert write([]) == {}


def test_an_absent_body_and_flag_are_left_out_of_the_entry():
    """Absence encodes the default, so a plain test writes two keys and no more."""
    entry = write([Test("t1", "Just a title")])
    assert entry["tests"] == [{"id": "t1", "title": "Just a title"}]


def test_an_archived_test_still_reads_but_leaves_the_phrase():
    step = Step(title="A")
    give(step, Test("t1", "Live"), Test("t2", "Retired", archived=True))
    assert [test.id for test in read(step)] == ["t1", "t2"]
    assert summary(step) == "1 test"


def test_a_step_with_several_tests_says_how_many():
    step = Step(title="A")
    give(step, Test("t1", "One"), Test("t2", "Two"))
    assert summary(step) == "2 tests"


def test_unreadable_entries_read_as_absent_rather_than_raising():
    step = Step(title="A")
    step.module_data["testing"] = {"tests": [{"no": "id"}, "junk", {"id": "t1", "title": "Ok"}]}
    assert [test.id for test in read(step)] == ["t1"]
    step.module_data["testing"] = {"tests": "not a list"}
    assert read(step) == []


def test_replace_keeps_a_records_position():
    tests = [Test("t1", "One"), Test("t2", "Two"), Test("t3", "Three")]
    swapped = replace(tests, Test("t2", "Renamed"))
    assert [test.title for test in swapped] == ["One", "Renamed", "Three"]
    assert find(swapped, "t2") == Test("t2", "Renamed")


# -- ids are project-unique ---------------------------------------------------------


def test_ids_are_minted_across_the_whole_project_not_per_step():
    _library, project = build("A", "B")
    give(by_title(project, "A"), Test("t1", "One"), Test("t2", "Two"))
    assert next_test_id(project) == "t3"
    give(by_title(project, "B"), Test("t3", "Three"))
    assert next_test_id(project) == "t4"
    assert mint_ids(project, 3) == ["t4", "t5", "t6"]


def test_an_archived_test_still_holds_its_id():
    _library, project = build("A")
    give(by_title(project, "A"), Test("t1", "Gone", archived=True))
    assert next_test_id(project) == "t2"


def test_project_tests_walks_steps_then_tests_and_hides_the_archived():
    _library, project = build("A", "B")
    give(by_title(project, "A"), Test("t1", "One"), Test("t2", "Two", archived=True))
    give(by_title(project, "B"), Test("t3", "Three"))
    assert [test.id for _step, test in project_tests(project)] == ["t1", "t3"]
    assert [test.id for _step, test in project_tests(project, archived=True)] == [
        "t1",
        "t2",
        "t3",
    ]


# -- coverage: what a check, or a release, stands for --------------------------------


def test_a_check_covers_every_test_behind_it():
    library, project = build("Build", "Polish", "Pre-release check")
    give(by_title(project, "Build"), Test("t1", "One"))
    give(by_title(project, "Polish"), Test("t2", "Two"))
    link(library, project, "Polish", "Build")
    link(library, project, "Pre-release check", "Polish")
    scope = by_title(project, "Pre-release check")
    assert [test.id for _step, test in covered(library, project, scope.id)] == ["t1", "t2"]


def test_coverage_includes_the_scope_steps_own_tests():
    library, project = build("Build", "Check")
    give(by_title(project, "Build"), Test("t1", "One"))
    give(by_title(project, "Check"), Test("t2", "Two"))
    link(library, project, "Check", "Build")
    scope = by_title(project, "Check")
    assert [test.id for _step, test in covered(library, project, scope.id)] == ["t1", "t2"]


def test_coverage_reaches_nothing_that_is_not_behind_the_scope():
    library, project = build("Build", "Unrelated", "Check")
    give(by_title(project, "Build"), Test("t1", "One"))
    give(by_title(project, "Unrelated"), Test("t2", "Two"))
    link(library, project, "Check", "Build")
    scope = by_title(project, "Check")
    assert [test.id for _step, test in covered(library, project, scope.id)] == ["t1"]


# -- the check aspect ---------------------------------------------------------------


def test_a_check_is_a_marker_and_nothing_else():
    step = Step(title="A")
    assert not check.read(step)
    assert check.summary(step) == ""
    step.module_data["step_check"] = check.write(True)
    assert check.read(step)
    assert check.summary(step) == "check"
    assert check.write(False) == {}


# -- runs ---------------------------------------------------------------------------


def open_id(records):
    found = runs.open_run(records)
    assert found is not None
    return found.id


def outcome(records, test_id):
    found = runs.latest(records, test_id)
    assert found is not None
    return found


def project_with_runs(*records):
    project = Project(title="Widget")
    project.module_data["testing"] = runs.write(records)
    return project


def test_a_project_with_no_entry_has_no_runs():
    assert runs.read(Project(title="Widget")) == []
    assert runs.write([]) == {}


def test_a_run_round_trips_with_its_results():
    run = runs.Run(
        id="r1",
        label="Pre-release 3",
        opened="2026-08-30T09:00:00+00:00",
        tests=("t1", "t2"),
        results={"t1": runs.Result("failed", "still flickers")},
    )
    assert runs.read(project_with_runs(run)) == [run]


def test_a_test_with_no_result_entry_is_pending():
    run = runs.Run(id="r1", tests=("t1",))
    assert run.result("t1") == runs.Result("pending")
    assert "t1" not in runs.write([run])["runs"][0].get("results", {})


def test_starting_a_run_closes_whatever_was_open():
    first = runs.started([], ["t1"], label="One")
    assert open_id(first) == "r1"
    second = runs.started(first, ["t1", "t2"], label="Two")
    assert [run.id for run in second] == ["r1", "r2"]
    assert not second[0].is_open
    assert open_id(second) == "r2"


def test_a_run_freezes_the_tests_it_was_opened_over():
    opened = runs.started([], ["t1", "t2"])[0]
    assert opened.tests == ("t1", "t2")


def test_marking_pending_removes_the_entry_rather_than_writing_the_default():
    run = runs.marked(runs.Run(id="r1", tests=("t1",)), "t1", "failed", "broke")
    assert run.result("t1") == runs.Result("failed", "broke")
    assert runs.marked(run, "t1", "pending").results == {}


def test_marking_refuses_a_word_it_does_not_know():
    with pytest.raises(ValueError, match="unknown test result"):
        runs.marked(runs.Run(id="r1"), "t1", "flaky")


def test_a_written_out_pending_reads_back_as_absent():
    """A hand-edited file saying pending must not outrank an older real result."""
    project = Project(title="Widget")
    project.module_data["testing"] = {
        "runs": [{"id": "r1", "results": {"t1": {"status": "pending"}}}]
    }
    assert runs.read(project)[0].results == {}


def test_closing_an_already_closed_run_leaves_it_alone():
    run = runs.closed(runs.Run(id="r1"))
    assert runs.closed(run) is run


def test_the_latest_outcome_is_the_newest_run_that_recorded_one():
    """A test absent from yesterday's run keeps last week's answer, not a fresh pending."""
    old = runs.Run(id="r1", tests=("t1", "t2"), results={"t1": runs.Result("ok")})
    new = runs.Run(id="r2", tests=("t2",), results={"t2": runs.Result("failed")})
    assert outcome([old, new], "t1").run.id == "r1"
    assert outcome([old, new], "t1").result.status == "ok"
    assert outcome([old, new], "t2").run.id == "r2"
    assert runs.latest([old, new], "t3") is None
    assert {k: v.result.status for k, v in runs.latest_results([old, new]).items()} == {
        "t1": "ok",
        "t2": "failed",
    }


def test_a_tally_names_every_status_so_nobody_guesses_a_zero():
    assert runs.tally(["ok", "ok", "failed"]) == {
        "pending": 0,
        "ok": 2,
        "failed": 1,
        "skipped": 0,
    }
