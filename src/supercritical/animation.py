"""Timeline that turns a settled move into something watchable.

The engine resolves a move instantly. This module slices that result into
timed phases so the renderer can show orbs flying between cells with cubic
easing rather than snapping to the final board.
"""

from __future__ import annotations

from dataclasses import dataclass

from .board import BoardSnapshot, Placement

PHASE_PLACE = "place"
PHASE_CASCADE = "cascade"


def ease_in_out_cubic(t: float) -> float:
    """Cubic ease-in-out interpolation.

    Slow at both ends, fast through the middle, which also makes the motion
    blur trail bunch up on arrival and stretch out mid-flight for free.

    Parameters
    ----------
    t : float
        Normalised progress, clamped to ``[0, 1]``.

    Returns
    -------
    float
        Eased progress in ``[0, 1]``.
    """
    t = min(1.0, max(0.0, t))
    if t < 0.5:
        return 4.0 * t * t * t
    return 1.0 - ((-2.0 * t + 2.0) ** 3) / 2.0


def ease_out_back(t: float, overshoot: float = 1.9) -> float:
    """Ease-out with a small overshoot, used for the placement pop.

    Parameters
    ----------
    t : float
        Normalised progress, clamped to ``[0, 1]``.
    overshoot : float, optional
        Strength of the overshoot, by default 1.9.

    Returns
    -------
    float
        Eased progress, which may briefly exceed 1.
    """
    t = min(1.0, max(0.0, t))
    c3 = overshoot + 1.0
    return 1.0 + c3 * (t - 1.0) ** 3 + overshoot * (t - 1.0) ** 2


@dataclass(frozen=True)
class OrbFlight:
    """A single orb travelling from one cell to a neighbour.

    Attributes
    ----------
    src : tuple of int
        Source coordinate.
    dst : tuple of int
        Destination coordinate.
    player : int
        Owner of the orb in flight.
    """

    src: tuple[int, int]
    dst: tuple[int, int]
    player: int


@dataclass(frozen=True)
class Phase:
    """One timed slice of a move.

    Attributes
    ----------
    kind : str
        Either ``PHASE_PLACE`` or ``PHASE_CASCADE``.
    duration : float
        Length in seconds.
    board : BoardSnapshot
        Static board drawn underneath. For a cascade phase this is the transit
        snapshot, with sources already drained and targets not yet credited.
    flights : tuple of OrbFlight
        Orbs in motion during this phase.
    sources : tuple of tuple of int
        Cells detonating, used for the shockwave rings.
    focus : tuple of int or None
        Cell being placed on, used for the placement pop.
    player : int or None
        Player the phase belongs to.
    """

    kind: str
    duration: float
    board: BoardSnapshot
    flights: tuple[OrbFlight, ...] = ()
    sources: tuple[tuple[int, int], ...] = ()
    focus: tuple[int, int] | None = None
    player: int | None = None


class Animator:
    """Plays a placement out as a sequence of phases.

    Parameters
    ----------
    place_duration : float, optional
        Seconds for the placement pop, by default 0.12.
    step_duration : float, optional
        Seconds per cascade wave, by default 0.22.
    speed : float, optional
        Multiplier applied to every duration; higher is faster, by default 1.0.
    enabled : bool, optional
        When False every phase is zero length and the board jumps to its final
        state, by default True.
    """

    def __init__(
        self,
        place_duration: float = 0.12,
        step_duration: float = 0.22,
        speed: float = 1.0,
        enabled: bool = True,
    ) -> None:
        self.place_duration = place_duration
        self.step_duration = step_duration
        self.speed = max(0.05, speed)
        self.enabled = enabled
        self.phases: list[Phase] = []
        self.index = 0
        self.elapsed = 0.0
        self.final_board: BoardSnapshot | None = None

    @property
    def busy(self) -> bool:
        """Return whether phases are still playing.

        Returns
        -------
        bool
            True while a phase remains.
        """
        return self.index < len(self.phases)

    @property
    def current(self) -> Phase | None:
        """Return the phase being played.

        Returns
        -------
        Phase or None
            The active phase, or None when idle.
        """
        if not self.busy:
            return None
        return self.phases[self.index]

    @property
    def progress(self) -> float:
        """Return raw progress through the active phase.

        Returns
        -------
        float
            Value in ``[0, 1]``; 1.0 when idle.
        """
        phase = self.current
        if phase is None or phase.duration <= 0.0:
            return 1.0
        return min(1.0, self.elapsed / phase.duration)

    @property
    def display_board(self) -> BoardSnapshot | None:
        """Return the snapshot the renderer should draw right now.

        Returns
        -------
        BoardSnapshot or None
            The active phase's static board, else the settled board.
        """
        phase = self.current
        if phase is not None:
            return phase.board
        return self.final_board

    def load(self, placement: Placement) -> None:
        """Queue the phases for one move, replacing anything still playing.

        Parameters
        ----------
        placement : Placement
            The engine result to animate.
        """
        self.phases = list(self._build_phases(placement))
        self.index = 0
        self.elapsed = 0.0
        self.final_board = placement.steps[-1].after if placement.steps else placement.initial
        if not self.enabled:
            self.index = len(self.phases)

    def skip(self) -> None:
        """Jump straight to the settled board, discarding pending phases."""
        self.index = len(self.phases)
        self.elapsed = 0.0

    def update(self, dt: float) -> None:
        """Advance the timeline.

        Parameters
        ----------
        dt : float
            Seconds elapsed since the previous frame.
        """
        if not self.busy:
            return
        self.elapsed += dt
        while self.busy and self.elapsed >= self.phases[self.index].duration:
            self.elapsed -= self.phases[self.index].duration
            self.index += 1

    def _build_phases(self, placement: Placement):
        """Yield the phases making up one move.

        Parameters
        ----------
        placement : Placement
            The engine result to slice up.

        Yields
        ------
        Phase
            Phases in playback order.
        """
        yield Phase(
            kind=PHASE_PLACE,
            duration=self.place_duration / self.speed,
            board=placement.initial,
            focus=(placement.row, placement.col),
            player=placement.player,
        )
        for step in placement.steps:
            flights = tuple(
                OrbFlight(src=(explosion.row, explosion.col), dst=target, player=explosion.player)
                for explosion in step.explosions
                for target in explosion.targets
            )
            yield Phase(
                kind=PHASE_CASCADE,
                duration=self.step_duration / self.speed,
                board=step.transit,
                flights=flights,
                sources=tuple((e.row, e.col) for e in step.explosions),
                player=placement.player,
            )
