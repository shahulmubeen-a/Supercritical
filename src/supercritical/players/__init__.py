"""Player implementations and the interface the engine talks to."""

from .base import Player
from .greedy_player import GreedyPlayer
from .random_player import RandomPlayer
from .strategies import STRATEGY_TYPES, ScoringPlayer, SimulatingPlayer

__all__ = [
    "PLAYER_TYPES",
    "STRATEGY_TYPES",
    "GreedyPlayer",
    "Player",
    "RandomPlayer",
    "ScoringPlayer",
    "SimulatingPlayer",
    "build_player",
    "offline_types",
    "types_in_tier",
]

PLAYER_TYPES: dict[str, type[Player]] = {
    "random": RandomPlayer,
    "greedy": GreedyPlayer,
    **STRATEGY_TYPES,
}


def types_in_tier(tier: str) -> list[str]:
    """Return every offline player type searching to a given depth.

    Parameters
    ----------
    tier : str
        Either ``"positional"`` or ``"simulating"``.

    Returns
    -------
    list of str
        Sorted type names in that tier.
    """
    return sorted(k for k in offline_types() if PLAYER_TYPES[k].tier == tier)


def offline_types() -> list[str]:
    """Return every registered player type.

    Returns
    -------
    list of str
        Sorted type names.
    """
    return sorted(PLAYER_TYPES)


def build_player(kind: str, player_id: int, name: str | None = None, **kwargs) -> Player:
    """Construct a player by short type name.

    Parameters
    ----------
    kind : str
        One of the keys of ``PLAYER_TYPES``.
    player_id : int
        Seat id assigned to the player.
    name : str or None, optional
        Display name, by default ``"<kind>-<player_id>"``.
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
        name = f"{kind}-{player_id}"
    return PLAYER_TYPES[kind](player_id=player_id, name=name, **kwargs)
