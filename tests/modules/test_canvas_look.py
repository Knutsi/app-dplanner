"""The look: one per-user value for the marks, the spotlight, the ground and snapping; and
the pitch the ground's grid is drawn at. No canvas."""

import pytest

from dplanner.modules.project_editor.ground import MIN_SCREEN_PITCH, pitch_for
from dplanner.modules.project_editor.look import BACKGROUNDS, Look
from dplanner.modules.project_editor.marks import Marks
from dplanner.modules.project_editor.positions import GRID


def test_the_look_round_trips_through_json_and_forgives_junk():
    look = (
        Look()
        .with_mark("ends", True)
        .with_background("lines")
        .with_snap(False)
        .with_spotlight(True)
    )
    assert Look.from_json(look.to_json()) == look
    assert look.marks == Marks(ends=True)
    assert Look.from_json(None) == Look()
    assert Look.from_json({"background": "plaid", "snap": 0, "marks": "no"}) == Look(snap=False)
    with pytest.raises(KeyError):
        Look().with_background("plaid")


def test_the_default_look_is_dots_with_snapping_on_and_the_spotlight_off():
    """The marks are on by default and the spotlight is not: a mark says what the graph
    could be *wrong* about, where the spotlight only hides the parts you are not reading."""
    assert Look() == Look(marks=Marks(), spotlight=False, background="dots", snap=True)
    assert Look.from_json({}).spotlight is False
    assert list(BACKGROUNDS) == ["none", "dots", "lines", "crosses"]


@pytest.mark.parametrize("zoom", (0.4, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5))
def test_the_drawn_pitch_coarsens_the_snap_grid_to_stay_readable(zoom):
    """Always a power-of-two multiple of the snap pitch — a card's corner is on a line the
    ground could show — and never closer than MIN_SCREEN_PITCH device pixels."""
    pitch = pitch_for(zoom)
    assert pitch * zoom >= MIN_SCREEN_PITCH
    assert pitch / 2 * zoom < MIN_SCREEN_PITCH or pitch == GRID
    ratio = pitch / GRID
    assert ratio == int(ratio) and int(ratio) & (int(ratio) - 1) == 0


def test_the_pitch_at_one_to_one_is_thirty_two():
    assert pitch_for(1.0) == 32.0 and pitch_for(0.5) == 64.0 and pitch_for(2.5) == 16.0
