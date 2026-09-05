"""Which front door a command line opens.

`dplanner` is one binary because "which executable do I run" is a paragraph of instructions
that a single name makes unnecessary — but that only works if the dispatch is right. Two
incidents shaped it. Reading a `--library` path as the first command word made `dplanner
--library ~/plans.json project list` open a window instead of listing anything, on
somebody's actual screen. And while the window was the default, an agent running `dplanner`
bare to see the usage, or with a mistyped noun, opened a window on the developer's desktop
and hung its own shell until somebody closed it — so the window became a word, and
everything else is the CLI.
"""

import os
import subprocess
import sys
from io import StringIO

import pytest

from dplanner.cli.main import WINDOW_WORD, run
from dplanner.entry import VALUE_OPTIONS, command_words, opens_a_window, window_arguments
from dplanner.modules import default_module_formats


def test_both_value_options_are_skipped():
    assert VALUE_OPTIONS == ("--library", "--project")


@pytest.mark.parametrize(
    "argv",
    [
        ["window"],
        ["window", "--library", "/tmp/plans.json"],
        ["--library", "/tmp/plans.json", "window"],
        ["--library", "window", "window"],  # A library file named like the word.
        ["window", "-style", "Fusion"],
        ["window", "--library", "/tmp/plans.json", "-platform", "offscreen"],
    ],
)
def test_these_open_a_window(argv):
    assert opens_a_window(argv)


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--help"],
        ["-h"],
        ["--version"],
        ["project", "list"],
        ["--library", "/tmp/plans.json", "project", "list"],
        ["--json", "library", "list"],
        ["--library", "/tmp/plans.json", "--json", "step", "add", "p", "t"],
        ["--project", "widget", "step", "list"],
        ["skill", "show"],
        ["frobnicate"],
        ["projct", "list"],  # A typo is refused, never a window.
        ["--library", "window"],  # A path named like the word.
        ["--library", "/tmp/plans.json"],
        ["-style", "Fusion"],  # Qt's flags follow the word; on their own they are nothing.
        ["step", "add", "p", "window"],  # A step titled like the word.
    ],
)
def test_these_run_the_cli(argv):
    assert not opens_a_window(argv)


def test_an_option_value_is_never_a_command_word():
    assert command_words(["--library", "/tmp/step", "project", "list"]) == ["project", "list"]
    assert command_words(["--project", "step", "step", "list"]) == ["step", "list"]


def test_the_window_word_is_taken_out_before_qt_sees_the_rest():
    assert window_arguments(["window"]) == []
    assert window_arguments(["--library", "/tmp/p.json", "window", "-style", "Fusion"]) == [
        "--library",
        "/tmp/p.json",
        "-style",
        "Fusion",
    ]
    assert window_arguments(["--library", "window", "window"]) == ["--library", "window"]


def test_the_window_word_is_reserved(registry):
    """A noun spelled like it would be shadowed by the dispatch and never reachable."""
    assert WINDOW_WORD not in registry.groups()


def test_a_bare_run_prints_the_help_and_exits_2(registry):
    out, err = StringIO(), StringIO()
    assert run(registry, default_module_formats(), [], out, err) == 2
    assert out.getvalue() == ""
    assert "usage: dplanner" in err.getvalue()
    assert f"dplanner {WINDOW_WORD}" in err.getvalue()


def test_an_unknown_noun_is_a_usage_error(registry, capsys):
    with pytest.raises(SystemExit) as info:
        run(registry, default_module_formats(), ["frobnicate"], StringIO(), StringIO())
    assert info.value.code == 2
    assert "invalid choice: 'frobnicate'" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("argv", "said"),
    [([], "usage: dplanner"), (["frobnicate"], "invalid choice: 'frobnicate'")],
)
def test_the_entry_point_answers_a_bare_or_mistyped_call_without_qt(tmp_path, argv, said):
    """The incident, end to end: the console script's `main` with nothing, or with a word it
    does not know, runs the CLI, never imports PySide6, and so never opens anything."""
    probe = (
        "import sys\n"
        "from dplanner.entry import main\n"
        "try:\n"
        f"    code = main({argv!r})\n"
        "except SystemExit as error:\n"
        "    code = error.code\n"
        "assert code == 2, code\n"
        "assert 'PySide6' not in sys.modules, sorted(m for m in sys.modules if 'Side' in m)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=False,
        # `main` installs the file-backed journal under config_dir(): never the developer's.
        env={
            **os.environ,
            "XDG_CONFIG_HOME": str(tmp_path),
            "HOME": str(tmp_path),
            "APPDATA": str(tmp_path),
        },
    )
    assert result.returncode == 0, result.stderr
    assert said in result.stderr


# -- never from inside an agent's shell -------------------------------------------------------


def test_the_window_refuses_inside_an_agents_shell(monkeypatch, capsys):
    """The incident: an agent ran `dplanner show F3`, which opened a window — the agent's
    own background process — and every agent launched from that window was a child
    session of the first; one `pkill` later, four were gone. The word is explicit now,
    and even the word refuses where an agent's shell is around it."""
    from dplanner.entry import AGENT_SHELL_MARKERS, agent_shell_marker, main

    assert AGENT_SHELL_MARKERS == ("CLAUDECODE",)
    assert agent_shell_marker({"CLAUDECODE": "1"}) == "CLAUDECODE"
    assert agent_shell_marker({"CLAUDECODE": ""}) == ""  # Set to nothing is not set.
    assert agent_shell_marker({"PATH": "/usr/bin"}) == ""
    monkeypatch.setenv("CLAUDECODE", "1")
    assert main([WINDOW_WORD]) == 2
    err = capsys.readouterr().err
    assert "not from inside an agent's shell (CLAUDECODE is set)" in err
    assert "Open DPlanner from your own terminal" in err


@pytest.mark.parametrize(
    ("argv", "code", "said"),
    [
        ([WINDOW_WORD], 2, "CLAUDECODE is set"),
        (["--version"], 0, "dplanner "),  # Only the window: the CLI is how an agent drives it.
    ],
)
def test_inside_an_agents_shell_the_window_is_refused_and_the_cli_runs(tmp_path, argv, code, said):
    probe = (
        "import sys\n"
        "from dplanner.entry import main\n"
        "try:\n"
        f"    result = main({argv!r})\n"
        "except SystemExit as error:\n"
        "    result = error.code\n"
        f"assert result == {code}, result\n"
        "assert 'PySide6' not in sys.modules, sorted(m for m in sys.modules if 'Side' in m)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "CLAUDECODE": "1",
            "XDG_CONFIG_HOME": str(tmp_path),
            "HOME": str(tmp_path),
            "APPDATA": str(tmp_path),
        },
    )
    assert result.returncode == 0, result.stderr
    assert said in result.stderr + result.stdout
