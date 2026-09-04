"""The activity contract: one tab's worth of user-facing behaviour.

An activity is a controller (this object) owning a view (``widget``) bound to the model.
The framework only needs the small surface below; everything else — bindings, actions,
context updates — is the activity's own business.
"""

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from PySide6.QtWidgets import QWidget

from dplanner.domain.model import Library, NodeId, Project, ProjectId, TextEdit
from dplanner.framework.context import (
    SCOPE_ACTIVITY,
    SCOPE_SELECTION,
    ContextNode,
    ContextService,
    Uri,
    entity_uri,
)

if TYPE_CHECKING:
    # Runtime-imported, tabs.py would be a cycle: it imports the Activity protocol above.
    from dplanner.core.signals import Signal as CoreSignal
    from dplanner.framework.tabs import TabHost


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


class EntityActivity(ActivityBase):
    """An activity that is a view of one entity, speaking for the user only while current.

    Five modules had copied the same two obligations by hand: publish the activity scope
    with an entity edge on activation, and publish a selection **only while current** —
    the window can show panes side by side, and a background pane republishing its
    selection is what once made the detail panel flicker between two tabs' answers.

    A subclass supplies ``uri``/``title``/``widget`` as ever; extra activity edges come
    from overriding :meth:`activity_nodes`, and anything more to do on activation from
    overriding :meth:`on_activated` and calling ``super()``. Selections go through
    :meth:`publish_selection`, which owns the only-while-current rule.
    """

    def __init__(self, context: "ContextService", entity_kind: str, entity_id: str) -> None:
        self._context = context
        self._entity_kind = entity_kind
        self.entity_id = entity_id
        self._is_active = False

    @property
    def uri(self) -> Uri:
        raise NotImplementedError

    @property
    def title(self) -> str:
        raise NotImplementedError

    @property
    def widget(self) -> QWidget:
        raise NotImplementedError

    def activity_nodes(self) -> tuple["ContextNode", ...]:
        return (
            ContextNode(self.uri, (("entity", entity_uri(self._entity_kind, self.entity_id)),)),
        )

    def on_activated(self) -> None:
        self._is_active = True
        self._context.set_scope(SCOPE_ACTIVITY, self.activity_nodes())

    def on_deactivated(self) -> None:
        self._is_active = False

    def publish_selection(self, nodes: tuple["ContextNode", ...]) -> None:
        if not self._is_active:
            return  # A background pane does not speak for the user.
        self._context.set_scope(SCOPE_SELECTION, nodes)


def follow_entity_tabs(
    tabs: "TabHost",
    activity_type: type[EntityActivity],
    still_exists: Callable[[str], bool],
    *,
    closes_on: "CoreSignal[*tuple[Any, ...]]",
    retitles_on: "CoreSignal[*tuple[Any, ...]]",
) -> None:
    """Keep a module's entity tabs honest against the model, from one place.

    Connects two upkeep rules every entity-tab module was copying: when ``closes_on``
    fires (a structure change), a tab whose entity ``still_exists`` denies is closed;
    when ``retitles_on`` fires (a field change), the survivors' tab titles are re-read.
    The subscriptions live as long as the tab host — module registration is once per
    build, so there is nothing to unhook.
    """

    def activities() -> list[EntityActivity]:
        return [a for a in tabs.activities() if isinstance(a, activity_type)]

    def close_orphans(*_args: object) -> None:
        for activity in activities():
            if not still_exists(activity.entity_id):
                tabs.close_activity(activity)

    def retitle(*args: object) -> None:
        # A field signal names the node it changed; only that entity's tab can be retitled
        # by it. With no node named, every survivor is re-read.
        changed = args[0] if args else None
        for activity in activities():
            if changed is not None and changed != activity.entity_id:
                continue
            if still_exists(activity.entity_id):
                tabs.set_tab_title(activity, activity.title)

    closes_on.connect(close_orphans)
    retitles_on.connect(retitle)


type ModelSignal = CoreSignal[*tuple[Any, ...]]


def follow_project(
    library: Library,
    project_id: ProjectId,
    changed: Callable[[], None],
    *,
    signals: Sequence[ModelSignal] | None = None,
) -> Callable[[], None]:
    """Call ``changed`` for every model change inside one project, and for nothing else.

    A view of one project used to connect ``lambda *_: self._refresh()`` to every library
    signal — so a rename in another project rebuilt its table, and seven modules carried
    the copy. Each signal names a node: the parent of a structure change, the step of an
    edge or a text edit, the node of a field or module-data write. The filter is the
    model's own ``belongs_to`` over that node. ``signals`` narrows which changes count
    (a view that reads no prose leaves ``text_edited`` out); the default is all five.
    Returns one unsubscribe for the lot.
    """
    return _follow(
        library, lambda node_id: library.belongs_to(node_id, project_id), changed, signals
    )


def follow_target(
    library: Library,
    target_of: Callable[[], NodeId | None],
    changed: Callable[[], None],
    *,
    signals: Sequence[ModelSignal] | None = None,
) -> Callable[[], None]:
    """:func:`follow_project` for a surface whose subject moves — a panel section showing
    whichever step is selected. ``target_of`` is asked at each signal, and a change counts
    when it is inside the target's project (the target's own, when it is a project)."""

    def within(node_id: NodeId) -> bool:
        target = target_of()
        if target is None or not library.has(target):
            return False
        node = library.node(target)
        owner = node.id if isinstance(node, Project) else library.project_of(target).id
        return library.belongs_to(node_id, owner)

    return _follow(library, within, changed, signals)


def _follow(
    library: Library,
    within: Callable[[NodeId], bool],
    changed: Callable[[], None],
    signals: Sequence[ModelSignal] | None,
) -> Callable[[], None]:
    def on_change(first: object, *_rest: object) -> None:
        node_id = first.node_id if isinstance(first, TextEdit) else first
        if isinstance(node_id, str) and within(node_id):
            changed()

    chosen = (
        signals
        if signals is not None
        else (
            library.structure_changed,
            library.edges_changed,
            library.field_changed,
            library.module_data_changed,
            library.text_edited,
        )
    )
    unsubscribes = [signal.connect(on_change) for signal in chosen]

    def unfollow() -> None:
        for unsubscribe in unsubscribes:
            unsubscribe()

    return unfollow
