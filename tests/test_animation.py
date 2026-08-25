"""Tests for the animation timeline."""

from __future__ import annotations

from itertools import pairwise

import pytest

from supercritical.animation import PHASE_CASCADE, PHASE_PLACE, Animator, ease_in_out_cubic
from supercritical.board import Board


@pytest.mark.parametrize(
    "value,expected", [(-1.0, 0.0), (0.0, 0.0), (0.5, 0.5), (1.0, 1.0), (2.0, 1.0)]
)
def test_easing_endpoints_and_clamping(value: float, expected: float) -> None:
    assert ease_in_out_cubic(value) == pytest.approx(expected)


def test_easing_is_monotonic() -> None:
    samples = [ease_in_out_cubic(i / 40) for i in range(41)]
    assert all(b >= a for a, b in pairwise(samples))


def test_quiet_move_produces_a_single_place_phase() -> None:
    board = Board(4, 4)
    animator = Animator()
    animator.load(board.place(1, 1, 0))

    assert [phase.kind for phase in animator.phases] == [PHASE_PLACE]
    assert animator.busy


def test_cascade_produces_one_phase_per_wave_with_matching_flights() -> None:
    board = Board(3, 3)
    board.cells[0][0].count = 1
    board.cells[0][0].owner = 0
    board.cells[0][1].count = 2
    board.cells[0][1].owner = 0
    animator = Animator()
    placement = board.place(0, 1, 0)
    animator.load(placement)

    cascades = [phase for phase in animator.phases if phase.kind == PHASE_CASCADE]
    assert len(cascades) == len(placement.steps) == 2
    assert len(cascades[0].flights) == 3
    assert len(cascades[1].flights) == 2
    assert all(flight.player == 0 for phase in cascades for flight in phase.flights)


def test_timeline_drains_and_lands_on_the_settled_board() -> None:
    board = Board(3, 3)
    board.cells[0][1].count = 2
    board.cells[0][1].owner = 0
    animator = Animator(place_duration=0.1, step_duration=0.2)
    animator.load(board.place(0, 1, 0))

    for _ in range(200):
        animator.update(1 / 60)
    assert not animator.busy
    assert animator.display_board is animator.final_board
    assert animator.display_board.at(0, 1).count == 0


def test_disabled_animator_jumps_straight_to_the_result() -> None:
    board = Board(3, 3)
    animator = Animator(enabled=False)
    animator.load(board.place(1, 1, 0))

    assert not animator.busy
    assert animator.display_board.at(1, 1).count == 1


def test_skip_discards_pending_phases() -> None:
    board = Board(3, 3)
    animator = Animator()
    animator.load(board.place(1, 1, 0))
    animator.skip()

    assert not animator.busy
