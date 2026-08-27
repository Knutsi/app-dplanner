"""The GitHub aspect: the branch and pull request a step's work lands in.

One branch ref and one PR ref, plus the PR's *last-seen* state and title. The refs are
plain recorded strings — setting them never needs GitHub — while the state is a cache of
an external fact, filled in when a ref is set with ``gh`` available and kept current by
``dplanner github refresh`` and the window's background refresher.
"""

from dataclasses import dataclass
from typing import Any

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.model import Step
from dplanner.modules.github.gh import PrInfo

MODULE_ID = "github"
DATA_FORMAT = ModuleDataFormat(MODULE_ID)

PR_STATES = ("open", "merged", "closed", "")  # "" = never checked, e.g. recorded gh-less.

SPEC = AspectSpec(
    id=MODULE_ID,
    label="GitHub",
    summary=(
        "The branch and pull request a step's work lands in; record the branch with "
        "`dplanner github set --branch` when you start a step, and the PR as soon as it "
        "exists."
    ),
    data_format=DATA_FORMAT,
)


@dataclass(frozen=True)
class GithubRefs:
    branch: str = ""
    pr_number: int | None = None
    pr_url: str = ""
    pr_state: str = ""  # One of PR_STATES; last seen, not live.
    pr_title: str = ""

    def is_empty(self) -> bool:
        return not (self.branch or self.pr_number is not None or self.pr_url)

    def has_pr(self) -> bool:
        return self.pr_number is not None or bool(self.pr_url)


def read(step: Step) -> GithubRefs | None:
    entry = step.module_data.get(MODULE_ID)
    if not entry:
        return None
    number = entry.get("pr_number")
    refs = GithubRefs(
        branch=str(entry.get("branch", "")),
        # bool is an int; True stored by a buggy writer must not read as PR #1.
        pr_number=int(number) if isinstance(number, int) and not isinstance(number, bool) else None,
        pr_url=str(entry.get("pr_url", "")),
        pr_state=str(entry.get("pr_state", "")),
        pr_title=str(entry.get("pr_title", "")),
    )
    return None if refs.is_empty() else refs


def write(refs: GithubRefs | None) -> dict[str, Any]:
    """The entry to store. Empty refs give ``{}``, which removes the file.

    The PR number stays an ``int``, unlike FORMAT.md's float rule for numbers: that rule
    targets quantities a module handles as floats, where reopening rewrites ``5`` as
    ``5.0``. A PR number is an identity nothing coerces, and a JSON int round-trips as an
    int — byte-stable by construction.
    """
    if refs is None or refs.is_empty():
        return {}
    entry: dict[str, Any] = {}
    if refs.branch:
        entry["branch"] = refs.branch
    if refs.pr_number is not None:
        entry["pr_number"] = int(refs.pr_number)
    for field in ("pr_url", "pr_state", "pr_title"):
        if getattr(refs, field):
            entry[field] = getattr(refs, field)
    return stamped(entry, DATA_FORMAT.version)


def refreshed(refs: GithubRefs, info: PrInfo) -> GithubRefs:
    """``refs`` with what GitHub just said about its PR — the one merge every surface uses.

    A recorded branch always wins over the PR's head ref: the user may have named the
    long-lived branch while the PR merges from a fork.
    """
    return GithubRefs(
        branch=refs.branch or info.head_ref,
        pr_number=info.number,
        pr_url=info.url,
        pr_state=info.state,
        pr_title=info.title,
    )


def summary(step: Step) -> str:
    """One short phrase for a step's row, or "" when there is nothing to say."""
    refs = read(step)
    if refs is None:
        return ""
    if refs.has_pr():
        name = f"PR #{refs.pr_number}" if refs.pr_number is not None else "PR"
        return f"{name} {refs.pr_state}".strip() if refs.pr_state != "open" else name
    return refs.branch
