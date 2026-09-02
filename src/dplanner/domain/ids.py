"""Short, readable ids minted per project: ``f1, f2, …``, ``a1, a2, …``.

An id a person can say out loud and an agent can guess the shape of. Shared by every
module that keeps a list of records beside a project — a feature, a spec figure — so the
minting rule is written once and every list numbers the same way. Test ids (``T100``)
are minted in ``modules/testing/aspect.py`` on their own rule: they start at 100 so an id
never collides with a step index, and that is a different rule, not a second copy.
"""

from collections.abc import Sequence


def next_id(existing: Sequence[str], prefix: str) -> str:
    """The next free ``<prefix>N`` — one past the highest number already taken, so a
    removed record's id is never handed out again while a higher one exists."""
    numbers = [
        int(entry[len(prefix) :])
        for entry in existing
        if entry.startswith(prefix) and entry[len(prefix) :].isdigit()
    ]
    return f"{prefix}{max(numbers, default=0) + 1}"
