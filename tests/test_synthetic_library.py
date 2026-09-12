"""The synthetic library the scaling harness measures over is a real plan on disk."""

from pathlib import Path

from scripts.synthetic_library import build_library

from dplanner.domain.store import LibraryStore
from dplanner.modules.feature.catalogue import read_catalogue
from dplanner.modules.project_editor.positions import read_position
from dplanner.modules.step_milestone.aspect import read as milestone_label
from dplanner.modules.testing import runs


def test_the_library_reads_back_with_the_mix_it_promises(tmp_path: Path) -> None:
    library_file = build_library(tmp_path, steps=30)

    store = LibraryStore(library_file)
    library = store.load()
    try:
        by_title = {project.title: project for project in library.projects}
        assert set(by_title) == {"Big", "Sibling", "Small"}
        big = by_title["Big"]
        assert len(big.steps) == 30
        assert len(by_title["Small"].steps) == 20
        assert all(read_position(step) is not None for step in big.steps)
        assert any(milestone_label(step) for step in big.steps)
        assert any(step.edges.get("requires") for step in big.steps)
        assert read_catalogue(big)
        assert runs.open_run(runs.read(big)) is not None
        assert all(step.module_text.get("step_description") for step in big.steps)
    finally:
        store.close()


def test_an_unplaced_share_leaves_positions_to_the_layout(tmp_path: Path) -> None:
    library_file = build_library(tmp_path, steps=30, projects=1, unplaced=0.5)

    store = LibraryStore(library_file)
    library = store.load()
    try:
        (big,) = library.projects
        placed = sum(1 for step in big.steps if read_position(step) is not None)
        assert 0 < placed < 30
    finally:
        store.close()
