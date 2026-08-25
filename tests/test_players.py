"""Tests for the bot players and the player registry."""

from __future__ import annotations

import random

import pytest

from supercritical.board import Board
from supercritical.players import PLAYER_TYPES, build_player
from supercritical.players.greedy_player import GreedyPlayer

OFFLINE_TYPES = sorted(PLAYER_TYPES)


def random_board(rng: random.Random, rows: int = 6, cols: int = 5) -> Board:
    """Build a settled board with orbs scattered across three owners.

    Parameters
    ----------
    rng : random.Random
        Randomness source.
    rows : int, optional
        Board height.
    cols : int, optional
        Board width.

    Returns
    -------
    Board
        A settled board.
    """
    board = Board(rows, cols)
    for row in range(rows):
        for col in range(cols):
            if rng.random() < 0.45:
                mass = board.critical_mass(row, col)
                board.cells[row][col].count = rng.randint(1, mass - 1)
                board.cells[row][col].owner = rng.choice([0, 1, 2])
    return board


@pytest.mark.parametrize("kind", OFFLINE_TYPES)
@pytest.mark.parametrize("seed", range(15))
def test_bots_always_return_a_legal_move(kind: str, seed: int) -> None:
    rng = random.Random(seed)
    board = random_board(rng)
    player = build_player(kind, 0, rng=random.Random(seed))
    row, col = player.choose_move(board)

    assert board.is_legal(row, col, 0)


def test_build_player_rejects_unknown_types() -> None:
    with pytest.raises(KeyError):
        build_player("nonesuch", 0)


def test_the_removed_model_backend_is_no_longer_registered() -> None:
    """Guards the Ollama removal: the seat type and its module are both gone."""
    assert "ollama" not in PLAYER_TYPES
    with pytest.raises(ImportError):
        import supercritical.ollama  # noqa: F401


def test_greedy_prefers_a_capture_over_an_empty_corner() -> None:
    board = Board(4, 4)
    board.cells[0][0].count = 1
    board.cells[0][0].owner = 0
    board.cells[0][1].count = 2
    board.cells[0][1].owner = 1
    greedy = GreedyPlayer(0, rng=random.Random(0))

    capture = greedy.score_move(board, 0, 0)
    quiet = greedy.score_move(board, 3, 3)

    assert capture > quiet


def test_greedy_avoids_sitting_next_to_a_loaded_enemy() -> None:
    board = Board(5, 5)
    board.cells[2][2].count = 3
    board.cells[2][2].owner = 1
    greedy = GreedyPlayer(0, rng=random.Random(0))

    exposed = greedy.score_move(board, 2, 3)
    safe = greedy.score_move(board, 4, 4)

    assert exposed < safe


def test_greedy_beats_random_over_a_series() -> None:
    from supercritical.game import Game

    rng = random.Random(11)
    wins = {"greedy": 0, "random": 0}
    for match in range(24):
        board = Board(6, 5)
        players = [
            build_player("greedy", 0, name="greedy", rng=random.Random(match)),
            build_player("random", 1, name="random", rng=random.Random(match + 500)),
        ]
        game = Game(board, players, rng=rng)
        turns = 0
        while not game.over and turns < 3000:
            game.step()
            turns += 1
        if game.winner is not None:
            wins[game.player_by_id(game.winner).name] += 1

    assert wins["greedy"] > wins["random"]
