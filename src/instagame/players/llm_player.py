"""A player backed by a local model served by Ollama."""

from __future__ import annotations

import json
import re

from ..board import Board
from ..logging_config import get_logger
from ..ollama import OllamaClient, OllamaError
from .base import Player

logger = get_logger("llm")

PLAYER_SYMBOLS = ("R", "B", "G", "Y", "P", "O")
MAX_ENUMERATED_MOVES = 60

SYSTEM_PROMPT = """You are an expert player of a turn-based orb cascade game.

Rules:
- Every cell has a capacity equal to its number of orthogonal neighbours: 2 in a
  corner, 3 along an edge, 4 in the interior.
- On your turn you place one orb on an empty cell or a cell you already own. You
  may never place on a cell owned by an opponent.
- When a cell's orb count reaches its capacity it explodes: it sends one orb to
  each orthogonal neighbour and loses that many orbs.
- An orb landing on a cell converts that entire cell to the exploding player,
  opponent orbs included.
- Explosions can push neighbours to capacity as well, so one move can set off a
  chain reaction.
- A player who has already moved and holds no orbs is eliminated. The last
  player left wins.

Strong play: build toward chain reactions that capture opponent stacks, favour
corners and edges because they explode sooner, and avoid parking a large stack
next to an opponent cell that is one orb short of capacity.

Reply with JSON only. Keep any explanation under fifteen words."""

MOVE_SCHEMA: dict = {
    "type": "object",
    "properties": {"row": {"type": "integer"}, "col": {"type": "integer"}},
    "required": ["row", "col"],
}

MOVE_SCHEMA_WITH_REASON: dict = {
    "type": "object",
    "properties": {
        "row": {"type": "integer"},
        "col": {"type": "integer"},
        "why": {"type": "string", "maxLength": 120},
    },
    "required": ["row", "col", "why"],
}


def player_symbol(player_id: int) -> str:
    """Return the single letter used for a seat in prompts.

    Parameters
    ----------
    player_id : int
        Seat id.

    Returns
    -------
    str
        A one character symbol.
    """
    return PLAYER_SYMBOLS[player_id % len(PLAYER_SYMBOLS)]


def render_board(board: Board) -> str:
    """Render the board as an aligned text table for a prompt.

    Each cell reads ``owner count/capacity``, so the model never has to work
    out corner and edge capacities for itself.

    Parameters
    ----------
    board : Board
        The board to describe.

    Returns
    -------
    str
        The table, including a column header row.
    """
    width = 7
    lines = ["".join(["    "] + [f"c{c}".rjust(width) for c in range(board.cols)])]
    for row in range(board.rows):
        entries = [f"r{row}".ljust(4)]
        for col in range(board.cols):
            cell = board.cells[row][col]
            mass = board.critical_mass(row, col)
            if cell.owner is None or not cell.count:
                entries.append(f"-/{mass}".rjust(width))
            else:
                entries.append(f"{player_symbol(cell.owner)}{cell.count}/{mass}".rjust(width))
        lines.append("".join(entries))
    return "\n".join(lines)


def build_prompt(board: Board, player_id: int) -> str:
    """Build the per-turn prompt describing the position.

    Parameters
    ----------
    board : Board
        Current board.
    player_id : int
        Seat the prompt is written for.

    Returns
    -------
    str
        The user prompt.
    """
    counts = board.counts_by_player()
    totals = "  ".join(f"{player_symbol(pid)}={counts[pid]}" for pid in sorted(counts)) or "none"
    moves = board.legal_moves(player_id)
    if len(moves) <= MAX_ENUMERATED_MOVES:
        move_text = " ".join(f"({r},{c})" for r, c in moves)
    else:
        move_text = (
            f"{len(moves)} available: every cell shown as '-' or owned by "
            f"{player_symbol(player_id)}"
        )
    return (
        f"You are player {player_symbol(player_id)}.\n\n"
        f"Board, {board.rows} rows by {board.cols} columns. "
        f"Each cell is 'owner count/capacity', '-' means empty.\n"
        f"{render_board(board)}\n\n"
        f"Orb totals: {totals}\n\n"
        f"Your legal moves (row, col):\n{move_text}\n\n"
        f"Choose one legal move."
    )


