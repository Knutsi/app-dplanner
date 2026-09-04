"""The ground under the graph: a per-user value, and the pitch its grid is drawn at."""

import pytest

from dplanner.modules.project_editor.grid import (
    BACKGROUNDS,
    MIN_SCREEN_PITCH,
    Ground,
    pitch_for,
)
from dplanner.modules.project_editor.positions import GRID


def test_the_ground_round_trips_through_json_and_forgives_junk():
    ground = Ground().with_background("lines").with_snap(False)
    assert Ground.from_json(ground.to_json()) == ground
    assert Ground.from_json(None) == Ground()
    assert Ground.from_json({"background": "plaid", "snap": 0}) == Ground(snap=False)
    with pytest.raises(KeyError):
        Ground().with_background("plaid")


def test_the_default_ground_is_dots_with_snapping_on():
    assert Ground() == Ground(background="dots", snap=True)
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
