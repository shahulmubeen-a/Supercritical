"""The interface every player implements.

The engine only ever calls :meth:`Player.choose_move` and validates whatever
comes back, so a network-backed player is no different to a local bot.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..board import Board


class Player(ABC):
    """Abstract seat in a match.

    Parameters
    ----------
    player_id : int
        Unique seat id, also used as the cell owner value.
    name : str
        Display name.
    """

    def __init__(self, player_id: int, name: str) -> None:
        self.player_id = player_id
        self.name = name

    @abstractmethod
    def choose_move(self, board: Board) -> tuple[int, int]:
        """Pick a cell to place an orb on.

        The board handed in is always settled: no cell is at or above its
        critical mass.

        Parameters
        ----------
        board : Board
            The current board. Treat as read-only.

        Returns
        -------
        tuple of int
            Row and column to place on.
        """

    def __repr__(self) -> str:
        return f"{type(self).__name__}(id={self.player_id}, name={self.name!r})"
