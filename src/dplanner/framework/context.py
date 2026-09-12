"""What the user is doing, as a small graph of URIs.

Activities describe themselves and the user's selection here; actions read it back to decide
visibility, enablement and labels. Everything is addressed by URI string —
``app://entity/item/<id>``, ``app://selection/item/<id>`` — so the context never holds model
objects. That is the point: a graph of strings can be compared, logged, asserted on in a
test and handed to an action callback that has no way to reach the model at all, which is
what makes action state a pure function instead of a query against live widgets.

An *entity kind* is your word for a kind of thing (``item``, ``task``, ``segment``). The
framework never interprets it; it only routes it, so two features can address different
kinds of thing without a shared enum.

The graph is grouped into three replaceable scopes rather than one mutable soup, because
that matches how it changes: ``app`` is set once at startup, ``activity`` is replaced
wholesale on every tab switch, ``selection`` on every selection change. Replacing a scope
can never leave another scope's stale nodes behind.
"""

from collections.abc import Callable
from dataclasses import dataclass

from dplanner.core.signals import Signal

type Uri = str

SCOPE_APP = "app"
SCOPE_ACTIVITY = "activity"
SCOPE_SELECTION = "selection"

# One scheme for every application built from this template: the URIs are internal, never
# registered with the OS, and a per-app scheme would only make shared code harder to read.
SCHEME = "app://"

WORKSPACE_URI: Uri = f"{SCHEME}workspace"

_ENTITY_PREFIX = f"{SCHEME}entity/"
_SELECTION_PREFIX = f"{SCHEME}selection/"


def entity_uri(kind: str, entity_id: str) -> Uri:
    """Address one thing: ``app://entity/item/4f2a…``."""
    return f"{_ENTITY_PREFIX}{kind}/{entity_id}"


def selection_uri(kind: str, entity_id: str) -> Uri:
    """Address one *selected* thing. A separate prefix, so "what is open" and "what is
    picked" never have to be told apart by looking at which scope a node came from."""
    return f"{_SELECTION_PREFIX}{kind}/{entity_id}"


def entity_id_from_uri(uri: Uri, kind: str | None = None) -> str | None:
    """The id in an entity or selection URI, or None when it is neither (or the wrong kind)."""
    for prefix in (_ENTITY_PREFIX, _SELECTION_PREFIX):
        if uri.startswith(prefix):
            found_kind, _sep, entity_id = uri.removeprefix(prefix).partition("/")
            if not entity_id or (kind is not None and found_kind != kind):
                return None
            return entity_id
    return None


_ACTIVITY_PREFIX = f"{SCHEME}activity/"


def activity_uri(kind: str, target: str | None = None) -> Uri:
    base = f"{_ACTIVITY_PREFIX}{kind}"
    return f"{base}/{target}" if target else base


def parse_activity_uri(uri: Uri) -> tuple[str, str | None] | None:
    """Inverse of :func:`activity_uri`: (kind, target), or None for a non-activity URI."""
    if not uri.startswith(_ACTIVITY_PREFIX):
        return None
    rest = uri.removeprefix(_ACTIVITY_PREFIX)
    if not rest:
        return None
    kind, _sep, target = rest.partition("/")
    return kind, target or None


@dataclass(frozen=True)
class ContextNode:
    """One vertex: a URI plus labelled edges to other URIs (e.g. ``("entity", …)``)."""

    uri: Uri
    edges: tuple[tuple[str, Uri], ...] = ()


class Context:
    """An immutable snapshot of all scopes, handed to every action-state callback."""

    def __init__(self, scopes: dict[str, tuple[ContextNode, ...]]) -> None:
        self._scopes = scopes

    def nodes(self) -> tuple[ContextNode, ...]:
        return tuple(node for scope in self._scopes.values() for node in scope)

    def scope(self, name: str) -> tuple[ContextNode, ...]:
        return self._scopes.get(name, ())

    def uris_with_prefix(self, prefix: str) -> list[Uri]:
        return [node.uri for node in self.nodes() if node.uri.startswith(prefix)]

    def edge(self, label: str) -> Uri | None:
        """The first edge with ``label`` anywhere in the graph, or None."""
        for node in self.nodes():
            for edge_label, target in node.edges:
                if edge_label == label:
                    return target
        return None

    def selected_entities(self, kind: str | None = None) -> list[str]:
        """Every selected thing, in the order the selecting view listed them."""
        return [
            entity_id
            for uri in self.uris_with_prefix(_SELECTION_PREFIX)
            if (entity_id := entity_id_from_uri(uri, kind)) is not None
        ]

    def selected_entity(self, kind: str | None = None) -> str | None:
        """The one selected thing of this kind — None when nothing, or more than one, is.

        Distinct from :meth:`focus_entity`, which falls back to whatever the activity is about
        and answers *"what should this verb act on"*. This answers *"is there exactly one of
        these in front of the user"*, which is what a detail editor needs — and it is one
        definition rather than two, so a panel that shows a step and a panel that steps aside
        for it cannot disagree about what "a step is selected" means.
        """
        selected = self.selected_entities(kind)
        return selected[0] if len(selected) == 1 else None

    def focus_entity(self, kind: str | None = None) -> str | None:
        """The one thing an action should act on: the selection, else the activity's own.

        Nearly every action wants this rather than the raw graph. The fallback to the
        activity's ``entity`` edge is what makes a menu item work identically whether the
        user picked something in a list or simply has it open in a tab.
        """
        selected = self.selected_entities(kind)
        if selected:
            return selected[0]
        target = self.edge("entity")
        return entity_id_from_uri(target, kind) if target else None


class ContextService:
    """Holds the current context; announces a fresh snapshot when it changes.

    ``current()`` is always true the moment ``set_scope`` returns — a verb run right after a
    publish reads the selection it was handed. What the announcement reaches is every
    action's state, every toolbar, every panel and the menu bar, which is not cheap on a
    large plan, and a gesture may publish several times with an empty selection in
    between (a re-selection clears first). So :attr:`announce` is a seam: inline by
    default, and the builder routes it through a 0 ms ``Debounced`` so a burst of
    publishes fans out once, over the final state, after the gesture. The test suite runs
    the debounce service in immediate mode and sees every announcement inline.
    """

    def __init__(self) -> None:
        self._scopes: dict[str, tuple[ContextNode, ...]] = {}
        self.changed: Signal[Context] = Signal("context.changed")
        self.announce: Callable[[], None] = self.announce_now

    def current(self) -> Context:
        return Context(dict(self._scopes))

    def announce_now(self) -> None:
        """Emit the current snapshot to every listener — what ``announce`` defaults to."""
        self.changed.emit(self.current())

    def refresh(self) -> None:
        """Announce the current context unchanged, so action states re-evaluate — for
        modules whose action availability depends on state outside the context graph."""
        self.announce()

    def set_scope(self, scope: str, nodes: tuple[ContextNode, ...] | list[ContextNode]) -> None:
        self._scopes[scope] = tuple(nodes)
        self.announce()

    def clear_scope(self, scope: str) -> None:
        if self._scopes.pop(scope, None) is not None:
            self.announce()
