"""
Sleeper → ChatGPT Formatter
League ID: 1312581067286282240

This script is designed to be run manually OR automatically by GitHub Actions.

GitHub Action (placed in .github/workflows/sleeper_daily.yml):

name: Daily Sleeper League Update
on:
  schedule:
    - cron: "0 6 * * *"
  workflow_dispatch:

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: "3.11"
      - run: pip install requests
      - run: python sleeper_to_chatgpt.py --week 1
      - run: |
          git config user.name "github-actions"
          git config user.email "actions@github.com"
          git add sleeper_chatgpt.json
          git commit -m "Daily Sleeper data update" || echo "No changes"
          git push
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

def fetch_league_data(league_id=DEFAULT_LEAGUE_ID, week=None):
    league = get(f"league/{league_id}")
    users = get(f"league/{league_id}/users")
    rosters = get(f"league/{league_id}/rosters")
    players = fetch_players()

    matchups = get(f"league/{league_id}/matchups/{week}") if week else []

    user_map = {u["user_id"]: u.get("display_name", "Unknown") for u in users}

    def resolve_player(pid):
        p = players.get(pid, {})
        return {
            "id": pid,
            "name": p.get("full_name"),
            "team": p.get("team"),
            "position": p.get("position"),
            "status": p.get("status"),
        }

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

    return {
        "league_id": league_id,
        "league_name": league.get("name"),
        "season": league.get("season"),
        "week": week,
        "generated_at": datetime.utcnow().isoformat(),
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
