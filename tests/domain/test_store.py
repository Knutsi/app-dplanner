"""The library format on disk: what it writes, what it omits, and what it reads back.

The store is multi-root now: a per-user library file lists project directories, each one
self-contained inside a git repository. The fixtures mirror that — a real ``git init``-ed
repository, a seeded project directory, and a library file naming it.
"""

import json

import pytest

from dplanner.core.storage.locations import init_repo
from dplanner.domain.library_file import read_library_file, write_library_file
from dplanner.domain.model import Step
from dplanner.domain.seed import seed_project
from dplanner.domain.store import PROJECT_META, LibraryStore, StaleWorkspaceError


@pytest.fixture
def repo(tmp_path):
    return init_repo(tmp_path / "repo")


@pytest.fixture
def project_dir(repo):
    return seed_project(repo / "discovery", "Discovery")


@pytest.fixture
def store(tmp_path, project_dir):
    path = tmp_path / "library.json"
    write_library_file(path, [project_dir])
    return LibraryStore(path)


@pytest.fixture
def library(store):
    library = store.load()
    project = library.projects[0]
    library.set_field(project.id, "summary", "what we do not know")
    library.add_child(project.id, Step(title="Read the spec"))
    library.add_child(project.id, Step(title="Draft the model"))
    store.flush({(project.id, "meta"), (project.id, "structure")})
    return library


def find(library, title):
    return next(node for node in library.nodes() if getattr(node, "title", None) == title)


def read(path):
    return json.loads(path.read_text())


def flush_everything(store, library):
    """Every mark for every node — what ``save_all`` used to spell in one call.

    A "structure" mark belongs to a container (the model emits it with the parent's id),
    so only projects carry one here.
    """
    marks = set()
    for node in library.nodes():
        marks.update({(node.id, "meta"), (node.id, "module_text"), (node.id, "module_data")})
        if node.kind == "project":
            marks.add((node.id, "structure"))
    store.flush(marks)


def fingerprint(root):
    """Every file's path and bytes — what a commit would actually record."""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# -- the shape on disk -------------------------------------------------------------------------


def test_a_missing_library_file_reports_not_existing(store, tmp_path):
    assert store.exists()
    assert not LibraryStore(tmp_path / "nowhere.json").exists()


def test_a_project_becomes_container_directories(store, library, project_dir):
    assert (project_dir / "project.dproj").is_file()
    assert (project_dir / "steps" / "read-the-spec" / "step.json").is_file()


def test_ordering_lives_in_the_parent_not_in_filenames(store, library, project_dir):
    meta = read(project_dir / "project.dproj")
    assert meta["children"] == ["read-the-spec", "draft-the-model"]


def test_absence_encodes_the_default(store, library, project_dir):
    """A step at its default carries only identity — the id, the number the project dealt
    it, when it was born, its name — so a diff shows exactly what changed."""
    meta = read(project_dir / "steps" / "read-the-spec" / "step.json")
    assert set(meta) == {"id", "number", "created", "title"}


def test_numbers_are_dealt_per_project_and_round_trip(store, library, project_dir):
    """The number is minted where a step joins a project and the project keeps the mark
    it dealt last, so a reload deals the next step the next number — never a reused one."""
    project = library.projects[0]
    assert [step.number for step in project.steps] == [1, 2]
    assert read(project_dir / "project.dproj")["last_number"] == 2
    assert read(project_dir / "steps" / "draft-the-model" / "step.json")["number"] == 2

    reloaded = LibraryStore(store.library_path).load()
    again = reloaded.projects[0]
    assert [step.number for step in again.steps] == [1, 2] and again.last_number == 2
    reloaded.remove_child(again.steps[1].id)
    reloaded.add_child(again.id, Step(title="Review"))
    assert again.steps[-1].number == 3  # 2 is gone with its step, and stays gone.


