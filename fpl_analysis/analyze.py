"""Data-science-backed FPL player recommendations for the 2026-27 season.

Builds an expected-points-per-gameweek projection for every player from last
season's underlying rates (expected goals/assists, defensive contributions,
minutes, bonus, cards) applied to this season's prices, clubs and fixtures,
then solves the 15-man squad selection as an integer program.

Model outline (all rates are per-90, shrunk toward positional priors):

  E[pts/GW] = appearance
            + attacking      blend of actual G+A rates and xG/xA rates
            + clean sheets   Poisson P(0 conceded) from the current club's
                             defensive quality (main keeper's xGC/90)
            + def. contrib.  Poisson P(reaching the CBIT/CBIRT threshold)
            + saves          keepers only
            + bonus          historical rate, shrunk
            - conceded/cards expected deductions

Shrinkage: every per-90 rate is regressed toward the positional median of
established players with weight K=600 effective minutes, so small-sample
hot streaks do not top the rankings.

Scoring values assume the 2025-26 rules carry into 2026-27 (goal: 6/6/5/4 by
position, assist 3, clean sheet 4/4/1, defensive contribution +2 at 10 CBIT
for defenders / 12 CBIRT for midfielders and forwards, saves 1 per 3,
-1 per 2 conceded for GK/DEF).

Usage:
    python analyze.py [--data-dir data] [--out-dir output]
"""

import argparse
import math
import pathlib

import numpy as np
import pandas as pd

POS_NAME = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
GOAL_PTS = {1: 6, 2: 6, 3: 5, 4: 4}
CS_PTS = {1: 4, 2: 4, 3: 1, 4: 0}
DEFCON_THRESHOLD = {2: 10, 3: 12, 4: 12}  # per-match CBIT / CBIRT threshold

MIN_MINUTES = 600        # last-season minutes required to be modelled
SHRINK_K = 600           # effective minutes of prior mixed into each rate
XG_BLEND = 0.6           # weight on expected (xG/xA) vs actual returns
BENCH_WEIGHT = 0.15      # optimizer value of a bench seat vs a starting one
PROMOTED_XGC90 = 1.75    # default xG-conceded/90 for clubs with no PL data
FIXTURE_SWING = 0.05     # +/- proj share per point of fixture difficulty
BUDGET = 1000            # 100.0m in FPL tenths
SQUAD_SHAPE = {1: 2, 2: 5, 3: 5, 4: 3}


def poisson_sf(threshold: int, mean: float) -> float:
    """P(N >= threshold) for N ~ Poisson(mean)."""
    if mean <= 0:
        return 0.0
    p, total = math.exp(-mean), math.exp(-mean)
    for k in range(1, threshold):
        p *= mean / k
        total += p
    return max(0.0, 1.0 - total)


def expected_conceded_deduction(mean: float) -> float:
    """E[floor(N/2)] for N ~ Poisson(mean): the -1 per 2 conceded rule."""
    p = math.exp(-mean)
    total = 0.0
    for k in range(1, 12):
        p *= mean / k
        total += math.floor(k / 2) * p
    return total


def load(data_dir: pathlib.Path) -> dict:
    return {
        "players": pd.read_csv(data_dir / "current_players_raw.csv"),
        "teams": pd.read_csv(data_dir / "current_teams.csv"),
        "fixtures": pd.read_csv(data_dir / "current_fixtures.csv"),
        "prev_players": pd.read_csv(data_dir / "previous_players_raw.csv"),
        "prev_teams": pd.read_csv(data_dir / "previous_teams.csv"),
    }


