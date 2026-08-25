"""Sixteen heuristic strategies.

Each one commits to a single idea about how to win, so matches between them
read as an argument rather than a set of tuning variants. They divide into
cheap positional players, which only look at the cell and its neighbours, and
simulating players, which play each candidate move out on a copy of the board.
"""

from __future__ import annotations

import random
from abc import abstractmethod

from ..board import Board
from .base import Player
from .tactics import (
    Outcome,
    enemy_orbs_adjacent,
    friendly_neighbours,
    simulate,
    threat_level,
    would_explode,
)


class ScoringPlayer(Player):
    """Picks the highest scoring legal move, breaking ties at random.

    Parameters
    ----------
    player_id : int
        Seat id.
    name : str or None, optional
        Display name, defaulting to the strategy's registered key.
    rng : random.Random or None, optional
        Used for tie breaking.
    """

    key = "scoring"

    def __init__(
        self, player_id: int, name: str | None = None, rng: random.Random | None = None
    ) -> None:
        super().__init__(player_id, name or self.key)
        self.rng = rng or random.Random()

    @abstractmethod
    def score(self, board: Board, row: int, col: int) -> float:
        """Rate a single candidate move.

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
        float
            Higher is better.
        """

    def begin_turn(self, board: Board) -> None:
        """Hook for per-turn setup before any move is scored.

        Parameters
        ----------
        board : Board
            Current board.
        """

    def choose_move(self, board: Board) -> tuple[int, int]:
        """Return the best scoring legal move.

        Parameters
        ----------
        board : Board
            Current board.

        Returns
        -------
        tuple of int
            Row and column.
        """
        self.begin_turn(board)
        options = board.legal_moves(self.player_id)
        scored = [(self.score(board, r, c), (r, c)) for r, c in options]
        best = max(score for score, _ in scored)
        return self.rng.choice([move for score, move in scored if score == best])


class SimulatingPlayer(ScoringPlayer):
    """Scores moves by playing them out on a copy of the board."""

    key = "simulating"

    @abstractmethod
    def rate(self, board: Board, outcome: Outcome, row: int, col: int) -> float:
        """Rate the settled position a move would produce.

        Parameters
        ----------
        board : Board
            Board as it stands before the move.
        outcome : Outcome
            Result of simulating the move.
        row : int
            Candidate row.
        col : int
            Candidate column.

        Returns
        -------
        float
            Higher is better.
        """

    def score(self, board: Board, row: int, col: int) -> float:
        """Simulate the move and hand the result to :meth:`rate`.

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
        float
            Higher is better.
        """
        return self.rate(board, simulate(board, row, col, self.player_id), row, col)


class CornerHunter(ScoringPlayer):
    """Claims the cheapest cells to detonate: corners, then edges."""

    key = "corner"

    def score(self, board: Board, row: int, col: int) -> float:
        return -board.critical_mass(row, col) + 0.1 * board.cells[row][col].count


class CenterSeeker(ScoringPlayer):
    """Builds in the interior, where cells hold the most orbs."""

    key = "center"

    def score(self, board: Board, row: int, col: int) -> float:
        return board.critical_mass(row, col) + 0.1 * board.cells[row][col].count


class Aggressor(ScoringPlayer):
    """Detonates into the largest reachable pile of opponent orbs."""

    key = "aggressor"

    def score(self, board: Board, row: int, col: int) -> float:
        if not would_explode(board, row, col):
            return -1.0
        return 10.0 + enemy_orbs_adjacent(board, row, col, self.player_id)


class Cautious(ScoringPlayer):
    """Keeps away from opponent cells that are one orb from critical."""

    key = "cautious"

    def score(self, board: Board, row: int, col: int) -> float:
        risk = threat_level(board, row, col, self.player_id)
        exposure = board.cells[row][col].count + 1
        return -10.0 * risk * exposure - 0.5 * enemy_orbs_adjacent(board, row, col, self.player_id)


class Loader(ScoringPlayer):
    """Stockpiles orbs, filling cells to one short of critical."""

    key = "loader"

    def score(self, board: Board, row: int, col: int) -> float:
        mass = board.critical_mass(row, col)
        resulting = board.cells[row][col].count + 1
        if resulting >= mass:
            return -5.0
        return resulting / mass


class Detonator(ScoringPlayer):
    """Sets something off every turn it can."""

    key = "detonator"

    def score(self, board: Board, row: int, col: int) -> float:
        return 1.0 if would_explode(board, row, col) else 0.0


class Frontier(ScoringPlayer):
    """Grows as one connected mass, always building beside its own cells."""

    key = "frontier"

    def score(self, board: Board, row: int, col: int) -> float:
        own = board.cells[row][col].owner == self.player_id
        return friendly_neighbours(board, row, col, self.player_id) + (0.5 if own else 0.0)


class Parity(ScoringPlayer):
    """Occupies one colour of the board's checkerboard.

    Cells of a single parity are never orthogonally adjacent, so the player
    spreads into an interlocking lattice instead of a solid block.
    """

    key = "parity"

    def score(self, board: Board, row: int, col: int) -> float:
        preferred = 1.0 if (row + col) % 2 == self.player_id % 2 else 0.0
        return preferred * 2 + 0.1 * board.cells[row][col].count


