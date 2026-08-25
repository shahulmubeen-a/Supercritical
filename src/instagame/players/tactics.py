"""Shared building blocks for heuristic players.

Everything here is read-only with respect to the live board: simulation takes a
snapshot, mutates, reads the result, and restores.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..board import Board

SIM_MAX_STEPS = 400
SATURATED_MAX_STEPS = 4


def single_owner(board: Board) -> bool:
    """Return whether at most one player holds orbs.

    Used to stop a simulated cascade that would otherwise run forever on a
    board owned outright by one player.

    Parameters
    ----------
    board : Board
        Board being simulated.

    Returns
    -------
    bool
        True when one player or nobody holds orbs.
    """
    return len(board.counts_by_player()) <= 1


@dataclass(frozen=True)
class Outcome:
    """What a candidate move would produce.

    Attributes
    ----------
    waves : int
        Cascade waves the move sets off.
    orbs : dict of int to int
        Orb totals per player once the board settles.
    cells : dict of int to int
        Cell counts per player once the board settles.
    armed : dict of int to int
        Cells per player sitting exactly one orb below critical mass.
    """

    waves: int
    orbs: dict[int, int]
    cells: dict[int, int]
    armed: dict[int, int]

    def orbs_of(self, player: int) -> int:
        """Return one player's orb total.

        Parameters
        ----------
        player : int
            Player id.

        Returns
        -------
        int
            Orb count, zero when absent.
        """
        return self.orbs.get(player, 0)

    def enemy_orbs(self, player: int) -> int:
        """Return the combined orb total of everyone else.

        Parameters
        ----------
        player : int
            Player id to exclude.

        Returns
        -------
        int
            Sum of every other player's orbs.
        """
        return sum(n for pid, n in self.orbs.items() if pid != player)

    def best_enemy(self, player: int) -> int:
        """Return the largest orb total held by an opponent.

        Parameters
        ----------
        player : int
            Player id to exclude.

        Returns
        -------
        int
            Leading opponent's orb count, zero when none remain.
        """
        rivals = [n for pid, n in self.orbs.items() if pid != player]
        return max(rivals) if rivals else 0


def simulate(board: Board, row: int, col: int, player: int) -> Outcome:
    """Play a move on a copy of the board and report the settled result.

    Parameters
    ----------
    board : Board
        Live board. Restored before returning.
    row : int
        Candidate row.
    col : int
        Candidate column.
    player : int
        Player making the move.

    Returns
    -------
    Outcome
        The settled position the move would produce.
    """
    # A cascade can only run forever when the board holds more orbs than it can
    # stably carry. Orbs are conserved, so that is decidable up front, and it is
    # the only case worth capping. Aborting whenever a single player leads would
    # truncate ordinary cascades and hand every simulating strategy a wrong
    # answer.
    saturated = board.total_orbs() + 1 > board.stable_capacity()
    snapshot = board.snapshot()
    try:
        waves = board.apply_unrecorded(
            row,
            col,
            player,
            max_steps=SATURATED_MAX_STEPS if saturated else SIM_MAX_STEPS,
        )
        orbs: dict[int, int] = {}
        cells: dict[int, int] = {}
        armed: dict[int, int] = {}
        for r, c, cell in board.iter_cells():
            if cell.owner is None or not cell.count:
                continue
            orbs[cell.owner] = orbs.get(cell.owner, 0) + cell.count
            cells[cell.owner] = cells.get(cell.owner, 0) + 1
            if cell.count == board.critical_mass(r, c) - 1:
                armed[cell.owner] = armed.get(cell.owner, 0) + 1
        return Outcome(waves=waves, orbs=orbs, cells=cells, armed=armed)
    finally:
        board.restore(snapshot)


def enemy_orbs_adjacent(board: Board, row: int, col: int, player: int) -> int:
    """Count opponent orbs sitting on the cells a blast here would reach.

    Parameters
    ----------
    board : Board
        Current board.
    row : int
        Candidate row.
    col : int
        Candidate column.
    player : int
        Player making the move.

    Returns
    -------
    int
        Total opponent orbs adjacent to the cell.
    """
    total = 0
    for nr, nc in board.neighbours(row, col):
        neighbour = board.cells[nr][nc]
        if neighbour.owner is not None and neighbour.owner != player:
            total += neighbour.count
    return total


def threat_level(board: Board, row: int, col: int, player: int) -> int:
    """Count adjacent opponent cells that are one orb from critical.

    Each one can detonate next turn and capture this cell.

    Parameters
    ----------
    board : Board
        Current board.
    row : int
        Candidate row.
    col : int
        Candidate column.
    player : int
        Player making the move.

    Returns
    -------
    int
        Number of opponent cells poised to explode into this one.
    """
    threats = 0
    for nr, nc in board.neighbours(row, col):
        neighbour = board.cells[nr][nc]
        if neighbour.owner is None or neighbour.owner == player:
            continue
        if neighbour.count + 1 >= board.critical_mass(nr, nc):
            threats += 1
    return threats


def friendly_neighbours(board: Board, row: int, col: int, player: int) -> int:
    """Count adjacent cells the player already owns.

    Parameters
    ----------
    board : Board
        Current board.
    row : int
        Candidate row.
    col : int
        Candidate column.
    player : int
        Player making the move.

    Returns
    -------
    int
        Number of adjacent owned cells.
    """
    return sum(
        1
        for nr, nc in board.neighbours(row, col)
        if board.cells[nr][nc].owner == player and board.cells[nr][nc].count
    )


def would_explode(board: Board, row: int, col: int) -> bool:
    """Return whether placing here would immediately detonate the cell.

    Parameters
    ----------
    board : Board
        Current board.
    row : int
        Candidate row.
    col : int
        Candidate column.

    Returns
    -------
    bool
        True when the cell reaches critical mass.
    """
    return board.cells[row][col].count + 1 >= board.critical_mass(row, col)