def team_context(d: dict) -> pd.DataFrame:
    """Per-club defensive quality and early-season fixture ease."""
    teams = d["teams"][["id", "name", "short_name"]].copy()

    # Defensive quality of the CLUB last season, proxied by the keeper who
    # played most minutes for it, then mapped to this season's clubs by name.
    # (Mapping via the current keeper would import his old club's defence -
    # e.g. a keeper signed from a relegated side would drag his new club down.)
    prev, prev_teams = d["prev_players"], d["prev_teams"]
    club_of = dict(zip(prev_teams.id, prev_teams.short_name))
    gk = prev[prev.element_type == 1].copy()
    gk["short_name"] = gk.team.map(club_of)
    main_gk = gk.sort_values("minutes", ascending=False).groupby("short_name").head(1)
    gk_games = (main_gk.minutes / 90).clip(lower=1)
    ctx = teams.merge(
        pd.DataFrame({
            "short_name": main_gk.short_name.values,
            "xgc90": main_gk.expected_goals_conceded_per_90.values,
            "gk_cs_rate": (main_gk.clean_sheets / gk_games).values,
            "gk_minutes": main_gk.minutes.values,
        }),
        on="short_name", how="left",
    )
    no_data = (ctx.gk_minutes.fillna(0) < MIN_MINUTES) | (ctx.xgc90.fillna(0) <= 0)
    ctx.loc[no_data, "xgc90"] = PROMOTED_XGC90
    ctx.loc[no_data, "gk_cs_rate"] = math.exp(-PROMOTED_XGC90)
    # Blend the Poisson estimate with the keeper's realised CS rate.
    ctx["cs_prob"] = 0.5 * np.exp(-ctx.xgc90) + 0.5 * ctx.gk_cs_rate.clip(0, 0.7)

    fx = d["fixtures"]
    early = fx[fx.event <= 6]
    diff = pd.concat([
        early[["team_h", "team_h_difficulty"]].rename(
            columns={"team_h": "id", "team_h_difficulty": "fdr"}),
        early[["team_a", "team_a_difficulty"]].rename(
            columns={"team_a": "id", "team_a_difficulty": "fdr"}),
    ])
    ctx = ctx.merge(diff.groupby("id").fdr.mean().rename("fdr_next6"),
                    on="id", how="left")
    ctx["fixture_mult"] = 1 + FIXTURE_SWING * (3.0 - ctx.fdr_next6.fillna(3.0))
    return ctx


def shrunk_rate(raw_per90: pd.Series, minutes: pd.Series,
                prior: pd.Series) -> pd.Series:
    return (minutes * raw_per90 + SHRINK_K * prior) / (minutes + SHRINK_K)


def build_projections(d: dict) -> pd.DataFrame:
    ctx = team_context(d)
    p = d["players"].copy()
    p["position"] = p.element_type.map(POS_NAME)
    p["price"] = p.now_cost / 10
    p = p.merge(ctx[["id", "short_name", "cs_prob", "xgc90",
                     "fdr_next6", "fixture_mult"]],
                left_on="team", right_on="id", how="left",
                suffixes=("", "_team"))

    # Flag summer club changes: compare last season's final club (by name)
    # with the current one via the permanent player code.
    prev = d["prev_players"][["code", "team"]].merge(
        d["prev_teams"][["id", "short_name"]].rename(
            columns={"id": "team", "short_name": "prev_club"}),
        on="team", how="left")
    p = p.merge(prev[["code", "prev_club"]], on="code", how="left")
    p["new_club"] = p.prev_club.notna() & (p.prev_club != p.short_name)

    modelled = p[p.minutes >= MIN_MINUTES].copy()
    m90 = modelled.minutes / 90

    for col, raw in [
        ("g90", modelled.goals_scored / m90),
        ("a90", modelled.assists / m90),
        ("xg90", modelled.expected_goals / m90),
        ("xa90", modelled.expected_assists / m90),
        ("dc90", modelled.defensive_contribution / m90),
        ("sv90", modelled.saves / m90),
        ("bonus90", modelled.bonus / m90),
        ("yc90", modelled.yellow_cards / m90),
        ("rc90", modelled.red_cards / m90),
    ]:
        modelled[f"raw_{col}"] = raw

    established = modelled[modelled.minutes >= 1500]
    for col in ["g90", "a90", "xg90", "xa90", "dc90", "sv90",
                "bonus90", "yc90", "rc90"]:
        prior = established.groupby("element_type")[f"raw_{col}"].median()
        modelled[col] = shrunk_rate(
            modelled[f"raw_{col}"], modelled.minutes,
            modelled.element_type.map(prior).fillna(0))

    modelled["exp_mins_gw"] = (modelled.minutes / 38).clip(upper=90)
    exposure = modelled.exp_mins_gw / 90
    p60 = (modelled.exp_mins_gw / 85).clip(upper=1.0)

    goal_pts = modelled.element_type.map(GOAL_PTS)
    attack_blend = (
        XG_BLEND * (modelled.xg90 * goal_pts + modelled.xa90 * 3)
        + (1 - XG_BLEND) * (modelled.g90 * goal_pts + modelled.a90 * 3))
    modelled["attack_pts"] = attack_blend * exposure

    cs_value = modelled.element_type.map(CS_PTS)
    modelled["cs_pts"] = cs_value * modelled.cs_prob * p60

    is_backline = modelled.element_type.isin([1, 2])
    modelled["conceded_pts"] = -is_backline * exposure * modelled.xgc90.map(
        expected_conceded_deduction)

    thresholds = modelled.element_type.map(DEFCON_THRESHOLD)
    modelled["defcon_pts"] = [
        2 * poisson_sf(int(t), dc) * p6 if t == t else 0.0
        for t, dc, p6 in zip(thresholds, modelled.dc90, p60)]

    modelled["save_pts"] = modelled.sv90 / 3 * exposure
    modelled["bonus_pts"] = modelled.bonus90 * 0.85 * exposure
    modelled["card_pts"] = -(modelled.yc90 + 3 * modelled.rc90) * exposure
    appearance = np.where(modelled.exp_mins_gw >= 55,
                          2 * (modelled.exp_mins_gw / 85).clip(upper=1.0),
                          modelled.exp_mins_gw / 55)
    modelled["appearance_pts"] = appearance

    modelled["proj_pgw"] = (
        modelled.appearance_pts + modelled.attack_pts + modelled.cs_pts
        + modelled.conceded_pts + modelled.defcon_pts + modelled.save_pts
        + modelled.bonus_pts + modelled.card_pts)
    modelled["proj_season"] = modelled.proj_pgw * 38
    modelled["value"] = modelled.proj_pgw / modelled.price
    # Fixture-adjusted expectation for the opening six gameweeks: schedule
    # strength moves attacking and clean-sheet output, not the rest.
    modelled["proj_next6_pgw"] = (
        modelled.proj_pgw
        + (modelled.attack_pts + modelled.cs_pts) * (modelled.fixture_mult - 1))

    # A keeper priced below his club's most expensive fit keeper is not
    # priced as the #1: his minutes (from last season, possibly elsewhere)
    # may not carry over.
    fit_gk = p[(p.element_type == 1) & p.status.isin(["a", "d"])]
    top_gk_price = fit_gk.groupby("team").now_cost.max()
    modelled["gk_competition"] = (
        (modelled.element_type == 1)
        & (modelled.now_cost < modelled.team.map(top_gk_price)))

    flags = []
    for r in modelled.itertuples():
        f = []
        if r.penalties_order == 1:
            f.append("PEN")
        if r.new_club:
            f.append("NEW-CLUB")
        if r.gk_competition:
            f.append("GK-RISK")
        if r.status == "d":
            chance = r.chance_of_playing_next_round
            f.append(f"DOUBT-{int(chance)}%" if chance == chance else "DOUBT")
        flags.append(", ".join(f))
    modelled["flags"] = flags
    return modelled