def test_a_version_one_project_is_dealt_its_numbers_on_open(store, library, project_dir):
    """The format's first migration: steps written before numbers existed are numbered
    in the order the project lists them, once, and the project is saved at format 2."""
    meta = read(project_dir / "project.dproj")
    meta["format"] = 1
    meta.pop("last_number")
    (project_dir / "project.dproj").write_text(json.dumps(meta))
    for folder in ("read-the-spec", "draft-the-model"):
        step_file = project_dir / "steps" / folder / "step.json"
        step_meta = read(step_file)
        step_meta.pop("number")
        step_file.write_text(json.dumps(step_meta))

    migrated = LibraryStore(store.library_path).load().projects[0]
    assert [(step.title, step.number) for step in migrated.steps] == [
        ("Read the spec", 1),
        ("Draft the model", 2),
    ]
    assert migrated.last_number == 2
    assert read(project_dir / "project.dproj")["format"] == 2
    assert read(project_dir / "steps" / "read-the-spec" / "step.json")["number"] == 1


def test_the_format_version_is_written_per_project(store, library, project_dir):
    assert "format" in read(project_dir / "project.dproj")
    assert "format" not in read(project_dir / "steps" / "read-the-spec" / "step.json")


# -- the round trip ----------------------------------------------------------------------------


def test_what_is_written_reads_back_the_same(store, library):
    reopened = LibraryStore(store.library_path).load()
    assert [p.title for p in reopened.projects] == ["Discovery"]
    assert reopened.projects[0].summary == "what we do not know"
    assert [s.title for s in reopened.projects[0].steps] == ["Read the spec", "Draft the model"]


def test_saving_a_reloaded_library_changes_no_bytes(store, library, project_dir):
    """The bytes must not depend on whether the library has been reopened."""
    before = fingerprint(project_dir)
    reopened_store = LibraryStore(store.library_path)
    reopened = reopened_store.load()
    flush_everything(reopened_store, reopened)
    assert fingerprint(project_dir) == before


def test_edges_are_one_line_per_kind(store, library, project_dir):
    first, second = find(library, "Read the spec"), find(library, "Draft the model")
    library.set_edges(second.id, "requires", [first.id])
    store.flush({(second.id, "meta")})
    meta = read(project_dir / "steps" / "draft-the-model" / "step.json")
    assert meta["edges"] == {"requires": [first.id]}


def test_an_edge_kind_this_build_does_not_know_survives(store, library, project_dir):
    """A colleague's newer link must not vanish because an older build opened the file."""
    path = project_dir / "steps" / "read-the-spec" / "step.json"
    meta = read(path)
    meta["edges"] = {"invented_by_a_newer_build": ["whatever"]}
    path.write_text(json.dumps(meta))

    reopened_store = LibraryStore(store.library_path)
    reopened = reopened_store.load()
    flush_everything(reopened_store, reopened)
    assert read(path)["edges"] == {"invented_by_a_newer_build": ["whatever"]}


# -- module data, prose and files ----------------------------------------------------------------


def test_module_data_prose_and_files_sit_side_by_side(store, library, project_dir):
    step = find(library, "Read the spec")
    library.set_module_data(step.id, "step_estimation", {"days": 3.0})
    library.set_text(step.id, "step_description", "# Notes\n")
    store.flush({(step.id, "module_data"), (step.id, "module_text")})
    store.files(step.id, "step_description").write_bytes("assets/diagram.png", b"\x89PNG")

    modules = project_dir / "steps" / "read-the-spec" / "modules"
    assert (modules / "step_estimation.json").is_file()
    assert (modules / "step_description.md").read_text() == "# Notes\n"
    assert (modules / "step_description" / "assets" / "diagram.png").read_bytes() == b"\x89PNG"


def test_clearing_module_data_leaves_nothing_behind(store, library, project_dir):
    step = find(library, "Read the spec")
    modules = project_dir / "steps" / "read-the-spec" / "modules"
    library.set_module_data(step.id, "step_estimation", {"days": 3.0})
    store.flush({(step.id, "module_data")})
    assert modules.is_dir()

    library.set_module_data(step.id, "step_estimation", {})
    store.flush({(step.id, "module_data")})
    assert not modules.exists()


