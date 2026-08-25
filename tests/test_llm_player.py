"""Tests for prompt building, response parsing and the Ollama client.

Everything here runs offline against fakes; no model is contacted.
"""

from __future__ import annotations

import random

import pytest

from instagame.board import Board
from instagame.game import Game
from instagame.ollama import (
    Completion,
    OllamaClient,
    OllamaError,
    normalise_host,
    resolve_model_tag,
)
from instagame.players import build_player
from instagame.players.base import Player
from instagame.players.llm_player import (
    MAX_ENUMERATED_MOVES,
    OllamaPlayer,
    build_prompt,
    parse_move,
    player_symbol,
    render_board,
)


class FakeClient:
    """Stands in for OllamaClient and returns canned responses.

    Parameters
    ----------
    responses : list of str
        Response bodies handed out in order; the last repeats.
    error : Exception or None, optional
        Raised instead of responding, by default None.
    """

    def __init__(self, responses: list[str], error: Exception | None = None) -> None:
        self.responses = responses
        self.error = error
        self.calls: list[dict] = []

    def generate(self, **kwargs) -> Completion:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        text = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        return Completion(text=text, latency=0.5, eval_count=12)


def test_symbols_are_stable_and_wrap() -> None:
    assert player_symbol(0) == "R"
    assert player_symbol(1) == "B"
    assert player_symbol(6) == player_symbol(0)


def test_rendered_board_carries_capacity_for_every_cell() -> None:
    board = Board(3, 3)
    board.cells[1][1].count = 2
    board.cells[1][1].owner = 0
    text = render_board(board)
    lines = text.splitlines()

    assert lines[0].split() == ["c0", "c1", "c2"]
    assert lines[1].split() == ["r0", "-/2", "-/3", "-/2"]
    assert lines[2].split() == ["r1", "-/3", "R2/4", "-/3"]


def test_prompt_states_identity_totals_and_legal_moves() -> None:
    board = Board(3, 3)
    board.cells[0][0].count = 1
    board.cells[0][0].owner = 1
    prompt = build_prompt(board, 0)

    assert "You are player R." in prompt
    assert "B=1" in prompt
    assert "(0,0)" not in prompt
    assert "(2,2)" in prompt


def test_prompt_collapses_a_long_move_list() -> None:
    board = Board(20, 10)
    prompt = build_prompt(board, 0)

    assert board.rows * board.cols > MAX_ENUMERATED_MOVES
    assert "200 available" in prompt
    assert "(19,9)" not in prompt


@pytest.mark.parametrize(
    "text,expected",
    [
        ('{"row": 2, "col": 3}', (2, 3, "")),
        ('noise before {"row": 0, "col": 1} noise after', (0, 1, "")),
        ('{"row": 1, "col": 1, "why": "corner grab"}', (1, 1, "corner grab")),
        ('{"row": "4", "col": "5"}', (4, 5, "")),
    ],
)
def test_parse_move_handles_realistic_responses(text: str, expected: tuple) -> None:
    assert parse_move(text) == expected


@pytest.mark.parametrize(
    "text", ["", "no json here", "{broken", '{"row": 1}', '{"row": "x", "col": 1}']
)
def test_parse_move_rejects_unusable_responses(text: str) -> None:
    with pytest.raises(ValueError):
        parse_move(text)


def test_player_returns_the_model_move_and_records_stats() -> None:
    board = Board(4, 4)
    client = FakeClient(['{"row": 2, "col": 2}'])
    player = OllamaPlayer(0, model="fake", client=client)

    assert player.choose_move(board) == (2, 2)
    assert player.calls == 1
    assert player.illegal == 0
    assert player.average_latency == pytest.approx(0.5)
    assert client.calls[0]["model"] == "fake"
    assert client.calls[0]["schema"]["required"] == ["row", "col"]


def test_player_flags_but_still_returns_an_illegal_move() -> None:
    board = Board(4, 4)
    board.cells[1][1].count = 1
    board.cells[1][1].owner = 1
    client = FakeClient(['{"row": 1, "col": 1}'])
    player = OllamaPlayer(0, model="fake", client=client)

    assert player.choose_move(board) == (1, 1)
    assert player.illegal == 1


