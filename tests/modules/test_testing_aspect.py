"""The test aspect and the run records, with no application at all.

Both halves are plain functions over the model — the whole reason they live in Qt-free files
the CLI can reach without a graphics stack.
"""

import pytest

from dplanner.cli.command import CliError
from dplanner.domain.commands import SetEdgesCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.modules.step_check import aspect as check
from dplanner.modules.testing import runs
from dplanner.modules.testing.aspect import (
    AUDIENCE_IDS,
    DEFAULT_AUDIENCE,
    Test,
    audience_words,
    audiences_of,
    check_audience,
    covered,
    enabled,
    find,
    mint_ids,
    next_test_id,
    project_tests,
    read,
    remint_for_paste,
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
    give(step, Test("T100", "No flicker", "1. Open the list\n2. It must not flicker"))
    assert read(step) == [Test("T100", "No flicker", "1. Open the list\n2. It must not flicker")]
    assert enabled(step)


def test_an_empty_list_removes_the_file():
    assert write([]) == {}


def test_an_absent_body_and_flag_are_left_out_of_the_entry():
    """Absence encodes the default, so a plain test writes two keys and no more."""
    entry = write([Test("T100", "Just a title")])
    assert entry["tests"] == [{"id": "T100", "title": "Just a title"}]


def test_an_archived_test_still_reads_but_leaves_the_phrase():
    step = Step(title="A")
    give(step, Test("T100", "Live"), Test("T101", "Retired", archived=True))
    assert [test.id for test in read(step)] == ["T100", "T101"]
    assert summary(step) == "1 test"


def test_a_step_with_several_tests_says_how_many():
    step = Step(title="A")
    give(step, Test("T100", "One"), Test("T101", "Two"))
    assert summary(step) == "2 tests"


def test_unreadable_entries_read_as_absent_rather_than_raising():
    step = Step(title="A")
    step.module_data["testing"] = {"tests": [{"no": "id"}, "junk", {"id": "T100", "title": "Ok"}]}
    assert [test.id for test in read(step)] == ["T100"]
    step.module_data["testing"] = {"tests": "not a list"}
    assert read(step) == []


def test_replace_keeps_a_records_position():
    tests = [Test("T100", "One"), Test("T101", "Two"), Test("T102", "Three")]
    swapped = replace(tests, Test("T101", "Renamed"))
    assert [test.title for test in swapped] == ["One", "Renamed", "Three"]
    assert find(swapped, "T101") == Test("T101", "Renamed")


# -- ids are project-unique ---------------------------------------------------------


def test_ids_are_minted_across_the_whole_project_not_per_step():
    _library, project = build("A", "B")
    give(by_title(project, "A"), Test("T100", "One"), Test("T101", "Two"))
    assert next_test_id(project) == "T102"
    give(by_title(project, "B"), Test("T102", "Three"))
    assert next_test_id(project) == "T103"
    assert mint_ids(project, 3) == ["T103", "T104", "T105"]


def test_an_archived_test_still_holds_its_id():
    _library, project = build("A")
    give(by_title(project, "A"), Test("T100", "Gone", archived=True))
    assert next_test_id(project) == "T101"


def test_project_tests_walks_steps_then_tests_and_hides_the_archived():
    _library, project = build("A", "B")
    give(by_title(project, "A"), Test("T100", "One"), Test("T101", "Two", archived=True))
    give(by_title(project, "B"), Test("T102", "Three"))
    assert [test.id for _step, test in project_tests(project)] == ["T100", "T102"]
    assert [test.id for _step, test in project_tests(project, archived=True)] == [
        "T100",
        "T101",
        "T102",
    ]


# -- coverage: what a check, or a release, stands for --------------------------------


def test_a_check_covers_every_test_behind_it():
    library, project = build("Build", "Polish", "Pre-release check")
    give(by_title(project, "Build"), Test("T100", "One"))
    give(by_title(project, "Polish"), Test("T101", "Two"))
    link(library, project, "Polish", "Build")
    link(library, project, "Pre-release check", "Polish")
    scope = by_title(project, "Pre-release check")
    assert [test.id for _step, test in covered(library, project, scope.id)] == ["T100", "T101"]


def test_coverage_includes_the_scope_steps_own_tests():
    library, project = build("Build", "Check")
    give(by_title(project, "Build"), Test("T100", "One"))
    give(by_title(project, "Check"), Test("T101", "Two"))
    link(library, project, "Check", "Build")
    scope = by_title(project, "Check")
    assert [test.id for _step, test in covered(library, project, scope.id)] == ["T100", "T101"]


def test_coverage_reaches_nothing_that_is_not_behind_the_scope():
    library, project = build("Build", "Unrelated", "Check")
    give(by_title(project, "Build"), Test("T100", "One"))
    give(by_title(project, "Unrelated"), Test("T101", "Two"))
    link(library, project, "Check", "Build")
    scope = by_title(project, "Check")
    assert [test.id for _step, test in covered(library, project, scope.id)] == ["T100"]


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
        id="R100",
        label="Pre-release 3",
        opened="2026-08-30T09:00:00+00:00",
        tests=("T100", "T101"),
        results={"T100": runs.Result("failed", "still flickers")},
    )
    assert runs.read(project_with_runs(run)) == [run]


