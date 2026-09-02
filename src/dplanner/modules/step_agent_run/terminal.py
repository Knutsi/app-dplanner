"""Bringing a launched shell's terminal window back to the front, per platform.

There is no portable "raise the window running this shell", so this is a provider per
platform over the facts the wrapper script recorded (``runs.read_shell``): a tmux pane is
selected wherever it is; macOS asks Terminal or iTerm for the tab on the shell's tty
through AppleScript and activates any other terminal by its program name; Linux looks the
window up by the shell's ancestor pids and then by title with xdotool or wmctrl — whichever
the desktop has, and a Wayland session without either is honestly unsupported; Windows
activates by the PowerShell pid and then by title.

Every answer is a reason string — "" for success — so a verb can be greyed with it. Best
effort throughout: a terminal that renamed its window (an agent that set its own title)
still focuses by tty, pane or pid; one that cannot be found says so and nothing else
happens. ``run`` is the one subprocess seam, injected so a test needs no desktop.
"""

import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

Runner = Callable[[list[str]], tuple[int, str]]

UNSUPPORTED = "not supported on this platform"
NOT_FOUND = "the terminal window could not be found"


def run_quietly(argv: list[str]) -> tuple[int, str]:
    """The default runner: exit status and stdout, never an exception for a missing tool."""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return done.returncode, done.stdout


def support_reason(
    platform: str = sys.platform, which: Callable[[str], str | None] = shutil.which
) -> str:
    """Why this desktop cannot focus a terminal at all, or "" when it can try."""
    if platform == "darwin" or platform.startswith("win"):
        return ""
    if platform.startswith("linux"):
        if which("xdotool") or which("wmctrl"):
            return ""
        return "needs xdotool or wmctrl on this desktop"
    return UNSUPPORTED


def focus(
    facts: Mapping[str, str],
    platform: str = sys.platform,
    which: Callable[[str], str | None] = shutil.which,
    run: Runner = run_quietly,
    read_stat: Callable[[int], str | None] | None = None,
) -> str:
    """Raise the terminal the shell runs in. "" on success, else why not."""
    pane = facts.get("pane", "")
    if pane and which("tmux"):
        status, _ = run(["tmux", "select-window", "-t", pane])
        if status == 0:
            run(["tmux", "select-pane", "-t", pane])
            # The tmux client may sit in a terminal of its own; raise that too when we can.
            _raise_host(facts, platform, which, run, read_stat)
            return ""
    reason = support_reason(platform, which)
    if reason:
        return reason
    return _raise_host(facts, platform, which, run, read_stat)


def _raise_host(
    facts: Mapping[str, str],
    platform: str,
    which: Callable[[str], str | None],
    run: Runner,
    read_stat: Callable[[int], str | None] | None,
) -> str:
    if platform == "darwin":
        return _focus_mac(facts, run)
    if platform.startswith("linux"):
        return _focus_linux(facts, which, run, read_stat or _read_stat)
    if platform.startswith("win"):
        return _focus_windows(facts, run)
    return UNSUPPORTED


# -- macOS -------------------------------------------------------------------------------------

# Both scripts find the tab on the shell's tty and bring its window to the front; the
# terminal may have retitled the window, but the tty is the shell's for life.
_TERMINAL_SCRIPT = """
tell application "Terminal"
  repeat with w in windows
    repeat with t in tabs of w
      if tty of t is "{tty}" then
        set selected tab of w to t
        set index of w to 1
        activate
        return "ok"
      end if
    end repeat
  end repeat
end tell
return "none"
"""

_ITERM_SCRIPT = """
tell application "iTerm2"
  repeat with w in windows
    repeat with t in tabs of w
      repeat with s in sessions of t
        if tty of s is "{tty}" then
          select s
          select t
          select w
          activate
          return "ok"
        end if
      end repeat
    end repeat
  end repeat
end tell
return "none"
"""

_MAC_SCRIPTS = {"Apple_Terminal": _TERMINAL_SCRIPT, "iTerm.app": _ITERM_SCRIPT}


def _focus_mac(facts: Mapping[str, str], run: Runner) -> str:
    program = facts.get("program", "")
    tty = facts.get("tty", "")
    script = _MAC_SCRIPTS.get(program)
    if script is not None and tty:
        status, out = run(["osascript", "-e", script.format(tty=tty)])
        return "" if status == 0 and out.strip() == "ok" else NOT_FOUND
    if program and program != "tmux":
        # Ghostty and the rest have no scripting for a window: the application will do.
        status, _ = run(["open", "-a", program])
        return "" if status == 0 else NOT_FOUND
    return NOT_FOUND


# -- Linux -------------------------------------------------------------------------------------


def _read_stat(pid: int) -> str | None:
    try:
        return Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None


def ancestors(pid: int, read_stat: Callable[[int], str | None] = _read_stat) -> list[int]:
    """The process and its parents up to init, from ``/proc`` — the terminal that owns the
    shell's window is one of them for every terminal that owns its own windows."""
    chain: list[int] = []
    while pid > 1 and pid not in chain and len(chain) < 32:
        chain.append(pid)
        stat = read_stat(pid)
        if stat is None:
            break
        # The command name sits in parentheses and may hold spaces; the ppid follows it.
        try:
            pid = int(stat.rpartition(")")[2].split()[1])
        except (IndexError, ValueError):
            break
    return chain


def _focus_linux(
    facts: Mapping[str, str],
    which: Callable[[str], str | None],
    run: Runner,
    read_stat: Callable[[int], str | None],
) -> str:
    pid = facts.get("pid", "")
    title = facts.get("title", "")
    if which("xdotool"):
        if pid.isdigit():
            for ancestor in ancestors(int(pid), read_stat):
                status, out = run(["xdotool", "search", "--onlyvisible", "--pid", str(ancestor)])
                window = out.split()[0] if status == 0 and out.split() else ""
                if window:
                    run(["xdotool", "windowactivate", window])
                    return ""
        if title:
            status, out = run(["xdotool", "search", "--onlyvisible", "--name", title])
            if status == 0 and out.split():
                run(["xdotool", "windowactivate", out.split()[0]])
                return ""
    if which("wmctrl") and title:
        status, _ = run(["wmctrl", "-a", title])
        if status == 0:
            return ""
    return NOT_FOUND


# -- Windows -----------------------------------------------------------------------------------


def _focus_windows(facts: Mapping[str, str], run: Runner) -> str:
    # AppActivate takes a process id or a title; the pid is PowerShell's, which lives as
    # long as the agent does, and the title is what the script gave the window.
    targets = [facts.get("pid", ""), facts.get("title", "")]
    for target in targets:
        if not target:
            continue
        literal = target if target.isdigit() else f"'{target}'"
        status, out = run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(New-Object -ComObject WScript.Shell).AppActivate({literal})",
            ]
        )
        if status == 0 and out.strip().lower() == "true":
            return ""
    return NOT_FOUND