class Hunter(ScoringPlayer):
    """Goes after whichever opponent is closest to being wiped out."""

    key = "hunter"

    def __init__(self, player_id, name=None, rng=None) -> None:
        super().__init__(player_id, name, rng)
        self.quarry: int | None = None

    def begin_turn(self, board: Board) -> None:
        rivals = {pid: n for pid, n in board.counts_by_player().items() if pid != self.player_id}
        self.quarry = min(rivals, key=lambda pid: rivals[pid]) if rivals else None

    def score(self, board: Board, row: int, col: int) -> float:
        if self.quarry is None:
            return -board.critical_mass(row, col)
        prey = sum(
            board.cells[nr][nc].count
            for nr, nc in board.neighbours(row, col)
            if board.cells[nr][nc].owner == self.quarry
        )
        return (10.0 if would_explode(board, row, col) else 0.0) + 3.0 * prey


class Mirror(ScoringPlayer):
    """Answers each opponent move with its reflection through the centre."""

    key = "mirror"

    def __init__(self, player_id, name=None, rng=None) -> None:
        super().__init__(player_id, name, rng)
        self.seen: dict[tuple[int, int], int | None] = {}
        self.target: tuple[int, int] | None = None

    def begin_turn(self, board: Board) -> None:
        latest = None
        for r, c, cell in board.iter_cells():
            owner = cell.owner if cell.count else None
            if self.seen.get((r, c)) != owner and owner not in (None, self.player_id):
                latest = (r, c)
            self.seen[(r, c)] = owner
        # Hold the previous target when no new opponent move is visible, so
        # scoring the same position twice does not wipe the reflection.
        if latest is not None:
            self.target = (board.rows - 1 - latest[0], board.cols - 1 - latest[1])

    def score(self, board: Board, row: int, col: int) -> float:
        if self.target is None:
            return -board.critical_mass(row, col)
        return -(abs(row - self.target[0]) + abs(col - self.target[1]))


class ChainSeeker(SimulatingPlayer):
    """Chases the longest chain reaction available."""

    key = "chain"

    def rate(self, board: Board, outcome: Outcome, row: int, col: int) -> float:
        return outcome.waves * 10.0 + outcome.orbs_of(self.player_id)


class Harvester(SimulatingPlayer):
    """Maximises its own orb count after the dust settles."""

    key = "harvester"

    def rate(self, board: Board, outcome: Outcome, row: int, col: int) -> float:
        return outcome.orbs_of(self.player_id)


class Territorial(SimulatingPlayer):
    """Maximises the number of cells it holds, not the orbs in them."""

    key = "territorial"

    def rate(self, board: Board, outcome: Outcome, row: int, col: int) -> float:
        return outcome.cells.get(self.player_id, 0)


class Spoiler(SimulatingPlayer):
    """Plays against whoever is ahead rather than for itself."""

    key = "spoiler"

    def rate(self, board: Board, outcome: Outcome, row: int, col: int) -> float:
        return -outcome.best_enemy(self.player_id) + 0.25 * outcome.orbs_of(self.player_id)


class Sentinel(SimulatingPlayer):
    """Builds stored potential: as many armed cells as possible.

    An armed cell is one orb below critical, so a board full of them can be set
    off at will next turn.
    """

    key = "sentinel"

    def rate(self, board: Board, outcome: Outcome, row: int, col: int) -> float:
        return 3.0 * outcome.armed.get(self.player_id, 0) + outcome.orbs_of(self.player_id)


class Retaliator(SimulatingPlayer):
    """Looks a move ahead and limits the best reply against it.

    The only strategy here that models an opponent. It costs a second round of
    simulation per candidate, so it samples the strongest few replies rather
    than every one.
    """

    key = "retaliator"
    REPLY_SAMPLE = 12

    def rate(self, board: Board, outcome: Outcome, row: int, col: int) -> float:
        mine = outcome.orbs_of(self.player_id)
        snapshot = board.snapshot()
        try:
            board.apply_unrecorded(row, col, self.player_id, max_steps=400)
            rivals = [pid for pid in outcome.orbs if pid != self.player_id]
            if not rivals:
                return mine + 1000.0
            rival = max(rivals, key=lambda pid: outcome.orbs[pid])
            replies = board.legal_moves(rival)
            if len(replies) > self.REPLY_SAMPLE:
                replies = self.rng.sample(replies, self.REPLY_SAMPLE)
            worst = min(
                (simulate(board, r, c, rival).orbs_of(self.player_id) for r, c in replies),
                default=mine,
            )
        finally:
            board.restore(snapshot)
        return worst


STRATEGIES: tuple[type[ScoringPlayer], ...] = (
    CornerHunter,
    CenterSeeker,
    Aggressor,
    Cautious,
    Loader,
    Detonator,
    Frontier,
    Parity,
    Hunter,
    Mirror,
    ChainSeeker,
    Harvester,
    Territorial,
    Spoiler,
    Sentinel,
    Retaliator,
)

STRATEGY_TYPES: dict[str, type[ScoringPlayer]] = {cls.key: cls for cls in STRATEGIES}
