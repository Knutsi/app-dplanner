"""Debug module: developer-facing diagnostics — the LLM Calls tab and the Telemetry tab —
and the design system's living reference, Debug ▸ Design Example."""

from dataclasses import dataclass

from PySide6.QtWidgets import QWidget

from dplanner.core.telemetry import Telemetry
from dplanner.framework.action_registry import ActionRegistry, ActionSpec
from dplanner.framework.context import Context, ContextService
from dplanner.framework.debounce import DebounceService
from dplanner.framework.llm_service import LLMService
from dplanner.framework.tabs import TabHost
from dplanner.framework.theme_service import ThemeService
from dplanner.modules.debug.design_example import (
    DESIGN_TABLE_KIND,
    DesignExampleActivity,
    DesignExampleDialog,
)
from dplanner.modules.debug.telemetry_view import TELEMETRY_KIND, TelemetryActivity
from dplanner.modules.debug.view import LLM_CALLS_KIND, LLMCallsActivity


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


class DebugModule:
    id = "debug"

    def __init__(self, deps: DebugDeps) -> None:
        self._deps = deps

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
