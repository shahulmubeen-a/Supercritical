"""Pygame front end: board drawing, animation playback and the debug panel."""

from __future__ import annotations

import math
from dataclasses import dataclass

import pygame

from .animation import (
    PHASE_CASCADE,
    PHASE_PLACE,
    Animator,
    Phase,
    ease_in_out_cubic,
    ease_out_back,
)
from .board import BoardSnapshot
from .game import Game
from .logging_config import get_logger

logger = get_logger("render")

PANEL_WIDTH = 300
MARGIN = 24
MAX_BOARD_PIXELS = (1080, 900)
MIN_CELL, MAX_CELL = 18, 74
FPS = 60

COLOR_BG = (16, 16, 22)
COLOR_PANEL = (24, 24, 32)
COLOR_GRID = (46, 46, 60)
COLOR_TEXT = (226, 226, 236)
COLOR_MUTED = (128, 128, 146)
COLOR_BUTTON = (44, 44, 58)
COLOR_BUTTON_ON = (86, 86, 116)
COLOR_ILLEGAL = (220, 64, 64)

PLAYER_COLORS: tuple[tuple[int, int, int], ...] = (
    (232, 72, 85),
    (58, 154, 240),
    (58, 208, 132),
    (244, 194, 62),
    (176, 112, 240),
    (250, 140, 60),
)

TRAIL_GHOSTS = 7
TRAIL_SPACING = 0.055
ALPHA_QUANTUM = 8


def player_color(player_id: int) -> tuple[int, int, int]:
    """Return the display colour for a seat.

    Parameters
    ----------
    player_id : int
        Seat id.

    Returns
    -------
    tuple of int
        RGB colour.
    """
    return PLAYER_COLORS[player_id % len(PLAYER_COLORS)]


@dataclass
class Button:
    """A clickable region in the side panel.

    Attributes
    ----------
    rect : pygame.Rect
        Screen area.
    action : str
        Action name dispatched on click.
    value : int or None
        Optional payload, such as a player id.
    """

    rect: pygame.Rect
    action: str
    value: int | None = None


