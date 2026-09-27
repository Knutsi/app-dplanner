"""Actions as a pop-up menu: the fourth presenter, beside the menu bar, palette and toolbar.

Right-clicking a thing should offer exactly what that thing's menu offers, never a
hand-maintained copy of it. One builder, reading the same registry through the same
context, is what keeps four presentations of the same verbs from drifting apart.

A pop-up may be **composed of more than one render** — :func:`fill_bands` lays several
bands into one menu, so a surface whose subject is narrower than any one menu can
lead with the band that is about it and offer a whole menu beneath it as a child (the Tests
tab's right-click: the result verbs, then *Step*), and a surface whose subject changes with
the click can render a different set of bands for each (the canvas: a card, an arrow, a mixed
pick, empty canvas). What that rules out is an entry written by hand, not a shape; every
entry in such a pop-up still comes from the registry, so a verb added to the menu appears in
the composition without anybody editing the surface.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import QMenu, QWidget

from dplanner.framework.action_registry import (
    PATH_SEPARATOR,
    ActionRegistry,
    ActionSpec,
    ActionState,
    DataMenuSpec,
)
from dplanner.framework.context import ContextService


def menu_ink(target: QMenu) -> QColor:
    """The colour a glyph is painted in: this menu's own text colour, read now.

    A pop-up is built fresh every time it opens, so the colour cannot go stale — which is
    why an action's glyph is a pop-up presenter's business and not the menu bar's, whose
    QActions outlive every theme change. Public because a ``DataMenuSpec``'s fill paints
    its own rows' glyphs and must paint them in the same ink as the verbs beside them.
    """
    return QColor(target.palette().text().color())


def _decorate(entry: QAction, spec: ActionSpec, state: ActionState, target: QMenu) -> None:
    """The one presenter policy applied to a built entry: enablement, check, glyph."""
    entry.setEnabled(state.enabled)
    if state.checked is not None:
        entry.setCheckable(True)
        entry.setChecked(state.checked)
    if spec.icon is not None:
        entry.setIcon(spec.icon(menu_ink(target)))


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
    group: str | tuple[str, ...] | None = None,
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
    between them rather than two child menus with the same name; and a path (``"Theme ▸
    Omarchy"``) nests one child menu inside another, each level an entry of the one before.
    A child menu whose entries are all hidden is never created. Naming a submenu renders
    just that child menu's entries, flat — for a popup on a thing whose verbs live in a
    submenu, like the tab bar's right-click, or a toolbar button that drops its verb's
    submenu down. It names exactly one level: every caller renders a one-level child, and
    what a nested level would mean flat is nobody's question yet.

    Naming a ``group`` renders just that band of the menu, child menus and all — for a
    toolbar face that stands for one band rather than for one verb (the graph strip's
    *Options* is *Graph*'s ``look``); naming several renders those bands in the menu's own
    order, ruled as the menu rules them (a card on the graph is *Step*'s bands about the
    step, and not the ones a table adds). Named **with** a ``submenu`` it means that child
    menu's band instead, still flat: two groups may feed one child menu — Step ▸ Show in
    is fed by ``open`` and ``surfaces`` — and a surface whose subject is one of them can
    offer that one alone. A band is otherwise a run of top-level entries, and a child menu
    of one of them is already inside it, so there is nothing further to filter.

    A **data child menu** (`DataMenuSpec`) is placed by the same key and filled when it
    opens, as the bar's is — so a menu's right-click offers *Run Agent* because the
    Step menu does, and never a copy of it. It is a child of the menu itself, so a named
    ``submenu`` render leaves it out.
    """
    context = context_service.current()
    groups = (group,) if isinstance(group, str) else group
    previous_group: str | None = None
    submenus: dict[str, QMenu] = {}  # Child path → its menu.
    submenu_group: dict[str, str] = {}  # Child path → the group its last entry came from.

    def add_entry(child: QMenu, spec: ActionSpec, label: str, state: ActionState) -> None:
        action = child.addAction(label)
        _decorate(action, spec, state, child)
        action.triggered.connect(
            lambda _checked=False, sid=spec.id: actions.run(sid, context_service.current())
        )

    def child_menu(path: str, entry_group: str) -> QMenu:
        """The child menu at ``path``, creating each missing level here.

        A new level is an entry of its container, so the container's group bookkeeping
        applies to it exactly once, when it lands: the top-level rule for the outermost
        child, a rule inside the parent child for a nested one. A level that exists is
        passed through, and its container's bookkeeping stays where the entry that made
        it left it — the bar's rule, that a child sits at its first spec's position.
        """
        nonlocal previous_group
        container, container_path = target, None
        so_far = ""
        for title in path.split(PATH_SEPARATOR):
            so_far = title if not so_far else so_far + PATH_SEPARATOR + title
            child = submenus.get(so_far)
            if child is None:
                if container_path is None:
                    if previous_group is not None and entry_group != previous_group:
                        target.addSeparator()
                    previous_group = entry_group
                else:
                    # A container made in this same walk has no entry yet: no rule.
                    if submenu_group.get(container_path, entry_group) != entry_group:
                        container.addSeparator()
                    submenu_group[container_path] = entry_group
                child = submenus[so_far] = container.addMenu(title)
            container, container_path = child, so_far
        return container

    placed: list[ActionSpec | DataMenuSpec] = [*actions.all_specs(), *actions.data_menus()]
    for spec in sorted(placed, key=actions.menus.sort_key):
        if spec.menu != menu:
            continue
        if groups is not None and spec.group not in groups:
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
        if not spec.in_menus:
            continue
        state = spec.state(context)
        if not state.visible:
            continue
        label = state.label if state.label is not None else spec.label
        if submenu is None and spec.submenu is not None:
            # The child menu lands at its first visible spec's sort position, so the
            # container's group bookkeeping runs for it exactly once, inside child_menu.
            # A later group feeding the same child is not the container's entry and must
            # not move the container's group, or the group after it would lose its rule.
            child = child_menu(spec.submenu, spec.group)
            if spec.submenu in submenu_group and submenu_group[spec.submenu] != spec.group:
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
    group: str | None = None,
) -> QMenu:
    """A fresh pop-up holding one menu's visible actions — see :func:`fill_menu`."""
    return fill_menu(QMenu(parent), actions, context_service, menu, submenu, group)


