"""Actions as a pop-up menu: the fourth presenter, beside the menu bar, palette and toolbar.

Right-clicking a thing should offer exactly what that thing's menu offers, never a
hand-maintained copy of it. One builder, reading the same registry through the same
context, is what keeps four presentations of the same verbs from drifting apart.
"""

from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import QMenu, QWidget

from dplanner.framework.action_registry import (
    ActionRegistry,
    ActionSpec,
    ActionState,
    DataMenuSpec,
)
from dplanner.framework.context import ContextService


def _ink(target: QMenu) -> QColor:
    """The colour a glyph is painted in: this menu's own text colour, read now.

    A pop-up is built fresh every time it opens, so the colour cannot go stale — which is
    why an action's glyph is a pop-up presenter's business and not the menu bar's, whose
    QActions outlive every theme change.
    """
    return QColor(target.palette().text().color())


def _decorate(entry: QAction, spec: ActionSpec, state: ActionState, target: QMenu) -> None:
    """The one presenter policy applied to a built entry: enablement, check, glyph."""
    entry.setEnabled(state.enabled)
    if state.checked is not None:
        entry.setCheckable(True)
        entry.setChecked(state.checked)
    if spec.icon is not None:
        entry.setIcon(spec.icon(_ink(target)))


def append_action(
    target: QMenu,
    actions: ActionRegistry,
    context_service: ContextService,
    action_id: str,
) -> QAction | None:
    """One registered action as a menu entry, under the one presenter policy.

    Greyed when disabled, omitted only when hidden, the state's label over the spec's,
    checkable when the state says so, and the context re-read at trigger time. The policy
    lives here so a widget that assembles its popup by hand (a toolbar button mixing data
    rows with verbs) renders an entry, never a copy of one.
    """
    spec = actions.spec(action_id)
    state = spec.state(context_service.current())
    if not state.visible:
        return None
    entry = target.addAction(state.label if state.label is not None else spec.label)
    _decorate(entry, spec, state, target)
    entry.triggered.connect(
        lambda _checked=False, sid=spec.id: actions.run(sid, context_service.current())
    )
    return entry


def _fill_data(spec: DataMenuSpec, child: QMenu) -> None:
    """A data child menu's entries, read now — the same clear-and-refill the bar does."""
    child.clear()
    spec.fill(child)


def fill_menu(
    target: QMenu,
    actions: ActionRegistry,
    context_service: ContextService,
    menu: str,
    submenu: str | None = None,
) -> QMenu:
    """One menu's visible actions into an existing pop-up; a disabled one is greyed, not
    omitted.

    Same policy as the menu bar — hidden means the capability is absent, disabled means "not
    right now", and the greyed entry's label carries the reason (`steps.link`'s refusals are
    the worked example). Only the palette filters on runnable. The context is snapshotted for
    the labels ("Delete 3 Items") but re-read when an entry is triggered, so a menu left open
    across a selection change still acts on what the user has *now* rather than on what they
    had when it opened.

    ``submenu=None`` (the norm) renders the whole menu, nesting child menus exactly as the
    menu bar does: **one child menu per title**, sitting at its first visible spec's sort
    position, with a separator inside it wherever its entries change group. So two groups
    can feed one submenu — what a test *is* and what it *did*, say — and get the rule
    between them rather than two child menus with the same name. A child menu whose entries
    are all hidden is never created. Naming a submenu renders just that child menu's
    entries, flat — for a popup on a thing whose verbs live in a submenu, like the tab bar's
    right-click, or a toolbar button that drops its verb's submenu down.

    A **data child menu** (`DataMenuSpec`) is placed by the same key and filled when it
    opens, as the bar's is — so a menu's right-click offers *Run Agent With* because the
    Step menu does, and never a copy of it. It is a child of the menu itself, so a named
    ``submenu`` render leaves it out.
    """
    context = context_service.current()
    previous_group: str | None = None
    submenus: dict[str, QMenu] = {}
    submenu_group: dict[str, str] = {}  # Child title → the group its last entry came from.

    def add_entry(child: QMenu, spec: ActionSpec, label: str, state: ActionState) -> None:
        action = child.addAction(label)
        _decorate(action, spec, state, child)
        action.triggered.connect(
            lambda _checked=False, sid=spec.id: actions.run(sid, context_service.current())
        )

    placed: list[ActionSpec | DataMenuSpec] = [*actions.all_specs(), *actions.data_menus()]
    for spec in sorted(placed, key=actions.menus.sort_key):
        if spec.menu != menu:
            continue
        if isinstance(spec, DataMenuSpec):
            if submenu is not None:
                continue
            if previous_group is not None and spec.group != previous_group:
                target.addSeparator()
            previous_group = spec.group
            data_child = target.addMenu(spec.title)
            data_child.aboutToShow.connect(lambda s=spec, c=data_child: _fill_data(s, c))
            continue
        if submenu is not None and spec.submenu != submenu:
            continue
        state = spec.state(context)
        if not state.visible:
            continue
        label = state.label if state.label is not None else spec.label
        if submenu is None and spec.submenu is not None:
            child = submenus.get(spec.submenu)
            if child is None:
                # The child menu lands here, at its first visible spec's sort position —
                # so the group bookkeeping below must run for it exactly once. A later
                # group feeding the same child is not a top-level entry and must not move
                # ``previous_group``, or the group after it would lose its rule.
                if previous_group is not None and spec.group != previous_group:
                    target.addSeparator()
                previous_group = spec.group
                child = submenus[spec.submenu] = target.addMenu(spec.submenu)
            elif submenu_group[spec.submenu] != spec.group:
                child.addSeparator()
            submenu_group[spec.submenu] = spec.group
            add_entry(child, spec, label, state)
            continue
        if previous_group is not None and spec.group != previous_group:
            target.addSeparator()
        previous_group = spec.group
        add_entry(target, spec, label, state)
    return target


def build_menu(
    actions: ActionRegistry,
    context_service: ContextService,
    menu: str,
    parent: QWidget,
    submenu: str | None = None,
) -> QMenu:
    """A fresh pop-up holding one menu's visible actions — see :func:`fill_menu`."""
    return fill_menu(QMenu(parent), actions, context_service, menu, submenu)
