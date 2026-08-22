"""Maximum auction bids for the FFPL top players.

Converts the FFPL tier-adjusted projections into a maximum price per player
for the live auction, with the standard value-over-replacement method:

1. Replacement level per position = the points of the best player a team
   can still take for free in the draft. With N teams the league rosters
   about N goalkeepers, 5N defenders, 4.5N midfielders and 2.5N forwards,
   so the replacement is the player at that depth in the likely-starter
   pool.
2. A player's surplus = points above replacement, plus a captain premium
   for players good enough to hold a team's armband (points above the
   N-th best player overall, since each team doubles one player).
3. The league's discretionary money, N x (200 - 7 x 4), is shared over
   the auctioned pool (the top 7N surpluses) in proportion to surplus.
   Max bid = 4 (base price) + share, rounded down to whole millions.

By construction the sum of the top 7N max bids equals the league's total
budget, so these are break-even ceilings: pay more and the same money
returns more points somewhere else.

Usage:
    python auction_values.py [--out-dir output] [--teams 6 8 10]
"""

import argparse
import pathlib

import numpy as np
import pandas as pd

BUDGET = 200
AUCTION_SLOTS = 7
BASE_PRICE = 4
POSITION_DEPTH = {"GK": 1.0, "DEF": 5.0, "MID": 4.5, "FWD": 2.5}

# Unmodelled players (no 2025-26 PL minutes) still get rostered and set the
# real replacement level once the modelled pool runs thin. Any such player
# priced 5.0m+ in FPL is market-priced as a starter; value them at a
# discount to the positional starter median, scaled by their club's tier
# multiplier.
PROXY_MIN_PRICE = 5.0
PROXY_DISCOUNT = 0.75
POS_NAME = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def proxy_players(data_dir: pathlib.Path, pool: pd.DataFrame,
                  clubs: pd.DataFrame) -> pd.DataFrame:
    raw = pd.read_csv(data_dir / "current_players_raw.csv")
    teams = pd.read_csv(data_dir / "current_teams.csv")
    unmodelled = raw[(raw.status == "a") & (raw.minutes < 600)
                     & (raw.now_cost >= PROXY_MIN_PRICE * 10)].copy()
    unmodelled["position"] = unmodelled.element_type.map(POS_NAME)
    unmodelled["short_name"] = unmodelled.team.map(
        dict(zip(teams.id, teams.short_name)))
    club_mult = dict(zip(clubs.short_name, clubs.mult_attack))
    base_median = pool.groupby("position").proj_pgw.median()
    unmodelled["ffpl_pgw"] = (
        PROXY_DISCOUNT
        * unmodelled.position.map(base_median)
        * unmodelled.short_name.map(club_mult).fillna(1.0))
    return unmodelled[["position", "ffpl_pgw"]]


def replacement_level(available: pd.DataFrame, teams: int) -> dict:
    """Points of the best free option once the league has filled its quota.

    Computed over ALL available modelled players, not only likely starters:
    the marginal 13th roster spot is routinely a rotation player, and at
    larger league sizes the starter pool alone runs out.
    """
    repl = {}
    for pos, per_team in POSITION_DEPTH.items():
        ranked = (available[available.position == pos]
                  .ffpl_pgw.sort_values(ascending=False))
        depth = int(round(per_team * teams))
        idx = min(depth, len(ranked) - 1)
        repl[pos] = float(ranked.iloc[idx])
    return repl


