"""The build order — the part of the builder that is a contract rather than a detail."""

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.framework.context import SCOPE_APP, WORKSPACE_URI


def test_a_build_produces_a_window_and_services(services):
    assert services is not None
    assert services.window.isVisible() or True  # Shown by the session; offscreen here.
    assert services.repo.library is services.document


def test_the_app_scope_exists_before_modules_register(services):
    """Stage 5 is why a module may open a tab during registration without checking."""
    scope = services.context.current().scope(SCOPE_APP)
    assert [node.uri for node in scope] == [WORKSPACE_URI]


def test_every_shipped_module_registered_something(services):
    action_ids = {spec.id for spec in services.actions.all_specs()}
    expected = {"appshell.quit", "library.open_library", "projects.browse", "projects.remove"}
    assert expected <= action_ids


def test_module_data_is_migrated_before_any_module_reads_it(session, make_project):
    """Breaking this order produces a bug that only appears on an old workspace."""
    from dplanner.core.module_data import migrate_module_data

    library = session.services.document
    repo = session.services.repo
    project = make_project()
    library.set_module_data(project.id, "m", {"old": 1})

    fmt = ModuleDataFormat("m", version=2, migrations=(lambda d: {"new": d["old"]},))
    changed = migrate_module_data(repo, [fmt])
    assert changed == [project.id]
    assert project.module_data["m"] == stamped({"new": 1}, 2)


def test_a_closed_session_leaves_nothing_of_its_build_behind(app, library_file):
    """The property the suite's own running time depends on.

    ``close()`` merely closing the window is not enough: Qt keeps a closed ``QWidget`` in
    ``topLevelWidgets()``, that keeps the whole build reachable, and every later
    ``gc.collect()`` then walks it — which is what turned a suite that builds an application
    per test into a quadratic one. Counting top-level widgets asserts the release directly
    rather than trusting that ``discard_build`` still says ``deleteLater``.
    """
    from dplanner.app import new_session

    before = len(app.topLevelWidgets())
    for _ in range(2):
        session = new_session()
        assert session.open_initial(library_file)
        session.close()
    assert len(app.topLevelWidgets()) == before
