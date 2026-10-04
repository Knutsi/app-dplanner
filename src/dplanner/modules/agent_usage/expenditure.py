"""What each step's agents consumed, in the order the work can be done — the Expenditure
tab's columns, cells and words (the activity is ``module.py``'s ``ExpenditureActivity``).

The Order tab with other columns: the same rows (``framework/step_table.py``), the same
switches, the same gestures, and after the title what the ledger says each step's runs
consumed — fresh input, cache reads, output — the running total down the order, what was
expected of each step and the running offset between the two (``domain/expenditure.py``).
**Tokens, never money**: a token's price depends on the plan, the tier and the mode, and on
a subscription nothing is spent at all.

**Expected is learned**, from the tokens of work (fresh input and output) finished steps
consumed per estimated day — the library's other projects first, this one when nothing else
has history, which the volume line's tooltip says. With no history the expected columns are
empty rather than invented. The offset reads down the order: a finished row says how far the
work so far is over or under what its estimates predicted, in the tone a status takes —
under or on is ``ok``, up to a quarter over ``warn``, beyond that ``error``.

**By model** adds an in/out pair per model the project used, most work first — a playbook
runs one step on several. The CSV export is long, a row per step and model, so a new model
adds rows a spreadsheet pivots on, never columns.
"""

from collections.abc import Callable, Sequence

from dplanner.domain.agents import short_count
from dplanner.domain.expenditure import ELSEWHERE, Rate, Row, totals
from dplanner.domain.model import StepId
from dplanner.framework.signalling import Tone, tone_colour
from dplanner.framework.table import Cell, Column

EXPENDITURE_KIND = "expenditure"
# How far over its estimates the work so far may run before the offset says so loudly.
WARN_OVER = 0.25

TOTALS = (
    Column("Runs", numeric=True),
    Column("Models"),
    Column("In", numeric=True),
    Column("Cached", numeric=True),
    Column("Out", numeric=True),
)
RUNNING = (
    Column("Running", numeric=True),
    Column("Expected", numeric=True),
    Column("Running expected", numeric=True),
    # The last column takes the slack.
    Column("Offset"),
)


def columns(models: Sequence[str] = ()) -> tuple[Column, ...]:
    """The columns after the title, all in tokens: the totals, an in/out pair per model
    when asked for, and the running sums."""
    pairs = tuple(
        Column(f"{model} {side}", numeric=True) for model in models for side in ("in", "out")
    )
    return (*TOTALS, *pairs, *RUNNING)


def offset_tone(offset: float) -> Tone:
    """The tone of the number as it is shown: +0% is on budget, whatever the decimals."""
    if round(offset * 100) <= 0:
        return "ok"
    return "warn" if offset <= WARN_OVER else "error"


def offset_words(offset: float | None) -> str:
    return "" if offset is None else f"{round(offset * 100):+d}%"


def row_cells(row: Row, fixed: bool, models: Sequence[str] = ()) -> list[Cell]:
    """A row's cells after the title, in ``columns(models)``'s order. A count of nothing is
    an empty cell, not a zero: most steps have no runs, and a column of zeros reads louder
    than the few that do."""
    spent = row.spent
    tokens = spent.tokens

    def count(value: float | None) -> Cell:
        return Cell(short_count(value) if value else "", emphasis=fixed)

    cells = [
        count(spent.runs),
        Cell(", ".join(sorted(spent.models)), secondary=True, emphasis=fixed),
        count(tokens.input),
        count(tokens.cached),
        count(tokens.output),
    ]
    for model in models:
        used = spent.models.get(model)
        cells += [count(used.input if used else 0), count(used.output if used else 0)]
    cells += [
        count(row.running),
        count(row.expected),
        count(row.running_expected),
        Cell(
            offset_words(row.offset),
            ink=None if row.offset is None else tone_colour(offset_tone(row.offset)),
            emphasis=fixed,
        ),
    ]
    return cells


def volume_words(rows: Sequence[Row], finished: int, work: int) -> str:
    """The line under the caption: how far along, what it consumed, and how that compares."""
    total = totals(rows)
    said = (
        f"{finished} of {work} finished · {short_count(total.input)} in · "
        f"{short_count(total.cached)} cached · {short_count(total.output)} out"
    )
    last = next((row.offset for row in reversed(rows) if row.offset is not None), None)
    if last is not None:
        said += f" · {abs(round(last * 100))}% {'over' if last > 0 else 'under'} expected"
    return said


def rate_words(rate: Rate | None) -> str:
    """Where *expected* comes from, for the volume line's tooltip."""
    if rate is None:
        return (
            "Nothing is expected yet: a step's expected tokens are learned from finished"
            " steps that have an estimate and recorded agent runs."
        )
    where = "the library's other projects" if rate.source == ELSEWHERE else "this project"
    plural = "s" if rate.steps != 1 else ""
    return (
        f"Expected is the step's estimate times {short_count(rate.per_day)} tokens of work"
        f" (fresh input and output) per estimated day, learned from {rate.steps} finished"
        f" step{plural} in {where}."
    )


def export_rows(
    rows: Sequence[Row], key_of: Callable[[StepId], str], done_of: Callable[[StepId], bool]
) -> list[list[str]]:
    """One CSV row per step and model, so a new model adds rows, never columns."""
    out = [["#", "Key", "Step", "Finished", "Runs", "Model", "In", "Cached", "Out"]]
    for row in rows:
        step = row.place.step
        for model, counts in sorted(row.spent.models.items()):
            out.append(
                [
                    str(row.place.index),
                    key_of(step.id),
                    step.title,
                    "yes" if done_of(step.id) else "",
                    str(row.spent.runs),
                    model,
                    str(counts.input),
                    str(counts.cached),
                    str(counts.output),
                ]
            )
    return out
