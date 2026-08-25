"""The activity contract: one tab's worth of user-facing behaviour.

An activity is a controller (this object) owning a view (``widget``) bound to the model.
The framework only needs the small surface below; everything else — bindings, actions,
context updates — is the activity's own business.
"""

from typing import Protocol, runtime_checkable

from PySide6.QtWidgets import QWidget

from dplanner.framework.context import Uri


@runtime_checkable
class Activity(Protocol):
    # Read-only properties, so implementations may declare narrower types (a concrete
    # view class for ``widget``) and still satisfy the protocol.

    @property
    def uri(self) -> Uri:
        """Dedupe key: opening the same URI focuses the existing tab."""
        ...

    @property
    def title(self) -> str:
        """Tab label."""
        ...

    @property
    def widget(self) -> QWidget: ...

    def on_activated(self) -> None:
        """The tab became current: push activity/selection context."""
        ...

    def on_deactivated(self) -> None:
        """The tab is no longer current: seal undo coalescing, flush pending state."""
        ...

    def close(self) -> None:
        """The tab is being removed: disconnect model bindings."""
        ...


class ActivityBase:
    """Optional convenience base: sensible defaults for the hooks."""

    def on_activated(self) -> None:
        pass

    def on_deactivated(self) -> None:
        pass

    def close(self) -> None:
        pass
