"""Actions as a pop-up menu: the fourth presenter, beside the menu bar, palette and toolbar.

Right-clicking a thing should offer exactly what that thing's menu offers, never a
hand-maintained copy of it. One builder, reading the same registry through the same
context, is what keeps four presentations of the same verbs from drifting apart.
"""

from PySide6.QtWidgets import QMenu, QWidget

from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.context import ContextService


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

    ``submenu=None`` (the norm) renders the whole menu, flattening any child menus. Naming a
    submenu renders just that child menu's entries — for a popup on a thing whose verbs live
    in a submenu, like the tab bar's right-click.
    """
    context = context_service.current()
    popup = QMenu(parent)
    previous_group: str | None = None
    for spec in actions.all_specs():
        if spec.menu != menu or (submenu is not None and spec.submenu != submenu):
            continue
        state = spec.state(context)
        if not state.visible:
            continue
        if previous_group is not None and spec.group != previous_group:
            popup.addSeparator()
        previous_group = spec.group
        label = state.label if state.label is not None else spec.label
        action = popup.addAction(label)
        action.setEnabled(state.enabled)
        if state.checked is not None:
            action.setCheckable(True)
            action.setChecked(state.checked)
        action.triggered.connect(
            lambda _checked=False, sid=spec.id: actions.run(sid, context_service.current())
        )
    return popup