def test_clearing_prose_removes_the_document(store, library, project_dir):
    step = find(library, "Read the spec")
    document = project_dir / "steps" / "read-the-spec" / "modules" / "x.md"
    library.set_text(step.id, "x", "something")
    store.flush({(step.id, "module_text")})
    assert document.is_file()

    library.set_text(step.id, "x", "")
    store.flush({(step.id, "module_text")})
    assert not document.exists()


def test_an_unknown_module_entry_is_round_tripped(store, library, project_dir):
    """Data belonging to a module this build does not have must survive untouched."""
    modules = project_dir / "steps" / "read-the-spec" / "modules"
    modules.mkdir(parents=True, exist_ok=True)
    (modules / "from_the_future.json").write_text('{"kept": true}\n')

    reopened_store = LibraryStore(store.library_path)
    reopened = reopened_store.load()
    flush_everything(reopened_store, reopened)
    assert read(modules / "from_the_future.json") == {"kept": True}


def test_a_file_area_this_build_does_not_know_is_left_alone(store, library, project_dir):
    modules = project_dir / "steps" / "read-the-spec" / "modules"
    (modules / "from_the_future" / "assets").mkdir(parents=True)
    (modules / "from_the_future" / "assets" / "x.png").write_bytes(b"png")

    # Reopen, because the file above was written by "another build" and this store has to
    # have seen the project as it now is before it may write to it.
    reopened_store = LibraryStore(store.library_path)
    reopened = reopened_store.load()
    step = find(reopened, "Read the spec")
    reopened.set_module_data(step.id, "step_estimation", {"days": 1.0})
    reopened_store.flush({(step.id, "module_data")})
    reopened.set_module_data(step.id, "step_estimation", {})
    reopened_store.flush({(step.id, "module_data")})
    assert (modules / "from_the_future" / "assets" / "x.png").is_file()


def test_removing_the_last_file_removes_the_area(store, library, project_dir):
    step = find(library, "Read the spec")
    area = store.files(step.id, "step_description")
    area.write_bytes("diagram.png", b"png")
    area.remove("diagram.png")
    assert not (project_dir / "steps" / "read-the-spec" / "modules" / "step_description").exists()


# -- two writers, one folder -------------------------------------------------------------------


def test_a_project_changed_underneath_is_noticed(store, library, project_dir):
    assert not store.changed_underneath()
    (project_dir / "steps" / "read-the-spec" / "note.md").write_text("left by an agent\n")
    assert store.changed_underneath()


def test_only_the_plan_counts_as_another_writer(store, library, project_dir):
    """A project directory that is the repository root holds the user's source tree and
    the agent worktrees Run Agent keeps under .dplanner-worktrees/ — none of it plan
    content, and every edit there used to reload the whole window. The plan is
    project.dproj, modules/ and steps/; a file beside them is somebody else's business."""
    (project_dir / "main.py").write_text("print('hi')\n")
    worktree = project_dir / ".dplanner-worktrees" / "s1-build-it" / "src"
    worktree.mkdir(parents=True)
    (worktree / "main.py").write_text("print('agent')\n")
    assert not store.changed_underneath()

    (project_dir / "modules").mkdir(exist_ok=True)
    (project_dir / "modules" / "time_estimates.json").write_text("{}\n")
    assert store.changed_underneath()


def test_the_library_file_changing_is_noticed_too(store, library):
    assert not store.changed_underneath()
    write_library_file(store.library_path, [])
    assert store.changed_underneath()


