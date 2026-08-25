"""The product format on disk: what it writes, what it omits, and what it reads back."""

import json

import pytest

from dplanner.core.storage.local import LocalStorage
from dplanner.domain.model import Product, Project, Step
from dplanner.domain.store import ProductStore, StaleWorkspaceError


@pytest.fixture
def store(tmp_path):
    return ProductStore(LocalStorage(tmp_path / "ws"))


@pytest.fixture
def product(store):
    product = Product(name="Widget", repository="git@example.com:widget.git")
    project = Project(title="Discovery", summary="what we do not know")
    product.add_child(product.id, project)
    product.add_child(project.id, Step(title="Read the spec"))
    product.add_child(project.id, Step(title="Draft the model"))
    store.create(product)
    return product


def find(product, title):
    return next(node for node in product.nodes() if getattr(node, "title", None) == title)


def read(store, *parts):
    return json.loads((store.storage.root.joinpath(*parts)).read_text())


def fingerprint(root):
    """Every file's path and bytes — what a commit would actually record."""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# -- the shape on disk -------------------------------------------------------------------------


def test_a_new_store_reports_no_workspace(store):
    assert not store.exists()


def test_the_product_becomes_container_directories(store, product):
    root = store.storage.root
    assert (root / "product.json").is_file()
    assert (root / "projects" / "discovery" / "project.json").is_file()
    assert (root / "projects" / "discovery" / "steps" / "read-the-spec" / "step.json").is_file()


def test_ordering_lives_in_the_parent_not_in_filenames(store, product):
    meta = read(store, "projects", "discovery", "project.json")
    assert meta["children"] == ["read-the-spec", "draft-the-model"]


def test_absence_encodes_the_default(store, product):
    """A step at its default carries only identity — so a diff shows exactly what changed."""
    meta = read(store, "projects", "discovery", "steps", "read-the-spec", "step.json")
    assert set(meta) == {"id", "created", "title"}


def test_the_format_version_is_written_on_the_product_only(store, product):
    assert "format" in read(store, "product.json")
    assert "format" not in read(store, "projects", "discovery", "project.json")


# -- the round trip ----------------------------------------------------------------------------


def test_what_is_written_reads_back_the_same(store, product, tmp_path):
    reopened = ProductStore(LocalStorage(store.storage.root)).load()
    assert reopened.name == "Widget"
    assert [p.title for p in reopened.projects] == ["Discovery"]
    assert [s.title for s in reopened.projects[0].steps] == ["Read the spec", "Draft the model"]


def test_saving_a_reloaded_product_changes_no_bytes(store, product):
    """The bytes must not depend on whether the workspace has been reopened."""
    before = fingerprint(store.storage.root)
    reopened_store = ProductStore(LocalStorage(store.storage.root))
    reopened = reopened_store.load()
    reopened_store.save_all(reopened)
    assert fingerprint(store.storage.root) == before


def test_edges_are_one_line_per_kind(store, product):
    first, second = find(product, "Read the spec"), find(product, "Draft the model")
    product.set_edges(second.id, "requires", [first.id])
    store.flush({(second.id, "meta")})
    meta = read(store, "projects", "discovery", "steps", "draft-the-model", "step.json")
    assert meta["edges"] == {"requires": [first.id]}


def test_an_edge_kind_this_build_does_not_know_survives(store, product):
    """A colleague's newer link must not vanish because an older build opened the file."""
    path = store.storage.root / "projects/discovery/steps/read-the-spec/step.json"
    meta = json.loads(path.read_text())
    meta["edges"] = {"invented_by_a_newer_build": ["whatever"]}
    path.write_text(json.dumps(meta))

    reopened_store = ProductStore(LocalStorage(store.storage.root))
    reopened = reopened_store.load()
    reopened_store.save_all(reopened)
    assert json.loads(path.read_text())["edges"] == {"invented_by_a_newer_build": ["whatever"]}


# -- module data, prose and files ----------------------------------------------------------------


def test_module_data_prose_and_files_sit_side_by_side(store, product):
    step = find(product, "Read the spec")
    product.set_module_data(step.id, "step_estimation", {"days": 3.0})
    product.set_text(step.id, "step_description", "# Notes\n")
    store.flush({(step.id, "module_data"), (step.id, "module_text")})
    store.files(step.id, "step_description").write_bytes("assets/diagram.png", b"\x89PNG")

    modules = store.storage.root / "projects/discovery/steps/read-the-spec/modules"
    assert (modules / "step_estimation.json").is_file()
    assert (modules / "step_description.md").read_text() == "# Notes\n"
    assert (modules / "step_description" / "assets" / "diagram.png").read_bytes() == b"\x89PNG"


def test_clearing_module_data_leaves_nothing_behind(store, product):
    step = find(product, "Read the spec")
    modules = store.storage.root / "projects/discovery/steps/read-the-spec/modules"
    product.set_module_data(step.id, "step_estimation", {"days": 3.0})
    store.flush({(step.id, "module_data")})
    assert modules.is_dir()

    product.set_module_data(step.id, "step_estimation", {})
    store.flush({(step.id, "module_data")})
    assert not modules.exists()


def test_clearing_prose_removes_the_document(store, product):
    step = find(product, "Read the spec")
    document = store.storage.root / "projects/discovery/steps/read-the-spec/modules/x.md"
    product.set_text(step.id, "x", "something")
    store.flush({(step.id, "module_text")})
    assert document.is_file()

    product.set_text(step.id, "x", "")
    store.flush({(step.id, "module_text")})
    assert not document.exists()


