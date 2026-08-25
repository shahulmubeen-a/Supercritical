"""Tests for recording matches and building the standalone viewer page."""

from __future__ import annotations

import json
import random
import re

import pytest

from instagame.board import Board
from instagame.game import Game
from instagame.players import build_player
from instagame.replay import EMPTY_OWNER, REPLAY_VERSION, Recorder, encode_grid
from instagame.viewer import build_page, write_page


@pytest.fixture
def played_game() -> tuple[Game, Recorder]:
    """Play a short bot match and return the game with its recording.

    Returns
    -------
    tuple of (Game, Recorder)
        The finished game and its recorder.
    """
    rng = random.Random(3)
    players = [build_player(k, i, rng=random.Random(i)) for i, k in enumerate(["greedy", "random"])]
    game = Game(Board(4, 3), players, rng=rng)
    recorder = Recorder(game)
    turns = 0
    while not game.over and turns < 500:
        recorder.record(game.step())
        turns += 1
    return game, recorder


def test_encode_grid_marks_empty_cells() -> None:
    board = Board(2, 2)
    board.cells[0][1].count = 3
    board.cells[0][1].owner = 2
    grid = encode_grid(board.snapshot())

    assert len(grid) == 4
    assert grid[0] == [0, EMPTY_OWNER]
    assert grid[1] == [3, 2]


def test_recorded_turn_carries_placement_and_cascade(played_game) -> None:
    _, recorder = played_game
    turn = recorder.turns[0]

    assert set(turn) == {
        "player",
        "row",
        "col",
        "fallback",
        "initial",
        "steps",
        "eliminated",
        "winner",
    }
    assert len(turn["initial"]) == 4 * 3
    for step in turn["steps"]:
        assert len(step["transit"]) == 4 * 3
        assert len(step["after"]) == 4 * 3
        for explosion in step["explosions"]:
            assert 1 <= len(explosion["t"]) <= 4


def test_replay_dict_describes_the_whole_match(played_game) -> None:
    game, recorder = played_game
    data = recorder.to_dict()

    assert data["version"] == REPLAY_VERSION
    assert data["board"] == {"rows": 4, "cols": 3}
    assert [p["id"] for p in data["players"]] == [0, 1]
    assert len(data["turns"]) == game.turn_number
    assert data["winner"] == game.winner
    assert "stats" not in data


def test_written_json_round_trips(played_game, tmp_path) -> None:
    _, recorder = played_game
    path = recorder.write_json(tmp_path / "nested" / "m.json")
    loaded = json.loads(path.read_text())

    assert loaded == recorder.to_dict()


def test_page_embeds_the_replay_and_title(played_game) -> None:
    _, recorder = played_game
    page = build_page(recorder.to_dict(), title="My Match")

    assert "__REPLAY_DATA__" not in page
    assert "__TITLE__" not in page
    assert "<title>My Match</title>" in page
    assert '"version":2' in page


def test_page_escapes_a_title_that_looks_like_markup(played_game) -> None:
    _, recorder = played_game
    page = build_page(recorder.to_dict(), title='<img src=x onerror="boom">')

    assert "<img src=x" not in page
    assert "&lt;img src=x" in page


def test_embedded_payload_cannot_close_the_script_tag() -> None:
    board = Board(3, 3)
    player = build_player("random", 0, name="</script><b>oops</b>", rng=random.Random(0))
    game = Game(board, [player, build_player("random", 1, rng=random.Random(1))])
    page = build_page(Recorder(game).to_dict())

    assert "</script><b>oops" not in page
    assert "<\\/script>" in page


def test_page_is_self_contained(played_game, tmp_path) -> None:
    _, recorder = played_game
    path = write_page(recorder.to_dict(), tmp_path / "m.html")
    page = path.read_text()

    assert path.exists()
    remote = re.findall(r'(?:src|href)\s*=\s*["\']https?://[^"\']+', page)
    assert remote == []
