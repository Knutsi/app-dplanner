"""Where a step's run works: its name, its checkout, its worktree and its mainline.

The launcher prepares exactly what the briefing tells the agent — the worktree by this name,
under this checkout — so both read these functions rather than each composing the name.
Headless, like the rest of the package: a daemon names a run the way the window does.
"""

import re
from pathlib import Path

from dplanner.core.fsio import slugify

# Where a step's worktree lives, under the repository root: a sibling of the `.dplanner`
# index file, never inside it. Declared beside that file, since the plan repository scan
# has to know to skip it.
from dplanner.core.storage.pointer import WORKTREES_DIR
from dplanner.domain.locations import Placement
from dplanner.domain.model import Step
from dplanner.domain.repositories import RepositoryFacts
from dplanner.modules.step_ticket.aspect import read as ticket_read
from dplanner.planning.agent import uses_worktree, workplace
from dplanner.planning.kinds import key_of
from dplanner.planning.review import NO_WORKTREE_FOR_A_REVIEW, is_review

# A run name is a branch name's last component, so it keeps to what git's ref rules allow
# everywhere: letters, digits, `.`, `_` and `-`, none of them doubled up or at an end.
RUN_NAME_MAX = 60


def ref_safe(text: str) -> str:
    """``text`` as one component of a git ref: nothing a ref rule refuses, and nothing a
    shell would quote — the run name is written into three script dialects verbatim."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", text)
    safe = re.sub(r"[-.]{2,}", "-", safe).strip("-.")
    return safe[:RUN_NAME_MAX].rstrip("-.")


def run_name(step_key: str, ticket_key: str, title: str) -> str:
    """What a step's worktree and branch are called: ``<key>-<ticket>-<slug>``.

    The key first, so ``git branch`` and the worktrees directory sort by step; the ticket
    beside it when the step has one, so the branch answers the tracker too; the title's
    slug last, for the person reading the list. Every part is optional, and a step with
    none of them is still a run — ``step`` — rather than an empty name.
    """
    parts = [step_key.lower(), ref_safe(ticket_key), slugify(title, fallback="")]
    return ref_safe("-".join(part for part in parts if part)) or "step"


def workdir(facts: RepositoryFacts, step: Step | None = None) -> Path | None:
    """Where an agent on this project works — a step's, or one opened with nothing to do:
    the checkout of the code location the step names (its ``workplace``, else the
    project's primary code row) when the project records one, else where the facts read
    the code as being — the plan's own repository for the older shape of a plan kept
    beside its code, nowhere for a project whose code is not set. None when it is not
    here."""
    placement = code_placement(facts, step)
    if placement is not None:
        return placement.root if placement.here else None
    return facts.code_root


def code_placement(facts: RepositoryFacts, step: Step | None) -> Placement | None:
    """The code location a step works in, placed: the row its workplace names, else the
    primary. A named row that is gone falls back to the primary — lint says so."""
    named = facts.placement(workplace(step)) if step is not None else None
    return named if named is not None else facts.code


def worktree_path(workdir: Path, name: str) -> Path:
    return workdir / WORKTREES_DIR / name


def mainline(facts: RepositoryFacts | None, step: Step | None = None) -> str:
    """The branch a step's work lands on when no stretch holds it: the ref its code location
    names, "" for the repository's default branch."""
    placement = code_placement(facts, step) if facts is not None else None
    return placement.location.ref if placement is not None else ""


def run_name_of(step: Step) -> str:
    """What a step's agent run is called — its worktree, its branch, its terminal's title —
    from its key and its ticket, so the briefing names the worktree the script prepared."""
    ticket = ticket_read(step)
    return run_name(key_of(step), ticket.key if ticket is not None else "", step.title)


def no_worktree(step: Step) -> str:
    """Why a run of ``step`` gets no worktree whatever its agent aspect says, or "" — the
    review's rule: it reads the work it reviews where that work is, and commits none."""
    return NO_WORKTREE_FOR_A_REVIEW if is_review(step) else ""


def worktree(step: Step) -> bool:
    """Whether a run of ``step`` gets a fresh worktree: the step's own choice, unless what
    the step is rules one out. Every surface asks this rather than the aspect."""
    return uses_worktree(step) and not no_worktree(step)