def test_explain_mode_requests_a_reason() -> None:
    board = Board(4, 4)
    client = FakeClient(['{"row": 0, "col": 0, "why": "cheap corner"}'])
    player = OllamaPlayer(0, model="fake", client=client, explain=True)
    player.choose_move(board)

    assert "why" in client.calls[0]["schema"]["required"]
    assert player.last_reason == "cheap corner"


def test_transport_failure_is_counted_and_propagated() -> None:
    board = Board(4, 4)
    player = OllamaPlayer(0, model="fake", client=FakeClient([], error=OllamaError("down")))

    with pytest.raises(OllamaError):
        player.choose_move(board)
    assert player.errors == 1
    assert player.calls == 0


def test_engine_absorbs_a_model_that_only_returns_illegal_moves() -> None:
    class AlwaysIllegal(Player):
        def choose_move(self, board: Board) -> tuple[int, int]:
            return -1, -1

    board = Board(4, 4)
    players = [AlwaysIllegal(0, "broken"), build_player("greedy", 1, rng=random.Random(0))]
    game = Game(board, players, illegal_retries=1, rng=random.Random(0))
    result = game.step()

    assert result.used_fallback
    assert board.is_legal(result.placement.row, result.placement.col, 0)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("localhost:11434", "http://localhost:11434"),
        ("http://box:1234/", "http://box:1234"),
        ("https://remote:443", "https://remote:443"),
    ],
)
def test_host_normalisation(value: str, expected: str) -> None:
    assert normalise_host(value) == expected


def test_client_drops_the_think_field_for_models_that_reject_it() -> None:
    client = OllamaClient(host="http://x")
    seen: list[dict] = []

    def fake_post(path: str, payload: dict) -> dict:
        seen.append(dict(payload))
        if "think" in payload:
            raise OllamaError('400 from /api/generate: {"error":"think is not supported"}')
        return {"response": '{"row": 1, "col": 1}', "eval_count": 9}

    client._post = fake_post
    client.generate(model="plain", prompt="p")
    client.generate(model="plain", prompt="p")

    assert "think" in seen[0]
    assert "think" not in seen[1]
    assert "think" not in seen[2]
    assert "plain" in client._think_unsupported


def test_client_reraises_errors_unrelated_to_thinking() -> None:
    client = OllamaClient(host="http://x")

    def fake_post(path: str, payload: dict) -> dict:
        raise OllamaError("500 from /api/generate: out of memory")

    client._post = fake_post
    with pytest.raises(OllamaError, match="out of memory"):
        client.generate(model="plain", prompt="p")


@pytest.mark.parametrize(
    "text,expected",
    [
        (
            '{"row": 3, "col": 2, "why": "chain into the blue stack',
            (3, 2, "chain into the blue stack"),
        ),
        ('{\n  "row": 0,\n  "col": 1\n,\n  "why": "corner is chea', (0, 1, "corner is chea")),
        ('{"row": 2, "col": 2', (2, 2, "")),
    ],
)
def test_parse_move_recovers_from_truncated_output(text: str, expected: tuple) -> None:
    assert parse_move(text) == expected


def test_truncated_output_without_coordinates_still_raises() -> None:
    with pytest.raises(ValueError):
        parse_move('{"why": "I was thinking about')


@pytest.mark.parametrize(
    "name,expected",
    [
        ("gemma3:4b", "gemma3:4b"),
        ("phi4-mini", "phi4-mini:latest"),
        ("phi4-mini:latest", "phi4-mini:latest"),
        ("missing", None),
        ("gemma3:1b", None),
    ],
)
def test_bare_model_names_resolve_to_their_latest_tag(name: str, expected: str | None) -> None:
    available = {"gemma3:4b", "phi4-mini:latest", "qwen3.5:4b"}
    assert resolve_model_tag(name, available) == expected
