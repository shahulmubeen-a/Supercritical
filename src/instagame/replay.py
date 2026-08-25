"""Recording matches to a portable format for later replay.

The engine already produces everything a replay needs: each turn carries the
board immediately after placement plus one snapshot per cascade wave. Recording
stores those snapshots verbatim rather than storing only the moves, so a viewer
never has to reimplement the rules and cannot drift from the engine.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .board import BoardSnapshot
from .game import Game, TurnResult

REPLAY_VERSION = 1
EMPTY_OWNER = -1


def encode_grid(snapshot: BoardSnapshot) -> list[list[int]]:
    """Encode a snapshot as row-major ``[count, owner]`` pairs.

    Parameters
    ----------
    snapshot : BoardSnapshot
        Board state to encode.

    Returns
    -------
    list of list of int
        One pair per cell, with ``-1`` marking an unowned cell.
    """
    return [
        [cell.count, EMPTY_OWNER if cell.owner is None else cell.owner]
        for row in snapshot.cells
        for cell in row
    ]


@dataclass
class Recorder:
    """Accumulates a replay while a match is played.

    Parameters
    ----------
    game : Game
        The match being recorded. Read for board size and seat names only.
    """

    game: Game
    turns: list[dict] = field(default_factory=list)

    def record(self, result: TurnResult) -> None:
        """Append one completed turn.

        Parameters
        ----------
        result : TurnResult
            The turn to store.
        """
        player = self.game.player_by_id(result.player_id)
        placement = result.placement
        self.turns.append(
            {
                "player": result.player_id,
                "row": placement.row,
                "col": placement.col,
                "fallback": result.used_fallback,
                "reason": getattr(player, "last_reason", "") or "",
                "latency": round(float(getattr(player, "last_latency", 0.0) or 0.0), 3),
                "initial": encode_grid(placement.initial),
                "steps": [
                    {
                        "explosions": [
                            {
                                "r": e.row,
                                "c": e.col,
                                "p": e.player,
                                "t": [list(t) for t in e.targets],
                            }
                            for e in step.explosions
                        ],
                        "transit": encode_grid(step.transit),
                        "after": encode_grid(step.after),
                    }
                    for step in placement.steps
                ],
                "eliminated": list(result.eliminated),
                "winner": result.winner,
            }
        )

    def to_dict(self) -> dict:
        """Return the replay as a plain dictionary.

        Returns
        -------
        dict
            Everything a viewer needs to play the match back.
        """
        return {
            "version": REPLAY_VERSION,
            "board": {"rows": self.game.board.rows, "cols": self.game.board.cols},
            "players": [
                {
                    "id": player.player_id,
                    "name": player.name,
                    "kind": type(player).__name__,
                }
                for player in self.game.players
            ],
            "turns": self.turns,
            "winner": self.game.winner,
            "stats": [
                {
                    "id": player.player_id,
                    "name": player.name,
                    "calls": player.calls,
                    "average_latency": round(player.average_latency, 3),
                    "illegal": player.illegal,
                    "errors": player.errors,
                }
                for player in self.game.players
                if hasattr(player, "average_latency")
            ],
        }

    def write_json(self, path: Path) -> Path:
        """Write the replay as JSON.

        Parameters
        ----------
        path : Path
            Destination file.

        Returns
        -------
        Path
            The path written.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), separators=(",", ":")), encoding="utf-8")
        return path