class GameApp:
    """Interactive viewer for a match.

    Parameters
    ----------
    game : Game
        The match to drive. Must not have started.
    move_delay : float, optional
        Seconds of pause between bot turns, by default 0.35.
    anim_speed : float, optional
        Animation speed multiplier, by default 1.0.
    animate : bool, optional
        When False moves snap to their settled board, by default True.
    motion_blur : bool, optional
        Draw trailing ghosts behind flying orbs, by default True.
    debug : bool, optional
        Show the per-player takeover panel, by default True.
    """

    def __init__(
        self,
        game: Game,
        move_delay: float = 0.35,
        anim_speed: float = 1.0,
        animate: bool = True,
        motion_blur: bool = True,
        debug: bool = True,
    ) -> None:
        self.game = game
        self.move_delay = move_delay
        self.motion_blur = motion_blur
        self.debug = debug
        self.animator = Animator(speed=anim_speed, enabled=animate)
        self.animator.final_board = game.board.snapshot()

        self.auto_play = True
        self.armed_player: int | None = None
        self.pending_step = False
        self.illegal_flash = 0.0
        self.illegal_cell: tuple[int, int] | None = None
        self.time_since_move = 0.0
        self.clock_time = 0.0
        self.buttons: list[Button] = []
        self.running = False

        self.cell = self._compute_cell_size()
        self.board_w = self.cell * game.board.cols
        self.board_h = self.cell * game.board.rows
        width = self.board_w + PANEL_WIDTH + MARGIN * 3
        height = max(self.board_h + MARGIN * 2, 480)
        self.board_origin = (MARGIN, (height - self.board_h) // 2)

        pygame.init()
        pygame.display.set_caption("InstaGame")
        self.screen = pygame.display.set_mode((width, height))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 24)
        self.font_small = pygame.font.Font(None, 20)
        self.font_big = pygame.font.Font(None, 34)
        self._orb_cache: dict[tuple, pygame.Surface] = {}

    def _compute_cell_size(self) -> int:
        """Pick a cell size that fits the board on screen.

        Returns
        -------
        int
            Cell edge length in pixels.
        """
        by_width = MAX_BOARD_PIXELS[0] // self.game.board.cols
        by_height = MAX_BOARD_PIXELS[1] // self.game.board.rows
        return max(MIN_CELL, min(MAX_CELL, by_width, by_height))

    def run(self) -> int | None:
        """Run the main loop until the window closes.

        Returns
        -------
        int or None
            Winning player id, or None if the window closed first.
        """
        self.running = True
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            self.clock_time += dt
            self._handle_events()
            self._advance(dt)
            self._draw()
            pygame.display.flip()
        pygame.quit()
        return self.game.winner

    def _advance(self, dt: float) -> None:
        """Advance animation and, when idle, the match itself.

        Parameters
        ----------
        dt : float
            Seconds since the previous frame.
        """
        if self.illegal_flash > 0.0:
            self.illegal_flash = max(0.0, self.illegal_flash - dt)
        if self.animator.busy:
            self.animator.update(dt)
            return
        if self.game.over:
            return
        self.time_since_move += dt
        wants_move = self.pending_step or (
            self.auto_play and self.time_since_move >= self.move_delay
        )
        if not wants_move:
            return
        self.pending_step = False
        self.time_since_move = 0.0
        try:
            result = self.game.step()
        except RuntimeError as exc:
            logger.warning("turn skipped: %s", exc)
            return
        self.animator.load(result.placement)

    def _handle_events(self) -> None:
        """Drain the pygame event queue."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                self._handle_key(event.key)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self._handle_click(event.pos)

    def _handle_key(self, key: int) -> None:
        """Act on a key press.

        Parameters
        ----------
        key : int
            Pygame key constant.
        """
        if key in (pygame.K_ESCAPE, pygame.K_q):
            self.running = False
        elif key == pygame.K_SPACE:
            self.auto_play = not self.auto_play
        elif key == pygame.K_s:
            self.pending_step = True
        elif key == pygame.K_RETURN:
            self.animator.skip()

    def _handle_click(self, pos: tuple[int, int]) -> None:
        """Route a left click to a panel button or the board.

        Parameters
        ----------
        pos : tuple of int
            Mouse position.
        """
        for button in self.buttons:
            if button.rect.collidepoint(pos):
                self._dispatch(button)
                return
        cell = self._cell_at(pos)
        if cell is not None:
            self._debug_place(*cell)

    def _dispatch(self, button: Button) -> None:
        """Apply a panel button action.

        Parameters
        ----------
        button : Button
            The button clicked.
        """
        if button.action == "toggle_play":
            self.auto_play = not self.auto_play
        elif button.action == "step":
            self.pending_step = True
        elif button.action == "skip":
            self.animator.skip()
        elif button.action == "arm":
            if self.armed_player == button.value:
                self.armed_player = None
            else:
                self.armed_player = button.value
                self.auto_play = False

    def _cell_at(self, pos: tuple[int, int]) -> tuple[int, int] | None:
        """Convert a screen position to a board coordinate.

        Parameters
        ----------
        pos : tuple of int
            Mouse position.

        Returns
        -------
        tuple of int or None
            Row and column, or None when the click missed the board.
        """
        ox, oy = self.board_origin
        col = (pos[0] - ox) // self.cell
        row = (pos[1] - oy) // self.cell
        if 0 <= row < self.game.board.rows and 0 <= col < self.game.board.cols:
            return int(row), int(col)
        return None

    def _debug_place(self, row: int, col: int) -> None:
        """Place an orb for the armed player, if the click is valid.

        Goes through :meth:`Game.apply_move`, the same path a bot move takes.

        Parameters
        ----------
        row : int
            Row index.
        col : int
            Column index.
        """
        if not self.debug or self.armed_player is None:
            return
        if self.animator.busy or self.game.over:
            return
        if self.armed_player in self.game.eliminated:
            self._flash(row, col)
            return
        if not self.game.board.is_legal(row, col, self.armed_player):
            self._flash(row, col)
            return
        result = self.game.apply_move(row, col, self.armed_player)
        self.animator.load(result.placement)
        self.time_since_move = 0.0

    def _flash(self, row: int, col: int) -> None:
        """Mark a cell as an illegal click for a moment.

        Parameters
        ----------
        row : int
            Row index.
        col : int
            Column index.
        """
        self.illegal_cell = (row, col)
        self.illegal_flash = 0.35

    def _cell_center(self, row: int, col: int) -> tuple[float, float]:
        """Return the pixel centre of a cell.

        Parameters
        ----------
        row : int
            Row index.
        col : int
            Column index.

        Returns
        -------
        tuple of float
            Pixel coordinates.
        """
        ox, oy = self.board_origin
        return ox + (col + 0.5) * self.cell, oy + (row + 0.5) * self.cell

    def _orb_sprite(self, color: tuple[int, int, int], radius: int, alpha: int) -> pygame.Surface:
        """Return a cached orb sprite with a soft halo.

        Parameters
        ----------
        color : tuple of int
            RGB colour.
        radius : int
            Core radius in pixels.
        alpha : int
            Opacity, quantised internally to keep the cache small.

        Returns
        -------
        pygame.Surface
            The sprite, blit centred on the orb position.
        """
        radius = max(2, int(radius))
        alpha = max(0, min(255, (int(alpha) // ALPHA_QUANTUM) * ALPHA_QUANTUM))
        key = (color, radius, alpha)
        cached = self._orb_cache.get(key)
        if cached is not None:
            return cached
        pad = max(3, radius)
        size = radius * 2 + pad * 2
        surf = pygame.Surface((size, size), pygame.SRCALPHA)
        centre = (size // 2, size // 2)
        pygame.draw.circle(surf, (*color, alpha // 6), centre, radius + pad)
        pygame.draw.circle(surf, (*color, alpha // 3), centre, radius + pad // 2)
        pygame.draw.circle(surf, (*color, alpha), centre, radius)
        highlight = max(1, radius // 3)
        pygame.draw.circle(
            surf,
            (255, 255, 255, alpha // 3),
            (centre[0] - radius // 3, centre[1] - radius // 3),
            highlight,
        )
        self._orb_cache[key] = surf
        return surf

    def _blit_orb(
        self,
        center: tuple[float, float],
        color: tuple[int, int, int],
        radius: float,
        alpha: int = 255,
    ) -> None:
        """Draw one orb centred on a point.

        Parameters
        ----------
        center : tuple of float
            Pixel centre.
        color : tuple of int
            RGB colour.
        radius : float
            Core radius.
        alpha : int, optional
            Opacity, by default 255.
        """
        sprite = self._orb_sprite(color, int(radius), alpha)
        self.screen.blit(sprite, sprite.get_rect(center=(int(center[0]), int(center[1]))))

    def _orb_offsets(self, count: int, spread: float, phase: float) -> list[tuple[float, float]]:
        """Return orb positions within a cell, as offsets from its centre.

        A single orb sits centred; two or more sit on a slowly rotating ring,
        which also handles the transient counts above four that a cascade wave
        can leave behind.

        Parameters
        ----------
        count : int
            Number of orbs.
        spread : float
            Ring radius in pixels.
        phase : float
            Rotation angle in radians.

        Returns
        -------
        list of tuple of float
            Offsets in pixels.
        """
        if count <= 0:
            return []
        if count == 1:
            return [(0.0, 0.0)]
        step = 2.0 * math.pi / count
        return [
            (spread * math.cos(phase + i * step), spread * math.sin(phase + i * step))
            for i in range(count)
        ]

    def _draw(self) -> None:
        """Render one frame."""
        self.screen.fill(COLOR_BG)
        self.buttons = []
        snapshot = self.animator.display_board or self.game.board.snapshot()
        phase = self.animator.current
        t = self.animator.progress
        self._draw_grid(snapshot, phase, t)
        if phase is not None and phase.kind == PHASE_CASCADE:
            self._draw_shockwaves(phase, t)
            self._draw_flights(phase, t)
        self._draw_panel()

    def _draw_grid(self, snapshot: BoardSnapshot, phase: Phase | None, t: float) -> None:
        """Draw cells, tints and settled orbs.

        Parameters
        ----------
        snapshot : BoardSnapshot
            Board state to draw.
        phase : Phase or None
            Active animation phase, used for the placement pop.
        t : float
            Progress through that phase.
        """
        ox, oy = self.board_origin
        spread = self.cell * 0.20
        radius = self.cell * 0.155
        rotation = self.clock_time * 0.9
        focus = phase.focus if phase is not None and phase.kind == PHASE_PLACE else None

        for row in range(snapshot.rows):
            for col in range(snapshot.cols):
                rect = pygame.Rect(ox + col * self.cell, oy + row * self.cell, self.cell, self.cell)
                cell = snapshot.at(row, col)
                if cell.owner is not None and cell.count:
                    tint = pygame.Surface((self.cell, self.cell), pygame.SRCALPHA)
                    tint.fill((*player_color(cell.owner), 26))
                    self.screen.blit(tint, rect.topleft)
                pygame.draw.rect(self.screen, COLOR_GRID, rect, 1)

                mass = self._critical_mass(snapshot, row, col)
                if cell.count and cell.count == mass - 1:
                    self._draw_pulse(rect, cell.owner)

                if not cell.count or cell.owner is None:
                    continue
                pop = 1.0
                if focus == (row, col):
                    pop = 0.4 + 0.6 * ease_out_back(t)
                centre = self._cell_center(row, col)
                for dx, dy in self._orb_offsets(cell.count, spread, rotation):
                    self._blit_orb(
                        (centre[0] + dx, centre[1] + dy),
                        player_color(cell.owner),
                        radius * pop,
                    )

        if self.illegal_flash > 0.0 and self.illegal_cell is not None:
            row, col = self.illegal_cell
            alpha = int(200 * (self.illegal_flash / 0.35))
            overlay = pygame.Surface((self.cell, self.cell), pygame.SRCALPHA)
            pygame.draw.rect(
                overlay, (*COLOR_ILLEGAL, alpha), overlay.get_rect(), max(2, self.cell // 14)
            )
            self.screen.blit(overlay, (ox + col * self.cell, oy + row * self.cell))

        if self.armed_player is not None:
            pygame.draw.rect(
                self.screen,
                player_color(self.armed_player),
                pygame.Rect(ox - 3, oy - 3, self.board_w + 6, self.board_h + 6),
                2,
            )

    @staticmethod
    def _critical_mass(snapshot: BoardSnapshot, row: int, col: int) -> int:
        """Return a cell's critical mass from snapshot geometry.

        Parameters
        ----------
        snapshot : BoardSnapshot
            Board state, used only for its dimensions.
        row : int
            Row index.
        col : int
            Column index.

        Returns
        -------
        int
            Number of orthogonal neighbours.
        """
        mass = 4
        if row in (0, snapshot.rows - 1):
            mass -= 1
        if col in (0, snapshot.cols - 1):
            mass -= 1
        return mass

    def _draw_pulse(self, rect: pygame.Rect, owner: int | None) -> None:
        """Draw the breathing ring on a cell one orb from critical.

        Parameters
        ----------
        rect : pygame.Rect
            Cell rectangle.
        owner : int or None
            Cell owner.
        """
        if owner is None:
            return
        wave = 0.5 + 0.5 * math.sin(self.clock_time * 4.0)
        alpha = int(30 + 45 * wave)
        overlay = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.circle(
            overlay,
            (*player_color(owner), alpha),
            (rect.width // 2, rect.height // 2),
            int(rect.width * (0.34 + 0.05 * wave)),
            max(1, rect.width // 22),
        )
        self.screen.blit(overlay, rect.topleft)

    def _draw_shockwaves(self, phase: Phase, t: float) -> None:
        """Draw expanding rings at every detonating cell.

        Parameters
        ----------
        phase : Phase
            Active cascade phase.
        t : float
            Progress through the phase.
        """
        if phase.player is None:
            return
        color = player_color(phase.player)
        alpha = int(150 * (1.0 - t))
        if alpha <= 0:
            return
        radius = int(self.cell * (0.15 + 0.8 * ease_in_out_cubic(t)))
        size = radius * 2 + 4
        ring = pygame.Surface((size, size), pygame.SRCALPHA)
        pygame.draw.circle(
            ring, (*color, alpha), (size // 2, size // 2), radius, max(1, self.cell // 20)
        )
        for row, col in phase.sources:
            centre = self._cell_center(row, col)
            self.screen.blit(ring, ring.get_rect(center=(int(centre[0]), int(centre[1]))))

    def _draw_flights(self, phase: Phase, t: float) -> None:
        """Draw in-flight orbs with cubic easing and a motion blur trail.

        Parameters
        ----------
        phase : Phase
            Active cascade phase.
        t : float
            Raw progress through the phase.
        """
        radius = self.cell * 0.155
        ghosts = TRAIL_GHOSTS if self.motion_blur else 0
        for flight in phase.flights:
            color = player_color(flight.player)
            src = self._cell_center(*flight.src)
            dst = self._cell_center(*flight.dst)
            for ghost in range(ghosts, 0, -1):
                gt = t - ghost * TRAIL_SPACING
                if gt <= 0.0:
                    continue
                fade = 1.0 - ghost / (ghosts + 1)
                self._blit_orb(
                    self._lerp(src, dst, ease_in_out_cubic(gt)),
                    color,
                    radius * (0.45 + 0.5 * fade),
                    int(150 * fade**1.6),
                )
            self._blit_orb(self._lerp(src, dst, ease_in_out_cubic(t)), color, radius)

    @staticmethod
    def _lerp(a: tuple[float, float], b: tuple[float, float], t: float) -> tuple[float, float]:
        """Linearly interpolate between two points.

        Parameters
        ----------
        a : tuple of float
            Start point.
        b : tuple of float
            End point.
        t : float
            Interpolation factor.

        Returns
        -------
        tuple of float
            The interpolated point.
        """
        return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t

    def _draw_panel(self) -> None:
        """Draw the side panel: scores, controls and the debug takeover."""
        x = self.board_w + MARGIN * 2
        panel = pygame.Rect(x, MARGIN, PANEL_WIDTH, self.screen.get_height() - MARGIN * 2)
        pygame.draw.rect(self.screen, COLOR_PANEL, panel, border_radius=8)

        y = panel.top + 16
        self.screen.blit(self.font_big.render("InstaGame", True, COLOR_TEXT), (x + 16, y))
        y += 38
        status = f"turn {self.game.turn_number}"
        if self.game.over:
            status = "game over"
        elif not self.auto_play:
            status += "  (paused)"
        self.screen.blit(self.font_small.render(status, True, COLOR_MUTED), (x + 16, y))
        y += 28

        counts = self.game.board.counts_by_player()
        current = self.game.current_player().player_id if not self.game.over else None
        for player in self.game.players:
            y = self._draw_player_row(x, y, player, counts, current)

        y += 8
        y = self._draw_controls(x, y)

        if self.game.over:
            y += 10
            if self.game.winner is None:
                text = "draw"
                color = COLOR_MUTED
            else:
                text = f"{self.game.player_by_id(self.game.winner).name} wins"
                color = player_color(self.game.winner)
            self.screen.blit(self.font.render(text, True, color), (x + 16, y))

        hints = ["space  pause / resume", "s  single step", "enter  skip animation", "esc  quit"]
        hy = panel.bottom - 18 * len(hints) - 12
        for hint in hints:
            self.screen.blit(self.font_small.render(hint, True, COLOR_MUTED), (x + 16, hy))
            hy += 18

    def _draw_player_row(
        self,
        x: int,
        y: int,
        player,
        counts: dict[int, int],
        current: int | None,
    ) -> int:
        """Draw one seat's status line and, in debug mode, its arm button.

        Parameters
        ----------
        x : int
            Panel left edge.
        y : int
            Row top.
        player : Player
            The seat to draw.
        counts : dict of int to int
            Orb totals by player id.
        current : int or None
            Player id whose turn it is.

        Returns
        -------
        int
            The next free y coordinate.
        """
        pid = player.player_id
        out = pid in self.game.eliminated
        color = player_color(pid)
        row = pygame.Rect(x + 12, y, PANEL_WIDTH - 24, 34)
        if pid == current:
            pygame.draw.rect(self.screen, (*color, 255), row, 1, border_radius=6)
        pygame.draw.circle(self.screen, COLOR_MUTED if out else color, (x + 30, y + 17), 7)
        label = f"{player.name}"
        text_color = COLOR_MUTED if out else COLOR_TEXT
        self.screen.blit(self.font.render(label, True, text_color), (x + 46, y + 8))
        score = "OUT" if out else str(counts.get(pid, 0))
        surf = self.font.render(score, True, text_color)
        score_x = row.right - 12 - surf.get_width()
        if self.debug:
            score_x -= 62
        self.screen.blit(surf, (score_x, y + 8))
        if self.debug:
            armed = self.armed_player == pid
            btn = pygame.Rect(row.right - 58, y + 5, 52, 24)
            pygame.draw.rect(
                self.screen,
                COLOR_BUTTON_ON if armed else COLOR_BUTTON,
                btn,
                border_radius=5,
            )
            caption = "armed" if armed else "arm"
            cap = self.font_small.render(caption, True, color if armed else COLOR_TEXT)
            self.screen.blit(cap, cap.get_rect(center=btn.center))
            self.buttons.append(Button(btn, "arm", pid))
        return y + 38

    def _draw_controls(self, x: int, y: int) -> int:
        """Draw the pause, step and skip buttons.

        Parameters
        ----------
        x : int
            Panel left edge.
        y : int
            Row top.

        Returns
        -------
        int
            The next free y coordinate.
        """
        specs = [
            ("pause" if self.auto_play else "resume", "toggle_play"),
            ("step", "step"),
            ("skip", "skip"),
        ]
        width = (PANEL_WIDTH - 24 - 16) // 3
        for index, (caption, action) in enumerate(specs):
            btn = pygame.Rect(x + 12 + index * (width + 8), y, width, 28)
            pygame.draw.rect(self.screen, COLOR_BUTTON, btn, border_radius=5)
            cap = self.font_small.render(caption, True, COLOR_TEXT)
            self.screen.blit(cap, cap.get_rect(center=btn.center))
            self.buttons.append(Button(btn, action))
        return y + 34
