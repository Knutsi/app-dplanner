"""Which front door a command line opens.

`dplanner` is one binary because "which executable do I run" is a paragraph of instructions
that a single name makes unnecessary — but that only works if the dispatch is right. Reading
a `--workspace` path as the first command word made `dplanner --workspace ~/w project list`
open a window instead of listing anything, on somebody's actual screen.
"""

import pytest

from dplanner.entry import command_words, looks_like_a_verb


@pytest.mark.parametrize(
    "argv",
    [
        ["project", "list"],
        ["--workspace", "/tmp/widget", "project", "list"],
        ["--json", "product", "show"],
        ["--workspace", "/tmp/widget", "--json", "step", "add", "p", "t"],
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
        ["--workspace", "/tmp/widget"],
        ["--workspace", "/home/someone/product"],  # A directory named like a noun.
        ["-style", "Fusion"],
        ["--workspace", "/tmp/widget", "-platform", "offscreen"],
    ],
)
def test_these_open_a_window(argv):
    assert not looks_like_a_verb(argv)


def test_an_option_value_is_never_a_command_word():
    assert command_words(["--workspace", "/tmp/step", "project", "list"]) == ["project", "list"]
