"""Tests for the heuristic strategy players and their shared tactics."""

from __future__ import annotations

import random

import pytest

from supercritical.board import Board
from supercritical.game import Game
from supercritical.players import STRATEGY_TYPES, build_player, offline_types
from supercritical.players.tactics import (
    enemy_orbs_adjacent,
    friendly_neighbours,
    simulate,
    threat_level,
    would_explode,
)


def busy_board(seed: int = 0, rows: int = 6, cols: int = 5, moves: int = 30) -> Board:
    """Play random moves to reach a realistic mid-game position.

    Parameters
    ----------
    seed : int, optional
        RNG seed.
    rows : int, optional
        Board height.
    cols : int, optional
        Board width.
    moves : int, optional
        Number of random placements.

    Returns
    -------
    Board
        A settled board with four players present.
    """
    rng = random.Random(seed)
    board = Board(rows, cols)
    for i in range(moves):
        player = i % 4
        options = board.legal_moves(player)
        if not options:
            break
        board.apply_unrecorded(*rng.choice(options), player, max_steps=400)
    return board


def test_sixteen_strategies_are_registered() -> None:
    assert len(STRATEGY_TYPES) == 16
    assert len(set(STRATEGY_TYPES)) == 16


def test_every_strategy_has_a_distinct_class() -> None:
    assert len({cls.__name__ for cls in STRATEGY_TYPES.values()}) == 16


@pytest.mark.parametrize("kind", sorted(STRATEGY_TYPES))
@pytest.mark.parametrize("seed", range(6))
def test_strategies_always_return_a_legal_move(kind: str, seed: int) -> None:
    board = busy_board(seed)
    bot = build_player(kind, 0, rng=random.Random(seed))
    row, col = bot.choose_move(board)

    assert board.is_legal(row, col, 0)


@pytest.mark.parametrize("kind", sorted(STRATEGY_TYPES))
def test_strategies_do_not_mutate_the_board(kind: str) -> None:
    board = busy_board(2)
    before = [(c.count, c.owner) for _, _, c in board.iter_cells()]
    build_player(kind, 0, rng=random.Random(0)).choose_move(board)
    after = [(c.count, c.owner) for _, _, c in board.iter_cells()]

    assert before == after


@pytest.mark.parametrize("kind", sorted(STRATEGY_TYPES))
def test_strategies_work_on_a_fresh_board(kind: str) -> None:
    board = Board(5, 4)
    row, col = build_player(kind, 0, rng=random.Random(0)).choose_move(board)

    assert board.is_legal(row, col, 0)


def test_corner_and_center_pull_in_opposite_directions() -> None:
    board = Board(6, 5)
    corner = build_player("corner", 0, rng=random.Random(0)).choose_move(board)
    center = build_player("center", 0, rng=random.Random(0)).choose_move(board)

    assert board.critical_mass(*corner) == 2
    assert board.critical_mass(*center) == 4


def test_detonator_explodes_when_it_can() -> None:
    board = Board(5, 4)
    board.cells[0][0].count = 1
    board.cells[0][0].owner = 0
    row, col = build_player("detonator", 0, rng=random.Random(0)).choose_move(board)

    assert (row, col) == (0, 0)


def test_loader_refuses_to_tip_a_cell_over() -> None:
    board = Board(5, 4)
    board.cells[0][0].count = 1
    board.cells[0][0].owner = 0
    row, col = build_player("loader", 0, rng=random.Random(0)).choose_move(board)

    assert (row, col) != (0, 0)
    assert not would_explode(board, row, col)


def test_aggressor_detonates_onto_the_biggest_enemy_stack() -> None:
    board = Board(6, 5)
    board.cells[2][2].count = 3
    board.cells[2][2].owner = 0
    board.cells[2][3].count = 3
    board.cells[2][3].owner = 1
    board.cells[5][0].count = 1
    board.cells[5][0].owner = 0
    row, col = build_player("aggressor", 0, rng=random.Random(0)).choose_move(board)

    assert (row, col) == (2, 2)


def test_cautious_avoids_a_loaded_enemy_neighbour() -> None:
    board = Board(6, 5)
    board.cells[2][2].count = 3
    board.cells[2][2].owner = 1
    bot = build_player("cautious", 0, rng=random.Random(0))
    row, col = bot.choose_move(board)

    assert threat_level(board, row, col, 0) == 0


def test_hunter_targets_the_weakest_opponent() -> None:
    board = Board(6, 5)
    board.cells[0][1].count = 1
    board.cells[0][1].owner = 1
    for cell in (board.cells[4][4], board.cells[4][3], board.cells[3][4]):
        cell.count, cell.owner = 2, 2
    bot = build_player("hunter", 0, rng=random.Random(0))
    bot.begin_turn(board)

    assert bot.quarry == 1


def test_mirror_reflects_the_last_opponent_move() -> None:
    board = Board(5, 4)
    bot = build_player("mirror", 0, rng=random.Random(0))
    bot.begin_turn(board)
    board.cells[0][0].count = 1
    board.cells[0][0].owner = 1
    bot.begin_turn(board)

    assert bot.target == (4, 3)
    assert bot.choose_move(board) == (4, 3)