def optimize_squad(modelled: pd.DataFrame, force_codes=()):
    """15-man squad MILP: max XI points + weighted bench, standard FPL rules."""
    import pulp

    pool = modelled[modelled.status.isin(["a", "d"])].copy()
    pool = (pool.sort_values("proj_pgw", ascending=False)
            .groupby("element_type").head(40).reset_index(drop=True))

    prob = pulp.LpProblem("fpl_squad", pulp.LpMaximize)
    in_squad = pulp.LpVariable.dicts("squad", pool.index, cat="Binary")
    starts = pulp.LpVariable.dicts("start", pool.index, cat="Binary")

    prob += pulp.lpSum(
        starts[i] * pool.proj_pgw[i]
        + (in_squad[i] - starts[i]) * BENCH_WEIGHT * pool.proj_pgw[i]
        for i in pool.index)

    prob += pulp.lpSum(in_squad[i] * pool.now_cost[i] for i in pool.index) <= BUDGET
    prob += pulp.lpSum(starts[i] for i in pool.index) == 11
    for i in pool.index:
        prob += starts[i] <= in_squad[i]
    for etype, count in SQUAD_SHAPE.items():
        idx = pool.index[pool.element_type == etype]
        prob += pulp.lpSum(in_squad[i] for i in idx) == count
    gk = pool.index[pool.element_type == 1]
    prob += pulp.lpSum(starts[i] for i in gk) == 1
    defs = pool.index[pool.element_type == 2]
    prob += pulp.lpSum(starts[i] for i in defs) >= 3
    fwds = pool.index[pool.element_type == 4]
    prob += pulp.lpSum(starts[i] for i in fwds) >= 1
    for team in pool.team.unique():
        idx = pool.index[pool.team == team]
        prob += pulp.lpSum(in_squad[i] for i in idx) <= 3
    for code in force_codes:
        idx = pool.index[pool.code == code]
        if len(idx):
            prob += in_squad[idx[0]] == 1

    prob.solve(pulp.PULP_CBC_CMD(msg=0))
    if pulp.LpStatus[prob.status] != "Optimal":
        return None

    squad = pool[[in_squad[i].value() == 1 for i in pool.index]].copy()
    squad["starter"] = [starts[i].value() == 1 for i in squad.index]
    return squad.sort_values(["starter", "element_type", "proj_pgw"],
                             ascending=[False, True, False])


