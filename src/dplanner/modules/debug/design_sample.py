"""The sample the design examples render: rows of a made-up plan, their cells and the table they
fill. Nothing reads the model.
"""

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon

from dplanner.framework.table import Cell, Column, Table
from dplanner.theme.icons import (
    beaker_icon,
    done_icon,
    key_badge_icon,
    layers_icon,
    step_icon,
    tag_icon,
)
from dplanner.theme.palettes import PALETTES, shades
from dplanner.theme.tones import HIGHLIGHT_FILL, recoloured

ROW_MENU_TIP = "What you can do with this step"

# The sample's milestones wear real shades of the default map, dealt by place in the
# sequence, because that is what a milestone wears everywhere in the application now —
# a reference that showed one constant purple would teach the rule that was replaced.
SAMPLE_SHADES = shades(PALETTES[0], 3)


DEMO_DELAY_MS = 1500  # Long enough to see the indicator; a real view settles in 300.


COLUMNS = (
    Column("Step", glyph=True, detail=True, resize="interactive"),
    Column("Days", numeric=True),
    Column("Status"),
)


# The table tab's roster is ticked for its verbs: a check column is the selection, drawn —
# and each row ends in the ⋮ that drops what that one row can be told.
TICKED_COLUMNS = (Column("", check=True), *COLUMNS, Column("", menu=True))


@dataclass(frozen=True)
class SampleRow:
    kind: str  # "milestone" | "feature" | "step" | "test" — decides the glyph and the tint.
    key: str
    title: str
    days: str
    status: str
    agent: bool = False


SAMPLE: tuple[tuple[str, tuple[SampleRow, ...]], ...] = (
    (
        "Improvements #1",
        (
            SampleRow(
                "feature",
                "F1",
                "Design system: guidelines and primitives",
                "2 d",
                "in progress",
                True,
            ),
            SampleRow(
                "step", "S6", "Step details: toggles left, templates right", "1 d", "pending", True
            ),
            SampleRow(
                "test",
                "S9",
                "Boards: Ready to start launches every ready agent",
                "1.5 d",
                "pending",
                True,
            ),
            SampleRow("milestone", "M2", "Improvements #1", "", "pending"),
        ),
    ),
    (
        "Improvements #2",
        (
            SampleRow(
                "step", "S12", "Specs tab as CRUD with markdown tools", "2 d", "pending", True
            ),
            SampleRow("step", "S11", "Documentation compiled by an agent", "1 d", "done"),
            SampleRow("milestone", "M3", "Improvements #2", "", "pending"),
        ),
    ),
)


_GLYPHS = {"milestone": tag_icon, "feature": layers_icon, "step": step_icon, "test": beaker_icon}


# The sample's milestones, in roadmap order — what ``sample_shade`` deals along.
_MILESTONES = tuple(row for _heading, rows in SAMPLE for row in rows if row.kind == "milestone")


def sample_shade(row: SampleRow) -> str:
    """A sample milestone's shade — ``M1`` the deepest, in the order the roadmap runs."""
    place = [found.key for found in _MILESTONES].index(row.key)
    return SAMPLE_SHADES[place]


def sample_cells(row: SampleRow, ink: QColor) -> list[Cell]:
    done = row.status == "done"
    milestone = row.kind == "milestone"
    # A milestone is known by its key, so the key badge stands where the glyph would and
    # the second line says what the row gathers rather than the key again — in that
    # milestone's own shade of the project's colour map. Finished work trades its glyph for
    # the done mark and sets its title in italic; a milestone keeps both.
    finished = done and not milestone
    if milestone:
        glyph = key_badge_icon(row.key, sample_shade(row))
    else:
        glyph = done_icon() if finished else _GLYPHS[row.kind](ink)
    detail = "gathers every step above it" if milestone else row.key
    return [
        Cell(row.title, detail=detail, glyph=glyph, emphasis=milestone, finished=finished),
        Cell(row.days, secondary=done),
        Cell(row.status, secondary=done),
    ]


KEY_ROLE = int(Qt.ItemDataRole.UserRole) + 60  # The host's own role: which sample row.


Groups = list[tuple[str, list[SampleRow]]]


def sample_groups() -> Groups:
    """A mutable copy of the sample, for a surface whose verbs add and remove rows."""
    return [(heading, list(rows)) for heading, rows in SAMPLE]


def matches(row: SampleRow, active: set[str]) -> bool:
    """No filter on shows everything; several on show what matches any of them."""
    return (
        not active
        or ("agent" in active and row.agent)
        or ("milestone" in active and row.kind == "milestone")
        or ("done" in active and row.status == "done")
    )


def fill_sample(
    table: Table,
    ink: QColor,
    active: set[str] = frozenset(),  # type: ignore[assignment]
    groups: Groups | None = None,
    *,
    grouped: bool = True,
    folding: bool = False,
    ticked: bool = False,
) -> None:
    """The sample rows, narrowed by the active ``FILTERS`` keys, under their headings or flat.

    ``ticked`` fills a table whose first column is a check column (``TICKED_COLUMNS``): it
    holds nothing but the box, which the table draws from the row's selection — and whose
    last is the row's ⋮, which holds nothing but the glyph the table draws.

    ``folding`` gives each heading a ``key``, which is what makes it collapsible: a chevron,
    the whole row as the target, and what is shut remembered by key across this very
    rebuild. A long roster is read by folding the groups you are not in.
    """
    table.clear_rows()
    for heading, rows in groups if groups is not None else sample_groups():
        shown = [row for row in rows if matches(row, active)]
        if not shown:
            continue
        if grouped:
            table.add_heading(heading, key=heading if folding else "")
        for row in shown:
            tint = (
                recoloured(HIGHLIGHT_FILL, sample_shade(row)) if row.kind == "milestone" else None
            )
            cells = sample_cells(row, ink)
            table.add_row(
                [Cell(), *cells, Cell(tooltip=ROW_MENU_TIP)] if ticked else cells,
                tint=tint,
                data={KEY_ROLE: row.key},
            )
    table.fit_columns()


def glyph_for(kind: str, ink: QColor) -> QIcon:
    return _GLYPHS[kind](ink)