def test_simulate_leaves_the_board_untouched() -> None:
    board = busy_board(4)
    before = [(c.count, c.owner) for _, _, c in board.iter_cells()]
    outcome = simulate(board, *board.legal_moves(0)[0], 0)
    after = [(c.count, c.owner) for _, _, c in board.iter_cells()]

    assert before == after
    assert outcome.waves >= 0
    assert sum(outcome.orbs.values()) == board.total_orbs() + 1


def test_simulate_reports_the_cascade_it_would_cause() -> None:
    board = Board(3, 3)
    board.cells[0][0].count = 1
    board.cells[0][0].owner = 0
    board.cells[0][1].count = 2
    board.cells[0][1].owner = 0
    outcome = simulate(board, 0, 1, 0)

    assert outcome.waves == 2
    assert outcome.orbs_of(0) == 4
    assert outcome.enemy_orbs(0) == 0


def test_simulation_terminates_on_a_board_one_player_owns() -> None:
    board = Board(2, 2)
    for cell in (board.cells[0][0], board.cells[0][1], board.cells[1][0], board.cells[1][1]):
        cell.count, cell.owner = 1, 0
    outcome = simulate(board, 0, 0, 0)

    assert outcome.waves >= 1
    assert board.total_orbs() == 4


def test_tactics_helpers_read_the_neighbourhood() -> None:
    board = Board(4, 4)
    board.cells[1][1].count = 2
    board.cells[1][1].owner = 0
    board.cells[1][2].count = 3
    board.cells[1][2].owner = 1

    assert enemy_orbs_adjacent(board, 1, 1, 0) == 3
    assert threat_level(board, 1, 1, 0) == 1
    assert friendly_neighbours(board, 1, 2, 0) == 1
    assert would_explode(board, 1, 2) is True


@pytest.mark.parametrize("kind", sorted(STRATEGY_TYPES))
def test_each_strategy_can_finish_a_match(kind: str) -> None:
    players = [
        build_player(kind, 0, rng=random.Random(1)),
        build_player("random", 1, rng=random.Random(2)),
    ]
    game = Game(Board(4, 3), players, rng=random.Random(3))
    turns = 0
    while not game.over and turns < 2000:
        game.step()
        turns += 1

    assert game.over
    assert game.winner is not None


def test_offline_types_excludes_model_players() -> None:
    kinds = offline_types()

    assert len(kinds) == len(STRATEGY_TYPES) + 2
    assert {"random", "greedy"} <= set(kinds)


def test_loader_fires_when_the_blast_is_worth_taking() -> None:
    board = Board(6, 5)
    board.cells[0][0].count = 1
    board.cells[0][0].owner = 0
    board.cells[0][1].count = 2
    board.cells[0][1].owner = 1
    row, col = build_player("loader", 0, rng=random.Random(0)).choose_move(board)

    assert (row, col) == (0, 0)


def test_loader_fires_rather_than_lose_a_primed_cell() -> None:
    board = Board(6, 5)
    board.cells[2][2].count = 3
    board.cells[2][2].owner = 0
    board.cells[2][3].count = 3
    board.cells[2][3].owner = 1
    bot = build_player("loader", 0, rng=random.Random(0))

    assert threat_level(board, 2, 2, 0) == 1
    assert bot.choose_move(board) == (2, 2)


def test_loader_will_not_waste_a_primed_cell_on_nothing() -> None:
    board = Board(6, 5)
    board.cells[0][0].count = 1
    board.cells[0][0].owner = 0
    row, col = build_player("loader", 0, rng=random.Random(0)).choose_move(board)

    assert (row, col) != (0, 0)
    assert not would_explode(board, row, col)


def test_loader_arms_cells_that_point_at_the_enemy() -> None:
    """Between two interior cells, prefer the one whose blast would land."""
    board = Board(7, 6)
    board.cells[3][3].count = 2
    board.cells[3][3].owner = 1
    bot = build_player("loader", 0, rng=random.Random(0))
    aimed = bot.score(board, 3, 2)
    idle = bot.score(board, 1, 1)

    assert board.critical_mass(3, 2) == board.critical_mass(1, 1)
    assert aimed > idle


def test_every_player_declares_a_search_tier() -> None:
    from supercritical.players import PLAYER_TYPES, offline_types, types_in_tier

    positional = types_in_tier("positional")
    simulating = types_in_tier("simulating")

    assert set(positional) | set(simulating) == set(offline_types())
    assert not set(positional) & set(simulating)
    assert len(simulating) == 6
    assert PLAYER_TYPES["random"].tier == "positional"
    assert PLAYER_TYPES["retaliator"].tier == "simulating"


def test_positional_strategies_never_simulate(monkeypatch) -> None:
    """A positional player must not reach for the simulation helper."""
    import supercritical.players.strategies as strategies
    from supercritical.players import types_in_tier

    def forbidden(*args, **kwargs):
        raise AssertionError("positional strategy called simulate()")

    monkeypatch.setattr(strategies, "simulate", forbidden)
    board = busy_board(5)
    for kind in types_in_tier("positional"):
        bot = build_player(kind, 0, rng=random.Random(0))
        row, col = bot.choose_move(board)
        assert board.is_legal(row, col, 0), kind
