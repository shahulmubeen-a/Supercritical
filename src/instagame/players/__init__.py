"""Player implementations and the interface the engine talks to."""

from .base import Player
from .greedy_player import GreedyPlayer
from .llm_player import OllamaPlayer
from .random_player import RandomPlayer
from .strategies import STRATEGY_TYPES, ScoringPlayer, SimulatingPlayer

__all__ = [
    "PLAYER_TYPES",
    "STRATEGY_TYPES",
    "GreedyPlayer",
    "OllamaPlayer",
    "Player",
    "RandomPlayer",
    "ScoringPlayer",
    "SimulatingPlayer",
    "build_player",
    "offline_types",
]

PLAYER_TYPES: dict[str, type[Player]] = {
    "random": RandomPlayer,
    "greedy": GreedyPlayer,
    "ollama": OllamaPlayer,
    **STRATEGY_TYPES,
}


def offline_types() -> list[str]:
    """Return every player type that needs no external service.

    Returns
    -------
    list of str
        Sorted type names, excluding model backed players.
    """
    return sorted(set(PLAYER_TYPES) - {"ollama"})


def build_player(kind: str, player_id: int, name: str | None = None, **kwargs) -> Player:
    """Construct a player by short type name.

    Parameters
    ----------
    kind : str
        One of the keys of ``PLAYER_TYPES``.
    player_id : int
        Seat id assigned to the player.
    name : str or None, optional
        Display name. Defaults to the model tag for model backed players and
        ``"<kind>-<player_id>"`` otherwise.
    **kwargs
        Forwarded to the player constructor.

    Returns
    -------
    Player
        The constructed player.

    Raises
    ------
    KeyError
        If ``kind`` is not a known player type.
    """
    if kind not in PLAYER_TYPES:
        raise KeyError(f"unknown player type {kind!r}; known: {sorted(PLAYER_TYPES)}")
    if name is None:
        name = kwargs.get("model") or f"{kind}-{player_id}"
    return PLAYER_TYPES[kind](player_id=player_id, name=name, **kwargs)