def test_an_unknown_module_entry_is_round_tripped(store, product):
    """Data belonging to a module this build does not have must survive untouched."""
    modules = store.storage.root / "projects/discovery/steps/read-the-spec/modules"
    modules.mkdir(parents=True, exist_ok=True)
    (modules / "from_the_future.json").write_text('{"kept": true}\n')

    reopened_store = ProductStore(LocalStorage(store.storage.root))
    reopened = reopened_store.load()
    reopened_store.save_all(reopened)
    assert json.loads((modules / "from_the_future.json").read_text()) == {"kept": True}


def test_a_file_area_this_build_does_not_know_is_left_alone(store, product):
    modules = store.storage.root / "projects/discovery/steps/read-the-spec/modules"
    (modules / "from_the_future" / "assets").mkdir(parents=True)
    (modules / "from_the_future" / "assets" / "x.png").write_bytes(b"png")

    # Reopen, because the file above was written by "another build" and this store has to
    # have seen the workspace as it now is before it may write to it.
    reopened_store = ProductStore(LocalStorage(store.storage.root))
    reopened = reopened_store.load()
    step = find(reopened, "Read the spec")
    reopened.set_module_data(step.id, "step_estimation", {"days": 1.0})
    reopened_store.flush({(step.id, "module_data")})
    reopened.set_module_data(step.id, "step_estimation", {})
    reopened_store.flush({(step.id, "module_data")})
    assert (modules / "from_the_future" / "assets" / "x.png").is_file()


def test_removing_the_last_file_removes_the_area(store, product):
    step = find(product, "Read the spec")
    area = store.files(step.id, "step_description")
    area.write_bytes("diagram.png", b"png")
    area.remove("diagram.png")
    assert not (store.storage.root / area.directory).exists()


# -- two writers, one folder -------------------------------------------------------------------


def test_a_workspace_changed_underneath_is_noticed(store, product):
    assert not store.changed_underneath()
    (store.storage.root / "projects/discovery/project.json").write_text("{}\n")
    assert store.changed_underneath()


def test_flushing_over_someone_elses_write_is_refused(store, product):
    """The scenario this exists for: an agent edits the folder while a window is open.

    A flush that rewrote the node from a model which never saw that edit would erase it
    silently, and orphan removal would delete a directory the agent had just created.
    """
    step = find(product, "Read the spec")
    other = ProductStore(LocalStorage(store.storage.root))
    other_product = other.load()
    other_step = find(other_product, "Read the spec")
    other_product.set_field(other_step.id, "title", "Written by an agent")
    other.flush({(other_step.id, "meta")})

    product.set_field(step.id, "title", "Written in the window")
    with pytest.raises(StaleWorkspaceError, match="changed on disk"):
        store.flush({(step.id, "meta")})

    meta = read(store, "projects", "discovery", "steps", "read-the-spec", "step.json")
    assert meta["title"] == "Written by an agent"


def test_reopening_clears_the_refusal(store, product):
    """Reload is the way out, and it is the only one that cannot lose anybody's work."""
    (store.storage.root / "projects/discovery/project.json").write_text("{}\n")
    reopened_store = ProductStore(LocalStorage(store.storage.root))
    reopened = reopened_store.load()
    assert not reopened_store.changed_underneath()
    reopened_store.flush({(reopened.id, "meta")})


# -- structure ---------------------------------------------------------------------------------


def test_flush_resolves_each_kind_from_one_flat_mark(store, product):
    """`flush` is handed (id, aspect) pairs with no kind in them, so it has to work the
    kind out — the one place a three-level model meets a flat repository face."""
    project = find(product, "Discovery")
    step = find(product, "Read the spec")
    product.set_field(product.id, "name", "Widget Two")
    product.set_field(project.id, "title", "Discovery Phase")
    product.set_field(step.id, "title", "Read the whole spec")
    store.flush({(product.id, "meta"), (project.id, "meta"), (step.id, "meta")})

    assert read(store, "product.json")["name"] == "Widget Two"
    assert read(store, "projects", "discovery", "project.json")["title"] == "Discovery Phase"
    meta = read(store, "projects", "discovery", "steps", "read-the-spec", "step.json")
    assert meta["title"] == "Read the whole spec"


def test_a_new_step_gets_its_directory_on_flush(store, product):
    project = find(product, "Discovery")
    product.add_child(project.id, Step(title="Review"))
    store.flush({(project.id, "structure")})
    assert (store.storage.root / "projects/discovery/steps/review/step.json").is_file()


def test_a_removed_step_takes_its_directory_with_it(store, product):
    project = find(product, "Discovery")
    product.remove_child(find(product, "Read the spec").id)
    store.flush({(project.id, "structure")})
    assert not (store.storage.root / "projects/discovery/steps/read-the-spec").exists()


def test_deleting_and_undoing_writes_the_subtree_again(store, product):
    project = find(product, "Discovery")
    step = find(product, "Read the spec")
    parent_id, index = product.remove_child(step.id)
    store.flush({(project.id, "structure")})
    product.restore_child(parent_id, step, index)
    store.flush({(project.id, "structure")})
    assert (store.storage.root / "projects/discovery/steps/read-the-spec/step.json").is_file()


def test_an_unlisted_directory_holding_a_step_is_adopted(store, product):
    """A folder a merge resurrected is data, not noise."""
    stray = store.storage.root / "projects/discovery/steps/found-by-hand"
    stray.mkdir(parents=True)
    (stray / "step.json").write_text('{"id": "abc123", "title": "Found by hand"}\n')
    reopened = ProductStore(LocalStorage(store.storage.root)).load()
    assert "Found by hand" in [step.title for step in reopened.projects[0].steps]
