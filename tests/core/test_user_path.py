"""Putting back the PATH a desktop launch does not inherit.

Every test drives the platform, the environment, the home directory and the subprocess
runner by argument, so none of them depends on the machine the suite runs on — and the
Windows and macOS branches are both exercised from Linux, which is the only way they are
ever exercised at all.
"""

import os
import subprocess
from pathlib import Path

from dplanner.core import user_path


def completed(stdout: str = "", returncode: int = 0) -> "subprocess.CompletedProcess[str]":
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def answering(said: str, *, returncode: int = 0) -> user_path.Runner:
    return lambda _command: completed(said, returncode)


def refusing(error: Exception) -> user_path.Runner:
    def run(_command: list[str]) -> "subprocess.CompletedProcess[str]":
        raise error

    return run


LAUNCHD = "/usr/bin:/bin:/usr/sbin:/sbin"

# Only the home-relative ones, so what a repair adds is entirely this test's doing: the
# absolute entries of KNOWN_PREFIXES exist on the machine running the suite.
UNDER_HOME = ("~/.local/bin", "~/.cargo/bin")


def test_the_login_shell_is_asked_with_a_login_but_not_interactive_shell() -> None:
    seen: list[list[str]] = []

    def run(command: list[str]) -> "subprocess.CompletedProcess[str]":
        seen.append(command)
        return completed("/opt/homebrew/bin")

    said = user_path.login_path(platform="darwin", environ={"SHELL": "/bin/zsh"}, run=run)
    assert said == "/opt/homebrew/bin"
    assert seen == [["/bin/zsh", "-lc", user_path.PATH_QUERY]]
    # -i would source the user's interactive rc: nvm, pyenv and a prompt framework, seconds
    # of startup for a question a login shell already answers.
    assert "-i" not in seen[0][1]


def test_windows_is_asked_nothing_at_all() -> None:
    assert (
        user_path.login_path(
            platform="win32",
            environ={"SHELL": "/bin/zsh"},
            run=refusing(AssertionError("no subprocess on Windows")),
        )
        == ""
    )


def test_a_shell_that_cannot_be_asked_is_not_an_error() -> None:
    for run in (
        refusing(OSError("no such file")),
        refusing(subprocess.TimeoutExpired(cmd="zsh", timeout=3.0)),
        answering("whatever", returncode=1),
    ):
        assert user_path.login_path(platform="darwin", environ={"SHELL": "/bin/zsh"}, run=run) == ""


def test_no_shell_in_the_environment_asks_nothing() -> None:
    assert (
        user_path.login_path(
            platform="darwin", environ={}, run=refusing(AssertionError("nothing to ask"))
        )
        == ""
    )


def test_the_repair_appends_what_the_shell_knows_and_keeps_what_was_there(tmp_path: Path) -> None:
    environ = {"SHELL": "/bin/zsh", "PATH": LAUNCHD}
    added = user_path.repair(
        platform="darwin",
        environ=environ,
        home=tmp_path,
        prefixes=UNDER_HOME,
        remember=False,
        run=answering(f"{LAUNCHD}{os.pathsep}/opt/homebrew/bin"),
    )
    assert added.added == ("/opt/homebrew/bin",)
    # Appended, never reordered: a path the process was given deliberately still wins.
    assert environ["PATH"] == f"{LAUNCHD}{os.pathsep}/opt/homebrew/bin"


def test_the_repair_is_idempotent(tmp_path: Path) -> None:
    environ = {"SHELL": "/bin/zsh", "PATH": LAUNCHD}
    run = answering(f"{LAUNCHD}{os.pathsep}/opt/homebrew/bin")
    first = user_path.repair(
        platform="darwin",
        environ=environ,
        home=tmp_path,
        prefixes=UNDER_HOME,
        remember=False,
        run=run,
    )
    after = environ["PATH"]
    second = user_path.repair(
        platform="darwin",
        environ=environ,
        home=tmp_path,
        prefixes=UNDER_HOME,
        remember=False,
        run=run,
    )
    assert first.added and second.added == ()
    assert environ["PATH"] == after


def test_known_prefixes_fill_in_when_the_shell_cannot_be_asked(tmp_path: Path) -> None:
    (tmp_path / ".local" / "bin").mkdir(parents=True)
    environ = {"PATH": LAUNCHD}  # No SHELL: nothing to ask.
    added = user_path.repair(
        platform="darwin",
        environ=environ,
        home=tmp_path,
        prefixes=UNDER_HOME,
        remember=False,
        run=answering(""),
    )
    assert added.added == (str(tmp_path / ".local" / "bin"),)


def test_a_prefix_that_does_not_exist_is_never_added(tmp_path: Path) -> None:
    environ = {"PATH": LAUNCHD}
    added = user_path.repair(
        platform="darwin",
        environ=environ,
        home=tmp_path,
        prefixes=UNDER_HOME,
        remember=False,
        run=answering(""),
    )
    assert added.added == ()
    assert environ["PATH"] == LAUNCHD


def test_windows_repairs_nothing(tmp_path: Path) -> None:
    environ = {"PATH": "C:\\Windows"}
    done = user_path.repair(
        platform="win32",
        environ=environ,
        home=tmp_path,
        prefixes=UNDER_HOME,
        remember=False,
        run=refusing(AssertionError("no subprocess on Windows")),
    )
    assert done.added == ()
    # Not a failure to report: Explorer hands a full PATH, so there was nothing to ask.
    assert user_path.reading(done) == (True, "already complete when the window opened")
    assert environ["PATH"] == "C:\\Windows"


def test_no_repair_at_all_is_the_cli_and_is_well() -> None:
    """A verb was typed into a shell, so the PATH is the user's by construction."""
    ok, detail = user_path.reading(None)
    assert ok
    assert "from a shell" in detail


def test_a_repair_that_found_nothing_says_so() -> None:
    ok, detail = user_path.reading(user_path.Repair((), asked_shell=True, shell_answered=True))
    assert ok
    assert detail == "already complete when the window opened"


def test_a_repair_names_what_it_recovered() -> None:
    ok, detail = user_path.reading(
        user_path.Repair(("/opt/homebrew/bin",), asked_shell=True, shell_answered=True)
    )
    assert ok
    assert "/opt/homebrew/bin" in detail


def test_a_shell_that_would_not_answer_is_the_row_that_fails() -> None:
    """The only failing state, and the one worth a row: a launcher started the window and
    the login shell could not be asked, so the PATH may be launchd's four directories."""
    ok, detail = user_path.reading(
        user_path.Repair(("/usr/local/bin",), asked_shell=True, shell_answered=False)
    )
    assert not ok
    assert "could not be asked" in detail


def test_the_row_never_reports_which_tools_are_installed() -> None:
    """Each tool has a row of its own; two lists of the same names can disagree."""
    for done in (
        None,
        user_path.Repair((), asked_shell=True, shell_answered=True),
        user_path.Repair(("/opt/homebrew/bin",), asked_shell=True, shell_answered=False),
    ):
        _, detail = user_path.reading(done)
        assert "gh" not in detail.split()
        assert "git" not in detail.split()


def test_a_repair_is_remembered_for_the_checklist_to_read(tmp_path: Path) -> None:
    done = user_path.repair(
        platform="darwin",
        environ={"SHELL": "/bin/zsh", "PATH": LAUNCHD},
        home=tmp_path,
        prefixes=UNDER_HOME,
        run=answering(f"{LAUNCHD}{os.pathsep}/opt/homebrew/bin"),
    )
    try:
        assert user_path.last() == done
    finally:  # Module state: leave it as it was for whatever runs next in this worker.
        user_path._last = None
