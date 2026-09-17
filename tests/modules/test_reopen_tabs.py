"""Reopening the tabs the window had, and refusing to reopen the ones that no longer fit.

A reload is what a restart looks like from inside the process — the session builds a whole
new window, services and set of modules over the same library — so these drive the real
path rather than calling the module's own methods.
"""

import pytest

from dplanner.framework.context import activity_uri
from dplanner.framework.user_config import get_scoped, library_scope, set_global, set_scoped
from dplanner.modules.project_editor.module import PROJECT_KIND
from dplanner.modules.reopen_tabs.module import OPEN_KEY
from dplanner.modules.reopen_tabs.settings_page import MODULE_ID, REOPEN_KEY


@pytest.fixture
def project(services, make_project):
    """One flushed project, so the reload that follows reads it back."""
    project = make_project("Discovery")
    services.autosave.flush_now()
    return project


def remembered(library_file):
    return get_scoped(library_scope(library_file), MODULE_ID, OPEN_KEY, {})


def remember(library_file, open_uris, current=""):
    set_scoped(
        library_scope(library_file),
        MODULE_ID,
        OPEN_KEY,
        {"open": list(open_uris), "current": current},
    )


def open_uris(session):
    return [activity.uri for activity in session.services.tabs.activities()]


def test_the_tabs_come_back(session, services, project, library_file):
    services.tabs.open(PROJECT_KIND, project.id)
    assert session.reload()
    assert open_uris(session) == [activity_uri(PROJECT_KIND, project.id)]


def test_a_dashboard_tab_comes_back_too(session, services, project, library_file):
    from dplanner.modules.project_dashboard.activity import DASHBOARD_KIND

    services.tabs.open(DASHBOARD_KIND, project.id)
    assert session.reload()
    assert open_uris(session) == [activity_uri(DASHBOARD_KIND, project.id)]


def test_the_tab_the_user_was_on_is_the_one_they_come_back_to(
    session, services, project, make_project
):
    other = make_project("Build")
    services.autosave.flush_now()
    services.tabs.open(PROJECT_KIND, other.id)
    services.tabs.open(PROJECT_KIND, project.id)
    services.tabs.focus(next(a for a in services.tabs.activities() if a.uri.endswith(other.id)))
    assert session.reload()
    current = session.services.tabs.current_activity()
    assert current is not None and current.uri == activity_uri(PROJECT_KIND, other.id)


def test_closing_a_tab_the_user_is_not_on_is_still_remembered(
    session, services, project, make_project, library_file
):
    """The gap ``activity_changed`` alone leaves: closing a background tab changes the list
    and nothing else, which is what ``tabs_changed`` exists to say."""
    other = make_project("Build")
    services.autosave.flush_now()
    background = services.tabs.open(PROJECT_KIND, other.id)
    services.tabs.open(PROJECT_KIND, project.id)
    services.tabs.close_activity(background)
    assert remembered(library_file)["open"] == [activity_uri(PROJECT_KIND, project.id)]


def test_a_tab_whose_project_is_gone_is_not_reopened(session, project, library_file):
    """The library changed underneath — the honest answer is fewer tabs, not a bad one."""
    remember(
        library_file,
        [
            activity_uri(PROJECT_KIND, "a-project-that-was-deleted"),
            activity_uri(PROJECT_KIND, project.id),
        ],
    )
    assert session.reload()
    assert open_uris(session) == [activity_uri(PROJECT_KIND, project.id)]


def test_a_tab_of_a_kind_this_build_has_no_longer_is_not_reopened(session, project, library_file):
    remember(library_file, [activity_uri("a-feature-that-was-removed", project.id)])
    assert session.reload()
    assert open_uris(session) == []


def test_nonsense_in_the_store_costs_nothing(session, project, library_file):
    set_scoped(library_scope(library_file), MODULE_ID, OPEN_KEY, "not a tab list at all")
    assert session.reload()
    assert open_uris(session) == []


def test_switching_the_setting_off_starts_empty(session, project, library_file):
    remember(library_file, [activity_uri(PROJECT_KIND, project.id)])
    set_global(MODULE_ID, REOPEN_KEY, False)
    assert session.reload()
    assert open_uris(session) == []


def test_the_list_is_kept_even_while_the_setting_is_off(session, services, project, library_file):
    """So switching it back on returns the session you last had, not one from long ago."""
    set_global(MODULE_ID, REOPEN_KEY, False)
    services.tabs.open(PROJECT_KIND, project.id)
    assert remembered(library_file)["open"] == [activity_uri(PROJECT_KIND, project.id)]


def test_another_library_does_not_get_these_tabs(
    session, services, project, library_file, tmp_path
):
    services.tabs.open(PROJECT_KIND, project.id)
    assert remembered(library_file)["open"]
    assert remembered(tmp_path / "somebody-elses-library.json") == {}
