"""Actions as a pop-up menu: the fourth presenter, beside the menu bar, palette and toolbar.

Right-clicking a thing should offer exactly what that thing's menu offers, never a
hand-maintained copy of it. One builder, reading the same registry through the same
context, is what keeps four presentations of the same verbs from drifting apart.
"""

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QWidget

from dplanner.framework.action_registry import ActionRegistry, ActionState
from dplanner.framework.context import ContextService


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
    entry.setEnabled(state.enabled)
    if state.checked is not None:
        entry.setCheckable(True)
        entry.setChecked(state.checked)
    entry.triggered.connect(
        lambda _checked=False, sid=spec.id: actions.run(sid, context_service.current())
    )
    return entry


def build_menu(
    actions: ActionRegistry,
    context_service: ContextService,
    menu: str,
    parent: QWidget,
    submenu: str | None = None,
) -> QMenu:
    """One menu's visible actions as a context menu; a disabled one is greyed, not omitted.

    Same policy as the menu bar — hidden means the capability is absent, disabled means "not
    right now", and the greyed entry's label carries the reason (`steps.link`'s refusals are
    the worked example). Only the palette filters on runnable. The context is snapshotted for
    the labels ("Delete 3 Items") but re-read when an entry is triggered, so a menu left open
    across a selection change still acts on what the user has *now* rather than on what they
    had when it opened.

    ``submenu=None`` (the norm) renders the whole menu, nesting child menus exactly as the
    menu bar does: a child menu sits at its first visible spec's sort position, and one
    whose entries are all hidden is never created. Naming a submenu renders just that child
    menu's entries, flat — for a popup on a thing whose verbs live in a submenu, like the
    tab bar's right-click.
    """
    context = context_service.current()
    popup = QMenu(parent)
    previous_group: str | None = None
    submenus: dict[tuple[str, str], QMenu] = {}

    def add_entry(target: QMenu, spec_id: str, label: str, state: ActionState) -> None:
        action = target.addAction(label)
        action.setEnabled(state.enabled)
        if state.checked is not None:
            action.setCheckable(True)
            action.setChecked(state.checked)
        action.triggered.connect(
            lambda _checked=False, sid=spec_id: actions.run(sid, context_service.current())
        )

    for spec in actions.all_specs():
        if spec.menu != menu or (submenu is not None and spec.submenu != submenu):
            continue
        state = spec.state(context)
        if not state.visible:
            continue
        if submenu is None and spec.submenu is not None:
            key = (spec.group, spec.submenu)
            child = submenus.get(key)
            if child is None:
                # The child menu lands here, at its first visible spec's sort position —
                # so the group bookkeeping below must run for it exactly once.
                if previous_group is not None and spec.group != previous_group:
                    popup.addSeparator()
                previous_group = spec.group
                child = submenus[key] = popup.addMenu(spec.submenu)
            add_entry(child, spec.id, state.label if state.label is not None else spec.label, state)
            continue
        if previous_group is not None and spec.group != previous_group:
            popup.addSeparator()
        previous_group = spec.group
        add_entry(popup, spec.id, state.label if state.label is not None else spec.label, state)
    return popup