def max_bids(pool: pd.DataFrame, available: pd.DataFrame, teams: int):
    repl = replacement_level(available, teams)
    surplus = (pool.ffpl_pgw - pool.position.map(repl)).clip(lower=0)

    captain_repl = pool.ffpl_pgw.nlargest(teams).iloc[-1]
    surplus = surplus + (pool.ffpl_pgw - captain_repl).clip(lower=0)

    auction_pool = surplus.nlargest(AUCTION_SLOTS * teams)
    discretionary = teams * (BUDGET - AUCTION_SLOTS * BASE_PRICE)
    per_point = discretionary / auction_pool.sum()

    bids = BASE_PRICE + surplus * per_point
    return np.floor(bids).clip(lower=BASE_PRICE).astype(int), surplus


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data", type=pathlib.Path)
    parser.add_argument("--out-dir", default="output", type=pathlib.Path)
    parser.add_argument("--teams", nargs="+", type=int, default=[6, 8, 10])
    args = parser.parse_args()

    proj = pd.read_csv(args.out_dir / "ffpl_projections.csv")
    clubs = pd.read_csv(args.out_dir / "ffpl_club_tiers.csv")
    pool = proj[proj.likely_starter].reset_index(drop=True)
    available = pd.concat([
        proj[proj.status == "a"][["position", "ffpl_pgw"]],
        proxy_players(args.data_dir, pool, clubs),
    ], ignore_index=True)

    out = pool[["web_name", "short_name", "position", "ffpl_pgw",
                "ffpl_season", "flags"]].copy()
    # First-choice set-piece duties: penalties, direct free kicks, corners.
    out["set_pieces"] = [
        ", ".join(label for label, order in
                  (("PEN", r.penalties_order),
                   ("FK", r.direct_freekicks_order),
                   ("CK", r.corners_and_indirect_freekicks_order))
                  if order == 1)
        for r in pool.itertuples()]
    for n in args.teams:
        out[f"max_bid_{n}_teams"], out[f"surplus_{n}_teams"] = max_bids(
            pool, available, n)
        repl = replacement_level(available, n)
        print(f"{n} teams - replacement level (points each gameweek): "
              + ", ".join(f"{p} {v:.2f}" for p, v in repl.items()))

    # Target priority: order by surplus (mid league size), not raw points -
    # a player is a target for the points no free draft pick can give you.
    mid = args.teams[len(args.teams) // 2]
    out["priority"] = (out[f"surplus_{mid}_teams"]
                       .rank(ascending=False, method="first").astype(int))
    out = out.sort_values("ffpl_pgw", ascending=False)
    out.round(2).to_csv(args.out_dir / "ffpl_max_bids.csv", index=False)

    prio = out[out[f"surplus_{mid}_teams"] > 0].sort_values("priority")
    print(f"\nAuction target priority (surplus points above the free draft "
          f"level, {mid}-team basis):")
    for r in prio.head(20).itertuples():
        print(f"  {r.priority:2d}. {r.web_name:<16} {r.short_name} "
              f"{r.position:<3} surplus {getattr(r, f'surplus_{mid}_teams'):.2f}"
              f"  max bid {getattr(r, f'max_bid_{mid}_teams')}  {r.set_pieces}")

    for pos, count in [("GK", 6), ("DEF", 12), ("MID", 12), ("FWD", 8)]:
        sub = out[out.position == pos].sort_values("ffpl_pgw",
                                                   ascending=False).head(count)
        print(f"\n{pos} board (points/GW, priority, max bid "
              f"{'/'.join(str(n) for n in args.teams)} teams, set pieces):")
        for r in sub.itertuples():
            bids = " / ".join(str(getattr(r, f"max_bid_{n}_teams"))
                              for n in args.teams)
            print(f"   P{r.priority:<3d} {r.web_name:<16} {r.short_name} "
                  f"{r.ffpl_pgw:.2f}  {bids:<14} {r.set_pieces}")

    bid_cols = [f"max_bid_{n}_teams" for n in args.teams]
    print("\nMax bids (millions) for the top 20:")
    for i, r in enumerate(out.head(20).itertuples(), 1):
        bids = " / ".join(f"{getattr(r, c):3d}" for c in bid_cols)
        print(f"  {i:2d}. {r.web_name:<16} {r.short_name} {r.position:<3} "
              f"{r.ffpl_pgw:.2f}/GW   max bid {bids}")

    for n in args.teams:
        top = out.nlargest(AUCTION_SLOTS * n, f"max_bid_{n}_teams")
        print(f"sanity {n} teams: sum of top {AUCTION_SLOTS * n} max bids = "
              f"{top[f'max_bid_{n}_teams'].sum()} "
              f"(league budget {n * BUDGET})")


if __name__ == "__main__":
    main()
