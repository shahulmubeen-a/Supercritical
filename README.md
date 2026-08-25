# InstaGame

A turn-based orb cascade game on a rectangular grid, built as a testbed for
pitting different AI players against each other.

## Rules

- Players take turns placing one orb. A player may only place on an empty cell
  or a cell they already own.
- A cell's **critical mass** is its number of orthogonal neighbours: 2 in a
  corner, 3 on an edge, 4 in the interior.
- On reaching critical mass a cell detonates, sending exactly one orb to each
  neighbour and subtracting the critical mass from itself. Receiving an orb
  converts that cell to the exploding player.
- Detonations can push neighbours over their own critical mass, so a single
  move can set off a chain reaction. It runs until the board settles.
- Turns are strictly sequential. A cascade fully resolves before the next
  player is asked to move.
- A player who has moved and holds no orbs is out. Last player standing wins.

## Running

```bash
uv run instagame
```

Defaults to a 6-wide by 9-tall board with two greedy bots and two random bots.

```bash
uv run instagame --rows 20 --cols 10 --players greedy,greedy,greedy,random
uv run instagame --headless --games 200 --seed 7
```

`--rows` is the board height, `--cols` the width.

### Options

| Flag | Effect |
| --- | --- |
| `--rows`, `--cols` | Board dimensions |
| `--players` | Comma separated seats, see Strategies below |
| `--seed` | Reproducible match |
| `--headless`, `--games` | Simulate without a window and report a win tally |
| `--move-delay` | Seconds between bot turns |
| `--anim-speed` | Animation speed multiplier |
| `--no-animate` | Snap each move to its settled board |
| `--no-blur` | Disable motion blur trails |
| `--no-debug` | Hide the takeover panel |
| `--illegal-retries` | Illegal moves tolerated before a random legal one is substituted |
| `--record` | Write a replay: `.html` for a deployable page, `.json` for raw data |
| `--title` | Title shown on the replay page |

### Controls

`space` pause/resume, `s` single step, `enter` skip the current animation,
`esc` quit.

### Debug takeover

Each seat has an **arm** button. Arming a seat pauses auto-play and lets you
click cells to place for that player. It routes through the same
`Game.apply_move` path a bot uses, so hand-played moves cannot diverge from
real ones. It is a dev tool, not a seat: it does not take part in turn
rotation and can act out of turn.

## Strategies

Eighteen playable strategies ship with the game. Each commits to a single idea
about how to win, so a match between them reads as an argument rather than a set
of tuning variants.

```bash
uv run instagame --list-players
uv run instagame --players sentinel,retaliator,corner,loader
```

**Positional** — look only at the cell and its neighbours, so they cost nothing:

| Name | Idea |
| --- | --- |
| `random` | Uniform over legal moves. The baseline. |
| `greedy` | Capture value against adjacency risk, one move ahead |
| `corner` | Take the cheapest cells to detonate |
| `center` | Build in the interior, where cells hold the most |
| `aggressor` | Detonate into the biggest reachable enemy stack |
| `cautious` | Never sit next to an enemy cell one orb from critical |
| `loader` | Prime cells to one short of critical, then fire when the blast pays or the cell is about to be taken |
| `detonator` | Set something off every turn it can |
| `frontier` | Grow as one connected mass |
| `parity` | Occupy one colour of the checkerboard, interlocking rather than solid |
| `hunter` | Attack whichever opponent is closest to elimination |
| `mirror` | Answer each opponent move with its reflection through the centre |

**Simulating** — play each candidate out on a copy of the board:

| Name | Idea |
| --- | --- |
| `chain` | Longest chain reaction |
| `harvester` | Most own orbs once it settles |
| `territorial` | Most cells held, regardless of orbs in them |
| `spoiler` | Suppress whoever is ahead rather than build |
| `sentinel` | Most armed cells: stored potential to fire next turn |
| `retaliator` | One move deeper, minimising the best reply against it |

### Divisions

Strategies are ranked within their own division, because they do not search the
same amount and it is not a fair table otherwise:

- **Positional** players read the candidate cell and its neighbours. Zero ply.
- **Simulating** players play each candidate out on a copy of the board.
  `retaliator` goes a ply further and models the strongest reply.

