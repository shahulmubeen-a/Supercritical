"""Command line entry point for visual and headless matches."""

from __future__ import annotations

import argparse
import logging
import random
import sys
from collections import Counter
from pathlib import Path

from .board import Board
from .game import Game
from .logging_config import configure_logging
from .players import PLAYER_TYPES, build_player, offline_types, types_in_tier
from .replay import Recorder
from .viewer import DEFAULT_TITLE, write_page

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
        help=f"comma separated seats from: {', '.join(offline_types())}",
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
    parser.add_argument(
        "--illegal-retries",
        type=int,
        default=2,
        help="how many illegal moves a player may return before a random legal one is used",
    )
    parser.add_argument(
        "--record",
        default=None,
        help=(
            "write a replay to this path. A .html suffix writes a standalone, "
            "deployable viewer page; .json writes the raw replay data"
        ),
    )
    parser.add_argument("--title", default=DEFAULT_TITLE, help="title shown on the replay page")
    parser.add_argument(
        "--list-players", action="store_true", help="print every player type and exit"
    )
    parser.add_argument("--verbose", action="store_true", help="debug level logging")
    return parser


def save_replay(recorder: Recorder, path: Path, title: str, logger) -> None:
    """Write a recorded match as either a viewer page or raw JSON.

    Parameters
    ----------
    recorder : Recorder
        The recorded match.
    path : Path
        Destination. A ``.json`` suffix writes raw data, anything else writes
        a standalone HTML page.
    title : str
        Title for the page.
    logger : logging.Logger
        Logger for the confirmation message.
    """
    if path.suffix.lower() == ".json":
        recorder.write_json(path)
    else:
        write_page(recorder.to_dict(), path, title)
    logger.info("replay written to %s", path)


def replay_path(base: str, index: int, total: int) -> Path:
    """Return the output path for one game of a possibly multi-game run.

    Parameters
    ----------
    base : str
        Path given on the command line.
    index : int
        Zero based game number.
    total : int
        How many games are being played.

    Returns
    -------
    Path
        The path for this game, numbered when more than one is played.
    """
    path = Path(base)
    if total <= 1:
        return path
    return path.with_name(f"{path.stem}-{index + 1}{path.suffix}")


def make_game(rows: int, cols: int, kinds: list[str], rng: random.Random, args) -> Game:
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
    args : argparse.Namespace
        Parsed arguments.

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
    return Game(board, players, illegal_retries=args.illegal_retries, rng=rng)


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
        game = make_game(args.rows, args.cols, kinds, rng, args)
        recorder = Recorder(game) if args.record else None
        turns = 0
        while not game.over and turns < MAX_HEADLESS_TURNS:
            try:
                result = game.step()
            except RuntimeError as exc:
                logger.warning("game %d stopped: %s", index, exc)
                break
            if recorder is not None:
                recorder.record(result)
            turns += 1
        if recorder is not None:
            save_replay(
                recorder,
                replay_path(args.record, index, args.games),
                args.title,
                logger,
            )
        turns_total += turns
        if game.winner is None:
            tally["unfinished"] += 1
        else:
            tally[game.player_by_id(game.winner).name] += 1
    logger.setLevel(logging.INFO)
    logger.info("played %d games, %d turns total", args.games, turns_total)
    for name, count in tally.most_common():
        logger.info("%-20s %d", name, count)
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

    game = make_game(args.rows, args.cols, kinds, rng, args)
    recorder = Recorder(game) if args.record else None
    try:
        app = GameApp(
            game,
            move_delay=args.move_delay,
            anim_speed=args.anim_speed,
            animate=not args.no_animate,
            motion_blur=not args.no_blur,
            debug=not args.no_debug,
            on_turn=recorder.record if recorder is not None else None,
        )
    except Exception:
        logger.exception("could not open a window; rerun with --headless")
        return 2
    app.run()
    if recorder is not None:
        save_replay(recorder, Path(args.record), args.title, logger)
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
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list_players:
        logger = configure_logging(logging.INFO)
        for tier in ("positional", "simulating"):
            logger.info("[%s]", tier)
            for kind in types_in_tier(tier):
                doc = (PLAYER_TYPES[kind].__doc__ or "").strip().splitlines()[0]
                logger.info("  %-12s %s", kind, doc)
        return 0
    kinds = [spec.strip() for spec in args.players.split(",") if spec.strip()]
    if len(kinds) < 2:
        parser.error("need at least two players")
    unknown = sorted(set(kinds) - set(PLAYER_TYPES))
    if unknown:
        parser.error(f"unknown player types: {', '.join(unknown)}")
    rng = random.Random(args.seed)
    if args.headless:
        return run_headless(args, kinds, rng)
    return run_visual(args, kinds, rng)


if __name__ == "__main__":
    sys.exit(main())
