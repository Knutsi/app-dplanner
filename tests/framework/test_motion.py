"""The motion library: easings that start and end where they say, a spring that arrives, a
breeze that stays in bounds, particles that age out, and a clock that runs only while its
surface is seen — and can be stepped by hand, which is how every test here sets the time."""

import math

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QWidget

from dplanner.framework.motion.clock import MAX_STEP_S, FrameClock
from dplanner.framework.motion.curves import (
    Spring,
    Tween,
    breeze,
    cubic,
    in_out_cubic,
    in_out_sine,
    linear,
    out_back,
    out_cubic,
    out_quint,
    smoothstep,
    span,
)
from dplanner.framework.motion.draw import paint_particles, petal, star, tapered
from dplanner.framework.motion.particles import Particle, Particles

EASINGS = (linear, in_out_sine, out_cubic, in_out_cubic, out_quint, out_back, smoothstep)


@pytest.mark.parametrize("ease", EASINGS, ids=lambda ease: ease.__name__)
def test_every_easing_starts_at_nought_and_ends_at_one(ease):
    assert ease(0.0) == pytest.approx(0.0, abs=1e-9)
    assert ease(1.0) == pytest.approx(1.0, abs=1e-9)


def test_out_back_goes_past_the_mark_before_it_settles():
    assert max(out_back(p / 100) for p in range(101)) > 1.05


def test_a_tween_waits_its_delay_then_eases_to_its_end():
    tween = Tween(10.0, 20.0, duration=2.0, delay=1.0)
    assert tween.at(0.5) == 10.0
    assert 10.0 < tween.at(2.0) < 20.0
    assert tween.at(3.0) == 20.0 and tween.done(3.0) and not tween.done(2.9)
    assert span(5.0, 5.0, 0.0) == 1.0  # A zero-length span is over the moment it starts.


def test_a_critically_damped_spring_arrives_without_overshooting():
    spring = Spring(0.0, 100.0)
    furthest = 0.0
    for _ in range(120):
        furthest = max(furthest, spring.step(1 / 60))
    assert spring.settled(0.5)
    assert furthest <= 100.0 + 1e-6


def test_a_long_frame_does_not_throw_a_spring_past_its_target():
    spring = Spring(0.0, 1.0)
    spring.step(1.0)  # One enormous step, taken in small slices.
    assert 0.9 < spring.value <= 1.0 + 1e-6


def test_the_breeze_stays_between_minus_one_and_one_and_neighbours_agree():
    gusts = [breeze(t / 10, x) for t in range(300) for x in (0, 500, 1000)]
    assert all(-1.0 <= gust <= 1.0 for gust in gusts)
    assert abs(breeze(3.0, 100.0) - breeze(3.0, 104.0)) < 0.1


def test_a_bezier_runs_from_its_first_point_to_its_last():
    points = ((0.0, 0.0), (1.0, 5.0), (3.0, 5.0), (4.0, 0.0))
    assert cubic(*points, 0.0) == points[0]
    assert cubic(*points, 1.0) == points[3]
    assert cubic(*points, 0.5)[1] > 0


def test_particles_fall_age_out_and_land():
    system = Particles(capacity=3)
    for number in range(5):
        system.emit(Particle(0.0, 0.0, vy=0.0, life=1.0 + number))
    assert len(system) == 3  # The oldest went first.
    system.step(0.5, gravity=100.0)
    assert all(item.y > 0 for item in system.items)
    system.step(10.0, floor=5.0)
    assert len(system) == 0


def test_a_particle_fades_in_quickly_and_out_slowly():
    item = Particle(0.0, 0.0, life=1.0)
    item.age = 0.05
    early = item.fade
    item.age = 0.5
    middle = item.fade
    item.age = 1.0
    assert early > 0 and middle > 0.2 and item.fade == 0.0


def test_the_shapes_are_closed_and_drawn(app):
    assert not star(QPointF(10, 10), 6).isEmpty()
    assert not petal(QPointF(10, 10), 12, 6, -math.pi / 2).isEmpty()
    assert not tapered([(0, 0), (0, 10), (2, 20)], 3, 1).isEmpty()
    assert tapered([(0, 0)], 3, 1).isEmpty()
    image = QImage(40, 40, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    paint_particles(
        painter,
        [Particle(20, 20, age=0.2, size=4, shape=shape) for shape in ("dot", "spark", "petal")],
        {0: QColor(255, 255, 255, 255)},
    )
    painter.end()
    assert any(image.pixelColor(x, y).alpha() for x in range(40) for y in range(40))


def test_a_clock_hands_its_listeners_the_time_since_the_last_tick(app):
    clock = FrameClock()
    heard: list[float] = []
    clock.ticked.connect(heard.append)
    clock.step(0.016)
    frames = clock._frames
    frames.updateCurrentTime(16)
    frames.updateCurrentTime(5000)  # A laptop lid: one short step, never a leap.
    assert heard == [0.016, 0.016, MAX_STEP_S]
    clock.deleteLater()


def test_a_followed_clock_runs_only_while_its_widget_is_shown(app):
    widget = QWidget()
    clock = FrameClock(widget)
    clock.follow(widget)
    assert not clock.running()
    widget.show()
    assert clock.running()
    widget.hide()
    assert not clock.running()
    widget.deleteLater()
