"""Turn sequencing, elimination and win detection."""

from __future__ import annotations

import random
from dataclasses import dataclass

from .board import DEFAULT_MAX_CASCADE_STEPS, Board, IllegalMoveError, Placement
from .logging_config import get_logger
from .players.base import Player

logger = get_logger("game")


@dataclass(frozen=True)
class TurnResult:
    """Everything one completed turn produced.

    Attributes
    ----------
    player_id : int
        Player who moved.
    placement : Placement
        The move and its cascade.
    eliminated : tuple of int
        Players knocked out by this move.
    winner : int or None
        Winning player id if the game ended on this move, else None.
    used_fallback : bool
        True when the player returned illegal moves and a random legal move
        was substituted.
    """

    player_id: int
    placement: Placement
    eliminated: tuple[int, ...] = ()
    winner: int | None = None
    used_fallback: bool = False


class Game:
    """Strictly sequential round-robin match.

    Exactly one player moves at a time. A turn does not return until that
    player's cascade has fully settled and elimination has been re-evaluated,
    so no player is ever handed a mid-cascade board.

    Parameters
    ----------
    board : Board
        The grid to play on.
    players : list of Player
        Seats in turn order. Player ids must be unique.
    illegal_retries : int, optional
        How many times a player may return an illegal move before a random
        legal move is substituted, by default 2.
    max_cascade_steps : int, optional
        Backstop ceiling passed through to :meth:`Board.place`.
    rng : random.Random or None, optional
        Source of randomness for fallback moves, by default a fresh Random.
    """

    def __init__(
        self,
        board: Board,
        players: list[Player],
        illegal_retries: int = 2,
        max_cascade_steps: int = DEFAULT_MAX_CASCADE_STEPS,
        rng: random.Random | None = None,
    ) -> None:
        if len(players) < 2:
            raise ValueError("need at least two players")
        ids = [p.player_id for p in players]
        if len(set(ids)) != len(ids):
            raise ValueError("player ids must be unique")
        self.board = board
        self.players = players
        self.illegal_retries = illegal_retries
        self.max_cascade_steps = max_cascade_steps
        self.rng = rng or random.Random()
        self.moves_made: dict[int, int] = {pid: 0 for pid in ids}
        self.eliminated: set[int] = set()
        self.turn_index = 0
        self.winner: int | None = None
        self.over = False
        self.turn_number = 0

    @property
    def player_ids(self) -> list[int]:
        """Return every seat id in turn order.

        Returns
        -------
        list of int
            Player ids.
        """
        return [p.player_id for p in self.players]

    def player_by_id(self, player_id: int) -> Player:
        """Return the seat with the given id.

        Parameters
        ----------
        player_id : int
            Player id.

        Returns
        -------
        Player
            The matching player.
        """
        for player in self.players:
            if player.player_id == player_id:
                return player
        raise KeyError(f"no player with id {player_id}")

    def active_players(self) -> list[Player]:
        """Return players still in the game, in turn order.

        Returns
        -------
        list of Player
            Players not yet eliminated.
        """
        return [p for p in self.players if p.player_id not in self.eliminated]

    def current_player(self) -> Player:
        """Return the player whose turn it is.

        Returns
        -------
        Player
            The player to move.
        """
        return self.players[self.turn_index]

    def step(self) -> TurnResult:
        """Advance exactly one turn.

        Asks the current player for a move, applies it, resolves the cascade to
        a settled board, updates elimination and hands the turn on.

        Returns
        -------
        TurnResult
            The completed turn.

        Raises
        ------
        RuntimeError
            If the game is already over.
        """
        if self.over:
            raise RuntimeError("game is already over")
        if not self.board.is_settled():
            raise RuntimeError("cannot start a turn on an unsettled board")

        row, col, used_fallback = self.ask_current_player()
        return self.commit_turn(row, col, used_fallback=used_fallback)

    def ask_current_player(self) -> tuple[int, int, bool]:
        """Query the current player for a move without applying it.

        Split out from :meth:`step` so a caller can run a slow player, such as
        one backed by a language model, on a worker thread and keep its UI
        responsive. This only reads the board, so it is safe off the main
        thread as long as nothing else mutates the game meanwhile.

        Returns
        -------
        tuple of (int, int, bool)
            Row, column and whether the random fallback was used.

        Raises
        ------
        RuntimeError
            If the game is over, the board is unsettled, or the player has no
            legal move.
        """
        if self.over:
            raise RuntimeError("game is already over")
        if not self.board.is_settled():
            raise RuntimeError("cannot start a turn on an unsettled board")
        player = self.current_player()
        options = self.board.legal_moves(player.player_id)
        if not options:
            logger.warning("player %s has no legal move; eliminating", player.name)
            self.eliminated.add(player.player_id)
            self._check_winner()
            self._advance_turn()
            raise RuntimeError("player had no legal move")
        return self._ask(player, options)

    def commit_turn(self, row: int, col: int, used_fallback: bool = False) -> TurnResult:
        """Apply a move for the current player and hand the turn on.

        Parameters
        ----------
        row : int
            Row index.
        col : int
            Column index.
        used_fallback : bool, optional
            Recorded on the result for reporting, by default False.

        Returns
        -------
        TurnResult
            The completed turn.
        """
        player_id = self.current_player().player_id
        if not self.board.is_legal(row, col, player_id):
            raise IllegalMoveError(f"player {player_id} may not place at ({row}, {col})")
        result = self.apply_move(row, col, player_id, used_fallback=used_fallback)
        self._advance_turn()
        return result

    def apply_move(
        self,
        row: int,
        col: int,
        player_id: int,
        used_fallback: bool = False,
    ) -> TurnResult:
        """Apply one move for a given player and settle the board.

        Shared by the bot turn loop and the debug takeover panel so both take
        the identical code path. Does not advance the turn index.

        Parameters
        ----------
        row : int
            Row index.
        col : int
            Column index.
        player_id : int
            Player placing the orb.
        used_fallback : bool, optional
            Recorded on the result for reporting, by default False.

        Returns
        -------
        TurnResult
            The completed move.
        """
        if self.over:
            raise RuntimeError("game is already over")
        placement = self.board.place(
            row,
            col,
            player_id,
            on_settle_check=self._sole_survivor_remains,
            max_steps=self.max_cascade_steps,
        )
        self.moves_made[player_id] += 1
        self.turn_number += 1
        knocked_out = self._update_elimination()
        self._check_winner()
        return TurnResult(
            player_id=player_id,
            placement=placement,
            eliminated=knocked_out,
            winner=self.winner,
            used_fallback=used_fallback,
        )

    def _ask(self, player: Player, options: list[tuple[int, int]]) -> tuple[int, int, bool]:
        """Ask a player for a move, retrying and then falling back.

        Parameters
        ----------
        player : Player
            The player to query.
        options : list of tuple of int
            Legal coordinates, used for the fallback.

        Returns
        -------
        tuple of (int, int, bool)
            Row, column, and whether the fallback was used.
        """
        for attempt in range(self.illegal_retries + 1):
            try:
                row, col = player.choose_move(self.board)
            except Exception:
                logger.exception("player %s raised on attempt %d", player.name, attempt + 1)
                continue
            if self.board.is_legal(row, col, player.player_id):
                return row, col, False
            logger.warning(
                "player %s returned illegal move (%s, %s) on attempt %d",
                player.name,
                row,
                col,
                attempt + 1,
            )
        row, col = self.rng.choice(options)
        logger.warning("substituting random legal move (%d, %d) for %s", row, col, player.name)
        return row, col, True

    def _potential_survivors(self) -> set[int]:
        """Return players who are not out.

        A player holding no orbs is only out once they have actually moved,
        otherwise every seat would be eliminated on the opening turn.

        Returns
        -------
        set of int
            Player ids still in contention.
        """
        holding = {pid for pid, n in self.board.counts_by_player().items() if n > 0}
        untested = {pid for pid, n in self.moves_made.items() if n == 0}
        return holding | untested

    def _sole_survivor_remains(self, board: Board) -> bool:
        """Return whether only one player is left in contention.

        Passed to :meth:`Board.place` and evaluated after every cascade wave,
        so a cascade that wipes out the last opponent stops immediately instead
        of running away on a board owned by a single player.

        Parameters
        ----------
        board : Board
            The live board, supplied by the cascade loop.

        Returns
        -------
        bool
            True when at most one player is still in contention.
        """
        return len(self._potential_survivors()) <= 1

    def _update_elimination(self) -> tuple[int, ...]:
        """Eliminate players who have moved and now hold no orbs.

        Returns
        -------
        tuple of int
            Ids eliminated by this call.
        """
        counts = self.board.counts_by_player()
        knocked_out: list[int] = []
        for pid in self.player_ids:
            if pid in self.eliminated:
                continue
            if self.moves_made[pid] > 0 and counts.get(pid, 0) == 0:
                self.eliminated.add(pid)
                knocked_out.append(pid)
                logger.info("player %s eliminated", self.player_by_id(pid).name)
        return tuple(knocked_out)

    def _check_winner(self) -> None:
        """End the game as soon as a single player remains."""
        remaining = self.active_players()
        if len(remaining) <= 1:
            self.over = True
            self.winner = remaining[0].player_id if remaining else None
            if self.winner is not None:
                logger.info("winner: %s", self.player_by_id(self.winner).name)

    def _advance_turn(self) -> None:
        """Move the turn marker to the next player still in the game."""
        if self.over:
            return
        for _ in range(len(self.players)):
            self.turn_index = (self.turn_index + 1) % len(self.players)
            if self.current_player().player_id not in self.eliminated:
                return
