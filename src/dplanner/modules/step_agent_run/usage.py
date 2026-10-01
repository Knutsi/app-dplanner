"""What the agent runs on a step consumed, in words — and the step aspect that kept it before.

The tokens live in the project's ledger (``domain/ledger.py``), a record per run, filled by
the harvest (``harvest.py``); this file is how every surface *says* them — the Agent tab's
"tokens so far", a row in the Agents browser, ``dplanner usage show`` — in the one
vocabulary of :class:`~dplanner.domain.agents.Tokens`: fresh input, cache reads, output.
Totals are never stored: they are summed over the records on every read.

**The retired aspect.** Until the ledger, a step kept its runs as rows on its own
``agent_usage`` module data — one file per step, rewritten by whoever recorded a run, so
two writers on one step collided and a deleted step took its history with it. The format
survives only as an absorption (FORMAT.md's *Retiring a module*): at every open, each row
still on a step becomes a ``legacy`` ledger record — named by its session, so an open that
runs twice writes one file — and the step's entry is removed.
"""

from collections.abc import Iterable
from typing import Any

from dplanner.core.module_data import ModuleDataFormat
from dplanner.core.repository import Repository
from dplanner.domain import ledger
from dplanner.domain.agents import Tokens, summed
from dplanner.domain.ledger import LedgerRecord
from dplanner.domain.model import Library
from dplanner.domain.store import LibraryStore

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
    return f"{short(tokens.input)} in · {short(tokens.cached)} cached · {short(tokens.output)} out"


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
    return f"briefed {short(chars)} chars" if chars else ""


def short(count: int) -> str:
    """``12.3k``, ``4.1M`` — a token count at a glance."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}k"
    return str(count)


def summary(records: Iterable[LedgerRecord]) -> str:
    """One short phrase for a step, or "" when no run has been recorded."""
    total = spent(records)
    return "" if total is None else f"tokens: {words(total)}"
