"""Debug module: developer-facing diagnostics — the LLM Calls tab and the Telemetry tab."""

from dataclasses import dataclass

from dplanner.core.telemetry import Telemetry
from dplanner.framework.action_registry import ActionRegistry, ActionSpec
from dplanner.framework.context import Context, ContextService
from dplanner.framework.llm_service import LLMService
from dplanner.framework.tabs import TabHost
from dplanner.modules.debug.telemetry_view import TELEMETRY_KIND, TelemetryActivity
from dplanner.modules.debug.view import LLM_CALLS_KIND, LLMCallsActivity


@dataclass(frozen=True)
class DebugDeps:
    llm: LLMService
    telemetry: Telemetry
    actions: ActionRegistry
    tabs: TabHost
    context: ContextService


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
