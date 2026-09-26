"""How good the model's forecasts are over a played timeline, as numbers.

Every working day from the day work began to the day a milestone really landed, the plan as
it stood that evening is dated by the model, and its forecast is set against the truth.
Three numbers per series, all in working days:

- **error**: the mean distance between the forecast and the real landing;
- **movement**: how far the forecast travelled in total, day to day;
- **moves**: on how many days it moved at all.

A forecast that is right and still scores zero on all three. *By the book* must, every day
(``tests/modules/test_time_simulation.py``); ``scripts/time_accuracy.py`` prints the rest.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from dplanner.domain.schedule import SATURDAY
from dplanner.modules.time_estimates.progress import landing_shift
from dplanner.modules.time_estimates.simulation.replay import Replay
from dplanner.modules.time_estimates.simulation.timeline import Timeline


@dataclass(frozen=True)
class Accuracy:
    error: float = 0.0
    movement: int = 0
    moves: int = 0
    samples: int = 0


def accuracy_of(line: Sequence[tuple[date, date]], truth: date) -> Accuracy:
    """A series' forecasts — ``(day, landing)`` — against its real landing."""
    error = 0
    movement = moves = 0
    for index, (_day, landing) in enumerate(line):
        error += abs(landing_shift(truth, landing))
        if index:
            moved = abs(landing_shift(line[index - 1][1], landing))
            movement += moved
            moves += 1 if moved else 0
    return Accuracy(error / len(line) if line else 0.0, movement, moves, len(line))


def combined(parts: Sequence[Accuracy]) -> Accuracy:
    """Several series summed, the error weighted by how many days each was forecast."""
    samples = sum(part.samples for part in parts)
    return Accuracy(
        sum(part.error * part.samples for part in parts) / samples if samples else 0.0,
        sum(part.movement for part in parts),
        sum(part.moves for part in parts),
        samples,
    )


@dataclass(frozen=True)
class TimelineAccuracy:
    whole: Accuracy  # The whole plan's landing.
    milestones: Accuracy  # Every milestone's, combined.


def timeline_accuracy(timeline: Timeline, replay: Replay) -> TimelineAccuracy:
    """``timeline`` written into ``replay`` and every day's forecast held to the truth."""
    last = timeline.days[-1].steps
    truths = {step.id: timeline.finished[step.id] for step in last if step.id in timeline.finished}
    milestones = [step.id for step in last if step.milestone and step.id in truths]
    # The whole lands when its last step does — known only once every step has.
    whole_truth = max(truths.values()) if len(truths) == len(last) else None
    until = max(truths.values(), default=None)
    lines: dict[str | None, list[tuple[date, date]]] = {key: [] for key in (None, *milestones)}
    for played, frame in zip(timeline.days, timeline.frames(), strict=True):
        replay.apply(frame)
        day = played.day
        if until is None or day < timeline.begin or day > until or day.weekday() >= SATURDAY:
            continue
        said = replay.forecast(day)
        if said is None:
            continue
        for key, line in lines.items():
            truth = whole_truth if key is None else truths[key]
            landing = said.landing(key)
            if truth is not None and day <= truth and landing is not None:
                line.append((day, landing))
    whole = accuracy_of(lines[None], whole_truth) if whole_truth is not None else Accuracy()
    parts = [accuracy_of(lines[key], truths[key]) for key in milestones]
    return TimelineAccuracy(whole, combined(parts))