@dataclass(frozen=True)
class Band:
    """One render of the registry inside a composed pop-up — :func:`fill_menu`'s arguments.

    ``menu`` alone is the whole menu; ``group`` one band of it or several, and with
    ``submenu`` that child menu's band. ``child`` renders it into a child menu of that title
    rather than flat.
    """

    menu: str
    group: str | tuple[str, ...] | None = None
    submenu: str | None = None
    child: str | None = None


def fill_bands(
    target: QMenu,
    bands: Sequence[Band],
    actions: ActionRegistry,
    context_service: ContextService,
) -> QMenu:
    """Several renders in one pop-up, in order, with the one rule policy for all of them.

    A rule goes above a band only when something was drawn above it **and** the band drew
    something — a rule under nothing is a line the reader has to account for, and what a
    state hides is the registry's business, not the surface's to assume. Two child menus in
    a row get none, for the reason Step's ``track`` band has none between Status and
    Estimate: their names already part them. A child menu that came out empty is taken away
    rather than left to open on nothing.
    """
    after_child = False
    for band in bands:
        above = len(target.actions())
        into = target if band.child is None else target.addMenu(band.child)
        fill_menu(into, actions, context_service, band.menu, band.submenu, band.group)
        if into is not target and into.isEmpty():
            target.removeAction(into.menuAction())
        drawn = target.actions()[above:]
        if not drawn:
            continue
        if above and not (after_child and band.child is not None):
            target.insertSeparator(drawn[0])
        after_child = band.child is not None
    return target