def parse_move(text: str) -> tuple[int, int, str]:
    """Extract a move from a model response.

    Parameters
    ----------
    text : str
        Raw model output.

    Returns
    -------
    tuple of (int, int, str)
        Row, column and the stated reason, which may be empty.

    Raises
    ------
    ValueError
        If no usable JSON object with integer coordinates is present.
    """
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is not None:
        try:
            payload = json.loads(match.group(0))
            return (
                int(payload["row"]),
                int(payload["col"]),
                str(payload.get("why", "")).strip(),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            logger.debug("falling back to field scan for response %r", text[:160])
    return _scan_fields(text)


def _scan_fields(text: str) -> tuple[int, int, str]:
    """Recover a move from output that is not valid JSON.

    Models routinely run out of output tokens partway through the explanation
    string, leaving the object unterminated. The coordinates are already
    present by then, so scan for them directly rather than discarding the turn.

    Parameters
    ----------
    text : str
        Raw model output.

    Returns
    -------
    tuple of (int, int, str)
        Row, column and the reason, which may be truncated or empty.

    Raises
    ------
    ValueError
        If no row and column can be found.
    """
    row = re.search(r'"row"\s*:\s*"?(-?\d+)', text)
    col = re.search(r'"col"\s*:\s*"?(-?\d+)', text)
    if row is None or col is None:
        raise ValueError(f"no row and col in response: {text[:160]!r}")
    why = re.search(r'"why"\s*:\s*"([^"]*)', text)
    return int(row.group(1)), int(col.group(1)), (why.group(1).strip() if why else "")


class OllamaPlayer(Player):
    """Plays via a local model served by Ollama.

    The engine validates whatever comes back and retries before substituting a
    random legal move, so a model that hallucinates coordinates degrades the
    quality of play rather than breaking the game.

    Parameters
    ----------
    player_id : int
        Seat id.
    model : str, optional
        Ollama model tag, by default ``"qwen3.5:4b"``.
    name : str or None, optional
        Display name, by default the model tag.
    client : OllamaClient or None, optional
        Client to use, by default a fresh one.
    host : str or None, optional
        Ollama base URL, used only when ``client`` is not supplied.
    timeout : float, optional
        Per-request timeout in seconds, by default 120.
    temperature : float, optional
        Sampling temperature, by default 0.7.
    explain : bool, optional
        Ask the model for a one line reason as well, which costs extra tokens
        and latency but makes matches easier to follow, by default False.
    """

    def __init__(
        self,
        player_id: int,
        model: str = "qwen3.5:4b",
        name: str | None = None,
        client: OllamaClient | None = None,
        host: str | None = None,
        timeout: float = 120.0,
        temperature: float = 0.7,
        explain: bool = False,
    ) -> None:
        super().__init__(player_id, name or model)
        self.model = model
        self.client = client or OllamaClient(host=host, timeout=timeout)
        self.temperature = temperature
        self.explain = explain
        self.calls = 0
        self.illegal = 0
        self.errors = 0
        self.total_latency = 0.0
        self.last_reason = ""

    @property
    def average_latency(self) -> float:
        """Return mean seconds per completed call.

        Returns
        -------
        float
            Average latency, or 0.0 before the first call.
        """
        return self.total_latency / self.calls if self.calls else 0.0

    def stats_line(self) -> str:
        """Return a one line summary of this player's model usage.

        Returns
        -------
        str
            Call count, average latency and failure counts.
        """
        return (
            f"{self.name}: {self.calls} calls, {self.average_latency:.1f}s avg, "
            f"{self.illegal} illegal, {self.errors} errors"
        )

    def choose_move(self, board: Board) -> tuple[int, int]:
        """Ask the model for a move.

        Parameters
        ----------
        board : Board
            Current board.

        Returns
        -------
        tuple of int
            Row and column as returned by the model, not yet validated.

        Raises
        ------
        ValueError
            If the response cannot be parsed into coordinates.
        OllamaError
            If the server cannot be reached.
        """
        schema = MOVE_SCHEMA_WITH_REASON if self.explain else MOVE_SCHEMA
        try:
            completion = self.client.generate(
                model=self.model,
                prompt=build_prompt(board, self.player_id),
                system=SYSTEM_PROMPT,
                schema=schema,
                temperature=self.temperature,
                num_predict=192 if self.explain else 32,
            )
        except OllamaError:
            self.errors += 1
            raise
        self.calls += 1
        self.total_latency += completion.latency
        row, col, reason = parse_move(completion.text)
        self.last_reason = reason
        if not board.is_legal(row, col, self.player_id):
            self.illegal += 1
            logger.warning(
                "%s proposed illegal move (%d, %d) after %.1fs",
                self.name,
                row,
                col,
                completion.latency,
            )
        return row, col
