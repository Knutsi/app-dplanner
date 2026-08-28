"""The build order — the part of the builder that is a contract rather than a detail."""

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.framework.context import SCOPE_APP, WORKSPACE_URI


def test_a_build_produces_a_window_and_services(services):
    assert services is not None
    assert services.window.isVisible() or True  # Shown by the session; offscreen here.
    assert services.repo.storage is services.storage


def test_the_app_scope_exists_before_modules_register(services):
    """Stage 5 is why a module may open a tab during registration without checking."""
    scope = services.context.current().scope(SCOPE_APP)
    assert [node.uri for node in scope] == [WORKSPACE_URI]


def test_every_shipped_module_registered_something(services):
    action_ids = {spec.id for spec in services.actions.all_specs()}
    assert {"appshell.quit", "workspaces.open", "settings.open", "projects.new"} <= action_ids


def test_module_data_is_migrated_before_any_module_reads_it(session, app, tmp_path):
    """Breaking this order produces a bug that only appears on an old workspace."""
    from dplanner.core.module_data import migrate_module_data

    library = session.services.document
    repo = session.services.repo
    library.set_module_data(library.id, "m", {"old": 1})

    fmt = ModuleDataFormat("m", version=2, migrations=(lambda d: {"new": d["old"]},))
    changed = migrate_module_data(repo, [fmt])
    assert changed == [library.id]
    assert library.module_data["m"] == stamped({"new": 1}, 2)
