"""*Jump to*: naming a step, and putting the viewport on it.

A plan of three hundred steps has perhaps a dozen a person navigates by — the milestones
and the features — so the picker opens on those and searches everything from the first
keystroke (``PickerRow.landmark``). A row is found by its title or by its key, which is
how a step is named everywhere else: ``S7`` and ``jump`` both reach *Jump to a step*.

**The kind is the accent's, not the model's.** The canvas is handed how every step should
look by the composition root (``step_accents``) and learns nothing about aspects; this
list is a second reader of that same answer, so a milestone's key badge here is the badge
the card and the order table wear, in the shade the project dealt it.
"""

from collections.abc import Mapping, Sequence

from PySide6.QtGui import QColor

from dplanner.domain.model import Project, StepId
from dplanner.framework.picker import PickerRow
from dplanner.modules.project_editor.renderers import NodeAccent
from dplanner.theme.icons import glyph_painter, key_badge_icon, step_icon

# The medallion a step wears, as the word this list says it by — coarsest claim first, the
# same order ``_step_key`` reads a step's letter in.
KINDS: tuple[tuple[str, str], ...] = (
    ("tag", "Milestone"),
    ("layers", "Feature"),
    ("shield", "Check"),
)
LANDMARKS = ("Milestone", "Feature")


def _kind(accent: NodeAccent) -> str:
    for glyph, word in KINDS:
        if glyph in accent.icons:
            return word
    return "Step"


def _row(step_id: StepId, title: str, accent: NodeAccent, ink: QColor) -> PickerRow:
    kind = _kind(accent)
    key = accent.key_text
    if kind == "Milestone" and key:
        # A milestone is known by its key across the graph, so it wears it as a badge where
        # the glyph goes — and the second line then says what it is, not the key again.
        icon = key_badge_icon(key, accent.tone_color or ink)
        trailing = ""
    else:
        painter = glyph_painter(accent.icons[0]) if accent.icons else None
        icon = (painter or step_icon)(ink)
        trailing = key
    return PickerRow(
        id=step_id,
        label=title or "Untitled step",
        detail=kind,
        trailing=trailing,
        icon=icon,
        also=key,
        landmark=kind in LANDMARKS,
    )


def jump_rows(
    project: Project, accents: Mapping[StepId, NodeAccent], ink: QColor
) -> Sequence[PickerRow]:
    """Every step, the landmarks leading — milestones, then features, then the work.

    The order is the list somebody arrows through before typing anything, so it is the
    plan's own: a project's steps in the order it holds them, read three times.
    """
    rows = [
        _row(step.id, step.title, accents.get(step.id) or NodeAccent(), ink)
        for step in project.steps
    ]
    leading = [row for word in LANDMARKS for row in rows if row.detail == word]
    return [*leading, *[row for row in rows if not row.landmark]]
