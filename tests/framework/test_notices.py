"""The standing-notice bar: a fact that holds, said over the window's content.

Two properties carry the primitive. It is **data in, rows out** — an owner may recompute
its notice on a two-second timer and hand it over, and a notice that would not change
redraws nothing, which is what makes polling it safe. And it is **gone while nothing
stands**, so an ordinary window grows no chrome it did not ask for.
"""

import pytest

from dplanner.framework.notices import Notice, NoticeBar


@pytest.fixture
def bar(app):
    bar = NoticeBar()
    yield bar
    bar.deleteLater()


def test_a_bar_with_nothing_to_say_is_not_there(bar):
    assert bar.notices() == []
    assert bar.isHidden()


def test_a_notice_appears_and_the_bar_with_it(bar):
    bar.show_notice(Notice(id="one", words="Something is happening"))
    assert [n.words for n in bar.notices()] == ["Something is happening"]
    assert not bar.isHidden()


def test_a_notice_is_replaced_by_its_id_rather_than_stacked(bar):
    bar.show_notice(Notice(id="one", words="First"))
    bar.show_notice(Notice(id="one", words="Second"))
    assert [n.words for n in bar.notices()] == ["Second"]


def test_rows_keep_the_order_they_first_appeared_in(bar):
    bar.show_notice(Notice(id="one", words="First"))
    bar.show_notice(Notice(id="two", words="Second"))
    bar.show_notice(Notice(id="one", words="First, again"))
    assert [n.id for n in bar.notices()] == ["one", "two"]


def test_clearing_the_last_notice_takes_the_bar_away(bar):
    bar.show_notice(Notice(id="one", words="First"))
    bar.show_notice(Notice(id="two", words="Second"))
    bar.clear_notice("one")
    assert not bar.isHidden()
    bar.clear_notice("two")
    assert bar.isHidden()
    bar.clear_notice("gone")  # Clearing what is not there is nothing, not an error.


def test_showing_the_same_notice_again_changes_nothing(bar):
    """What makes a two-second poll free: an owner recomputes and hands it over, and a row
    that would not change is left alone — nothing repaints, nothing under the pointer moves."""
    bar.show_notice(Notice(id="one", words="Working", busy=True))
    row = bar._rows["one"]
    bar.show_notice(Notice(id="one", words="Working", busy=True))
    assert bar._rows["one"] is row
    assert bar.notices()[0].words == "Working"


def test_a_busy_notice_turns_the_arc_and_a_settled_one_stops_it(bar):
    """The application's one motion for *something is running here* — the same arc a
    working button turns — and nothing new invented for an agent."""
    bar.show_notice(Notice(id="one", words="Working", busy=True))
    assert bar._rows["one"]._spinner.is_spinning()
    bar.show_notice(Notice(id="one", words="Was working", busy=False))
    assert not bar._rows["one"]._spinner.is_spinning()


def test_a_declared_count_draws_the_bar_and_no_count_draws_none(bar):
    bar.show_notice(Notice(id="one", words="Half way", fraction=0.5))
    assert not bar._rows["one"]._bar.isHidden()
    bar.show_notice(Notice(id="one", words="No telling", fraction=-1.0))
    assert bar._rows["one"]._bar.isHidden()


def test_a_notice_carries_one_verb_and_runs_it(bar):
    ran = []
    bar.show_notice(Notice(id="one", words="Waiting", action="Settle…", act=lambda: ran.append(1)))
    row = bar._rows["one"]
    assert not row._button.isHidden() and row._button.text() == "Settle…"
    row._button.click()
    assert ran == [1]


def test_a_verb_is_re_bound_even_when_the_words_did_not_change(bar):
    """An owner rebuilds its notice every poll and closes over what it read this time; the
    row keeps its look and takes the newer closure."""
    ran = []
    bar.show_notice(Notice(id="one", words="Waiting", action="Settle…", act=lambda: ran.append(1)))
    bar.show_notice(Notice(id="one", words="Waiting", action="Settle…", act=lambda: ran.append(2)))
    bar._rows["one"]._button.click()
    assert ran == [2]


def test_a_notice_with_no_verb_shows_no_button(bar):
    bar.show_notice(Notice(id="one", words="Just so you know"))
    assert bar._rows["one"]._button.isHidden()