def test_gits_own_files_are_never_another_writer(tmp_path):
    """A project at the repository root — New Project's git-init flow — puts `.git/`
    inside the watched directory, and git rewrites its own files on every commit and
    even on `git status`. Counting that as an outside change made every Save reload the
    application in a loop; a real content change must still be seen."""
    import subprocess

    repo = init_repo(tmp_path / "at-root")
    project_dir = seed_project(repo, "At Root")
    path = tmp_path / "library.json"
    write_library_file(path, [project_dir])
    store = LibraryStore(path)
    store.load()
    assert not store.changed_underneath()

    git = ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run([*git, "add", "-A"], check=True, capture_output=True)
    subprocess.run([*git, "commit", "-qm", "Save"], check=True, capture_output=True)
    subprocess.run([*git, "status", "--porcelain"], check=True, capture_output=True)
    assert not store.changed_underneath()

    (project_dir / "steps").mkdir(exist_ok=True)
    (project_dir / "steps" / "note.md").write_text("left by an agent\n")
    assert store.changed_underneath()


def test_flushing_over_someone_elses_write_is_refused(store, library, project_dir):
    """The scenario this exists for: an agent edits the folder while a window is open.

    A flush that rewrote the node from a model which never saw that edit would erase it
    silently, and orphan removal would delete a directory the agent had just created.
    """
    step = find(library, "Read the spec")
    other = LibraryStore(store.library_path)
    other_library = other.load()
    other_step = find(other_library, "Read the spec")
    other_library.set_field(other_step.id, "title", "Written by an agent")
    other.flush({(other_step.id, "meta")})

    library.set_field(step.id, "title", "Written in the window")
    with pytest.raises(StaleWorkspaceError, match="changed on disk"):
        store.flush({(step.id, "meta")})

    meta = read(project_dir / "steps" / "read-the-spec" / "step.json")
    assert meta["title"] == "Written by an agent"


def test_reopening_clears_the_refusal(store, library, project_dir):
    """Reload is the way out, and it is the only one that cannot lose anybody's work."""
    path = project_dir / "steps" / "read-the-spec" / "step.json"
    meta = read(path)
    meta["title"] = "Edited by hand"
    path.write_text(json.dumps(meta))

    reopened_store = LibraryStore(store.library_path)
    reopened = reopened_store.load()
    assert not reopened_store.changed_underneath()
    reopened_store.flush({(reopened.projects[0].id, "meta")})


def test_an_outside_edit_in_one_project_does_not_block_another(tmp_path):
    """Staleness is per project: an agent working in Beta never blocks saving Alpha."""
    repo = init_repo(tmp_path / "repo")
    alpha_dir = seed_project(repo / "alpha", "Alpha")
    beta_dir = seed_project(repo / "beta", "Beta")
    path = tmp_path / "library.json"
    write_library_file(path, [alpha_dir, beta_dir])
    store = LibraryStore(path)
    loaded = store.load()
    alpha, beta = loaded.projects

    (beta_dir / "steps").mkdir()
    (beta_dir / "steps" / "note.md").write_text("left by an agent\n")

    loaded.set_field(alpha.id, "summary", "still saveable")
    store.flush({(alpha.id, "meta")})
    assert read(alpha_dir / "project.dproj")["summary"] == "still saveable"

    loaded.set_field(beta.id, "summary", "would overwrite the agent")
    with pytest.raises(StaleWorkspaceError, match="Beta"):
        store.flush({(beta.id, "meta")})


# -- membership --------------------------------------------------------------------------------


def test_a_bad_entry_becomes_a_problem_row_and_the_rest_still_load(tmp_path):
    """One row this build cannot read must not take every healthy project down with it."""
    repo = init_repo(tmp_path / "repo")
    healthy = seed_project(repo / "healthy", "Healthy")
    missing = tmp_path / "vanished"
    no_meta = repo / "just-a-folder"
    no_meta.mkdir()
    outside = seed_project(tmp_path / "outside", "Outside")  # not inside any git repo
    path = tmp_path / "library.json"
    write_library_file(path, [healthy, missing, no_meta, outside])

    store = LibraryStore(path)
    loaded = store.load()

    assert [p.title for p in loaded.projects] == ["Healthy"]
    problems = {problem.path: problem.reason for problem in store.problems()}
    assert "does not exist" in problems[missing]
    assert "project.dproj" in problems[no_meta]
    assert "not inside a git repository" in problems[outside]


