"""Tests for grid geometry and the explosion cascade."""

from __future__ import annotations

import pytest

from supercritical.board import Board, IllegalMoveError


def seed(board: Board, cells: dict[tuple[int, int], tuple[int, int]]) -> None:
    """Force a board into a known state.

    Parameters
    ----------
    board : Board
        Board to overwrite.
    cells : dict
        Mapping of coordinate to ``(count, owner)``.
    """
    for (row, col), (count, owner) in cells.items():
        board.cells[row][col].count = count
        board.cells[row][col].owner = owner


@pytest.mark.parametrize("rows,cols", [(3, 3), (9, 6), (20, 10)])
def test_critical_mass_by_position(rows: int, cols: int) -> None:
    board = Board(rows, cols)
    assert board.critical_mass(0, 0) == 2
    assert board.critical_mass(rows - 1, cols - 1) == 2
    assert board.critical_mass(0, 1) == 3
    assert board.critical_mass(1, 0) == 3
    assert board.critical_mass(1, 1) == 4


def test_single_explosion_drains_source_and_converts_neighbours() -> None:
    board = Board(3, 3)
    seed(board, {(0, 0): (1, 1), (0, 1): (1, 2), (1, 0): (1, 2)})
    placement = board.place(0, 0, 1)

    assert len(placement.steps) == 1
    assert board.cells[0][0].count == 0
    assert board.cells[0][0].owner is None
    assert board.cells[0][1].owner == 1
    assert board.cells[0][1].count == 2
    assert board.cells[1][0].owner == 1
    assert board.cells[1][0].count == 2


def test_multi_wave_cascade_matches_hand_computed_result() -> None:
    board = Board(3, 3)
    seed(board, {(0, 0): (1, 1), (0, 1): (2, 1)})
    placement = board.place(0, 1, 1)

    assert len(placement.steps) == 2
    expected = {(0, 0): 0, (0, 1): 1, (0, 2): 1, (1, 0): 1, (1, 1): 1}
    for (row, col), count in expected.items():
        assert board.cells[row][col].count == count, (row, col)
    assert board.total_orbs() == 4
    assert board.is_settled()


def test_cascade_conserves_orbs() -> None:
    board = Board(5, 4)
    total = 0
    for player, (row, col) in [
        (1, (0, 0)),
        (2, (4, 3)),
        (1, (0, 0)),
        (2, (4, 3)),
        (1, (1, 1)),
        (2, (3, 2)),
        (1, (1, 1)),
        (2, (3, 2)),
        (1, (1, 1)),
        (2, (3, 2)),
        (1, (2, 1)),
        (2, (2, 2)),
    ]:
        board.place(row, col, player)
        total += 1
        assert board.total_orbs() == total


def test_transit_snapshot_holds_orbs_in_flight() -> None:
    board = Board(3, 3)
    seed(board, {(1, 1): (3, 1)})
    placement = board.place(1, 1, 1)
    step = placement.steps[0]

    assert step.before.at(1, 1).count == 4
    assert step.transit.at(1, 1).count == 0
    assert step.after.at(0, 1).count == 1
    in_flight = sum(cell.count for row in step.transit.cells for cell in row)
    assert in_flight + len(step.explosions[0].targets) == board.total_orbs()


def test_illegal_moves_are_rejected() -> None:
    board = Board(3, 3)
    board.place(1, 1, 1)

    assert not board.is_legal(1, 1, 2)
    assert not board.is_legal(-1, 0, 1)
    assert not board.is_legal(0, 3, 1)
    with pytest.raises(IllegalMoveError):
        board.place(1, 1, 2)
    with pytest.raises(IllegalMoveError):
        board.place(9, 9, 1)


def test_legal_moves_excludes_enemy_cells() -> None:
    board = Board(2, 3)
    board.place(0, 0, 1)
    moves = board.legal_moves(2)

    assert (0, 0) not in moves
    assert len(moves) == 5
    assert (0, 0) in board.legal_moves(1)


def test_saturated_single_owner_board_hits_the_step_ceiling() -> None:
    board = Board(2, 2)
    seed(board, {(0, 0): (1, 1), (0, 1): (1, 1), (1, 0): (1, 1), (1, 1): (1, 1)})
    placement = board.place(1, 1, 1, max_steps=25)

    assert placement.truncated
    assert len(placement.steps) == 25


def test_settle_check_aborts_the_cascade_immediately() -> None:
    board = Board(2, 2)
    seed(board, {(0, 0): (1, 1), (0, 1): (1, 1), (1, 0): (1, 1), (1, 1): (1, 1)})
    placement = board.place(1, 1, 1, on_settle_check=lambda _: True, max_steps=25)

    assert not placement.truncated
    assert len(placement.steps) == 1


def test_snapshot_is_independent_of_later_mutation() -> None:
    board = Board(3, 3)
    board.place(1, 1, 1)
    snap = board.snapshot()
    board.place(1, 1, 1)

    assert snap.at(1, 1).count == 1
    assert board.cells[1][1].count == 2

    board.restore(snap)
    assert board.cells[1][1].count == 1


def test_tiny_boards_are_rejected() -> None:
    with pytest.raises(ValueError):
        Board(1, 5)
