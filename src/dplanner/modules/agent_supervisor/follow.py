"""``dplanner agent follow <run>``: a headless run, watched as it goes, read-only.

The supervisor tees each turn's JSON stream to ``turn-<n>.jsonl`` in the run's directory
(``ledger.run_dir``) and writes the turn's end into the record once the stream is drained.
Following is reading the two in that order — the record first, then the stream to its end — so
a turn the record says has ended has nothing left unsaid. Each event is said by its harness
(``Headless.say``): what the agent wrote, each tool it called with its arguments shortened, the
first line of what came back. A turn's end says how it ended, and a park the question it waits
on; the next turn is followed as soon as it starts, since an answer resumes the run. Once the
run is over it says how — and the verb waits for Enter, so the terminal stays to be read.

Nothing here takes a lock or writes: a follower is never a reason a run waits.
"""

import json
import time
from collections.abc import Callable
from pathlib import Path

from dplanner.domain import ledger, questions
from dplanner.domain.agents import AgentHarness, harness_by_id
from dplanner.domain.headless import TurnEnd
from dplanner.domain.ledger import LedgerRecord, Turn
from dplanner.modules.agent_supervisor import limits
from dplanner.modules.agent_supervisor.supervisor import RefusedError, dplanner_argv
from dplanner.modules.agent_supervisor.takeover import elsewhere

POLL_S = 0.5


def follow(
    project_dir: Path,
    run: str,
    harnesses: tuple[AgentHarness, ...],
    *,
    out: Callable[[str], None],
    sleep: Callable[[float], None] = time.sleep,
    config: Path | None = None,
) -> str:
    """Say the run's turns as they are streamed, until it is over; answer how it ended.
    ``RefusedError`` for a run that is not here to follow."""
    record = ledger.find(project_dir, run)
    if record is None:
        raise RefusedError(f"no run {run} in {project_dir}")
    if why := elsewhere(record, config):
        raise RefusedError(f"run {run} cannot be followed here: {why}, which has its streams")
    harness = harness_by_id(harnesses, record.harness)
    say = harness.headless.say if harness is not None and harness.headless else None
    out(heading(record, harness.label if harness is not None else record.harness))
    directory = ledger.run_dir(run, config)
    n, offset, partial = 1, 0, b""
    announced = ended = 0  # The last turn whose start, and whose end, was said.
    while True:
        record = ledger.find(project_dir, run) or record
        turn = next((each for each in record.turns if each.n == n), None)
        stream = directory / f"turn-{n}.jsonl"
        if announced < n and (turn is not None or stream.exists()):
            out(f"── turn {n} · {turn.prompt if turn is not None else 'starting'} ──")
            announced = n
        chunk = _read_from(stream, offset)
        if chunk:
            offset += len(chunk)
            *lines, partial = (partial + chunk).split(b"\n")
            for line in lines:
                for said in _said(say, line):
                    out(said)
            continue  # Read to the stream's end before believing the record's word on it.
        if turn is not None and turn.end:
            if ended < n:
                out(ended_words(project_dir, turn))
                ended = n
            if any(each.n == n + 1 for each in record.turns):
                n, offset, partial = n + 1, 0, b""
                continue
        if record.over:
            break
        sleep(POLL_S)
    words = over_words(record)
    out(words)
    return words


def follow_argv(library: Path | None, project: str, project_dir: Path, run: str) -> list[str]:
    """``dplanner agent follow <run>`` as a terminal runs it: this build, this library."""
    words = ("agent", "follow", run, "--project-dir", str(project_dir))
    return dplanner_argv(library, project, *words)


def heading(record: LedgerRecord, agent: str) -> str:
    """Who the run is: its step, its stage, its member and its agent."""
    parts = [f"Run {record.run} on step {record.step}"]
    if record.stage:
        parts.append(f"{record.stage} attempt {record.attempt or 1}")
    if record.callsign:
        parts.append(record.callsign)
    parts.append(agent or "an unknown agent")
    return " · ".join(parts)


def ended_words(project_dir: Path, turn: Turn) -> str:
    """How a turn ended, with what a person needs: the failure, the reset, the question."""
    words = f"── turn {turn.n} ended {turn.end}"
    if turn.why:
        words += f" ({turn.why})"
    if turn.reason:
        words += f": {turn.reason}"
    reset = limits.parse(turn.resets) if turn.end == TurnEnd.LIMIT else None
    if reset is not None:
        words += f" — the account comes back at {limits.clock(reset)}"
    asked = questions.find(project_dir, turn.question) if turn.question else None
    if asked is not None and asked.text:
        words += f"\n   {asked.short} asks: {asked.text}"
    return words


def over_words(record: LedgerRecord) -> str:
    """How the run ended, as its record says."""
    if record.fence:
        return f"The run is over: {record.fence.get('why') or 'it was fenced'}."
    last = record.last_turn
    return f"The run is over: its last turn ended {last.end if last is not None else 'unstarted'}."


def _read_from(stream: Path, offset: int) -> bytes:
    try:
        with stream.open("rb") as file:
            file.seek(offset)
            return file.read()
    except OSError:
        return b""


def _said(say: Callable[[dict[str, object]], list[str]] | None, line: bytes) -> list[str]:
    """One line of the stream in the harness's words; nothing for a line that is no event."""
    try:
        event = json.loads(line)
    except ValueError:
        return []
    if not isinstance(event, dict) or say is None:
        return []
    return [said for said in say(event) if said.strip()]
