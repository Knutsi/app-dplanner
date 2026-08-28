"""Which front door a command line opens.

`dplanner` is one binary because "which executable do I run" is a paragraph of instructions
that a single name makes unnecessary — but that only works if the dispatch is right. Reading
a `--library` path as the first command word made `dplanner --library ~/plans.json project
list` open a window instead of listing anything, on somebody's actual screen.
"""

import pytest

from dplanner.entry import VALUE_OPTIONS, command_words, looks_like_a_verb


def test_both_value_options_are_skipped():
    assert VALUE_OPTIONS == ("--library", "--project")


@pytest.mark.parametrize(
    "argv",
    [
        ["project", "list"],
        ["--library", "/tmp/plans.json", "project", "list"],
        ["--json", "library", "list"],
        ["--library", "/tmp/plans.json", "--json", "step", "add", "p", "t"],
        ["--project", "widget", "step", "list"],
        ["skill", "show"],
        ["--help"],
    ],
)
def test_these_run_a_verb(argv):
    assert looks_like_a_verb(argv)


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--library", "/tmp/plans.json"],
        ["--library", "project"],  # A path named like a noun.
        ["--project", "step"],  # A project named like a noun.
        ["-style", "Fusion"],
        ["--library", "/tmp/plans.json", "-platform", "offscreen"],
    ],
)
def test_these_open_a_window(argv):
    assert not looks_like_a_verb(argv)


def test_an_option_value_is_never_a_command_word():
    assert command_words(["--library", "/tmp/step", "project", "list"]) == ["project", "list"]
    assert command_words(["--project", "step", "step", "list"]) == ["step", "list"]
