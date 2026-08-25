"""Command line entry point for visual and headless matches."""

from __future__ import annotations

import argparse
import logging
import random
import sys
from collections import Counter

from .board import Board
from .game import Game
from .logging_config import configure_logging
from .players import PLAYER_TYPES, build_player

DEFAULT_ROWS = 9
DEFAULT_COLS = 6
DEFAULT_PLAYERS = "greedy,greedy,random,random"
MAX_HEADLESS_TURNS = 20000


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Returns
    -------
    argparse.ArgumentParser
        The configured parser.
    """
    parser = argparse.ArgumentParser(
        prog="instagame",
        description="Turn-based orb cascade game with bot players.",
    )
    parser.add_argument("--rows", type=int, default=DEFAULT_ROWS, help="board height")
    parser.add_argument("--cols", type=int, default=DEFAULT_COLS, help="board width")
    parser.add_argument(
        "--players",
        default=DEFAULT_PLAYERS,
        help=f"comma separated seats, from: {', '.join(sorted(PLAYER_TYPES))}",
    )
    parser.add_argument("--seed", type=int, default=None, help="seed for reproducible matches")
    parser.add_argument(
        "--headless", action="store_true", help="run without pygame, for fast simulation"
    )
    parser.add_argument(
        "--games", type=int, default=1, help="number of games to run in headless mode"
    )
    parser.add_argument("--move-delay", type=float, default=0.35, help="seconds between bot turns")
    parser.add_argument("--anim-speed", type=float, default=1.0, help="animation speed multiplier")
    parser.add_argument("--no-animate", action="store_true", help="snap moves to their result")
    parser.add_argument("--no-blur", action="store_true", help="disable motion blur trails")
    parser.add_argument(
        "--no-debug", action="store_true", help="hide the per-player takeover panel"
    )
    parser.add_argument("--verbose", action="store_true", help="debug level logging")
    return parser


def make_game(rows: int, cols: int, kinds: list[str], rng: random.Random) -> Game:
    """Build a fresh match.

    Parameters
    ----------
    rows : int
        Board height.
    cols : int
        Board width.
    kinds : list of str
        Player type names, one per seat.
    rng : random.Random
        Randomness source shared with the players.

    Returns
    -------
    Game
        The new match.
    """
    board = Board(rows, cols)
    players = [
        build_player(kind, index, rng=random.Random(rng.getrandbits(64)))
        for index, kind in enumerate(kinds)
    ]
    return Game(board, players, rng=rng)


def run_headless(args: argparse.Namespace, kinds: list[str], rng: random.Random) -> int:
    """Simulate matches with no rendering and report the tally.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments.
    kinds : list of str
        Player type names.
    rng : random.Random
        Randomness source.

    Returns
    -------
    int
        Process exit code.
    """
    logger = configure_logging(logging.DEBUG if args.verbose else logging.WARNING)
    tally: Counter[str] = Counter()
    turns_total = 0
    for index in range(args.games):
        game = make_game(args.rows, args.cols, kinds, rng)
        turns = 0
        while not game.over and turns < MAX_HEADLESS_TURNS:
            try:
                game.step()
            except RuntimeError as exc:
                logger.warning("game %d stopped: %s", index, exc)
                break
            turns += 1
        turns_total += turns
        if game.winner is None:
            tally["unfinished"] += 1
        else:
            tally[game.player_by_id(game.winner).name] += 1
    logger.setLevel(logging.INFO)
    logger.info("played %d games, %d turns total", args.games, turns_total)
    for name, count in tally.most_common():
        logger.info("%-12s %d", name, count)
    return 0 if tally["unfinished"] == 0 else 1


def run_visual(args: argparse.Namespace, kinds: list[str], rng: random.Random) -> int:
    """Run one match in a pygame window.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments.
    kinds : list of str
        Player type names.
    rng : random.Random
        Randomness source.

    Returns
    -------
    int
        Process exit code.
    """
    logger = configure_logging(logging.DEBUG if args.verbose else logging.INFO)
    try:
        from .render import GameApp
    except ImportError:
        logger.error("pygame is not available; rerun with --headless")
        return 2

    game = make_game(args.rows, args.cols, kinds, rng)
    try:
        app = GameApp(
            game,
            move_delay=args.move_delay,
            anim_speed=args.anim_speed,
            animate=not args.no_animate,
            motion_blur=not args.no_blur,
            debug=not args.no_debug,
        )
    except Exception:
        logger.exception("could not open a window; rerun with --headless")
        return 2
    app.run()
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run the requested mode.

    Parameters
    ----------
    argv : list of str or None, optional
        Argument vector, by default ``sys.argv[1:]``.

    Returns
    -------
    int
        Process exit code.
    """
    args = build_parser().parse_args(argv)
    kinds = [kind.strip() for kind in args.players.split(",") if kind.strip()]
    if len(kinds) < 2:
        build_parser().error("need at least two players")
    unknown = sorted(set(kinds) - set(PLAYER_TYPES))
    if unknown:
        build_parser().error(f"unknown player types: {', '.join(unknown)}")
    rng = random.Random(args.seed)
    if args.headless:
        return run_headless(args, kinds, rng)
    return run_visual(args, kinds, rng)


if __name__ == "__main__":
    sys.exit(main())
