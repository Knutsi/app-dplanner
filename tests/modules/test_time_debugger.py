"""Debug ▸ Time Simulation: the real Time tab over a simulated plan, in a world of its own."""

from dplanner.framework.context import Context
from dplanner.modules.time_estimates.activity import TimeEstimatesActivity
from dplanner.modules.time_estimates.debugger import (
    OPENS_AFTER,
    SIMULATED,
    SIMULATION_KIND,
    TimeSimulationActivity,
)
from dplanner.modules.time_estimates.module import TimeEstimatesDeps
from dplanner.modules.time_estimates.progress import read_history
from dplanner.modules.time_estimates.simulation.replay import keep
from dplanner.modules.time_estimates.simulation.sample import SAMPLE_START


def _opened(services) -> TimeSimulationActivity:
    services.actions.run("debug.time_simulation", Context({}))
    tab = services.tabs.open(SIMULATION_KIND)
    assert isinstance(tab, TimeSimulationActivity)
    return tab


def test_the_debug_menu_opens_the_real_time_tab_over_a_simulated_plan(services):
    tab = _opened(services)
    inner = tab.inner
    assert isinstance(inner, TimeEstimatesActivity)
    assert tab.day == SAMPLE_START + OPENS_AFTER  # two weeks in: some history to read
    assert inner.snapshot() is not None and inner.landing is not None
    assert read_history(tab.library.projects[0])  # the recorder's rows by then


def test_the_simulated_world_shares_nothing_that_holds_state(services):
    tab = _opened(services)
    inner = tab.inner
    assert inner is not None
    deps = inner._deps
    assert deps.library is tab.library and deps.library is not services.document
    assert deps.undo is not services.undo and deps.context is not services.context
    assert deps.clock is tab.clock and deps.clock is not services.clock
    assert deps.debounce is tab.debounce and deps.debounce is not services.debounce
    assert deps.day_over and not services.document.projects  # nothing reached the window's
    before = services.undo.can_undo()
    tab.show_day(3)
    assert services.undo.can_undo() == before


def test_the_embedded_tabs_writers_are_the_simulators(services):
    """A Budget change there would be undone by the next day restored, so the tab says who
    writes this plan and greys its own writers."""
    tab = _opened(services)
    inner = tab.inner
    assert inner is not None
    assert inner.writers_refusal() == SIMULATED
    assert not inner.budget.isEnabled() and not inner.save_snapshot.isEnabled()
    assert not inner.months.pickable


def test_the_axes_hold_the_whole_run_until_let_go(services):
    """Held, every day is drawn against the reach of the whole run, so a day early in the
    work already has the axis its last landing needs; let go, the axes follow the day. Scope
    creep, so the landing moves out as the days play."""
    tab = _opened(services)
    tab.scenario.setCurrentIndex(tab.scenario.findData("scope-creep"))
    inner, found = tab.inner, tab.simulated
    assert inner is not None and found is not None and tab.hold.isChecked()
    last = max(row.landing(None) or row.day for row in found.recorded.rows)
    tab.show_day(3)
    assert inner.shown is not None and inner.shown.reach.last >= last
    tab.hold.trigger()
    assert not tab.hold.isChecked()
    assert inner.shown is not None and inner.shown.reach.last < last
    tab.hold.trigger()
    assert inner.shown.reach.last >= last


def test_a_day_is_restored_in_place_whichever_way_the_slider_moves(services):
    tab = _opened(services)
    found = tab.simulated
    assert found is not None
    project = tab.library.projects[0]
    last = len(found.timeline.days) - 1
    for index in (last, 2, last - 5):
        tab.slider.setValue(index)
        played = found.timeline.days[index]
        assert tab.day == played.day and tab.clock.today() == played.day
        assert keep(project) == found.recorded.days[index]
        assert tab.inner is not None and tab.inner.snapshot() is not None
    assert "since work began" in tab.day_words.text()


def test_the_days_play_to_the_end_and_stop(services):
    tab = _opened(services)
    found = tab.simulated
    assert found is not None
    tab.show_day(len(found.timeline.days) - 3)
    tab.play.trigger()
    assert tab.play.isChecked()
    for _step in range(5):
        tab._step()
    assert tab.day == found.timeline.days[-1].day and not tab.play.isChecked()
    assert not tab.later.isEnabled()


def test_another_scenario_or_seed_plays_again_on_the_same_day(services):
    tab = _opened(services)
    day = tab.day
    tab.scenario.setCurrentIndex(tab.scenario.findData("scope-creep"))
    found = tab.simulated
    assert found is not None and found.setup.scenario == "scope-creep" and tab.day == day
    assert "Breaks: " in tab.scenario.toolTip()
    tab.seed.setValue(2)
    assert tab.simulated is not None and tab.simulated.setup.seed == 2 and tab.day == day


def test_a_rebudget_from_the_day_shown_changes_the_team_from_that_day(services):
    tab = _opened(services)
    day = tab.day
    assert day is not None
    tab.people.setValue(2)
    tab.agents.setValue(3)
    tab.rebudget.trigger()
    found = tab.simulated
    assert found is not None and len(found.setup.budgets) == 1 and tab.day == day
    at = found.timeline.index_of(day)
    assert at is not None and found.timeline.days[at].state.team == (2, 3)
    assert found.timeline.days[at - 1].state.team == (1, 2)
    assert tab.clear.isEnabled()
    tab.clear.trigger()
    assert tab.simulated is not None and tab.simulated.setup.budgets == ()


def test_nothing_is_simulated_until_the_tab_is_shown(services):
    from dplanner.modules import _time_readers, _time_writers
    from dplanner.modules.time_estimates.debugger import TimeSimulationDeps

    def refused(*_args: object) -> TimeEstimatesDeps:
        raise AssertionError("built before it was shown")

    deps = TimeSimulationDeps(
        actions=services.actions,
        context=services.context,
        tabs=services.tabs,
        readers=_time_readers(),
        writers=_time_writers(),
        time_deps=refused,
    )
    tab = TimeSimulationActivity(deps)
    assert tab.simulated is None and tab.inner is None
    tab.close()
    tab.widget.deleteLater()


def test_closing_the_tab_closes_the_tab_inside_it(services):
    tab = _opened(services)
    inner = tab.inner
    assert inner is not None
    assert services.tabs.close_activity(tab)
    assert tab.inner is None
