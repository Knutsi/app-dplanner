"""A launch's intent, written before its shell is spawned — a launch is an external effect.

An unattended launch spawns a detached shell and then claims its step; the claim reaches the
plan file only at the next flush. A process that died between the spawn and that flush left
no trace, and the next window found the step due and launched it a second time. So the
launcher writes its intent first — which step, which run, who launched — and forgets it only
once the claim is on disk. An intent still here when the launcher next runs is a launch that
was interrupted, and it is **reconciled, never retried blind**: a shell that started (the
wrapper script wrote its shell file into the run directory) is a run, and its step is
claimed; one that never started is refused for a person to start again.

Like the launch lock it sits beside, this is this machine's fact — a temp directory, a shell
that may or may not exist here — so it lives under the config directory, never in the plan.
One file per intent, and only the holder of the library's launch lock writes them.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dplanner.core.fsio import write_atomic
from dplanner.domain.model import StepId
from dplanner.domain.workflow import Actor, AgentRun, Daemon, Person
from dplanner.modules.step_agent_instruction.launcher import SHELL_FILE

FORMAT = 1

_WORDS: dict[str, Actor] = {"person": Person(), "agent": AgentRun(), "daemon": Daemon()}


@dataclass(frozen=True)
class LaunchIntent:
    """A launch about to spawn: ``run`` is its name in the ledger, ``run_dir`` where the
    wrapper writes its shell file once the shell starts."""

    step: StepId
    run: str
    run_dir: Path
    actor: Actor
    recorded: str

    @property
    def started(self) -> bool:
        """Whether its shell started — the spawn happened, whatever became of the claim."""
        return (self.run_dir / SHELL_FILE).exists()

    def to_json(self) -> dict[str, Any]:
        actor = next(word for word, each in _WORDS.items() if each == self.actor)
        return {
            "format": FORMAT,
            "step": self.step,
            "run": self.run,
            "run_dir": str(self.run_dir),
            "actor": actor,
            "recorded": self.recorded,
        }

    @classmethod
    def from_json(cls, raw: Any) -> "LaunchIntent | None":
        """A stored intent, or None for one this build cannot read — never a crash over it."""
        if not isinstance(raw, dict):
            return None
        step, run, run_dir, recorded = (
            raw.get(key) for key in ("step", "run", "run_dir", "recorded")
        )
        actor = _WORDS.get(raw.get("actor", ""))
        if not (
            isinstance(step, str)
            and isinstance(run, str)
            and isinstance(run_dir, str)
            and isinstance(recorded, str)
            and step
            and run
            and run_dir
            and actor is not None
        ):
            return None
        return cls(step, run, Path(run_dir), actor, recorded)


class LaunchIntents:
    """One library's launch intents on this machine: a file per run under ``directory``."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def record(self, intent: LaunchIntent) -> None:
        """Write the intent durably; raises OSError when it cannot be written, and then
        nothing may be spawned."""
        self._directory.mkdir(parents=True, exist_ok=True)
        write_atomic(self._file(intent.run), json.dumps(intent.to_json(), indent=2) + "\n")

    def drop(self, run: str) -> None:
        self._file(run).unlink(missing_ok=True)

    def clear(self) -> None:
        """Forget every intent this build reads; one it cannot is left for whoever can."""
        for intent in self.pending():
            self.drop(intent.run)

    def pending(self) -> list[LaunchIntent]:
        """Every intent still recorded, oldest first; a file this build cannot read is
        skipped and left for whoever can."""
        found = []
        for path in self._paths():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if (intent := LaunchIntent.from_json(raw)) is not None:
                found.append(intent)
        return found

    def _paths(self) -> list[Path]:
        if not self._directory.is_dir():
            return []
        return sorted(self._directory.glob("*.json"))

    def _file(self, run: str) -> Path:
        return self._directory / f"{run}.json"
