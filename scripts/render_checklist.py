"""Render *Tools ▸ Setup Checklist…* in the dark and the light theme, to PNG.

    uv run python scripts/render_checklist.py --out docs/screenshots/f13-checklist

The rows are invented, not probed: a screenshot of the developer's own machine would show
whatever that machine happens to have, and the states worth seeing — a required row missing,
a recommendation failing, a remedy with a button — are rarely all true at once. Two images
per theme: the machine as found, and the sweep still running.
"""

import argparse
import os
import sys
import threading
from pathlib import Path

# A shell that presets the platform would put every render on the desktop.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_PLATFORMTHEME"] = ""

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QWidget

from dplanner.cli.checklist import MachineCheck, Reading, Remedy
from dplanner.framework.tasks import TaskService
from dplanner.modules.checklist.dialog import ChecklistDialog
from dplanner.theme import apply_theme
from dplanner.theme.themes import DARK, LIGHT, Theme

WAIT_S = 10.0  # A held probe never hangs the render: the gate opens, or this does.

INSTALL = Remedy(
    words="Install or update DPlanner on this machine.",
    command="dplanner install all",
    action="install.dplanner",
    verb="Install…",
)


def row(check_id, group, label, detail, *, ok=True, required=False, remedy=None):
    return MachineCheck(
        id=check_id,
        group=group,
        label=label,
        probe=lambda: Reading(ok=ok, detail=detail),
        remedy=remedy,
        required=required,
    )


def machine() -> list[MachineCheck]:
    """One machine's worth of rows: mostly well, one required piece out of date."""
    return [
        row(
            "install.command",
            "DPlanner",
            "dplanner command",
            "Resolves at ~/.local/bin/dplanner",
            required=True,
            remedy=INSTALL,
        ),
        row(
            "install.skill",
            "DPlanner",
            "Agent skill",
            "Installed from another build — updating rewrites it from this one",
            ok=False,
            required=True,
            remedy=INSTALL,
        ),
        row(
            "install.launcher",
            "DPlanner",
            "Desktop launcher",
            "DPlanner is not in this desktop's applications menu",
            ok=False,
            remedy=INSTALL,
        ),
        row("git.installed", "Git and GitHub", "git", "git version 2.51.0", required=True),
        row("github.gh", "Git and GitHub", "GitHub CLI (gh)", "/usr/bin/gh"),
        row(
            "github.auth",
            "Git and GitHub",
            "gh signed in",
            "gh is not authenticated — run `gh auth login`",
            ok=False,
            remedy=Remedy(
                words="Sign in so DPlanner can list branches and pull requests.",
                command="gh auth login",
            ),
        ),
        row("agents.cli", "Agents", "An agent CLI", "Claude Code, Codex on PATH"),
        row("agents.terminal", "Agents", "A terminal to launch in", "Ghostty, foot"),
        row("agents.multiplexer", "Agents", "A multiplexer", "herdr"),
        row(
            "network.internet", "Services", "Internet reachable", "https://api.github.com/ answered"
        ),
        row("secrets.keychain", "Services", "OS keychain", "usable"),
        row(
            "llm.key",
            "Services",
            "An AI provider key",
            "no key stored for OpenAI, Anthropic",
            ok=False,
            remedy=Remedy(words="Add one under Settings ▸ LLM."),
        ),
        row(
            "az.installed",
            "Other tools",
            "Azure CLI (az)",
            "not installed — only needed if your work deploys to Azure",
            ok=False,
            remedy=Remedy(
                words="DPlanner never calls az — this row is here for the work you "
                "plan, not for DPlanner.",
                command="az login",
            ),
        ),
    ]


def settle(app: QApplication) -> None:
    for _ in range(30):
        app.processEvents()


def save(widget: QWidget, out: Path, name: str, theme: Theme, app: QApplication) -> None:
    settle(app)
    path = out / f"{name}-{theme.name}.png"
    widget.grab().save(str(path), "PNG")
    print(path)


def discard(widget: QWidget) -> None:
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def render(app: QApplication, theme: Theme, out: Path) -> None:
    apply_theme(app, theme)
    tasks = TaskService()

    # No resize: the dialog's own size is what a person gets, and what the image should show.
    dialog = ChecklistDialog(machine(), tasks, lambda _action: None)
    dialog.show()
    save(dialog, out, "checklist", theme, app)
    discard(dialog)

    # The sweep still running: every row in the busy tone, the arc turning in Re-check. The
    # probes hold at a gate so the state can be photographed — a real one answers in a blink.
    gate = threading.Event()
    held = [
        MachineCheck(
            id=check.id,
            group=check.group,
            label=check.label,
            probe=lambda: (gate.wait(WAIT_S), Reading(ok=True))[1],
            remedy=check.remedy,
            required=check.required,
        )
        for check in machine()
    ]
    working = ChecklistDialog(held, tasks, lambda _action: None)
    working.show()
    save(working, out, "checklist-checking", theme, app)
    gate.set()
    settle(app)
    discard(working)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out", type=Path, default=Path("docs/screenshots/f13-checklist"))
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    assert isinstance(app, QApplication)
    for theme in (DARK, LIGHT):
        render(app, theme, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
