"""Command line entry point for visual and headless matches."""

from __future__ import annotations

import argparse
import logging
import os
import random
import sys
from collections import Counter

from .board import Board
from .game import Game
from .logging_config import configure_logging, get_logger
from .ollama import OllamaClient, OllamaError, resolve_model_tag
from .players import PLAYER_TYPES, build_player, offline_types

DEFAULT_ROWS = 9
DEFAULT_COLS = 6
DEFAULT_PLAYERS = "greedy,greedy,random,random"
DEFAULT_OLLAMA_MODEL = "qwen3.5:4b"
MAX_HEADLESS_TURNS = 20000


def parse_seat(spec: str) -> tuple[str, str | None]:
    """Split a seat specification into a player type and its argument.

    Splits on the first colon only, so a model tag that itself contains a
    colon survives intact: ``ollama:gemma3:4b`` yields ``("ollama", "gemma3:4b")``.

    Parameters
    ----------
    spec : str
        Seat specification from ``--players``.

    Returns
    -------
    tuple of (str, str or None)
        Player type and its optional argument.
    """
    kind, _, rest = spec.partition(":")
    return kind.strip(), (rest.strip() or None)


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
        help=(
            "comma separated seats. Strategies: "
            f"{', '.join(offline_types())}. "
            "Model seats take a tag, for example ollama:gemma3:4b"
        ),
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
    parser.add_argument("--ollama-host", default=None, help="ollama base url")
    parser.add_argument(
        "--llm-timeout", type=float, default=120.0, help="seconds to wait for a model move"
    )
    parser.add_argument(
        "--llm-temperature", type=float, default=0.7, help="sampling temperature for models"
    )
    parser.add_argument(
        "--llm-explain",
        action="store_true",
        help="ask models for a one line reason, shown in the panel; costs latency",
    )
    parser.add_argument(
        "--list-players", action="store_true", help="print every player type and exit"
    )
    parser.add_argument("--verbose", action="store_true", help="debug level logging")
    return parser


def make_game(
    rows: int,
    cols: int,
    seats: list[tuple[str, str | None]],
    rng: random.Random,
    args: argparse.Namespace,
    client: OllamaClient | None = None,
) -> Game:
    """Build a fresh match.

    Parameters
    ----------
    rows : int
        Board height.
    cols : int
        Board width.
    seats : list of tuple
        Player type and optional argument, one per seat.
    rng : random.Random
        Randomness source shared with the bots.
    args : argparse.Namespace
        Parsed arguments, used for model settings.
    client : OllamaClient or None, optional
        Shared client for model seats.

    Returns
    -------
    Game
        The new match.
    """
    board = Board(rows, cols)
    players = []
    used_names: Counter[str] = Counter()
    for index, (kind, spec) in enumerate(seats):
        if kind == "ollama":
            model = spec or DEFAULT_OLLAMA_MODEL
            used_names[model] += 1
            suffix = f" #{used_names[model]}" if used_names[model] > 1 else ""
            player = build_player(
                kind,
                index,
                name=f"{model}{suffix}",
                model=model,
                client=client,
                temperature=args.llm_temperature,
                explain=args.llm_explain,
            )
        else:
            player = build_player(kind, index, rng=random.Random(rng.getrandbits(64)))
        players.append(player)
    return Game(board, players, illegal_retries=args.illegal_retries, rng=rng)


def make_client(
    args: argparse.Namespace, seats: list[tuple[str, str | None]]
) -> tuple[OllamaClient | None, list[tuple[str, str | None]]]:
    """Preflight Ollama and resolve model names to the tags it actually holds.

    Sharing one client across seats also shares its cache of which models
    reject the thinking flag.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments.
    seats : list of tuple
        Seat specifications.

    Returns
    -------
    tuple
        The client, or None when no seat needs one, and the seat list with
        model names resolved to canonical tags.

    Raises
    ------
    SystemExit
        If the server is unreachable or a requested model is missing.
    """
    wanted = {spec or DEFAULT_OLLAMA_MODEL for kind, spec in seats if kind == "ollama"}
    if not wanted:
        return None, seats
    client = OllamaClient(host=args.ollama_host, timeout=args.llm_timeout)
    try:
        available = set(client.available_models())
    except OllamaError as exc:
        raise SystemExit(f"{exc}\nIs ollama running? Try: ollama serve") from exc

    resolved = {name: resolve_model_tag(name, available) for name in wanted}
    missing = sorted(name for name, tag in resolved.items() if tag is None)
    if missing:
        raise SystemExit(
            "missing models: "
            + ", ".join(missing)
            + "\nPull them first, for example: ollama pull "
            + missing[0]
        )
    limit = int(os.environ.get("OLLAMA_MAX_LOADED_MODELS") or 0)
    if len(wanted) > 1 and 0 < limit < len(wanted):
        get_logger("cli").warning(
            "%d models in play but OLLAMA_MAX_LOADED_MODELS is %d; "
            "ollama will unload between turns and each reload costs more than the move",
            len(wanted),
            limit,
        )
    seats = [
        (kind, resolved[spec or DEFAULT_OLLAMA_MODEL] if kind == "ollama" else spec)
        for kind, spec in seats
    ]
    return client, seats


def report_model_stats(logger, game: Game) -> None:
    """Log per-model call counts, latency and failure counts.

    Parameters
    ----------
    logger : logging.Logger
        Logger to write to.
    game : Game
        Finished match.
    """
    for player in game.players:
        if hasattr(player, "stats_line"):
            logger.info("%s", player.stats_line())


def run_headless(
    args: argparse.Namespace, seats: list[tuple[str, str | None]], rng: random.Random
) -> int:
    """Simulate matches with no rendering and report the tally.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments.
    seats : list of tuple
        Seat specifications.
    rng : random.Random
        Randomness source.

    Returns
    -------
    int
        Process exit code.
    """
    logger = configure_logging(logging.DEBUG if args.verbose else logging.WARNING)
    client, seats = make_client(args, seats)
    tally: Counter[str] = Counter()
    turns_total = 0
    last_game = None
    for index in range(args.games):
        game = make_game(args.rows, args.cols, seats, rng, args, client)
        last_game = game
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
        logger.info("%-20s %d", name, count)
    if last_game is not None:
        report_model_stats(logger, last_game)
    return 0 if tally["unfinished"] == 0 else 1


def run_visual(
    args: argparse.Namespace, seats: list[tuple[str, str | None]], rng: random.Random
) -> int:
    """Run one match in a pygame window.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments.
    seats : list of tuple
        Seat specifications.
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

    client, seats = make_client(args, seats)
    game = make_game(args.rows, args.cols, seats, rng, args, client)
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
    report_model_stats(logger, game)
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
        for kind in offline_types():
            doc = (PLAYER_TYPES[kind].__doc__ or "").strip().splitlines()[0]
            logger.info("%-12s %s", kind, doc)
        logger.info("%-12s %s", "ollama", "Plays via a local model served by Ollama.")
        return 0
    seats = [parse_seat(spec) for spec in args.players.split(",") if spec.strip()]
    if len(seats) < 2:
        parser.error("need at least two players")
    unknown = sorted({kind for kind, _ in seats} - set(PLAYER_TYPES))
    if unknown:
        parser.error(f"unknown player types: {', '.join(unknown)}")
    rng = random.Random(args.seed)
    if args.headless:
        return run_headless(args, seats, rng)
    return run_visual(args, seats, rng)


if __name__ == "__main__":
    sys.exit(main())