def test_a_test_with_no_result_entry_is_pending():
    run = runs.Run(id="R100", tests=("T100",))
    assert run.result("T100") == runs.Result("pending")
    assert "T100" not in runs.write([run])["runs"][0].get("results", {})


def test_starting_a_run_closes_whatever_was_open():
    first = runs.started([], ["T100"], label="One")
    assert open_id(first) == "R100"
    second = runs.started(first, ["T100", "T101"], label="Two")
    assert [run.id for run in second] == ["R100", "R101"]
    assert not second[0].is_open
    assert open_id(second) == "R101"


def test_a_run_freezes_the_tests_it_was_opened_over():
    opened = runs.started([], ["T100", "T101"])[0]
    assert opened.tests == ("T100", "T101")


def test_marking_pending_removes_the_entry_rather_than_writing_the_default():
    run = runs.marked(runs.Run(id="R100", tests=("T100",)), "T100", "failed", "broke")
    assert run.result("T100") == runs.Result("failed", "broke")
    assert runs.marked(run, "T100", "pending").results == {}


def test_marking_refuses_a_word_it_does_not_know():
    with pytest.raises(ValueError, match="unknown test result"):
        runs.marked(runs.Run(id="R100"), "T100", "flaky")


def test_a_written_out_pending_reads_back_as_absent():
    """A hand-edited file saying pending must not outrank an older real result."""
    project = Project(title="Widget")
    project.module_data["testing"] = {
        "runs": [{"id": "R100", "results": {"T100": {"status": "pending"}}}]
    }
    assert runs.read(project)[0].results == {}


def test_closing_an_already_closed_run_leaves_it_alone():
    run = runs.closed(runs.Run(id="R100"))
    assert runs.closed(run) is run


def test_the_latest_outcome_is_the_newest_run_that_recorded_one():
    """A test absent from yesterday's run keeps last week's answer, not a fresh pending."""
    old = runs.Run(id="R100", tests=("T100", "T101"), results={"T100": runs.Result("ok")})
    new = runs.Run(id="R101", tests=("T101",), results={"T101": runs.Result("failed")})
    assert outcome([old, new], "T100").run.id == "R100"
    assert outcome([old, new], "T100").result.status == "ok"
    assert outcome([old, new], "T101").run.id == "R101"
    assert runs.latest([old, new], "T102") is None
    assert {k: v.result.status for k, v in runs.latest_results([old, new]).items()} == {
        "T100": "ok",
        "T101": "failed",
    }


def test_a_tally_names_every_status_so_nobody_guesses_a_zero():
    assert runs.tally(["ok", "ok", "failed"]) == {
        "pending": 0,
        "ok": 2,
        "failed": 1,
        "skipped": 0,
    }


# -- who a test is for --------------------------------------------------------------


def test_an_audience_survives_a_write_and_a_read():
    _library, project = build("A")
    step = by_title(project, "A")
    give(step, Test("T100", "One", audiences=("qa", "technical")))
    assert read(step) == [Test("T100", "One", audiences=("qa", "technical"))]


def test_a_test_that_says_nothing_stores_nothing_and_reads_as_the_default():
    unclassified = Test("T100", "One")
    assert "audiences" not in write([unclassified])["tests"][0]
    assert unclassified.audiences == ()
    assert audiences_of(unclassified) == (DEFAULT_AUDIENCE,)
    # The two questions kept apart: what it counts as, and whether anybody has said.
    assert audiences_of(Test("T101", "Two", audiences=("other",))) == ("other",)


def test_the_stored_order_is_canonical_however_it_was_named():
    named = write([Test("T100", "One", audiences=("technical", "qa"))])
    reversed_ = write([Test("T100", "One", audiences=("qa", "technical"))])
    assert named == reversed_
    assert named["tests"][0]["audiences"] == ["qa", "technical"]


def test_an_audience_this_build_does_not_know_reads_as_absent():
    _library, project = build("A")
    step = by_title(project, "A")
    step.module_data["testing"] = {
        "tests": [{"id": "T100", "title": "One", "audiences": ["technical", "astrologer"]}]
    }
    assert read(step) == [Test("T100", "One", audiences=("technical",))]


def test_audience_words_names_the_labels_in_order():
    assert audience_words(Test("T100", "One", audiences=("technical", "qa"))) == "QA, Technical"
    assert audience_words(Test("T101", "Two")) == "Other"


def test_an_audience_off_the_list_is_refused_by_name():
    assert check_audience("qa") == "qa"
    with pytest.raises(CliError) as refused:
        check_audience("astrologer")
    assert "astrologer" in str(refused.value)
    for audience_id in AUDIENCE_IDS:
        assert audience_id in str(refused.value)


def test_a_pasted_test_keeps_its_audience_and_loses_only_its_id():
    _library, project = build("A")
    step = by_title(project, "A")
    give(step, Test("T100", "One", audiences=("qa",)))
    remint_for_paste(project, [step])
    pasted = read(step)[0]
    assert pasted.audiences == ("qa",)
    assert pasted.id != "T100"
