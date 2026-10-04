"""What the agent runs on a step consumed, in words — and the step aspect that kept it before.

The tokens live in the project's ledger (``domain/ledger.py``), a record per run, filled by
the harvest (``harvest.py``); this file is how every surface *says* them — the Agent tab's
"tokens so far", a row in the Agents browser, ``dplanner usage show`` — in the one
vocabulary of :class:`~dplanner.domain.agents.Tokens`: fresh input, cache reads, output.
Totals are never stored: they are summed over the records on every read. The ledger is
read per project here too — what each step spent, and the rate of tokens per estimated day
the Expenditure tab compares against — with the store saying where each ledger lives.

**The retired aspect.** Until the ledger, a step kept its runs as rows on its own
``agent_usage`` module data — one file per step, rewritten by whoever recorded a run, so
two writers on one step collided and a deleted step took its history with it. The format
survives only as an absorption (FORMAT.md's *Retiring a module*): at every open, each row
still on a step becomes a ``legacy`` ledger record — named by its session, so an open that
runs twice writes one file — and the step's entry is removed.
"""

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from dplanner.core.module_data import ModuleDataFormat
from dplanner.core.repository import Repository
from dplanner.domain import ledger
from dplanner.domain.agents import Tokens, short_count, summed
from dplanner.domain.expenditure import ELSEWHERE, HERE, Rate, Spent, learned_rate, spent_by_step
from dplanner.domain.ledger import LedgerRecord
from dplanner.domain.model import Library, Step
from dplanner.domain.store import LibraryStore
from dplanner.planning.estimate import read as days_for

MODULE_ID = "agent_usage"


def absorb_rows(repo: Repository[Any], library: Library) -> list[str]:
    """Every step's retired usage rows into its project's ledger; the steps changed."""
    if not isinstance(repo, LibraryStore):
        return []  # Only a store on disk has a project directory to write the ledger in.
    changed: list[str] = []
    for project in library.projects:
        for step in project.steps:
            entry = step.module_data.get(MODULE_ID)
            if entry is None:
                continue
            rows = entry.get("runs") if isinstance(entry, dict) else None
            kept = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
            for record in ledger.legacy(project.id, step.id, kept):
                ledger.write(repo.project_dir(project.id), record)
            repo.set_module_data(step.id, MODULE_ID, {})
            changed.append(step.id)
    return changed


DATA_FORMAT = ModuleDataFormat(MODULE_ID, absorb=absorb_rows)


def spent(records: Iterable[LedgerRecord]) -> Tokens | None:
    """What a set of runs consumed, or None when there are none — "nothing recorded" is not
    "consumed nothing"."""
    found = list(records)
    return summed(record.tokens for record in found) if found else None


def words(tokens: Tokens) -> str:
    """``12.3k in · 410k cached · 1.2k out`` — how a row or a chip says it."""
    fresh, cached, out = (short_count(n) for n in (tokens.input, tokens.cached, tokens.output))
    return f"{fresh} in · {cached} cached · {out} out"


def record_words(record: LedgerRecord) -> str:
    """One run as a line: the day, the agent CLI, what it spent, its models, and — last,
    because it matters least — what it was handed."""
    line = f"{record.launched[:10]}  {record.harness or '?':9} {words(record.tokens)}"
    models = sorted(model for model in record.models() if model != ledger.UNKNOWN_MODEL)
    if models:
        line += f" · {', '.join(models)}"
    if len(record.agents) > 1:
        line += f" · {len(record.agents) - 1} subagent{'s' if len(record.agents) > 2 else ''}"
    if record.prompt_chars:
        line += f" · {brief_words(record.prompt_chars)}"
    return line


def brief_words(chars: int) -> str:
    """``briefed 18.4k chars`` — how every surface says what a run was handed, and "" when
    nobody measured. *Briefed* rather than a bare number because the count beside it is
    tokens: two quantities in one line must not be readable as the same one."""
    return f"briefed {short_count(chars)} chars" if chars else ""


def summary(records: Iterable[LedgerRecord]) -> str:
    """One short phrase for a step, or "" when no run has been recorded."""
    total = spent(records)
    return "" if total is None else f"tokens: {words(total)}"


def ledger_dir(store: LibraryStore, project_id: str) -> Path | None:
    """Where a project keeps its ledger: its directory, or None for one the store does
    not hold."""
    try:
        return store.project_dir(project_id)
    except KeyError:
        return None


def ledger_stamp(store: LibraryStore, project_id: str) -> object:
    """What changes when a run is written into the project's ledger, None for no ledger."""
    directory = ledger_dir(store, project_id)
    return None if directory is None else ledger.fingerprint(directory)


def step_spent(store: LibraryStore, project_id: str) -> dict[str, Spent]:
    """What each step's agent runs consumed, per model, from the project's usage ledger."""
    directory = ledger_dir(store, project_id)
    if directory is None:
        return {}
    return spent_by_step((record.step, record.models()) for record in ledger.records(directory))


def token_rate(
    store: LibraryStore,
    library: Library,
    project_id: str,
    done_for: Callable[[Step], bool],
) -> Rate | None:
    """Tokens of work per estimated day: learned from the library's *other* projects when
    they have finished history, since a rate learned from the steps it is compared with
    would make the offset end at nought; from this project only when nothing else has."""

    def over(project_ids: list[str], source: str) -> Rate | None:
        by_step: dict[str, Spent] = {}
        for other in project_ids:
            by_step.update(step_spent(store, other))
        steps = [step for other in project_ids for step in library.project(other).steps]
        return learned_rate(
            steps, lambda step: by_step.get(step.id, Spent()), days_for, done_for, source
        )

    others = [project.id for project in library.projects if project.id != project_id]
    return over(others, ELSEWHERE) or over([project_id], HERE)


def step_usage_words(store: LibraryStore, library: Library, step_id: str) -> str:
    """What the agent runs on a step consumed, as the Agent tab says it; "" for none."""
    if not library.has(step_id):
        return ""
    directory = ledger_dir(store, library.project_of(step_id).id)
    if directory is None:
        return ""
    return summary(record for record in ledger.records(directory) if record.step == step_id)