def test_adding_a_project_rewrites_the_library_file(tmp_path):
    """A structure mark on the library root means membership changed — and entries that
    failed to open keep their place in the file: they are still the user's projects."""
    repo = init_repo(tmp_path / "repo")
    first = seed_project(repo / "one", "One")
    missing = tmp_path / "vanished"
    path = tmp_path / "library.json"
    write_library_file(path, [first, missing])
    store = LibraryStore(path)
    loaded = store.load()
    assert [problem.path for problem in store.problems()] == [missing]

    second = seed_project(repo / "two", "Two")
    project = store.attach(second)
    loaded.add_child(loaded.id, project)
    store.flush({(loaded.id, "structure")})

    assert [entry.path for entry in read_library_file(path)] == [first, second, missing]


def test_two_projects_in_one_repo_share_one_scoped_provider(tmp_path):
    """A Save should commit that repository once, covering exactly both directories."""
    repo = init_repo(tmp_path / "repo")
    a = seed_project(repo / "plans" / "alpha", "Alpha")
    b = seed_project(repo / "beta", "Beta")
    path = tmp_path / "library.json"
    write_library_file(path, [a, b])
    store = LibraryStore(path)
    store.load()

    from dplanner.core.storage.git import GitStorage

    groups = store.repo_groups()
    assert len(groups) == 1
    group = groups[0]
    assert isinstance(group, GitStorage)  # A repo group is a provider with a history.
    assert set(group.scopes) == {"plans/alpha", "beta"}


def test_two_repos_get_two_providers(tmp_path):
    a = seed_project(init_repo(tmp_path / "first") / "alpha", "Alpha")
    b = seed_project(init_repo(tmp_path / "second") / "beta", "Beta")
    path = tmp_path / "library.json"
    write_library_file(path, [a, b])
    store = LibraryStore(path)
    store.load()
    assert len(store.repo_groups()) == 2


# -- structure ---------------------------------------------------------------------------------


def test_flush_resolves_each_kind_from_one_flat_mark(store, library, project_dir):
    """`flush` is handed (id, aspect) pairs with no kind in them, so it has to work the
    kind out — the one place a two-level model meets a flat repository face."""
    project = find(library, "Discovery")
    step = find(library, "Read the spec")
    library.set_field(project.id, "title", "Discovery Phase")
    library.set_field(step.id, "title", "Read the whole spec")
    store.flush({(project.id, "meta"), (step.id, "meta")})

    assert read(project_dir / "project.dproj")["title"] == "Discovery Phase"
    meta = read(project_dir / "steps" / "read-the-spec" / "step.json")
    assert meta["title"] == "Read the whole spec"


def test_a_new_step_gets_its_directory_on_flush(store, library, project_dir):
    project = find(library, "Discovery")
    library.add_child(project.id, Step(title="Review"))
    store.flush({(project.id, "structure")})
    assert (project_dir / "steps" / "review" / "step.json").is_file()


def test_a_removed_step_takes_its_directory_with_it(store, library, project_dir):
    project = find(library, "Discovery")
    library.remove_child(find(library, "Read the spec").id)
    store.flush({(project.id, "structure")})
    assert not (project_dir / "steps" / "read-the-spec").exists()


def test_deleting_and_undoing_writes_the_subtree_again(store, library, project_dir):
    project = find(library, "Discovery")
    step = find(library, "Read the spec")
    parent_id, index = library.remove_child(step.id)
    store.flush({(project.id, "structure")})
    library.restore_child(parent_id, step, index)
    store.flush({(project.id, "structure")})
    assert (project_dir / "steps" / "read-the-spec" / "step.json").is_file()


def test_an_unlisted_directory_holding_a_step_is_adopted(store, library, project_dir):
    """A folder a merge resurrected is data, not noise."""
    stray = project_dir / "steps" / "found-by-hand"
    stray.mkdir(parents=True)
    (stray / "step.json").write_text('{"id": "abc123", "title": "Found by hand"}\n')
    reopened = LibraryStore(store.library_path).load()
    assert "Found by hand" in [step.title for step in reopened.projects[0].steps]


