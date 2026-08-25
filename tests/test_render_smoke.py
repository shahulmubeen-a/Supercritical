"""Smoke test driving the pygame front end against a dummy video driver."""

from __future__ import annotations

import os
import random

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

pygame = pytest.importorskip("pygame")

from instagame.board import Board  # noqa: E402
from instagame.game import Game  # noqa: E402
from instagame.players import build_player  # noqa: E402
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
    instance = GameApp(game, move_delay=0.0, anim_speed=6.0)
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
