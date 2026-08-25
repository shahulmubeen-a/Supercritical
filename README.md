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
| `--ollama-host` | Ollama base URL, defaults to `$OLLAMA_HOST` then localhost |
| `--llm-timeout` | Seconds to wait for a model move |
| `--llm-temperature` | Sampling temperature |
| `--llm-explain` | Ask models for a one line reason, shown in the panel |

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
| `loader` | Stockpile: fill cells to one short of critical |
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

### Results

800 four-player games on a 6x5 board, seats drawn at random. Baseline is 25%.

| Strategy | Win rate | | Strategy | Win rate |
| --- | --- | --- | --- | --- |
| `sentinel` | **59.9%** | | `detonator` | 17.1% |
| `retaliator` | 49.4% | | `parity` | 17.0% |
| `greedy` | 43.7% | | `corner` | 10.9% |
| `chain` | 42.8% | | `random` | 10.7% |
| `harvester` | 41.3% | | `mirror` | 8.2% |
| `spoiler` | 38.4% | | `cautious` | 8.1% |
| `aggressor` | 30.8% | | `frontier` | 6.0% |
| `territorial` | 30.0% | | `loader` | 1.7% |
| `center` | 19.7% | | | |
| `hunter` | 19.3% | | | |

Reproduce with any four names on `--players`, or read the tournament as a
statement about the game: stored potential beats spent potential. `sentinel`
wins by keeping the board armed and letting opponents commit first, while
`loader`, which also stockpiles but never fires, comes last. Holding the threat
is worth more than either hoarding or discharging it.

## Model players

Seats can be driven by local models through [Ollama](https://ollama.com). No API
key and no extra Python dependency: the client is built on the standard library.

```bash
ollama serve
ollama pull gemma3:4b
```

Then name a model on any seat. The seat spec splits on its first colon only, so
model tags keep theirs:

```bash
uv run instagame --rows 6 --cols 5 --llm-explain \
  --players ollama:gemma3:4b,ollama:qwen3.5:4b,ollama:llama3.2:3b,ollama:phi4-mini
```

Missing models and an unreachable server are caught before the match starts.

### Making it bearable

Model moves run on a worker thread, so the window keeps animating and the panel
shows who is thinking and for how long. Measured on a 31GB CPU-only box with a
small board, warm:

| Tier | Latency per move | Four models resident |
| --- | --- | --- |
| ~1B | ~2s | ~4GB |
| ~4B | ~7s | ~12GB |
| ~9B | ~14s | ~24GB, will not fit |

Two things matter far more than model choice:

- **Keep the board small.** A 6x5 board finishes in tens of turns. Turn count
  grows with area, so 20x10 at seven seconds a move is an afternoon.
- **Keep every model resident.** Ollama unloads models to stay under its limit,
  and a reload costs more than the move itself. Raise the cap before starting:

  ```bash
  OLLAMA_MAX_LOADED_MODELS=4 OLLAMA_KEEP_ALIVE=30m ollama serve
  ```

### How a model is asked

Each turn it gets a fixed system prompt with the rules, then a board table where
every cell reads `owner count/capacity`, so capacities never have to be inferred.
The legal move list is enumerated outright, and Ollama's structured output holds
the reply to a JSON schema.

Responses are still messy in practice. Models truncate mid-explanation and leave
the JSON unterminated, so the parser falls back to scanning for the coordinate
fields rather than throwing the turn away. Genuinely illegal moves are retried,
then replaced with a random legal move, and both are counted per model:

```
gemma3:4b: 48 calls, 5.2s avg, 1 illegal, 0 errors
```

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
selectable from `--players`. `OllamaPlayer` is the worked example: the engine
validates whatever a player returns and never trusts it, so a slow or unreliable
one degrades the quality of play rather than corrupting the game.

## Development

```bash
uv run pytest
uv run ruff check .
uv run black .
```
