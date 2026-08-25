"""Grid state and the explosion cascade that drives the game.

A cell explodes once it holds as many orbs as it has orthogonal neighbours
(2 in a corner, 3 on an edge, 4 in the interior). Exploding sends exactly one
orb to each neighbour and subtracts the critical mass from the source, so the
total orb count on the board is conserved. Receiving an orb converts the
target cell to the exploding player.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from .logging_config import get_logger

logger = get_logger("board")

DEFAULT_MAX_CASCADE_STEPS = 2000


@dataclass
class Cell:
    """A single grid square.

    Attributes
    ----------
    count : int
        Number of orbs currently held.
    owner : int or None
        Player id owning the orbs, or None when the cell is empty.
    """

    count: int = 0
    owner: int | None = None

    def copy(self) -> Cell:
        """Return an independent copy of this cell.

        Returns
        -------
        Cell
            A new cell with the same count and owner.
        """
        return Cell(self.count, self.owner)


@dataclass(frozen=True)
class BoardSnapshot:
    """An immutable-by-convention capture of the grid at one instant.

    Attributes
    ----------
    rows : int
        Number of rows.
    cols : int
        Number of columns.
    cells : tuple of tuple of Cell
        Row-major copies of every cell. Treat as read-only.
    """

    rows: int
    cols: int
    cells: tuple[tuple[Cell, ...], ...]

    def at(self, row: int, col: int) -> Cell:
        """Return the cell at the given coordinate.

        Parameters
        ----------
        row : int
            Row index.
        col : int
            Column index.

        Returns
        -------
        Cell
            The captured cell.
        """
        return self.cells[row][col]


@dataclass(frozen=True)
class Explosion:
    """One cell detonating during a cascade step.

    Attributes
    ----------
    row : int
        Source row.
    col : int
        Source column.
    player : int
        Player who owned the source at the moment it detonated.
    targets : tuple of tuple of int
        Coordinates each receiving exactly one orb.
    """

    row: int
    col: int
    player: int
    targets: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class CascadeStep:
    """One simultaneous wave of explosions.

    Attributes
    ----------
    explosions : tuple of Explosion
        Every cell that detonated in this wave.
    before : BoardSnapshot
        State at the start of the wave.
    transit : BoardSnapshot
        State with sources drained but targets not yet credited. This is the
        board the renderer draws underneath in-flight orbs.
    after : BoardSnapshot
        State once every orb has landed.
    """

    explosions: tuple[Explosion, ...]
    before: BoardSnapshot
    transit: BoardSnapshot
    after: BoardSnapshot


@dataclass(frozen=True)
class Placement:
    """The full result of one move, including its cascade.

    Attributes
    ----------
    row : int
        Row the orb was placed on.
    col : int
        Column the orb was placed on.
    player : int
        Player who moved.
    initial : BoardSnapshot
        State immediately after the orb was added, before any explosion.
    steps : tuple of CascadeStep
        Cascade waves in order. Empty when the move settled immediately.
    truncated : bool
        True when the cascade was stopped early by the step ceiling.
    """

    row: int
    col: int
    player: int
    initial: BoardSnapshot
    steps: tuple[CascadeStep, ...] = ()
    truncated: bool = False


class IllegalMoveError(ValueError):
    """Raised when a move targets a cell the player may not use."""


class Board:
    """Mutable game grid.

    Parameters
    ----------
    rows : int
        Number of rows (board height).
    cols : int
        Number of columns (board width).
    """

    def __init__(self, rows: int, cols: int) -> None:
        if rows < 2 or cols < 2:
            raise ValueError("board must be at least 2x2")
        self.rows = rows
        self.cols = cols
        self.cells: list[list[Cell]] = [[Cell() for _ in range(cols)] for _ in range(rows)]

    def in_bounds(self, row: int, col: int) -> bool:
        """Return whether a coordinate lies on the board.

        Parameters
        ----------
        row : int
            Row index.
        col : int
            Column index.

        Returns
        -------
        bool
            True when the coordinate is on the board.
        """
        return 0 <= row < self.rows and 0 <= col < self.cols

    def neighbours(self, row: int, col: int) -> list[tuple[int, int]]:
        """Return the orthogonal in-bounds neighbours of a cell.

        Parameters
        ----------
        row : int
            Row index.
        col : int
            Column index.

        Returns
        -------
        list of tuple of int
            Neighbour coordinates, up to four of them.
        """
        candidates = ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1))
        return [(r, c) for r, c in candidates if self.in_bounds(r, c)]

    def critical_mass(self, row: int, col: int) -> int:
        """Return the orb count at which a cell detonates.

        Parameters
        ----------
        row : int
            Row index.
        col : int
            Column index.

        Returns
        -------
        int
            Number of orthogonal neighbours: 2, 3 or 4.
        """
        return len(self.neighbours(row, col))

    def is_legal(self, row: int, col: int, player: int) -> bool:
        """Return whether a player may place on a cell.

        Parameters
        ----------
        row : int
            Row index.
        col : int
            Column index.
        player : int
            Player id.

        Returns
        -------
        bool
            True when the cell is on the board and empty or already owned.
        """
        if not self.in_bounds(row, col):
            return False
        owner = self.cells[row][col].owner
        return owner is None or owner == player

    def legal_moves(self, player: int) -> list[tuple[int, int]]:
        """Return every cell a player may place on.

        Parameters
        ----------
        player : int
            Player id.

        Returns
        -------
        list of tuple of int
            Legal coordinates.
        """
        return [
            (r, c)
            for r in range(self.rows)
            for c in range(self.cols)
            if self.cells[r][c].owner in (None, player)
        ]

    def iter_cells(self) -> Iterator[tuple[int, int, Cell]]:
        """Iterate over every cell with its coordinates.

        Yields
        ------
        tuple of (int, int, Cell)
            Row, column and the cell itself.
        """
        for r in range(self.rows):
            for c in range(self.cols):
                yield r, c, self.cells[r][c]

    def counts_by_player(self) -> dict[int, int]:
        """Return the orb total held by each player currently on the board.

        Returns
        -------
        dict of int to int
            Mapping of player id to orb count. Players with no orbs are absent.
        """
        totals: dict[int, int] = {}
        for _, _, cell in self.iter_cells():
            if cell.owner is not None and cell.count:
                totals[cell.owner] = totals.get(cell.owner, 0) + cell.count
        return totals

    def total_orbs(self) -> int:
        """Return the number of orbs on the board.

        Returns
        -------
        int
            Sum of every cell count.
        """
        return sum(cell.count for _, _, cell in self.iter_cells())

    def is_settled(self) -> bool:
        """Return whether no cell is at or above its critical mass.

        Returns
        -------
        bool
            True when the board holds no unstable cell.
        """
        return not self._unstable_cells()

    def snapshot(self) -> BoardSnapshot:
        """Capture the current grid.

        Returns
        -------
        BoardSnapshot
            A deep copy of every cell.
        """
        return BoardSnapshot(
            rows=self.rows,
            cols=self.cols,
            cells=tuple(tuple(cell.copy() for cell in row) for row in self.cells),
        )

    def restore(self, snapshot: BoardSnapshot) -> None:
        """Overwrite the grid from a snapshot.

        Parameters
        ----------
        snapshot : BoardSnapshot
            State to restore. Must match the board dimensions.
        """
        if snapshot.rows != self.rows or snapshot.cols != self.cols:
            raise ValueError("snapshot dimensions do not match the board")
        self.cells = [[cell.copy() for cell in row] for row in snapshot.cells]

    def place(
        self,
        row: int,
        col: int,
        player: int,
        on_settle_check: Callable[[Board], bool] | None = None,
        max_steps: int = DEFAULT_MAX_CASCADE_STEPS,
    ) -> Placement:
        """Place one orb and resolve the resulting cascade.

        Parameters
        ----------
        row : int
            Row index.
        col : int
            Column index.
        player : int
            Player placing the orb.
        on_settle_check : callable or None, optional
            Evaluated after every cascade wave. Returning True aborts the
            cascade immediately. Used to stop the runaway cascade that occurs
            once a single player owns every orb.
        max_steps : int, optional
            Hard ceiling on cascade waves, a backstop behind ``on_settle_check``.

        Returns
        -------
        Placement
            The move and every cascade wave it produced.

        Raises
        ------
        IllegalMoveError
            If the target cell is off the board or owned by another player.
        """
        if not self.is_legal(row, col, player):
            raise IllegalMoveError(f"player {player} may not place at ({row}, {col})")
        cell = self.cells[row][col]
        cell.count += 1
        cell.owner = player
        initial = self.snapshot()
        steps, truncated = self._resolve(on_settle_check, max_steps)
        return Placement(
            row=row,
            col=col,
            player=player,
            initial=initial,
            steps=tuple(steps),
            truncated=truncated,
        )

    def _unstable_cells(self) -> list[tuple[int, int]]:
        """Return coordinates of every cell at or above critical mass.

        Returns
        -------
        list of tuple of int
            Unstable coordinates in row-major order.
        """
        return [
            (r, c) for r, c, cell in self.iter_cells() if cell.count >= self.critical_mass(r, c)
        ]

    def _resolve(
        self,
        on_settle_check: Callable[[Board], bool] | None,
        max_steps: int,
    ) -> tuple[list[CascadeStep], bool]:
        """Run the cascade to completion, one simultaneous wave at a time.

        Parameters
        ----------
        on_settle_check : callable or None
            Early-abort predicate evaluated after each wave.
        max_steps : int
            Hard ceiling on the number of waves.

        Returns
        -------
        tuple of (list of CascadeStep, bool)
            The waves produced and whether the ceiling truncated the cascade.
        """
        steps: list[CascadeStep] = []
        while True:
            unstable = self._unstable_cells()
            if not unstable:
                return steps, False
            if len(steps) >= max_steps:
                logger.warning(
                    "cascade truncated at %d waves; the sole-survivor check "
                    "should have stopped this first",
                    max_steps,
                )
                return steps, True
            steps.append(self._explode_wave(unstable))
            if on_settle_check is not None and on_settle_check(self):
                return steps, False

    def _explode_wave(self, unstable: list[tuple[int, int]]) -> CascadeStep:
        """Detonate every currently unstable cell once.

        Parameters
        ----------
        unstable : list of tuple of int
            Coordinates to detonate.

        Returns
        -------
        CascadeStep
            The wave, with before, transit and after snapshots.
        """
        before = self.snapshot()
        explosions: list[Explosion] = []
        for r, c in unstable:
            cell = self.cells[r][c]
            owner = cell.owner
            if owner is None:
                continue
            mass = self.critical_mass(r, c)
            cell.count -= mass
            if cell.count == 0:
                cell.owner = None
            explosions.append(
                Explosion(row=r, col=c, player=owner, targets=tuple(self.neighbours(r, c)))
            )
        transit = self.snapshot()
        for explosion in explosions:
            for tr, tc in explosion.targets:
                target = self.cells[tr][tc]
                target.count += 1
                target.owner = explosion.player
        return CascadeStep(
            explosions=tuple(explosions),
            before=before,
            transit=transit,
            after=self.snapshot(),
        )
