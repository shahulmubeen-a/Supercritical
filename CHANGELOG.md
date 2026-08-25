# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-08-25

First stable release. The engine, both front ends and the full strategy roster
are in place, and the public surface is now covered by semantic versioning.

### Added

- **Game engine.** Rectangular grid where each cell's critical mass is its
  number of orthogonal neighbours. Reaching it sends one orb to each neighbour
  and subtracts that mass from the source, so the orb count is conserved and
  chain reactions resolve deterministically.
- **Sequential turn engine** with elimination, win detection and a two-layer
  guard against the runaway cascade that occurs once a single player owns every
  orb. The primary guard ends the game inside the cascade loop the moment only
  one player remains in contention; a step ceiling sits behind it as a backstop.
- **Eighteen strategies** across two search tiers. Positional players read only
  the candidate cell and its neighbours: `random`, `greedy`, `corner`, `center`,
  `aggressor`, `cautious`, `loader`, `detonator`, `frontier`, `parity`,
  `hunter`, `mirror`. Simulating players play candidates out on a copy of the
  board: `chain`, `harvester`, `territorial`, `spoiler`, `sentinel`,
  `retaliator`.
- **Pygame front end** with cubic-eased orb flight, motion-blur trails,
  shockwave rings and a debug takeover panel that lets you place cells as any
  seat through the same code path a bot uses.
- **Replay recording.** `--record` writes either a single self-contained HTML
  page that replays the match with the same animations, a scrubbable timeline
  and per-turn stepping, or raw JSON for analysis. Replays store the engine's
  own board snapshots, so a viewer never reimplements the rules and cannot
  drift from them.
- **Headless mode** for fast simulation and tournaments, reporting a win tally.
- `--list-players` prints every strategy with its search tier.
- Proprietary licence, changelog, continuous integration and project notes
  for Claude Code sessions.

### Changed

- Renamed the Python package from `instagame` to `supercritical`, matching the
  game. The console script is now `supercritical`.
- `loader` no longer refuses to fire. It primes cells to one below critical and
  aims them at opponent orbs, then pulls the trigger when the blast is worth
  taking or when an adjacent opponent is about to capture the primed cell
  anyway. Its win rate in the positional division went from 1.7% to 78.5%.
- Strategies now declare a `tier` and are ranked within their own division,
  because comparing a zero-ply player against a two-ply one measures search
  budget as much as strategy.
- Replay format is version 2: the per-model `stats`, `latency` and `reason`
  fields are gone with the model backend that populated them.

### Removed

- **The Ollama and language-model player backend**, along with its client,
  player class, five CLI flags and the model statistics panel. The project now
  ships only deterministic strategies.

### Fixed

- Simulated cascades were being truncated by an over-eager guard that fired
  whenever a single player happened to lead, so every simulating strategy was
  scoring against a half-resolved board. A cascade can only run forever when the
  board holds more orbs than `sum(critical_mass - 1)`, which is decidable up
  front because orbs are conserved.
- `mirror` forgot its target when its turn hook ran twice.
- `greedy` subtracted an adjacency-risk penalty from moves that detonate, even
  though detonating converts the very neighbour posing the risk, so it was
  declining free captures.
- The replay viewer rendered blank in a background tab, because
  `requestAnimationFrame` does not fire while a tab is hidden. It now paints
  once synchronously and relays out on resize and visibility change.
- The replay viewer painted no canvas background of its own, so an exported or
  saved frame lost the page's colours.
- The side panel's status and statistics blocks could overlap the shortcut
  hints on a short window.

[Unreleased]: https://github.com/shahulmubeen-a/Supercritical-AI/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/shahulmubeen-a/Supercritical-AI/releases/tag/v1.0.0
