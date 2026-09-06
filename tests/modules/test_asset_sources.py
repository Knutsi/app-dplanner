"""What each module counts as "used" in the asset catalog — the per-source contracts.

The catalog machinery itself is tested in ``tests/domain/test_assets.py``; these pin the
semantics each ``asset_source()`` exports, because a sweep that misreads one of them
deletes somebody's file.
"""

import pytest

from dplanner.core.storage.locations import init_repo
from dplanner.domain.assets import attach, catalog, prunable
from dplanner.domain.library_file import write_library_file
from dplanner.domain.model import Step
from dplanner.domain.seed import seed_project
from dplanner.domain.store import LibraryStore
from dplanner.modules.docs.aspect import COMPILED_ID
from dplanner.modules.docs.aspect import MODULE_ID as DOCS_ID
from dplanner.modules.docs.aspect import asset_source as docs_source
from dplanner.modules.spec.aspect import MODULE_ID as SPEC_ID
from dplanner.modules.spec.documents import (
    SpecIndex,
    import_document,
    record_asset,
    write_index,
)
from dplanner.modules.spec.documents import (
    asset_source as spec_source,
)
from dplanner.modules.step_agent_instruction.aspect import (
    MODULE_ID as INSTRUCTION_ID,
)
from dplanner.modules.step_agent_instruction.aspect import (
    asset_source as instruction_source,
)
from dplanner.modules.step_description.aspect import (
    MODULE_ID as DESCRIPTION_ID,
)
from dplanner.modules.step_description.aspect import (
    asset_source as description_source,
)
from dplanner.modules.step_handoff.aspect import (
    MODULE_ID as HANDOFF_ID,
)
from dplanner.modules.step_handoff.aspect import (
    asset_source as handoff_source,
)
from dplanner.modules.testing.aspect import (
    MODULE_ID as TESTING_ID,
)
from dplanner.modules.testing.aspect import (
    Test,
)
from dplanner.modules.testing.aspect import (
    asset_source as source_for_tests,  # Not "testing_source": pytest would collect it.
)
from dplanner.modules.testing.aspect import write as write_tests

PNG = b"\x89PNG-pretend"


@pytest.fixture
def store(tmp_path):
    project_dir = seed_project(init_repo(tmp_path / "repo") / "discovery", "Discovery")
    path = tmp_path / "library.json"
    write_library_file(path, [project_dir])
    return LibraryStore(path)


@pytest.fixture
def library(store):
    library = store.load()
    project = library.projects[0]
    library.add_child(project.id, Step(title="Read the spec"))
    store.flush({(project.id, "structure")})
    return library


@pytest.fixture
def project(library):
    return library.projects[0]


@pytest.fixture
def step(project):
    return project.steps[0]


def test_a_description_image_is_used_while_the_markdown_links_it(store, library, project, step):
    name = attach(store.files(step.id, DESCRIPTION_ID), PNG, "shot.png")
    (entry,) = catalog(library, project, store.files, [description_source()])
    assert entry.unused

    step.module_text[DESCRIPTION_ID] = f"![shot]({name})"
    (entry,) = catalog(library, project, store.files, [description_source()])
    assert [use.where for use in entry.uses] == ["description"]


def test_an_archived_tests_image_is_still_used(store, library, project, step):
    name = attach(store.files(step.id, TESTING_ID), PNG, "evidence.png")
    step.module_data[TESTING_ID] = write_tests(
        [Test(id="T100", title="Rejects an empty query", body=f"![]({name})", archived=True)]
    )

    (entry,) = catalog(library, project, store.files, [source_for_tests()])

    assert [use.where for use in entry.uses] == ["test T100 — Rejects an empty query"]


def test_a_handoff_file_is_always_used(store, library, project, step):
    attach(store.files(step.id, HANDOFF_ID), b"anything", "notes.txt")

    (entry,) = catalog(library, project, store.files, [handoff_source()])

    assert [use.where for use in entry.uses] == ["handoff"]
    assert prunable([entry]) == []


def test_an_instruction_file_is_used_without_a_link_because_briefings_carry_it(
    store, library, project, step
):
    attach(store.files(step.id, INSTRUCTION_ID), PNG, "mockup.png")
    attach(store.files(project.id, INSTRUCTION_ID), PNG, "mockup.png")

    (entry,) = catalog(library, project, store.files, [instruction_source()])

    assert [use.where for use in entry.uses] == ["standing instruction", "agent instruction"]
    assert prunable([entry]) == []


def test_a_docs_image_is_used_project_wide_because_compiled_documents_carry_it(
    store, library, project, step
):
    """A compiled document renders images from its *source* steps' areas, so a copy beside
    one step may be needed by a reference on another — "used" is answered by name."""
    name = attach(store.files(step.id, DOCS_ID), PNG, "figure.png")
    collector = Step(title="Ship the beta")
    library.add_child(project.id, collector)
    collector.module_text[COMPILED_ID] = f"![figure]({name})"

    (entry,) = catalog(library, project, store.files, [docs_source()])

    assert [use.where for use in entry.uses] == ["compiled docs"]
    assert [use.subject for use in entry.uses] == ["Ship the beta"]
    assert prunable([entry]) == []

    collector.module_text[COMPILED_ID] = ""
    (entry,) = catalog(library, project, store.files, [docs_source()])
    assert entry.unused  # Nothing anywhere names it now; the sweep may have it.


def test_a_spec_figure_is_used_by_its_index_row_or_a_markdown_body(store, library, project):
    area = store.files(project.id, SPEC_ID)
    indexed = attach(area, PNG, "figure.png")
    linked = attach(area, b"\x89PNG-other", "sketch.png")
    stray = attach(area, b"\x89PNG-third", "leftover.png")
    assets, _asset, _outcome = record_asset([], indexed, "", None, "2026-09-01")
    documents, _doc, _outcome = import_document(
        area, [], "notes", f"![sketch]({linked})".encode(), "notes.md", "2026-09-01"
    )
    project.module_data[SPEC_ID] = write_index(SpecIndex(documents=documents, assets=assets))

    entries = catalog(library, project, store.files, [spec_source()])
    by_name = {entry.name: entry for entry in entries}

    assert [use.where for use in by_name[indexed].uses] == ["spec figure a1"]
    assert [use.where for use in by_name[linked].uses] == ["spec document notes"]
    assert by_name[stray].unused
    # The document blob itself is never an asset: three entries, not four.
    assert len(entries) == 3
