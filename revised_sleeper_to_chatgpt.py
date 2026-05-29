"""
Sleeper → ChatGPT Full Data Exporter

Pulls Sleeper league data and writes a ChatGPT-friendly JSON file.

Includes:
- NFL state
- League metadata/settings/scoring
- League users
- Rosters
- Matchups by week
- Transactions by week
- Winners/losers playoff brackets
- League traded future picks
- League drafts
- Draft picks
- Draft traded picks
- Full NFL player database, optional
- Trending adds/drops, optional

Default League ID:
1312581067286282240
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests


DEFAULT_LEAGUE_ID = "1312581067286282240"
BASE_URL = "https://api.sleeper.app/v1"


# ==========================================================
# HTTP HELPERS
# ==========================================================

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sleeper_get(endpoint: str, default: Any = None, pause_seconds: float = 0.05) -> Any:
    """
    Safe GET wrapper for Sleeper API.
    Returns default on 404/empty failures instead of crashing.
    """
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"

    try:
        response = requests.get(url, timeout=30)

        if response.status_code == 404:
            return default

        response.raise_for_status()

        if pause_seconds:
            time.sleep(pause_seconds)

        return response.json()

    except requests.RequestException as exc:
        return {
            "_error": True,
            "endpoint": endpoint,
            "message": str(exc)
        }


# ==========================================================
# PLAYER HELPERS
# ==========================================================

def compact_player(player_id: Optional[str], players: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not player_id:
        return None

    player = players.get(player_id, {})

    return {
        "player_id": player_id,
        "name": player.get("full_name"),
        "first_name": player.get("first_name"),
        "last_name": player.get("last_name"),
        "team": player.get("team"),
        "position": player.get("position"),
        "fantasy_positions": player.get("fantasy_positions"),
        "status": player.get("status"),
        "injury_status": player.get("injury_status"),
        "age": player.get("age"),
        "years_exp": player.get("years_exp")
    }


def compact_player_list(player_ids: List[str], players: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        compact_player(player_id, players)
        for player_id in player_ids or []
        if player_id
    ]


# ==========================================================
# MAP HELPERS
# ==========================================================

def build_user_maps(users: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_user_id = {}

    for user in users:
        user_id = user.get("user_id")
        if not user_id:
            continue

        by_user_id[user_id] = {
            "user_id": user_id,
            "username": user.get("username"),
            "display_name": user.get("display_name"),
            "avatar": user.get("avatar"),
            "metadata": user.get("metadata", {})
        }

    return {
        "by_user_id": by_user_id,
        "display_name_by_user_id": {
            user_id: user.get("display_name") or user.get("username") or user_id
            for user_id, user in by_user_id.items()
        }
    }


def build_roster_maps(
    rosters: List[Dict[str, Any]],
    user_maps: Dict[str, Any]
) -> Dict[str, Any]:
    display_names = user_maps["display_name_by_user_id"]

    by_roster_id = {}
    roster_id_by_owner_id = {}

    for roster in rosters:
        roster_id = roster.get("roster_id")
        owner_id = roster.get("owner_id")

        if roster_id is None:
            continue

        by_roster_id[str(roster_id)] = {
            "roster_id": roster_id,
            "owner_id": owner_id,
            "owner_name": display_names.get(owner_id, "Unknown"),
            "settings": roster.get("settings", {})
        }

        if owner_id:
            roster_id_by_owner_id[owner_id] = roster_id

    return {
        "by_roster_id": by_roster_id,
        "roster_id_by_owner_id": roster_id_by_owner_id
    }


def owner_name_from_roster_id(roster_id: Any, roster_maps: Dict[str, Any]) -> str:
    if roster_id is None:
        return "Unknown"

    roster = roster_maps["by_roster_id"].get(str(roster_id), {})
    return roster.get("owner_name", "Unknown")


# ==========================================================
# CHATGPT-FRIENDLY SUMMARIES
# ==========================================================

def summarize_league(league: Dict[str, Any]) -> Dict[str, Any]:
    settings = league.get("settings", {})
    scoring = league.get("scoring_settings", {})

    return {
        "league_id": league.get("league_id"),
        "name": league.get("name"),
        "sport": league.get("sport"),
        "season": league.get("season"),
        "season_type": league.get("season_type"),
        "status": league.get("status"),
        "type": league.get("type"),
        "previous_league_id": league.get("previous_league_id"),
        "draft_id": league.get("draft_id"),
        "avatar": league.get("avatar"),
        "roster_positions": league.get("roster_positions", []),
        "settings_summary": {
            "teams": settings.get("num_teams"),
            "playoff_teams": settings.get("playoff_teams"),
            "playoff_rounds": settings.get("playoff_rounds"),
            "trade_deadline": settings.get("trade_deadline"),
            "waiver_type": settings.get("waiver_type"),
            "waiver_budget": settings.get("waiver_budget"),
            "taxi_slots": settings.get("taxi_slots"),
            "reserve_slots": settings.get("reserve_slots"),
            "bench_slots": settings.get("bench_slots"),
            "max_keepers": settings.get("max_keepers")
        },
        "scoring_settings": scoring,
        "all_settings": settings
    }


def summarize_rosters(
    rosters: List[Dict[str, Any]],
    players: Dict[str, Any],
    roster_maps: Dict[str, Any]
) -> List[Dict[str, Any]]:
    summaries = []

    for roster in rosters:
        roster_id = roster.get("roster_id")
        settings = roster.get("settings", {})

        summaries.append({
            "roster_id": roster_id,
            "owner_id": roster.get("owner_id"),
            "owner_name": owner_name_from_roster_id(roster_id, roster_maps),
            "record": {
                "wins": settings.get("wins", 0),
                "losses": settings.get("losses", 0),
                "ties": settings.get("ties", 0),
                "points_for": settings.get("fpts", 0),
                "points_for_decimal": settings.get("fpts_decimal", 0),
                "points_against": settings.get("fpts_against", 0),
                "points_against_decimal": settings.get("fpts_against_decimal", 0)
            },
            "waivers": {
                "waiver_position": settings.get("waiver_position"),
                "waiver_budget_used": settings.get("waiver_budget_used")
            },
            "moves": settings.get("total_moves"),
            "starters": compact_player_list(roster.get("starters", []), players),
            "players": compact_player_list(roster.get("players", []), players),
            "reserve": compact_player_list(roster.get("reserve", []), players),
            "taxi": compact_player_list(roster.get("taxi", []), players),
            "raw": roster
        })

    return summaries


def summarize_matchups(
    matchups_by_week: Dict[str, List[Dict[str, Any]]],
    players: Dict[str, Any],
    roster_maps: Dict[str, Any]
) -> Dict[str, Any]:
    output = {}

    for week, matchups in matchups_by_week.items():
        grouped = {}

        for matchup in matchups:
            matchup_id = matchup.get("matchup_id")
            key = str(matchup_id) if matchup_id is not None else "no_matchup_id"

            grouped.setdefault(key, [])

            roster_id = matchup.get("roster_id")

            grouped[key].append({
                "roster_id": roster_id,
                "owner_name": owner_name_from_roster_id(roster_id, roster_maps),
                "points": matchup.get("points"),
                "custom_points": matchup.get("custom_points"),
                "starters": compact_player_list(matchup.get("starters", []), players),
                "players": compact_player_list(matchup.get("players", []), players),
                "raw": matchup
            })

        output[str(week)] = grouped

    return output


def summarize_transactions(
    transactions_by_week: Dict[str, List[Dict[str, Any]]],
    players: Dict[str, Any],
    roster_maps: Dict[str, Any]
) -> Dict[str, Any]:
    output = {}

    for week, transactions in transactions_by_week.items():
        clean_transactions = []

        for tx in transactions:
            adds = tx.get("adds") or {}
            drops = tx.get("drops") or {}

            clean_transactions.append({
                "transaction_id": tx.get("transaction_id"),
                "type": tx.get("type"),
                "status": tx.get("status"),
                "created": tx.get("created"),
                "creator": tx.get("creator"),
                "roster_ids": tx.get("roster_ids", []),
                "teams": [
                    owner_name_from_roster_id(roster_id, roster_maps)
                    for roster_id in tx.get("roster_ids", [])
                ],
                "adds": [
                    {
                        "player": compact_player(player_id, players),
                        "to_roster_id": roster_id,
                        "to_owner": owner_name_from_roster_id(roster_id, roster_maps)
                    }
                    for player_id, roster_id in adds.items()
                ],
                "drops": [
                    {
                        "player": compact_player(player_id, players),
                        "from_roster_id": roster_id,
                        "from_owner": owner_name_from_roster_id(roster_id, roster_maps)
                    }
                    for player_id, roster_id in drops.items()
                ],
                "draft_picks": tx.get("draft_picks", []),
                "waiver_budget": tx.get("waiver_budget", []),
                "settings": tx.get("settings", {}),
                "metadata": tx.get("metadata", {}),
                "raw": tx
            })

        output[str(week)] = clean_transactions

    return output


def summarize_drafts(
    drafts: List[Dict[str, Any]],
    draft_details: Dict[str, Any],
    draft_picks: Dict[str, Any],
    draft_traded_picks: Dict[str, Any],
    players: Dict[str, Any],
    roster_maps: Dict[str, Any],
    user_maps: Dict[str, Any]
) -> List[Dict[str, Any]]:
    display_names = user_maps["display_name_by_user_id"]
    output = []

    for draft in drafts:
        draft_id = draft.get("draft_id")
        details = draft_details.get(draft_id, draft)
        picks = draft_picks.get(draft_id, [])
        traded = draft_traded_picks.get(draft_id, [])

        rounds = {}

        for pick in picks:
            round_no = str(pick.get("round"))
            rounds.setdefault(round_no, [])

            player_id = pick.get("player_id")
            picked_by = pick.get("picked_by")
            roster_id = pick.get("roster_id")

            rounds[round_no].append({
                "pick_no": pick.get("pick_no"),
                "round": pick.get("round"),
                "draft_slot": pick.get("draft_slot"),
                "roster_id": roster_id,
                "owner_name": owner_name_from_roster_id(roster_id, roster_maps),
                "picked_by_user_id": picked_by,
                "picked_by_name": display_names.get(picked_by, picked_by),
                "player": compact_player(player_id, players),
                "metadata": pick.get("metadata", {}),
                "is_keeper": pick.get("is_keeper"),
                "raw": pick
            })

        for round_no in rounds:
            rounds[round_no] = sorted(
                rounds[round_no],
                key=lambda item: item.get("pick_no") or 0
            )

        output.append({
            "draft_id": draft_id,
            "season": details.get("season"),
            "status": details.get("status"),
            "type": details.get("type"),
            "sport": details.get("sport"),
            "start_time": details.get("start_time"),
            "created": details.get("created"),
            "last_picked": details.get("last_picked"),
            "settings": details.get("settings", {}),
            "metadata": details.get("metadata", {}),
            "draft_order": details.get("draft_order", {}),
            "slot_to_roster_id": details.get("slot_to_roster_id", {}),
            "rounds": rounds,
            "traded_picks": traded,
            "raw": details
        })

    return output


def summarize_traded_future_picks(
    traded_picks: List[Dict[str, Any]],
    roster_maps: Dict[str, Any]
) -> Dict[str, Any]:
    by_current_owner = {}

    for pick in traded_picks:
        current_owner_roster_id = pick.get("owner_id")
        original_owner_roster_id = pick.get("roster_id")
        previous_owner_roster_id = pick.get("previous_owner_id")

        current_owner = owner_name_from_roster_id(current_owner_roster_id, roster_maps)

        by_current_owner.setdefault(current_owner, [])

        by_current_owner[current_owner].append({
            "season": pick.get("season"),
            "round": pick.get("round"),
            "current_owner_roster_id": current_owner_roster_id,
            "current_owner_name": current_owner,
            "original_owner_roster_id": original_owner_roster_id,
            "original_owner_name": owner_name_from_roster_id(original_owner_roster_id, roster_maps),
            "previous_owner_roster_id": previous_owner_roster_id,
            "previous_owner_name": owner_name_from_roster_id(previous_owner_roster_id, roster_maps),
            "raw": pick
        })

    return by_current_owner


def summarize_trending(
    trending: Dict[str, List[Dict[str, Any]]],
    players: Dict[str, Any]
) -> Dict[str, Any]:
    output = {}

    for trend_type, rows in trending.items():
        output[trend_type] = [
            {
                "count": row.get("count"),
                "player": compact_player(row.get("player_id"), players),
                "raw": row
            }
            for row in rows
        ]

    return output


# ==========================================================
# FETCH ALL DATA
# ==========================================================

def fetch_all_sleeper_data(
    league_id: str,
    weeks: Optional[List[int]],
    include_players: bool,
    include_trending: bool,
    trending_hours: int,
    trending_limit: int
) -> Dict[str, Any]:

    nfl_state = sleeper_get("state/nfl", default={})
    league = sleeper_get(f"league/{league_id}", default={})
    users = sleeper_get(f"league/{league_id}/users", default=[])
    rosters = sleeper_get(f"league/{league_id}/rosters", default=[])

    season = league.get("season") or nfl_state.get("season")
    current_week = nfl_state.get("week") or nfl_state.get("display_week")

    if weeks is None:
        if current_week:
            weeks = list(range(1, int(current_week) + 1))
        else:
            weeks = list(range(1, 18))

    players = sleeper_get("players/nfl", default={})

    user_maps = build_user_maps(users)
    roster_maps = build_roster_maps(rosters, user_maps)

    matchups_by_week = {}
    transactions_by_week = {}

    for week in weeks:
        matchups_by_week[str(week)] = sleeper_get(
            f"league/{league_id}/matchups/{week}",
            default=[]
        )

        transactions_by_week[str(week)] = sleeper_get(
            f"league/{league_id}/transactions/{week}",
            default=[]
        )

    winners_bracket = sleeper_get(
        f"league/{league_id}/winners_bracket",
        default=[]
    )

    losers_bracket = sleeper_get(
        f"league/{league_id}/losers_bracket",
        default=[]
    )

    league_traded_picks = sleeper_get(
        f"league/{league_id}/traded_picks",
        default=[]
    )

    drafts = sleeper_get(
        f"league/{league_id}/drafts",
        default=[]
    )

    draft_details = {}
    draft_picks = {}
    draft_traded_picks = {}

    for draft in drafts:
        draft_id = draft.get("draft_id")
        if not draft_id:
            continue

        draft_details[draft_id] = sleeper_get(
            f"draft/{draft_id}",
            default={}
        )

        draft_picks[draft_id] = sleeper_get(
            f"draft/{draft_id}/picks",
            default=[]
        )

        draft_traded_picks[draft_id] = sleeper_get(
            f"draft/{draft_id}/traded_picks",
            default=[]
        )

    trending = {}

    if include_trending:
        trending["adds"] = sleeper_get(
            f"players/nfl/trending/add?lookback_hours={trending_hours}&limit={trending_limit}",
            default=[]
        )

        trending["drops"] = sleeper_get(
            f"players/nfl/trending/drop?lookback_hours={trending_hours}&limit={trending_limit}",
            default=[]
        )

    chatgpt_view = {
        "league": summarize_league(league),
        "users": user_maps["by_user_id"],
        "teams": summarize_rosters(rosters, players, roster_maps),
        "matchups_by_week": summarize_matchups(matchups_by_week, players, roster_maps),
        "transactions_by_week": summarize_transactions(transactions_by_week, players, roster_maps),
        "drafts": summarize_drafts(
            drafts=drafts,
            draft_details=draft_details,
            draft_picks=draft_picks,
            draft_traded_picks=draft_traded_picks,
            players=players,
            roster_maps=roster_maps,
            user_maps=user_maps
        ),
        "future_traded_picks_by_current_owner": summarize_traded_future_picks(
            league_traded_picks,
            roster_maps
        ),
        "playoff_brackets": {
            "winners": winners_bracket,
            "losers": losers_bracket
        },
        "trending_players": summarize_trending(trending, players) if include_trending else {}
    }

    raw_data = {
        "nfl_state": nfl_state,
        "league": league,
        "users": users,
        "rosters": rosters,
        "matchups_by_week": matchups_by_week,
        "transactions_by_week": transactions_by_week,
        "winners_bracket": winners_bracket,
        "losers_bracket": losers_bracket,
        "league_traded_picks": league_traded_picks,
        "drafts": drafts,
        "draft_details": draft_details,
        "draft_picks": draft_picks,
        "draft_traded_picks": draft_traded_picks,
        "trending": trending
    }

    if include_players:
        raw_data["players"] = players
    else:
        raw_data["players"] = "Omitted. Run with --include-players to include the full NFL player database."

    return {
        "metadata": {
            "generated_at": utc_now(),
            "source": "Sleeper API",
            "league_id": league_id,
            "season": season,
            "weeks_included": weeks,
            "include_full_players_database": include_players,
            "include_trending": include_trending,
            "format": "ChatGPT-friendly JSON with readable summaries plus raw Sleeper payloads",
            "notes": [
                "The chatgpt_view section is optimized for analysis.",
                "The raw_data section preserves Sleeper API responses.",
                "The full players database is large; use --include-players only when needed."
            ]
        },
        "chatgpt_view": chatgpt_view,
        "raw_data": raw_data
    }


# ==========================================================
# CLI
# ==========================================================

def parse_weeks(value: Optional[str]) -> Optional[List[int]]:
    if not value:
        return None

    weeks = []

    for part in value.split(","):
        part = part.strip()

        if "-" in part:
            start, end = part.split("-", 1)
            weeks.extend(range(int(start), int(end) + 1))
        else:
            weeks.append(int(part))

    return sorted(set(weeks))


def main():
    parser = argparse.ArgumentParser(
        description="Export Sleeper league data into ChatGPT-friendly JSON."
    )

    parser.add_argument(
        "--league",
        default=DEFAULT_LEAGUE_ID,
        help="Sleeper league ID"
    )

    parser.add_argument(
        "--weeks",
        default=None,
        help="Weeks to pull, for example: 1,2,3 or 1-17. Defaults to season-to-date."
    )

    parser.add_argument(
        "--out",
        default="sleeper_chatgpt_full.json",
        help="Output JSON file"
    )

    parser.add_argument(
        "--include-players",
        action="store_true",
        help="Include the full NFL players database in raw_data. This makes the file much larger."
    )

    parser.add_argument(
        "--include-trending",
        action="store_true",
        help="Include trending adds and drops."
    )

    parser.add_argument(
        "--trending-hours",
        type=int,
        default=24,
        help="Lookback hours for trending players."
    )

    parser.add_argument(
        "--trending-limit",
        type=int,
        default=50,
        help="Limit for trending adds/drops."
    )

    args = parser.parse_args()

    if os.getenv("GITHUB_ACTIONS") == "true":
        print("Running inside GitHub Actions CI pipeline")

    data = fetch_all_sleeper_data(
        league_id=args.league,
        weeks=parse_weeks(args.weeks),
        include_players=args.include_players,
        include_trending=args.include_trending,
        trending_hours=args.trending_hours,
        trending_limit=args.trending_limit
    )

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False,
            sort_keys=False
        )

    print(f"Saved ChatGPT-friendly Sleeper export to {args.out}")


if __name__ == "__main__":
    main()
