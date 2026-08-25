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
| `--players` | Comma separated seats: `random`, `greedy` |
| `--seed` | Reproducible match |
| `--headless`, `--games` | Simulate without a window and report a win tally |
| `--move-delay` | Seconds between bot turns |
| `--anim-speed` | Animation speed multiplier |
| `--no-animate` | Snap each move to its settled board |
| `--no-blur` | Disable motion blur trails |
| `--no-debug` | Hide the takeover panel |

### Controls

`space` pause/resume, `s` single step, `enter` skip the current animation,
`esc` quit.

### Debug takeover

Each seat has an **arm** button. Arming a seat pauses auto-play and lets you
click cells to place for that player. It routes through the same
`Game.apply_move` path a bot uses, so hand-played moves cannot diverge from
real ones. It is a dev tool, not a seat: it does not take part in turn
rotation and can act out of turn.

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
selectable from `--players`.

## Development

```bash
uv run pytest
uv run ruff check .
uv run black .
```
