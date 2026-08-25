"""A player that picks uniformly at random from its legal moves."""

from __future__ import annotations

import random

from ..board import Board
from .base import Player


class RandomPlayer(Player):
    """Uniform random baseline.

    Parameters
    ----------
    player_id : int
        Seat id.
    name : str, optional
        Display name, by default ``"random"``.
    rng : random.Random or None, optional
        Randomness source, by default a fresh Random.
    """

    def __init__(
        self, player_id: int, name: str = "random", rng: random.Random | None = None
    ) -> None:
        super().__init__(player_id, name)
        self.rng = rng or random.Random()

    def choose_move(self, board: Board) -> tuple[int, int]:
        """Return a uniformly chosen legal move.

        Parameters
        ----------
        board : Board
            The current board.

        Returns
        -------
        tuple of int
            Row and column.
        """
        return self.rng.choice(board.legal_moves(self.player_id))