# -- the code repository and the checkout ----------------------------------------------------


def test_repository_and_colocation_round_trip_and_stay_absent_by_default(store, library):
    project = library.projects[0]
    assert (project.repository, project.colocation) == ("", "")
    library.set_field(project.id, "repository", "git@github.com:acme/widget.git")
    library.set_field(project.id, "colocation", "accepted")
    store.flush({(project.id, "meta")})
    meta = read(store.project_dir(project.id) / PROJECT_META)
    assert meta["repository"] == "git@github.com:acme/widget.git"
    assert meta["colocation"] == "accepted"

    reloaded = LibraryStore(store.library_path).load().projects[0]
    assert (reloaded.repository, reloaded.colocation) == (
        "git@github.com:acme/widget.git",
        "accepted",
    )

    library.set_field(project.id, "colocation", "")
    store.flush({(project.id, "meta")})
    assert "colocation" not in read(store.project_dir(project.id) / PROJECT_META)


def test_a_checkout_is_recorded_in_the_library_file_without_a_flush(store, library, tmp_path):
    project = library.projects[0]
    checkout = tmp_path / "src" / "widget"
    assert store.checkout_of(project.id) is None
    marks = []
    store.dirty.connect(lambda owner, aspect: marks.append((owner, aspect)))
    seen: list[str] = []
    store.checkout_changed.connect(seen.append)

    store.set_checkout(project.id, checkout)

    assert store.checkout_of(project.id) == checkout and seen == [project.id]
    assert marks == []  # Not a dirty mark: a read verb's transaction is never refused over it.
    assert not store.changed_underneath()  # Our own write, stamped as seen.
    assert read_library_file(store.library_path)[0].checkout == checkout
    store.flush({(library.id, "structure")})  # A membership flush keeps what was recorded.
    assert read_library_file(store.library_path)[0].checkout == checkout
    store.set_checkout(project.id, None)
    assert read_library_file(store.library_path)[0].checkout is None


def test_a_relocated_project_is_followed_by_the_store(store, library, tmp_path):
    """The store's half of a move: the record opens where the files went, the node map is
    kept, and the library file is marked for rewriting."""
    import shutil

    project = library.projects[0]
    old = store.project_dir(project.id)
    target = init_repo(tmp_path / "plans") / "discovery"
    shutil.copytree(old, target)
    marks = []
    store.dirty.connect(lambda owner, aspect: marks.append((owner, aspect)))

    store.relocate(project.id, target, tmp_path / "src")

    assert store.project_dir(project.id) == target.resolve()
    assert store.checkout_of(project.id) == tmp_path / "src"
    assert marks == [(library.id, "structure")]
    step = find(library, "Read the spec")
    area = store.files(step.id, "step_description")
    assert area.absolute("x").is_relative_to(target.resolve())
    store.flush({(library.id, "structure"), (step.id, "meta")})
    assert read_library_file(store.library_path)[0].path == target.resolve()
    assert (target / "steps" / "read-the-spec" / "step.json").is_file()


def test_a_file_area_refuses_a_name_that_would_leave_it(store, library, project_dir):
    """Names reach an area off a shared file — a markdown body, a module's JSON — so the
    one place they are joined is the one place a traversal is refused."""
    import pytest

    from dplanner.domain.store import is_area_name

    area = store.files(library.projects[0].id, "spec")
    area.write_bytes("assets/ok.png", b"x")
    for bad in ("../../etc/passwd", "/etc/passwd", "assets/../../x", "a\\b", "./x"):
        assert not is_area_name(bad)
        assert area.read_bytes(bad) is None
        with pytest.raises(ValueError):
            area.write_bytes(bad, b"y")
        with pytest.raises(ValueError):
            area.absolute(bad)
    assert is_area_name("assets/ok.png") and area.read_bytes("assets/ok.png") == b"x"
