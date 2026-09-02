"""The asset catalog: one derivation over every module's file areas.

The machinery only — grouping, the never-flushed tolerance, the sweep — over inline
sources; what each real module counts as "used" is its own contract, tested beside the
modules in ``tests/modules/test_asset_sources.py``. Built over a real store, because the
``KeyError`` tolerance and the on-disk grouping are the points and a fake area would
assert nothing about either.
"""

from collections.abc import Collection, Sequence

import pytest

from dplanner.core.storage.locations import init_repo
from dplanner.domain.assets import (
    AssetEntry,
    AssetLocation,
    AssetSource,
    AssetUse,
    area_assets,
    asset_references,
    attach,
    catalog,
    prunable,
)
from dplanner.domain.library_file import write_library_file
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.seed import seed_project
from dplanner.domain.store import FilesFor, LibraryStore

MODULE_ID = "pictures"  # A stand-in module: the catalog never knows a real one.
PNG = b"\x89PNG-pretend"


def source(referenced: Collection[str] = (), prunable: bool = True) -> AssetSource:
    """An inline source over ``MODULE_ID``'s step areas: used = named in ``referenced``."""

    def scan(_library: Library, project: Project, files: FilesFor) -> Sequence[AssetLocation]:
        return [
            AssetLocation(
                node_id=step.id,
                module_id=MODULE_ID,
                name=name,
                uses=(AssetUse("step", step.id, step.title, "a caption"),)
                if name in referenced
                else (),
            )
            for step in project.steps
            for name in area_assets(files, step.id, MODULE_ID)
        ]

    return AssetSource(id=MODULE_ID, label="Pictures", scan=scan, prunable=prunable)


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
    library.add_child(project.id, Step(title="Draft the model"))
    store.flush({(project.id, "structure")})
    return library


def test_asset_references_reads_both_link_forms_and_skips_foreign_targets():
    body = (
        "![shot](assets/ab12.png) and [notes](assets/cd34.pdf), plus\n"
        "![ext](https://example.com/x.png), ![other](figures/e.png),"
        " and ![again]( assets/ab12.png )"
    )
    assert asset_references(body) == ["assets/ab12.png", "assets/cd34.pdf"]


def test_catalog_groups_identical_bytes_across_areas_into_one_entry(store, library):
    project = library.projects[0]
    first, second = project.steps
    name = attach(store.files(first.id, MODULE_ID), PNG, "shot.png")
    assert attach(store.files(second.id, MODULE_ID), PNG, "shot.png") == name

    entries = catalog(library, project, store.files, [source(referenced={name})])

    assert [entry.name for entry in entries] == [name]
    assert [location.node_id for _s, location in entries[0].locations] == [first.id, second.id]
    assert not entries[0].unused  # A referenced copy makes the content used.


def test_catalog_skips_a_node_the_store_has_never_flushed(store, library):
    project = library.projects[0]
    library.add_child(project.id, Step(title="Just added"))  # No flush: no directory yet.

    assert catalog(library, project, store.files, [source()]) == []


def test_prunable_sweeps_only_the_unused_copies(store, library):
    project = library.projects[0]
    first, second = project.steps
    name = attach(store.files(first.id, MODULE_ID), PNG, "shot.png")
    attach(store.files(second.id, MODULE_ID), PNG, "shot.png")

    def used_by_first(_library: Library, prj: Project, files: FilesFor):
        return [
            AssetLocation(
                node_id=step.id,
                module_id=MODULE_ID,
                name=found,
                uses=(AssetUse("step", step.id, step.title, "a caption"),)
                if step.id == first.id
                else (),
            )
            for step in prj.steps
            for found in area_assets(files, step.id, MODULE_ID)
        ]

    entries = catalog(
        library,
        project,
        store.files,
        [AssetSource(id=MODULE_ID, label="Pictures", scan=used_by_first)],
    )
    swept = prunable(entries)

    assert [(location.node_id, location.name) for _s, location in swept] == [(second.id, name)]


def test_prunable_keeps_unused_copies_of_an_unprunable_source():
    location = AssetLocation(node_id="n1", module_id="pool", name="assets/ab.png", uses=())
    pool = AssetSource(id="pool", label="Pool", scan=lambda *_a: [], prunable=False)
    entry = AssetEntry(name=location.name, locations=((pool, location),))

    assert entry.unused
    assert prunable([entry]) == []


def test_same_bytes_with_different_suffixes_are_two_entries(store, library):
    """Grouping is by content *name*, and the suffix is part of it — on purpose: links in
    prose carry the suffix, and a group that ignored it would claim two differently
    linkable files are one."""
    project = library.projects[0]
    carrier = project.steps[0]
    attach(store.files(carrier.id, MODULE_ID), PNG, "shot.jpg")
    attach(store.files(carrier.id, MODULE_ID), PNG, "shot.jpeg")

    entries = catalog(library, project, store.files, [source()])

    assert len(entries) == 2
