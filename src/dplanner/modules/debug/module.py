"""Debug module: developer-facing diagnostics, starting with the LLM Calls tab."""

from dataclasses import dataclass

from dplanner.framework.action_registry import ActionRegistry, ActionSpec
from dplanner.framework.context import Context, ContextService
from dplanner.framework.llm_service import LLMService
from dplanner.framework.tabs import TabHost
from dplanner.modules.debug.view import LLM_CALLS_KIND, LLMCallsActivity


@dataclass(frozen=True)
class DebugDeps:
    llm: LLMService
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
