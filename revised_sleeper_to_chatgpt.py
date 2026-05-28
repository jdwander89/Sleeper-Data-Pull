"""
Sleeper → ChatGPT Formatter
League ID: 1312581067286282240

This script is designed to be run manually OR automatically by GitHub Actions.
"""

import os
import requests
import json
from datetime import datetime

DEFAULT_LEAGUE_ID = "1312581067286282240"

def get(endpoint):
    url = f"https://api.sleeper.app/v1/{endpoint}"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()

def fetch_players():
    return get("players/nfl")

def extract_league_rules(league):
    """Extracts league rules/settings from the Sleeper league object."""

    scoring = league.get("scoring_settings", {})
    settings = league.get("settings", {})

    return {
        "type": league.get("type"),
        "season_type": league.get("season_type"),
        "scoring_settings": scoring,
        "roster_positions": league.get("roster_positions", []),
        "playoff_teams": settings.get("playoff_teams"),
        "playoff_rounds": settings.get("playoff_rounds"),
        "trade_deadline": settings.get("trade_deadline"),
        "waiver_type": settings.get("waiver_type"),
        "waiver_budget": settings.get("waiver_budget"),
        "max_keepers": settings.get("max_keepers"),
        "taxi_slots": settings.get("taxi_slots"),
        "reserve_slots": settings.get("reserve_slots"),
        "bench_slots": settings.get("bench_slots"),
        "league_average_match": settings.get("league_average_match"),
    }

def build_draft_order(picks):
    """Creates a clean draft order structure from draft picks."""
    draft_order = {}

    for pick in picks:
        rnd = pick.get("round")
        if rnd not in draft_order:
            draft_order[rnd] = []

        draft_order[rnd].append({
            "pick_no": pick.get("pick_no"),
            "roster_id": pick.get("roster_id"),
            "owner_id": pick.get("owner_id"),
            "player_id": pick.get("player_id"),
        })

    # Sort each round by pick number
    for rnd in draft_order:
        draft_order[rnd] = sorted(draft_order[rnd], key=lambda x: x["pick_no"])

    return draft_order

def fetch_draft_data(league_id, players):
    """
    Fetches draft metadata, picks (with full player objects),
    traded picks, and draft order.
    """

    drafts = get(f"league/{league_id}/drafts")

    if not drafts:
        return {
            "drafts": [],
            "draft_picks": {},
            "traded_picks": {},
            "draft_order": {}
        }

    def resolve_player(pid):
        p = players.get(pid, {})
        return {
            "id": pid,
            "name": p.get("full_name"),
            "team": p.get("team"),
            "position": p.get("position"),
            "status": p.get("status"),
        }

    draft_results = []
    draft_picks_map = {}
    traded_picks_map = {}
    draft_order_map = {}

    for draft in drafts:
        draft_id = draft.get("draft_id")

        # Raw picks + traded picks for this draft
        picks = get(f"draft/{draft_id}/picks")
        traded = get(f"draft/{draft_id}/traded_picks")

        # Enrich picks with player objects
        enriched_picks = []
        for p in picks:
            player_id = p.get("player_id")
            enriched_picks.append({
                **p,
                "player": resolve_player(player_id) if player_id else None
            })

        draft_results.append(draft)
        draft_picks_map[draft_id] = enriched_picks
        traded_picks_map[draft_id] = traded

        # Build draft order from enriched picks
        draft_order_map[draft_id] = build_draft_order(enriched_picks)

    return {
        "drafts": draft_results,
        "draft_picks": draft_picks_map,
        "traded_picks": traded_picks_map,
        "draft_order": draft_order_map
    }

def fetch_future_picks(league_id):
    """
    Fetches league-level traded picks (future picks) and groups them by team.
    This does NOT fabricate non-traded original picks; it reflects what Sleeper returns.
    """

    traded_future = get(f"league/{league_id}/traded_picks")

    # Raw list straight from Sleeper
    raw = traded_future

    # Group by roster (current owner)
    by_team = {}
    for tp in traded_future:
        # Sleeper fields typically: season, round, roster_id (original), owner_id (new)
        season = tp.get("season")
        current_owner = tp.get("owner_id")  # roster_id of current owner
        if current_owner is None:
            continue

        if current_owner not in by_team:
            by_team[current_owner] = {}

        if season not in by_team[current_owner]:
            by_team[current_owner][season] = []

        by_team[current_owner][season].append(tp)

    return {
        "raw_traded_future_picks": raw,
        "future_picks_by_team": by_team
    }

def fetch_league_data(league_id=DEFAULT_LEAGUE_ID, week=None):
    league = get(f"league/{league_id}")
    users = get(f"league/{league_id}/users")
    rosters = get(f"league/{league_id}/rosters")
    players = fetch_players()

    matchups = get(f"league/{league_id}/matchups/{week}") if week else []

    # League rules
    league_rules = extract_league_rules(league)

    # Draft data (picks, traded picks, draft order) with full player objects
    draft_data = fetch_draft_data(league_id, players)

    # Future picks (league-level traded picks), grouped by team
    future_picks = fetch_future_picks(league_id)

    # Map user_id → display_name
    user_map = {u["user_id"]: u.get("display_name", "Unknown") for u in users}

    # Player resolver for rosters/matchups
    def resolve_player(pid):
        p = players.get(pid, {})
        return {
            "id": pid,
            "name": p.get("full_name"),
            "team": p.get("team"),
            "position": p.get("position"),
            "status": p.get("status"),
        }

    # Build roster map
    roster_map = {}
    for r in rosters:
        roster_map[r["roster_id"]] = {
            "owner_id": r["owner_id"],
            "owner_name": user_map.get(r["owner_id"], "Unknown"),
            "players": [resolve_player(pid) for pid in r.get("players", [])],
            "starters": [resolve_player(pid) for pid in r.get("starters", [])],
            "wins": r.get("settings", {}).get("wins", 0),
            "losses": r.get("settings", {}).get("losses", 0),
            "points": r.get("settings", {}).get("fpts", 0),
        }

    # Format matchups
    formatted_matchups = []
    for m in matchups:
        roster = roster_map.get(m["roster_id"], {})
        formatted_matchups.append({
            "roster_id": m["roster_id"],
            "owner_name": roster.get("owner_name"),
            "starters": [resolve_player(pid) for pid in m.get("starters", [])],
            "players": [resolve_player(pid) for pid in m.get("players", [])],
            "points": m.get("points", 0),
        })

    # Final output
    return {
        "league_id": league_id,
        "league_name": league.get("name"),
        "season": league.get("season"),
        "week": week,
        "generated_at": datetime.utcnow().isoformat(),
        "league_rules": league_rules,
        "draft_data": draft_data,        # drafts, draft_picks (with players), traded_picks, draft_order
        "future_picks": future_picks,    # league-level traded future picks, grouped by team
        "teams": list(roster_map.values()),
        "matchups": formatted_matchups,
    }

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Pull Sleeper league data and format for ChatGPT")
    parser.add_argument("--league", default=DEFAULT_LEAGUE_ID)
    parser.add_argument("--week", type=int)
    parser.add_argument("--out", default="sleeper_chatgpt.json")

    args = parser.parse_args()

    if os.getenv("GITHUB_ACTIONS") == "true":
        print("Running inside GitHub Actions CI pipeline")

    data = fetch_league_data(args.league, args.week)

    with open(args.out, "w") as f:
        json.dump(data, f, indent=4)

    print(f"Saved formatted data to {args.out}")