The game is deterministic and fully observable, so simulating your own move is
arithmetic a human does in their head rather than hidden information. Still,
comparing zero-ply against two-ply in one table measures search budget as much
as strategy. `uv run instagame --list-players` prints the divisions.

### Positional division

700 four-player games, 6x5, seats drawn at random. Baseline 25%.

| Strategy | Win rate | | Strategy | Win rate |
| --- | --- | --- | --- | --- |
| `loader` | **78.5%** | | `parity` | 17.5% |
| `greedy` | 50.2% | | `corner` | 16.9% |
| `aggressor` | 33.8% | | `cautious` | 9.9% |
| `detonator` | 30.8% | | `mirror` | 9.1% |
| `center` | 26.7% | | `random` | 8.9% |
| `hunter` | 19.8% | | `frontier` | 3.8% |

### Simulating division

400 four-player games, 6x5.

| Strategy | Win rate |
| --- | --- |
| `sentinel` | **44.1%** |
| `retaliator` | 28.0% |
| `spoiler` | 24.5% |
| `harvester` | 21.9% |
| `territorial` | 16.1% |
| `chain` | 15.1% |

### Does searching further actually win?

Not obviously. Best of each division, 200 games with seats rotated every game so
turn order cannot flatter anyone:

| Strategy | Division | Win rate |
| --- | --- | --- |
| `sentinel` | simulating | 39.0% |
| `loader` | positional | 36.0% |
| `greedy` | positional | 14.5% |
| `retaliator` | simulating | 10.5% |

A zero-ply player is level with the best simulator, and a second zero-ply player
beats the two-ply one. Picking the right thing to measure matters more here than
looking further ahead.

### Board size changes the answer

Ranked across all strategies together, `chain` goes from 42.8% on 6x5 to 68.2%
on 20x10 while `sentinel` falls from 59.9% to 39.1%. Small boards saturate fast,
so holding threat everywhere decides them; on 200 cells with games running
around 390 turns, cascade reach and accumulation pay instead. Any conclusion
here is a conclusion about a board size.

The 20x10 figures come from 120 games, roughly 20 to 40 per strategy, so treat
them as directional. The 6x5 tables are far firmer.

## Replays

Any match can be recorded and played back later:

```bash
uv run instagame --headless --rows 6 --cols 5 --record replays/match.html \
  --title "loader vs sentinel" \
  --players loader,sentinel,greedy,random
```

That writes a single self-contained HTML file with the replay embedded: no
server, no dependencies, no network requests. Open it from disk, drop it on
GitHub Pages, or publish it anywhere static. A 50-turn 6x5 match is about 64KB.

The page replays the match with the same animations as the live renderer, plus
a scrubbable timeline, per-turn stepping and speed control. `--record
match.json` writes the raw data instead if you want to analyse matches rather
than watch them.

Recording works for visual matches too, so you can watch live and keep the
replay.

A replay stores the board snapshots the engine produced, not just the moves. The
viewer therefore never reimplements the rules and cannot drift from the engine.

To preview locally:

```bash
python3 -m http.server 8777
```

Then open `http://localhost:8777/replays/match.html`. Opening the file directly
with a `file://` URL works too.

## Adding a player

Subclass `Player` and implement `choose_move`. The engine validates whatever
comes back, retrying and then substituting a random legal move, so a slow or
unreliable player cannot corrupt the game state.

```python
from instagame.players.base import Player

class MyPlayer(Player):
    def choose_move(self, board):
        return board.legal_moves(self.player_id)[0]
```

Register it in `PLAYER_TYPES` in `src/instagame/players/__init__.py` to make it
selectable from `--players`, and set `tier` so it is ranked against players that
search as far as it does. The engine validates whatever a player returns and
never trusts it: an illegal move is retried, then replaced with a random legal
one, so a buggy player degrades the quality of play rather than corrupting the
game.

For a strategy that scores candidate moves, subclass `ScoringPlayer` and
implement `score`; to judge moves by playing them out, subclass
`SimulatingPlayer` and implement `rate`. See
`src/instagame/players/strategies.py`.

## Development

```bash
uv run pytest
uv run ruff check .
uv run black .
```