def watchlist(d: dict) -> pd.DataFrame:
    """Players the model cannot score: no meaningful PL minutes last season."""
    p = d["players"]
    teams = dict(zip(d["teams"].id, d["teams"].short_name))
    w = p[(p.minutes < MIN_MINUTES) & (p.status == "a")
          & ((p.now_cost >= 60) | (p.penalties_order == 1))].copy()
    w["club"] = w.team.map(teams)
    w["price"] = w.now_cost / 10
    w["position"] = w.element_type.map(POS_NAME)
    w["pens"] = np.where(w.penalties_order == 1, "PEN", "")
    return w.sort_values("now_cost", ascending=False)


def fmt_table(df: pd.DataFrame, cols: dict) -> str:
    out = df[list(cols)].rename(columns=cols)
    for c in out.columns:
        if out[c].dtype.kind == "f":
            out[c] = out[c].round(2)
    header = "| " + " | ".join(out.columns) + " |"
    sep = "|" + "|".join("---" for _ in out.columns) + "|"
    rows = ["| " + " | ".join(str(v) for v in r) + " |"
            for r in out.itertuples(index=False)]
    return "\n".join([header, sep] + rows)


LIST_COLS = {
    "web_name": "Player", "short_name": "Club", "price": "£m",
    "proj_pgw": "Proj pts/GW", "proj_season": "Proj season",
    "value": "Pts/GW per £m", "fdr_next6": "Next-6 FDR", "flags": "Flags",
}


