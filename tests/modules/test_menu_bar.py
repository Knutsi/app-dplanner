"""The menu bar as the whole application registers it: sorted by subject, and never dead.

Each menu is filed by the principles in ``menus.py`` and ARCHITECTURE.md's *The menu bar is
sorted by subject*. What a test can hold is the part a refiling is most likely to break: a
menu that offers nothing where people spend their time, two entries fighting over one key,
and a composed pop-up still naming a band that moved.
"""

import re

from PySide6.QtWidgets import QMenu

from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Step
from dplanner.framework.action_menu import Band
from dplanner.menus import MENU_STRUCTURE


def test_every_menu_offers_something_with_a_project_open(services, make_project):
    """A whole menu greyed where people spend their time teaches nothing: every top-level
    menu has an entry that runs with a project's graph open and nothing picked."""
    project = make_project("Discovery")
    AddNodeCommand(project.id, Step(title="Read the spec")).redo(services.document)
    services.tabs.open("project", project.id)
    context = services.context.current()

    dead = [
        menu
        for menu in MENU_STRUCTURE
        if not any(
            spec.state(context).enabled
            for spec in services.actions.all_specs()
            if spec.menu == menu and spec.in_menus and spec.state(context).visible
        )
    ]
    assert dead == []


def test_what_a_step_is_is_set_where_its_aspects_are(services):
    """Type is the aspect bar across Step Details and Test the step's Tests tab there, so
    neither is in a menu — the palette still finds each under its path."""
    kinds = [spec for spec in services.actions.all_specs() if spec.group == "classify"]
    assert {spec.submenu for spec in kinds} == {"Type", "Test"}
    assert [spec.id for spec in kinds if spec.in_menus or not spec.palette] == []
    assert [spec.id for spec in services.actions.data_menus() if spec.group == "classify"] == []


def mnemonic(text: str) -> str | None:
    marked = re.search(r"&([^&])", text.replace("&&", ""))
    return marked.group(1).lower() if marked else None


def clashes(title: str, menu: QMenu) -> list[str]:
    """Every pair of entries in this menu, or any child of it, sharing a letter — hidden
    ones included, since what shows depends on the pick and a clash waits for the pick."""
    found = []
    seen: dict[str, str] = {}
    for action in menu.actions():
        if action.isSeparator():
            continue
        letter = mnemonic(action.text())
        if letter is not None and letter in seen:
            found.append(f"{title}: {seen[letter]!r} and {action.text()!r}")
        elif letter is not None:
            seen[letter] = action.text()
        if isinstance(child := action.menu(), QMenu):
            found += clashes(f"{title} ▸ {action.text()}", child)
    return found


def test_no_two_entries_in_one_menu_share_a_letter(services):
    """Qt answers a letter two entries share by moving between them rather than running
    either, so Alt+G opened nothing once Go and Graph both wanted it — and the same holds
    inside every menu and child menu."""
    bar = services.window.menuBar()

    titles = [action.text() for action in bar.actions()]
    letters = [mnemonic(title) for title in titles]
    assert len(set(letters)) == len(letters), titles
    menus = [action.menu() for action in bar.actions()]
    found = [
        problem
        for title, menu in zip(titles, menus, strict=True)
        if isinstance(menu, QMenu)
        for problem in clashes(title, menu)
    ]
    assert found == []


def compositions() -> list[tuple[str, Band]]:
    """Every pop-up that renders part of a menu by name rather than a whole one."""
    from dplanner.modules.progression.module import ROW_MENU
    from dplanner.modules.project_editor.canvas_menus import BANDS
    from dplanner.modules.project_editor.canvas_toolbar import LOOK_MENU, MENUS
    from dplanner.modules.projects.index import FOLDER_MENU
    from dplanner.modules.spec.activity import ADD_SUBMENU

    return [
        *((f"canvas {target}", band) for target, bands in BANDS.items() for band in bands),
        *((f"strip {verb}", Band(menu, submenu=child)) for verb, (menu, child) in MENUS.items()),
        ("strip Options", Band(LOOK_MENU[0], LOOK_MENU[1])),
        ("Specs tab +", Band("Project", submenu=ADD_SUBMENU)),
        ("Projects folder", Band(*FOLDER_MENU)),
        *(("a status row's ⋮", band) for band in ROW_MENU),
    ]


def test_every_band_a_composition_names_is_live(services):
    """A band naming a group nothing registers into, or a child menu nothing is filed in,
    renders nothing, silently — so each composition is held to what is registered, the one
    thing a refiling has to keep it in step with."""
    placed = [*services.actions.all_specs(), *services.actions.data_menus()]
    groups = {(spec.menu, spec.group) for spec in placed}
    children = {(spec.menu, spec.submenu) for spec in services.actions.all_specs()}

    dead = []
    for where, band in compositions():
        named = (band.group,) if isinstance(band.group, str) else band.group or ()
        dead += [
            f"{where}: {band.menu} ▸ {group}" for group in named if (band.menu, group) not in groups
        ]
        if band.submenu is not None and (band.menu, band.submenu) not in children:
            dead.append(f"{where}: {band.menu} ▸ {band.submenu}")
        if band.menu not in MENU_STRUCTURE:
            dead.append(f"{where}: {band.menu}")
    assert dead == []
