"""What the note log says in a report: every standing note as prose, grouped by label in
the ontology's order — and, on each step, the notes made on it.

A superseded note is history, not guidance, so it stays out — the same cut the briefing's
index makes. Qt-free by rule — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from collections.abc import Callable

from dplanner.cli.report.parts import Contribution, Facet, Placed, Prose, ReportSource, images_in
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.store import FilesFor
from dplanner.modules.notes.log import LABEL_IDS, MODULE_ID, Note, read_log, standing
from dplanner.modules.notes.reach import when_where


def report_source(*, key_of: Callable[[Step], str]) -> ReportSource:
    def source(_library: Library, project: Project, files: FilesFor) -> Contribution:
        notes = standing(read_log(project))
        placed = tuple(
            Placed("notes", 10 + index, _prose(project, note, files, key_of))
            for index, note in enumerate(sorted(notes, key=_label_rank))
        )
        facets: dict[str, tuple[Facet, ...]] = {}
        for note in notes:
            if note.step:
                label = note.label.replace("-", " ").capitalize()
                facet = Facet(label, f"{note.id} — {note.title}")
                facets[note.step] = (*facets.get(note.step, ()), facet)
        return Contribution(placed=placed, facets=facets)

    return source


def _label_rank(note: Note) -> int:
    return LABEL_IDS.index(note.label) if note.label in LABEL_IDS else len(LABEL_IDS)


def _prose(project: Project, note: Note, files: FilesFor, key_of: Callable[[Step], str]) -> Prose:
    meta = [note.label, when_where(project, note, key_of)]
    if note.supersedes:
        meta.append(f"supersedes {note.supersedes}")
    try:
        images = images_in(note.body, files(project.id, MODULE_ID))
    except KeyError:
        images = ()
    return Prose(
        note.id,
        f"{note.id} · {note.title}",
        note.body,
        meta=" · ".join(part for part in meta if part),
        images=images,
    )
