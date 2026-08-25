"""The plan format on disk: what it writes, what it omits, and what it reads back."""

import json

import pytest

from dplanner.core.storage.local import LocalStorage
from dplanner.domain.model import Plan, Task
from dplanner.domain.store import PlanStore


@pytest.fixture
def store(tmp_path):
    return PlanStore(LocalStorage(tmp_path / "ws"))


@pytest.fixture
def plan(store):
    root = Task(title="Project")
    plan = Plan(root)
    plan.add_task(root.id, Task(title="Build", description="what it is", estimate_days=5))
    store.create(plan)
    return plan


def task_id(plan, title):
    return next(task.id for task in plan.tasks() if task.title == title)


def test_a_new_store_reports_no_workspace(store):
    assert not store.exists()


def test_the_plan_becomes_nested_folders(store, plan):
    root_dir = store.storage.root
    assert (root_dir / "plan.json").is_file()
    assert (root_dir / "build" / "task.json").is_file()
    assert (root_dir / "build" / "description.md").read_text() == "what it is"


def test_absence_encodes_the_default(store, plan):
    """Only non-default fields are written, so a diff shows what actually changed."""
    meta = json.loads((store.storage.root / "build" / "task.json").read_text())
    assert meta["estimate_days"] == 5
    assert "status" not in meta  # todo is the default.
    assert "assignee" not in meta
    assert "depends_on" not in meta
    assert not (store.storage.root / "build" / "notes.md").exists()


def test_plan_fields_round_trip(store, plan):
    build = task_id(plan, "Build")
    plan.set_field(build, "status", "doing")
    plan.set_field(build, "assignee", "knut")
    plan.set_field(build, "due", "2026-09-01")
    store.flush({(build, "meta")})

    reloaded = PlanStore(store.storage).load()
    task = next(t for t in reloaded.tasks() if t.title == "Build")
    assert (task.status, task.assignee, task.due) == ("doing", "knut", "2026-09-01")
    assert task.estimate_days == 5


def test_dependencies_survive_a_round_trip(store, plan):
    root, build = plan.root.id, task_id(plan, "Build")
    other = Task(title="Design")
    plan.add_task(root, other)
    plan.set_dependencies(build, [other.id])
    store.flush({(root, "structure"), (build, "meta")})

    reloaded = PlanStore(store.storage).load()
    task = next(t for t in reloaded.tasks() if t.title == "Build")
    assert task.depends_on == [other.id]
    assert [b.title for b in reloaded.blockers(task.id)] == ["Design"]


def test_a_malformed_field_falls_back_rather_than_crashing(store, plan):
    """A hand-edited plan, or one from a newer build, must open."""
    path = store.storage.root / "build" / "task.json"
    meta = json.loads(path.read_text())
    meta["estimate_days"] = "five"
    meta["depends_on"] = ["ok", 7]
    path.write_text(json.dumps(meta))

    reloaded = PlanStore(store.storage).load()
    task = next(t for t in reloaded.tasks() if t.title == "Build")
    assert task.estimate_days is None
    assert task.depends_on == ["ok"]


def test_ordering_lives_in_the_parent(store, plan):
    plan.add_task(plan.root.id, Task(title="Ship"))
    store.flush({(plan.root.id, "structure")})
    meta = json.loads((store.storage.root / "plan.json").read_text())
    assert meta["children"] == ["build", "ship"]


def test_a_retitle_does_not_move_the_folder(store, plan):
    build = task_id(plan, "Build")
    plan.set_title(build, "Something Else")
    store.flush({(build, "meta")})
    assert (store.storage.root / "build" / "task.json").is_file()


def test_moving_a_task_moves_its_directory(store, plan):
    build = task_id(plan, "Build")
    phase = Task(title="Phase")
    plan.add_task(plan.root.id, phase)
    store.flush({(plan.root.id, "structure")})
    plan.move_task(build, phase.id, 0)
    store.flush({(plan.root.id, "structure"), (phase.id, "structure")})
    assert (store.storage.root / "phase" / "build" / "task.json").is_file()
    assert not (store.storage.root / "build").exists()


def test_deleting_a_task_removes_its_directory(store, plan):
    plan.remove_task(task_id(plan, "Build"))
    store.flush({(plan.root.id, "structure")})
    assert not (store.storage.root / "build").exists()


def test_an_unlisted_directory_is_adopted(store, plan):
    stray = store.storage.root / "stray"
    stray.mkdir()
    (stray / "task.json").write_text(json.dumps({"id": "stray1", "title": "Stray"}))
    reloaded = PlanStore(store.storage).load()
    assert "Stray" in [task.title for task in reloaded.tasks()]


def test_an_unreadable_format_is_refused(store, plan):
    from dplanner.core.formats import UnsupportedFormatError

    path = store.storage.root / "plan.json"
    meta = json.loads(path.read_text())
    meta["format"] = 99
    path.write_text(json.dumps(meta))
    with pytest.raises(UnsupportedFormatError) as caught:
        PlanStore(store.storage).load()
    assert caught.value.is_newer


def test_module_data_lands_in_its_own_file(store, plan):
    build = task_id(plan, "Build")
    plan.set_module_data(build, "notes_module", {"note": "hi", "format": 1})
    store.flush({(build, "module_data")})
    written = store.storage.root / "build" / "modules" / "notes_module.json"
    assert json.loads(written.read_text())["note"] == "hi"


def test_clearing_module_data_removes_the_file_and_the_directory(store, plan):
    build = task_id(plan, "Build")
    plan.set_module_data(build, "notes_module", {"note": "hi"})
    store.flush({(build, "module_data")})
    plan.set_module_data(build, "notes_module", {})
    store.flush({(build, "module_data")})
    assert not (store.storage.root / "build" / "modules").exists()
