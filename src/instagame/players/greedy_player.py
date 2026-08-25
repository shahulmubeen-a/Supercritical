"""A one-ply heuristic player.

Scores every legal move on immediate payoff and immediate risk. It does not
simulate the full cascade, so it is beatable, but it plays a recognisable game:
it grabs corners, detonates onto enemy stacks, and avoids parking orbs next to
an enemy cell that is one orb from critical.
"""

from __future__ import annotations

import random

from ..board import Board
from .base import Player

WEIGHT_EXPLODE = 4.0
WEIGHT_CAPTURE = 6.0
WEIGHT_LOW_MASS = 3.0
WEIGHT_DANGER = 8.0
WEIGHT_LOADED = 1.5


class GreedyPlayer(Player):
    """Heuristic bot scoring one move ahead.

    Parameters
    ----------
    player_id : int
        Seat id.
    name : str, optional
        Display name, by default ``"greedy"``.
    rng : random.Random or None, optional
        Used only to break score ties, by default a fresh Random.
    """

    def __init__(
        self, player_id: int, name: str = "greedy", rng: random.Random | None = None
    ) -> None:
        super().__init__(player_id, name)
        self.rng = rng or random.Random()

    def choose_move(self, board: Board) -> tuple[int, int]:
        """Return the highest scoring legal move, ties broken at random.

        Parameters
        ----------
        board : Board
            The current board.

        Returns
        -------
        tuple of int
            Row and column.
        """
        options = board.legal_moves(self.player_id)
        scored = [(self.score_move(board, r, c), (r, c)) for r, c in options]
        best = max(score for score, _ in scored)
        return self.rng.choice([move for score, move in scored if score == best])

    def score_move(self, board: Board, row: int, col: int) -> float:
        """Score a single candidate move.

        Parameters
        ----------
        board : Board
            The current board.
        row : int
            Candidate row.
        col : int
            Candidate column.

        Returns
        -------
        float
            Higher is better.

        Notes
        -----
        The adjacency danger penalty only applies to moves that do not
        detonate. A detonating move converts every orthogonal neighbour, so the
        threat it would otherwise be walking into no longer exists.
        """
        mass = board.critical_mass(row, col)
        cell = board.cells[row][col]
        resulting = cell.count + 1
        neighbours = board.neighbours(row, col)

        score = (4 - mass) * WEIGHT_LOW_MASS

        if resulting >= mass:
            score += WEIGHT_EXPLODE
            score += WEIGHT_CAPTURE * self._enemy_orbs_in_blast(board, neighbours)
            return score

        score += WEIGHT_LOADED * (resulting / mass)
        if self._is_threatened(board, neighbours):
            score -= WEIGHT_DANGER * resulting
        return score

    def _enemy_orbs_in_blast(self, board: Board, neighbours: list[tuple[int, int]]) -> int:
        """Count enemy orbs the immediate blast would convert.

        Parameters
        ----------
        board : Board
            The current board.
        neighbours : list of tuple of int
            Coordinates the blast would reach.

        Returns
        -------
        int
            Total enemy orbs sitting on those cells.
        """
        total = 0
        for nr, nc in neighbours:
            neighbour = board.cells[nr][nc]
            if neighbour.owner is not None and neighbour.owner != self.player_id:
                total += neighbour.count
        return total

    def _is_threatened(self, board: Board, neighbours: list[tuple[int, int]]) -> bool:
        """Return whether an adjacent enemy cell is one orb from critical.

        Parameters
        ----------
        board : Board
            The current board.
        neighbours : list of tuple of int
            Coordinates adjacent to the candidate move.

        Returns
        -------
        bool
            True when an enemy can detonate into the candidate cell next turn.
        """
        for nr, nc in neighbours:
            neighbour = board.cells[nr][nc]
            if neighbour.owner is None or neighbour.owner == self.player_id:
                continue
            if neighbour.count + 1 >= board.critical_mass(nr, nc):
                return True
        return False
