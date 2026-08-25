"""Smoke test driving the pygame front end against a dummy video driver."""

from __future__ import annotations

import os
import random
import time

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

pygame = pytest.importorskip("pygame")

from instagame.board import Board  # noqa: E402
from instagame.game import Game  # noqa: E402
from instagame.players import build_player  # noqa: E402
from instagame.players.base import Player  # noqa: E402
from instagame.render import GameApp  # noqa: E402


@pytest.fixture
def app():
    """Build an app on a small board with a dummy display.

    Yields
    ------
    GameApp
        The app under test.
    """
    rng = random.Random(5)
    players = [build_player(k, i, rng=random.Random(i)) for i, k in enumerate(["greedy"] * 4)]
    game = Game(Board(6, 5), players, rng=rng)
    instance = GameApp(game, move_delay=0.0, anim_speed=6.0, threaded=False)
    yield instance
    pygame.quit()


def test_frames_render_without_error(app: GameApp) -> None:
    for _ in range(400):
        app._advance(1 / 60)
        app._draw()
    assert app.game.turn_number > 10


def test_debug_arm_pauses_and_places_for_the_chosen_player(app: GameApp) -> None:
    app._draw()
    arm_buttons = [b for b in app.buttons if b.action == "arm"]
    assert len(arm_buttons) == 4

    app._dispatch(arm_buttons[2])
    assert app.armed_player == 2
    assert app.auto_play is False

    app._debug_place(3, 3)
    assert app.game.board.cells[3][3].owner == 2
    assert app.game.moves_made[2] == 1
    assert app.game.current_player().player_id == 0

    app._dispatch(arm_buttons[2])
    assert app.armed_player is None


def test_illegal_debug_click_flashes_and_changes_nothing(app: GameApp) -> None:
    app._draw()
    arm = [b for b in app.buttons if b.action == "arm"]
    app._dispatch(arm[0])
    app._debug_place(1, 1)
    while app.animator.busy:
        app.animator.update(1 / 30)

    app._dispatch(arm[0])
    app._dispatch(arm[1])
    app._debug_place(1, 1)

    assert app.game.board.cells[1][1].owner == 0
    assert app.illegal_flash > 0.0


def test_click_routing_maps_pixels_back_to_cells(app: GameApp) -> None:
    centre = app._cell_center(2, 3)
    assert app._cell_at((int(centre[0]), int(centre[1]))) == (2, 3)
    assert app._cell_at((5, 5)) is None


def test_control_buttons_toggle_playback(app: GameApp) -> None:
    app._draw()
    controls = {b.action: b for b in app.buttons if b.action != "arm"}
    app._dispatch(controls["toggle_play"])
    assert app.auto_play is False
    app._dispatch(controls["step"])
    assert app.pending_step is True
    app._advance(1 / 60)
    assert app.game.turn_number == 1


class SlowPlayer(Player):
    """Blocks briefly before answering, standing in for a model call.

    Parameters
    ----------
    player_id : int
        Seat id.
    delay : float, optional
        Seconds to sleep inside ``choose_move``.
    """

    def __init__(self, player_id: int, delay: float = 0.15) -> None:
        super().__init__(player_id, f"slow-{player_id}")
        self.delay = delay

    def choose_move(self, board):
        time.sleep(self.delay)
        return board.legal_moves(self.player_id)[0]


def test_threaded_mode_keeps_drawing_while_a_player_thinks() -> None:
    game = Game(Board(5, 4), [SlowPlayer(0), SlowPlayer(1)], rng=random.Random(0))
    app = GameApp(game, move_delay=0.0, threaded=True)
    try:
        frames_while_thinking = 0
        deadline = time.monotonic() + 10.0
        while game.turn_number < 2 and time.monotonic() < deadline:
            app._advance(1 / 60)
            app._draw()
            if app.thinking is not None:
                frames_while_thinking += 1

        assert game.turn_number >= 2
        assert frames_while_thinking > 5
        assert "slow-" in app.status
    finally:
        app.running = False
        if app.executor is not None:
            app.executor.shutdown(wait=True, cancel_futures=True)
        pygame.quit()


def test_status_line_is_clipped_to_the_available_space(app: GameApp) -> None:
    app.status = "a very long status line " * 10
    assert app._draw_status(0, 100, limit=100) == 100
    assert app._draw_status(0, 100, limit=10_000) > 100