def write_report(modelled, squads, watch, d, out_dir: pathlib.Path) -> str:
    lines = ["# FPL 2026-27: Data-Backed Player Recommendations", ""]
    lines.append(
        "Projections built from 2025-26 underlying rates (xG, xA, defensive "
        "contributions, minutes) applied to 2026-27 prices, clubs and opening "
        "fixtures. See `analyze.py` docstring for the model; all numbers are "
        "expected FPL points per gameweek.")
    lines.append("")

    # Ranked lists show only players currently available or merely doubtful;
    # injured/suspended/unavailable ones are surfaced in their own section.
    top = (modelled[modelled.status.isin(["a", "d"])]
           .sort_values("proj_pgw", ascending=False))
    lines += ["## Top 20 overall", "", fmt_table(top.head(20), LIST_COLS), ""]

    for etype, label, n in [(1, "Goalkeepers", 8), (2, "Defenders", 12),
                            (3, "Midfielders", 15), (4, "Forwards", 10)]:
        sub = top[top.element_type == etype].head(n)
        lines += [f"## {label}", "", fmt_table(sub, LIST_COLS), ""]

    lines += ["## Best value (projected points per gameweek per £m)", ""]
    nailed = top[(top.exp_mins_gw >= 60) & (top.status == "a")]
    lines += [fmt_table(nailed.sort_values("value", ascending=False).head(15),
                        LIST_COLS), ""]

    lines += ["## Budget enablers", ""]
    cheap = pd.concat([
        nailed[(nailed.element_type == 1) & (nailed.price <= 4.5)].head(3),
        nailed[(nailed.element_type == 2) & (nailed.price <= 4.5)].head(5),
        nailed[(nailed.element_type == 3) & (nailed.price <= 5.5)].head(5),
        nailed[(nailed.element_type == 4) & (nailed.price <= 6.0)].head(3),
    ])
    lines += [fmt_table(cheap, LIST_COLS), ""]

    for title, note, squad in squads:
        if squad is None:
            continue
        cost = squad.now_cost.sum() / 10
        xi = squad[squad.starter]
        proj = xi.proj_pgw.sum()
        shape = xi.element_type.value_counts()
        formation = f"{shape.get(2, 0)}-{shape.get(3, 0)}-{shape.get(4, 0)}"
        lines += [
            f"## {title}", "",
            f"Formation {formation}, cost £{cost:.1f}m, "
            f"projected {proj:.1f} pts/GW from the starting XI "
            f"(~{proj * 38:.0f} over the season before transfers/captaincy). "
            f"{note}",
            "",
            "**Starting XI**", "",
            fmt_table(xi, {**LIST_COLS, "position": "Pos"}), "",
            "**Bench**", "",
            fmt_table(squad[~squad.starter], {**LIST_COLS, "position": "Pos"}),
            ""]

    lines += [
        "## Watchlist: under 600 PL minutes last season, model cannot score them", "",
        "New signings from abroad, promoted-club players and injury returners. "
        "Priced-up or on penalties, so the market expects output - judge on "
        "eye test and preseason, not this model.", "",
        fmt_table(watch.head(15), {
            "web_name": "Player", "club": "Club", "position": "Pos",
            "price": "£m", "pens": "Pens"}), ""]

    unavailable = d["players"][
        (d["players"].status.isin(["i", "s", "u"]))
        & (d["players"].now_cost >= 55)
        & (d["players"].minutes >= MIN_MINUTES)]
    if len(unavailable):
        teams = dict(zip(d["teams"].id, d["teams"].short_name))
        u = unavailable[["web_name", "team", "now_cost", "news"]].copy()
        u["club"] = u.team.map(teams)
        u["price"] = u.now_cost / 10
        lines += ["## Notable unavailable players (excluded above)", "",
                  fmt_table(u.sort_values("now_cost", ascending=False).head(10),
                            {"web_name": "Player", "club": "Club",
                             "price": "£m", "news": "News"}), ""]

    lines += [
        "## Caveats", "",
        "- Rates come from 2025-26; a player's role can change with a new "
        "club or manager (`NEW-CLUB` flag).",
        "- Promoted clubs (Coventry, Hull, Ipswich) and new signings have no "
        "PL sample: they appear only on the watchlist.",
        "- Clean-sheet odds use last season's defensive quality mapped to "
        "the player's *current* club.",
        "- Penalty duty is flagged (`PEN`) but not separately added to the "
        "projection, since last season's xG already contains penalty xG.",
        "- Expected minutes come from last season and do not know about "
        "preseason pecking-order changes; `GK-RISK` marks keepers not "
        "priced as their club's #1.",
        "- Scoring rules assumed unchanged from 2025-26.", ""]

    report = "\n".join(lines)
    (out_dir / "REPORT.md").write_text(report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data", type=pathlib.Path)
    parser.add_argument("--out-dir", default="output", type=pathlib.Path)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    d = load(args.data_dir)
    modelled = build_projections(d)

    export_cols = [
        "web_name", "short_name", "position", "price", "proj_pgw",
        "proj_season", "proj_next6_pgw", "value", "exp_mins_gw", "attack_pts",
        "cs_pts", "defcon_pts", "save_pts", "bonus_pts", "appearance_pts",
        "conceded_pts", "card_pts", "xg90", "xa90", "dc90", "cs_prob",
        "fdr_next6", "selected_by_percent", "status", "flags"]
    (modelled.sort_values("proj_pgw", ascending=False)[export_cols]
     .round(3)
     .to_csv(args.out_dir / "player_projections.csv", index=False))

    squads = []
    try:
        squad = optimize_squad(modelled)
        squads.append((
            "Optimized £100m squad (integer program)",
            "Pure sum-of-points optimum: it spreads the budget rather than "
            "paying up for one premium.", squad))
        # Second build anchored on the most expensive available player, who
        # is also the natural every-week captain (captaincy doubles his
        # points, which the sum-of-points objective does not see).
        premium = (modelled[modelled.status == "a"]
                   .nlargest(1, "now_cost").iloc[0])
        if squad is not None and premium.code not in set(squad.code):
            anchored = optimize_squad(modelled, force_codes=[premium.code])
            squads.append((
                f"Alternative build: {premium.web_name} anchored",
                f"Forces in {premium.web_name} as the season-long captaincy "
                "anchor at the cost of depth elsewhere.", anchored))
    except ImportError:
        print("pulp not installed - skipping squad optimization")
    for label, (_, _, sq) in zip(["", "_premium"], squads):
        if sq is not None:
            (sq[["web_name", "short_name", "position", "price", "proj_pgw",
                 "starter", "flags"]]
             .round(2)
             .to_csv(args.out_dir / f"recommended_squad{label}.csv",
                     index=False))

    watch = watchlist(d)
    write_report(modelled, squads, watch, d, args.out_dir)

    # Sanity: rank-correlate the projection with FPL's own signals.
    ep = pd.to_numeric(modelled.ep_next, errors="coerce")
    ppg = pd.to_numeric(modelled.points_per_game, errors="coerce")
    proj_rank = modelled.proj_pgw.rank()
    print(f"modelled players: {len(modelled)}")
    print(f"spearman vs FPL ep_next:        "
          f"{proj_rank.corr(ep.rank()):.3f}")
    print(f"spearman vs last-season PPG:    "
          f"{proj_rank.corr(ppg.rank()):.3f}")
    print(f"report: {args.out_dir / 'REPORT.md'}")


if __name__ == "__main__":
    main()
