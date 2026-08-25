"""Tests for turn sequencing, elimination and win detection."""

from __future__ import annotations

import random

import pytest

from supercritical.board import Board
from supercritical.game import Game
from supercritical.players import build_player
from supercritical.players.base import Player


class ScriptedPlayer(Player):
    """Plays a fixed list of moves, then repeats the last one.

    Parameters
    ----------
    player_id : int
        Seat id.
    moves : list of tuple of int
        Moves to return in order.
    name : str, optional
        Display name.
    """

    def __init__(self, player_id: int, moves: list[tuple[int, int]], name: str = "scripted"):
        super().__init__(player_id, name)
        self.moves = list(moves)
        self.index = 0

    def choose_move(self, board: Board) -> tuple[int, int]:
        move = self.moves[min(self.index, len(self.moves) - 1)]
        self.index += 1
        return move


class SettledSpy(Player):
    """Asserts the board handed to it is always settled.

    Parameters
    ----------
    player_id : int
        Seat id.
    rng : random.Random
        Randomness source.
    """

    def __init__(self, player_id: int, rng: random.Random):
        super().__init__(player_id, f"spy-{player_id}")
        self.rng = rng
        self.calls = 0

    def choose_move(self, board: Board) -> tuple[int, int]:
        assert board.is_settled(), "player was asked to move on an unsettled board"
        self.calls += 1
        return self.rng.choice(board.legal_moves(self.player_id))


def make_game(rows: int = 4, cols: int = 4, kinds=("random", "random"), seed: int = 0) -> Game:
    """Build a small match for testing.

    Parameters
    ----------
    rows : int, optional
        Board height.
    cols : int, optional
        Board width.
    kinds : tuple of str, optional
        Player types.
    seed : int, optional
        RNG seed.

    Returns
    -------
    Game
        The new match.
    """
    rng = random.Random(seed)
    players = [
        build_player(kind, index, rng=random.Random(seed + index))
        for index, kind in enumerate(kinds)
    ]
    return Game(Board(rows, cols), players, rng=rng)


def test_players_are_never_asked_to_move_on_an_unsettled_board() -> None:
    rng = random.Random(3)
    spies = [SettledSpy(0, rng), SettledSpy(1, rng), SettledSpy(2, rng)]
    game = Game(Board(5, 4), spies, rng=rng)
    for _ in range(120):
        if game.over:
            break
        game.step()
    assert sum(spy.calls for spy in spies) > 20


def test_turns_are_strictly_sequential() -> None:
    game = make_game(kinds=("random", "random", "random"))
    seen = []
    for _ in range(9):
        if game.over:
            break
        seen.append(game.current_player().player_id)
        game.step()
    assert seen == [0, 1, 2, 0, 1, 2, 0, 1, 2]


def test_no_elimination_before_a_player_has_moved() -> None:
    game = make_game(kinds=("random", "random"))
    game.step()

    assert game.board.counts_by_player().get(1, 0) == 0
    assert 1 not in game.eliminated
    assert not game.over


def test_player_is_eliminated_once_wiped_after_moving() -> None:
    board = Board(3, 3)
    players = [ScriptedPlayer(0, [(0, 0)]), ScriptedPlayer(1, [(0, 1)])]
    game = Game(board, players, rng=random.Random(0))
    game.step()
    game.step()
    game.step()

    assert board.cells[0][1].owner == 0
    assert 1 in game.eliminated
    assert game.over
    assert game.winner == 0


def test_sole_survivor_ends_the_game_and_bounds_the_cascade() -> None:
    board = Board(2, 2)
    for (row, col), (count, owner) in {
        (0, 0): (1, 1),
        (0, 1): (1, 0),
        (1, 0): (1, 0),
        (1, 1): (1, 0),
    }.items():
        board.cells[row][col].count = count
        board.cells[row][col].owner = owner
    players = [ScriptedPlayer(0, [(0, 1)]), ScriptedPlayer(1, [(0, 0)])]
    game = Game(board, players, rng=random.Random(0))
    game.moves_made = {0: 1, 1: 1}

    result = game.apply_move(0, 1, 0)

    assert len(result.placement.steps) == 1
    assert not result.placement.truncated
    assert game.over
    assert game.winner == 0
    assert 1 in game.eliminated


def test_illegal_player_move_falls_back_to_a_random_legal_move() -> None:
    board = Board(3, 3)
    board.cells[0][0].count = 1
    board.cells[0][0].owner = 1
    players = [ScriptedPlayer(0, [(0, 0)]), ScriptedPlayer(1, [(2, 2)])]
    game = Game(board, players, illegal_retries=1, rng=random.Random(0))

    result = game.step()

    assert result.used_fallback
    assert board.is_legal(result.placement.row, result.placement.col, 0)
    assert result.placement.player == 0


def test_debug_move_uses_the_same_path_and_does_not_rotate_the_turn() -> None:
    game = make_game(kinds=("random", "random"))
    assert game.current_player().player_id == 0

    game.apply_move(1, 1, 1)

    assert game.current_player().player_id == 0
    assert game.board.cells[1][1].owner == 1
    assert game.moves_made[1] == 1


def test_step_refuses_an_unsettled_board() -> None:
    game = make_game()
    game.board.cells[0][0].count = 5
    game.board.cells[0][0].owner = 0
    with pytest.raises(RuntimeError):
        game.step()


def test_duplicate_ids_and_lone_player_are_rejected() -> None:
    board = Board(3, 3)
    with pytest.raises(ValueError):
        Game(board, [build_player("random", 0)])
    with pytest.raises(ValueError):
        Game(board, [build_player("random", 0), build_player("random", 0)])


@pytest.mark.parametrize("seed", range(12))
def test_matches_always_terminate_with_exactly_one_winner(seed: int) -> None:
    game = make_game(rows=6, cols=5, kinds=("random", "greedy", "random", "greedy"), seed=seed)
    turns = 0
    while not game.over and turns < 4000:
        game.step()
        turns += 1

    assert game.over
    assert game.winner is not None
    assert len(game.active_players()) == 1
