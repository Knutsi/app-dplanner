"""What a source of notices promises, and how the bell words them. Qt-free.

The notice itself is :class:`dplanner.domain.notice.Notice`. The contract below is
consumer-owned, like ``spec/source_kind.py``'s: a module satisfies it structurally and
never imports it, so the install module's skill source and this inbox stay strangers.
There is nothing to mark read and nothing that piles up; *mute* hides one until it has
cleared and come back. That is the derived-never-stored rule applied to attention, and it
is what lets the bell be honest — it counts what stands.
"""

from collections.abc import Sequence
from typing import Protocol

from dplanner.core.signals import Signal
from dplanner.domain.notice import Notice

# The bell's words when several stand; one notice shows its own title.
BELL_TITLE_MAX = 40


class NoticeSource(Protocol):
    """One module's answer to "what stands right now", switched on and off by the person.

    ``scan`` runs on the GUI thread and must be cheap — a few file reads, a lookup in what
    a poller already found. A source that has to reach a network or render something
    slow does that on its own worker between ``start`` and ``stop`` and says ``changed``
    when the answer moved; ``scan`` then only reads what the worker left.
    """

    id: str  # "install.skill" — the preference key, module-prefixed.
    label: str  # The switch's words on the tab: "Agent skill".
    changed: Signal[()]  # "Ask me again": a dialog closed, a check came back.

    def start(self) -> None:
        """The switch went on, or was on at launch."""
        ...

    def stop(self) -> None: ...

    def scan(self) -> Sequence[Notice]: ...


def mute_key(source_id: str, notice: Notice) -> str:
    return f"{source_id}:{notice.key}"


def bell_text(titles: Sequence[str]) -> str:
    """One notice reads its own title, elided; several read as a count; none reads empty."""
    if not titles:
        return ""
    if len(titles) == 1:
        title = titles[0]
        if len(title) > BELL_TITLE_MAX:
            return title[: BELL_TITLE_MAX - 1].rstrip() + "…"
        return title
    return f"{len(titles)} notices"
