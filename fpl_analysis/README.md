# FPL 2026-27 Player Recommendations

A data-science-backed player list for the 2026-27 Fantasy Premier League
season, generated from official FPL API data (via the
[vaastav/Fantasy-Premier-League](https://github.com/vaastav/Fantasy-Premier-League)
open dataset, a daily mirror of `https://fantasy.premierleague.com/api/`).

**The headline output is [`output/REPORT.md`](output/REPORT.md)** — ranked
players per position, best-value picks, budget enablers, two optimized £100m
squads, a watchlist and known caveats. The full per-player projection with
every model component is in
[`output/player_projections.csv`](output/player_projections.csv).

## How it works

1. `fetch_data.py` downloads five snapshots into `data/`:
   2026-27 players/teams/fixtures (prices, current clubs, availability,
   penalty takers, fixture difficulty) and 2025-26 players/teams (a full
   season of performance data).
2. `analyze.py` projects expected FPL points per gameweek for every player
   with at least 600 league minutes last season:
   - **Attacking** — a 60/40 blend of expected (xG, xA) and actual
     goal/assist rates, so finishing over-performance regresses.
   - **Clean sheets** — Poisson zero-goal probability from each *club's*
     defensive quality last season (main keeper's xG-conceded per 90),
     blended with realised clean-sheet rate, applied to the player's
     current club.
   - **Defensive contributions** — Poisson probability of clearing the
     per-match CBIT/CBIRT threshold (10 defenders / 12 midfielders-forwards).
   - **Appearance, saves, bonus, cards, goals conceded** — from last
     season's rates.
   - All per-90 rates are shrunk toward positional medians (K = 600
     effective minutes) so small samples don't dominate; expected minutes
     come from last season's share.
   - A fixture-difficulty multiplier over gameweeks 1-6 produces a
     separate early-season column.
3. The 15-man squad is solved as an integer program (PuLP/CBC): maximize
   starting-XI projected points plus 0.15x bench, subject to the £100.0m
   budget, 2 GK / 5 DEF / 5 MID / 3 FWD, max 3 per club and legal
   formations. A second run anchors the premium captaincy option.

## Run it

```bash
pip install -r requirements.txt
python fetch_data.py   # refresh data/ (optional; a snapshot is committed)
python analyze.py      # writes output/REPORT.md and the CSVs
```

Snapshot committed here: pre-season 2026-27 prices and availability as of
2026-08-21, the day of the gameweek 1 kickoff.
