# Supercritical — working notes

Guidance for Claude Code sessions in this repository. Read this before making
changes.

## What this is

A turn-based orb cascade game on a rectangular grid, used as a testbed for
comparing heuristic strategies. Pure Python plus pygame-ce. No network calls,
no external services, no API keys.

## Commands

```bash
uv sync                      # install
uv run supercritical         # play a visual match
uv run pytest                # tests
uv run ruff check .          # lint
uv run black .               # format
uv run supercritical --list-players
```

Tests that touch pygame need a display. In headless environments set
`SDL_VIDEODRIVER=dummy`, which is what CI does.

## Architecture

The engine knows nothing about how it is displayed or who is playing.

| Module | Responsibility |
| --- | --- |
| `board.py` | Grid state, critical mass, cascade resolution |
| `game.py` | Turn order, elimination, win detection |
| `players/base.py` | The `Player` interface the engine talks to |
| `players/strategies.py` | The eighteen strategies |
| `players/tactics.py` | Shared scoring helpers and move simulation |
| `animation.py` | Turns a settled move into a timeline of phases |
| `render.py` | Pygame front end. The only pygame-dependent module |
| `replay.py` | Records matches |
| `viewer.py`, `viewer_template.html` | Builds a standalone replay page |
| `cli.py` | Argument parsing, visual and headless entry points |

Three invariants worth protecting:

1. **Orbs are conserved.** A cell reaching critical mass sends one orb to each
   neighbour and subtracts that mass from itself. Never reset the source to
   zero: a cell can receive several orbs mid-cascade.
2. **The engine never trusts a player.** An illegal move is retried, then
   replaced with a random legal one. Do not move validation into players.
3. **Turns are atomic.** A cascade fully resolves before the next player is
   asked to move. `Game.step()` does not return early.

## The cascade can run forever

If one player owns every orb on a saturated board, the cascade never settles.
Two layers guard this, and both matter:

- `Game` ends the match the instant only one player remains in contention, and
  that check runs *inside* the cascade loop, not after it.
- `Board.place` takes a `max_steps` ceiling as a backstop. If it ever fires,
  the first layer has a bug.

For simulation, the condition is decidable up front: orbs are conserved, so a
cascade can only run forever when the board holds more than
`Board.stable_capacity()`. Do not reintroduce a "stop when one player leads"
check — it truncates ordinary cascades and silently corrupts every simulating
strategy's scoring.

## Adding a strategy

Subclass `ScoringPlayer` and implement `score`, or `SimulatingPlayer` and
implement `rate`. Register it in `PLAYER_TYPES` and set `tier` so it is ranked
against players that search as far as it does. Strategies must not mutate the
board; `tactics.simulate` snapshots and restores for you. There is a test that
enforces both.

## Conventions

- Numpy-style docstrings on public functions and classes.
- No `print`. Use `logging_config.get_logger`.
- No decorative comment banners.
- Comments explain *why*, not what. Prefer none over restating the code.
- `black` and `ruff` are authoritative; line length 100.
- Write tests. If you deliberately skip them, say so and why.

## Branching

`main` <- `release` <- `develop` <- feature branch. Never commit directly to
`main` or `develop`; cut a branch named `feat/`, `fix/`, `chore/`, `refactor/`,
`docs/` or `test/`. Merges happen as pull requests on GitHub, not locally.
Never push without being asked. Commit subjects are one line.

## Gotchas

- `--rows` is board height, `--cols` is width. A 10 wide by 20 tall board is
  `--rows 20 --cols 10`.
- Strategy win rates are only meaningful at a stated board size. `chain` is
  last in its division on 6x5 and near the top on 20x10.
- Replays store board snapshots rather than just moves, so the viewer cannot
  drift from the engine. Keep it that way.
- The replay page must stay self-contained: no external requests, no web fonts.
  A test asserts this.
