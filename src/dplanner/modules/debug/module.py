"""Debug module: developer-facing diagnostics — the LLM Calls tab and the Telemetry tab —
the design system's living reference, Debug ▸ Design Example, and Debug ▸ Windows Check."""

import subprocess
import sys
from dataclasses import dataclass

from PySide6.QtWidgets import QWidget

from dplanner.core.telemetry import Telemetry
from dplanner.framework.action_registry import ActionRegistry, ActionSpec, ActionState
from dplanner.framework.context import Context, ContextService
from dplanner.framework.debounce import DebounceService
from dplanner.framework.llm_service import LLMService
from dplanner.framework.tabs import TabHost
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.framework.theme_service import ThemeService
from dplanner.modules.debug.design_example import (
    DESIGN_TABLE_KIND,
    DESIGN_TOOLBARS_KIND,
    DesignExampleActivity,
    DesignExampleDialog,
    DesignExampleToolbars,
)
from dplanner.modules.debug.telemetry_view import TELEMETRY_KIND, TelemetryActivity
from dplanner.modules.debug.view import LLM_CALLS_KIND, LLMCallsActivity
from dplanner.modules.debug.windows_check import DESKTOP_COMMAND, command, probe


def launch_desktop(argv: tuple[str, ...]) -> None:
    """Start Omarchy's RDP launcher, detached — one seam, so a test can watch instead.

    Detached because the session is the developer's, not the application's: closing DPlanner
    must not take the RDP window down with it.
    """
    subprocess.Popen(
        list(argv), start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


@dataclass(frozen=True)
class DebugDeps:
    llm: LLMService
    telemetry: Telemetry
    actions: ActionRegistry
    tabs: TabHost
    context: ContextService
    parent: QWidget  # The example modal's.
    debounce: DebounceService  # The examples' demo debouncers settle with the window's.
    theme: ThemeService  # The example table re-inks its glyphs on a theme change.
    tasks: TaskService  # The Windows check is minutes of blocking work, so it is a task.


class DebugModule:
    id = "debug"

    def __init__(self, deps: DebugDeps) -> None:
        self._deps = deps
        self._runner = TaskRunner(deps.tasks, parent=deps.parent)
        # Asked once, here: an action state runs on every context change and may not walk
        # PATH. CLAUDE.md's *A checklist is a registry of probes* has the same rule.
        self._windows = probe()

    def register(self) -> None:
        deps = self._deps

        def factory(_target: str | None) -> LLMCallsActivity:
            return LLMCallsActivity(deps.llm, deps.context)

        deps.tabs.register_factory(LLM_CALLS_KIND, factory)

        def run_open(_context: Context) -> None:
            deps.tabs.open(LLM_CALLS_KIND)

        deps.actions.register(
            ActionSpec(
                id="debug.llm_calls",
                label="&LLM Calls",
                menu="Debug",
                group="llm",
                order=10,
                tip="Show the last 100 LLM requests, responses and errors",
                run=run_open,
            )
        )

        def telemetry_factory(_target: str | None) -> TelemetryActivity:
            return TelemetryActivity(deps.telemetry, deps.context)

        deps.tabs.register_factory(TELEMETRY_KIND, telemetry_factory)

        def run_open_telemetry(_context: Context) -> None:
            deps.tabs.open(TELEMETRY_KIND)

        deps.actions.register(
            ActionSpec(
                id="debug.telemetry",
                label="&Telemetry",
                menu="Debug",
                group="telemetry",
                order=10,
                tip="Show what ran and how long it took: actions, commands, slow listeners, "
                "stalls and failures",
                run=run_open_telemetry,
            )
        )

        def run_design_example(_context: Context) -> None:
            dialog = DesignExampleDialog(deps.debounce, deps.parent)
            dialog.exec()
            dialog.deleteLater()

        deps.actions.register(
            ActionSpec(
                id="debug.design_example",
                label="Design &Example…",
                menu="Debug",
                group="design",
                order=10,
                tip="The design system on one modal — a form, a table and every signalling "
                "state, built from the shared primitives: the reference to copy from",
                run=run_design_example,
            )
        )

        def design_table_factory(_target: str | None) -> DesignExampleActivity:
            return DesignExampleActivity(deps.context, deps.debounce, deps.theme)

        deps.tabs.register_factory(DESIGN_TABLE_KIND, design_table_factory)

        def run_open_design_table(_context: Context) -> None:
            deps.tabs.open(DESIGN_TABLE_KIND)

        deps.actions.register(
            ActionSpec(
                id="debug.design_table",
                label="Design Example &Table",
                menu="Debug",
                group="design",
                order=20,
                tip="The design system's table on a tab: a control strip, the Updating "
                "indicator at its right, an empty state that trades places with the rows",
                run=run_open_design_table,
            )
        )

        # -- the Windows check -------------------------------------------------------------
        # Minutes of blocking work driving a VM, so a task rather than the GUI thread. The
        # harness writes a log per step under ~/.local/share/dplanner-windows/logs/, which is
        # where the output is read; what this reports is whether it passed.
        def run_windows_check(_context: Context) -> None:
            argv = command(self._windows, sys.executable)

            def body() -> None:
                done = subprocess.run(argv, capture_output=True, text=True, check=False)
                if done.returncode != 0:
                    tail = (done.stdout or done.stderr).strip().splitlines()[-12:]
                    raise RuntimeError("Windows check failed:\n" + "\n".join(tail))

            self._runner.run("Windows check", body, cancellable=False)

        def windows_state(_context: Context) -> ActionState:
            # Disabled with the reason, never hidden: the entry is what says the capability
            # exists at all, and its label is where a machine learns what it is missing.
            refusal = self._windows.run_refusal
            if refusal:
                return ActionState(enabled=False, label=f"&Windows Check — {refusal}")
            return ActionState(enabled=not self._runner.is_busy())

        deps.actions.register(
            ActionSpec(
                id="debug.windows_check",
                label="&Windows Check",
                menu="Debug",
                group="windows",
                order=10,
                tip="Run the suite, the lint, the types and the frozen build on Windows, in "
                "Omarchy's VM — logs land under ~/.local/share/dplanner-windows/logs/",
                run=run_windows_check,
                state=windows_state,
            )
        )

        # Watching is its own verb, and a cheaper one: it needs only the VM, not the harness
        # — a build with no scripts/ can still open a session to one that is running, and
        # refusing that would be refusing something that works. Omarchy's launcher does the
        # RDP, with --keep-alive so the developer's VM outlives the window.
        def run_watch_windows(_context: Context) -> None:
            launch_desktop(DESKTOP_COMMAND)

        def watch_state(_context: Context) -> ActionState:
            refusal = self._windows.watch_refusal
            if refusal:
                return ActionState(enabled=False, label=f"Windows &Desktop — {refusal}")
            return ActionState()

        deps.actions.register(
            ActionSpec(
                id="debug.windows_desktop",
                label="Windows &Desktop",
                menu="Debug",
                group="windows",
                order=20,
                tip="Open an RDP session to Omarchy's Windows VM (omarchy-windows-vm launch "
                "--keep-alive: the VM stays up when the window closes)",
                run=run_watch_windows,
                state=watch_state,
            )
        )

        def design_toolbars_factory(_target: str | None) -> DesignExampleToolbars:
            return DesignExampleToolbars(deps.context, deps.theme)

        deps.tabs.register_factory(DESIGN_TOOLBARS_KIND, design_toolbars_factory)

        def run_open_design_toolbars(_context: Context) -> None:
            deps.tabs.open(DESIGN_TOOLBARS_KIND)

        deps.actions.register(
            ActionSpec(
                id="debug.design_toolbars",
                label="Design Example Tool&bars",
                menu="Debug",
                group="design",
                order=30,
                tip="Every shape a strip of verbs comes in: the flat strip, a tool "
                "palette's named bands, the same palette folding for want of room, and "
                "the dense strip that answers a question rather than offering verbs",
                run=run_open_design_toolbars,
            )
        )
