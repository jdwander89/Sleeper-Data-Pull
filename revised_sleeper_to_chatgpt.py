"""
Sleeper → ChatGPT Optimized JSON Exporter

Produces a clean, analysis-first JSON file for ChatGPT.

Default League ID:
1312581067286282240
"""

import argparse
import json
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests


DEFAULT_LEAGUE_ID = "1312581067286282240"
BASE_URL = "https://api.sleeper.app/v1"


REMOVED_KEYS = {
    "avatar",
    "birth_date",
    "birth_city",
    "birth_state",
    "birth_country",
    "high_school",
    "hometown",
    "height",
    "weight",
    "bmi",
    "hand_size",
    "arm_length",
    "wingspan",
    "forty_time",
    "forty",
    "shuttle",
    "three_cone",
    "cone",
    "vertical",
    "vertical_jump",
    "broad_jump",
    "bench_press",
    "bench_reps",
    "player_image",
    "image",
    "headshot",
    "taxi",
    "taxi_slots",
    "taxi_years",
    "taxi_allow_vets",
    "taxi_deadline",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sleeper_get(endpoint: str, default: Any = None, pause_seconds: float = 0.05) -> Any:
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
            "message": str(exc),
        }


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            if key in REMOVED_KEYS or key.startswith("taxi"):
                continue
            clean[key] = sanitize(item)
        return clean

    if isinstance(value, list):
        return [sanitize(item) for item in value]

    return value


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


def player_record(player_id: Optional[str], players: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not player_id:
        return None

    p = players.get(str(player_id), {}) or {}

    return {
        "player_id": str(player_id),
        "name": p.get("full_name"),
        "first_name": p.get("first_name"),
        "last_name": p.get("last_name"),
        "search_full_name": p.get("search_full_name"),
        "position": p.get("position"),
        "fantasy_positions": p.get("fantasy_positions"),
        "team": p.get("team"),
        "active": p.get("active"),
        "status": p.get("status"),
        "college": p.get("college"),
        "age": p.get("age"),
        "years_exp": p.get("years_exp"),
        "draft": {
            "year": p.get("draft_year"),
            "round": p.get("draft_round"),
            "pick": p.get("draft_pick"),
            "team": p.get("draft_team"),
        },
        "injury": {
            "status": p.get("injury_status"),
            "notes": p.get("injury_notes"),
            "body_part": p.get("injury_body_part"),
            "start_date": p.get("injury_start_date"),
        },
        "depth_chart": {
            "position": p.get("depth_chart_position"),
            "order": p.get("depth_chart_order"),
        },
        "fantasy_metadata": {
            "search_rank": p.get("search_rank"),
            "practice_participation": p.get("practice_participation"),
            "practice_description": p.get("practice_description"),
        },
        "jersey_number": p.get("number"),
    }


def compact_player_ids(player_ids: Optional[List[str]]) -> List[str]:
    return [str(pid) for pid in (player_ids or []) if pid]


def build_players_lookup(player_ids: List[str], players: Dict[str, Any]) -> Dict[str, Any]:
    lookup = {}
    for pid in sorted(set(compact_player_ids(player_ids))):
        record = player_record(pid, players)
        if record:
            lookup[pid] = record
    return lookup


def group_player_ids_by_position(player_ids: List[str], players: Dict[str, Any]) -> Dict[str, List[str]]:
    grouped = defaultdict(list)

    for pid in compact_player_ids(player_ids):
        position = players.get(pid, {}).get("position") or "UNKNOWN"
        grouped[position].append(pid)

    return dict(sorted(grouped.items()))


def get_primary_position(player_id: str, players: Dict[str, Any]) -> str:
    return players.get(str(player_id), {}).get("position") or "UNKNOWN"


def build_user_maps(users: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_user_id = {}

    for user in users:
        user_id = user.get("user_id")
        if not user_id:
            continue

        metadata = sanitize(user.get("metadata", {}))

        by_user_id[user_id] = {
            "user_id": user_id,
            "username": user.get("username"),
            "display_name": user.get("display_name"),
            "is_bot": user.get("is_bot"),
            "metadata": metadata,
            "team_name": (
                metadata.get("team_name")
                or metadata.get("nickname")
                or user.get("display_name")
                or user.get("username")
                or "Unknown Team"
            ),
        }

    return {
        "by_user_id": by_user_id,
        "display_name_by_user_id": {
            uid: u.get("display_name") or u.get("username") or uid
            for uid, u in by_user_id.items()
        },
        "team_name_by_user_id": {
            uid: u.get("team_name") or u.get("display_name") or uid
            for uid, u in by_user_id.items()
        },
    }


def build_roster_maps(rosters: List[Dict[str, Any]], user_maps: Dict[str, Any]) -> Dict[str, Any]:
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
            "owner_name": user_maps["display_name_by_user_id"].get(owner_id, "Unknown"),
            "team_name": user_maps["team_name_by_user_id"].get(owner_id, "Unknown Team"),
            "settings": sanitize(roster.get("settings", {})),
        }

        if owner_id:
            roster_id_by_owner_id[owner_id] = roster_id

    return {
        "by_roster_id": by_roster_id,
        "roster_id_by_owner_id": roster_id_by_owner_id,
    }


def roster_label(roster_id: Any, roster_maps: Dict[str, Any]) -> Dict[str, Any]:
    roster = roster_maps["by_roster_id"].get(str(roster_id), {})
    return {
        "roster_id": roster_id,
        "team_name": roster.get("team_name", "Unknown Team"),
        "owner_name": roster.get("owner_name", "Unknown"),
    }


def summarize_league(league: Dict[str, Any], nfl_state: Dict[str, Any]) -> Dict[str, Any]:
    settings = sanitize(league.get("settings", {}))

    return {
        "league_id": league.get("league_id"),
        "name": league.get("name"),
        "season": league.get("season"),
        "season_type": league.get("season_type"),
        "sport": league.get("sport"),
        "status": league.get("status"),
        "league_type": league.get("type"),
        "total_rosters": league.get("total_rosters"),
        "previous_league_id": league.get("previous_league_id"),
        "draft_id": league.get("draft_id"),
        "current_nfl_state": sanitize(nfl_state),
        "roster_positions": league.get("roster_positions", []),
        "scoring_settings": sanitize(league.get("scoring_settings", {})),
        "settings_summary": {
            "teams": settings.get("num_teams"),
            "playoff_teams": settings.get("playoff_teams"),
            "playoff_rounds": settings.get("playoff_rounds"),
            "trade_deadline": settings.get("trade_deadline"),
            "waiver_type": settings.get("waiver_type"),
            "waiver_budget": settings.get("waiver_budget"),
            "reserve_slots": settings.get("reserve_slots"),
            "bench_slots": settings.get("bench_slots"),
            "max_keepers": settings.get("max_keepers"),
            "best_ball": settings.get("best_ball"),
            "median_scoring": settings.get("median_scoring"),
            "daily_waivers": settings.get("daily_waivers"),
        },
        "all_settings": settings,
        "metadata": sanitize(league.get("metadata", {})),
    }


def summarize_teams(rosters, players, roster_maps):
    teams = []

    for roster in rosters:
        roster_id = roster.get("roster_id")
        settings = sanitize(roster.get("settings", {}))
        label = roster_label(roster_id, roster_maps)

        all_player_ids = compact_player_ids(roster.get("players", []))
        starter_ids = compact_player_ids(roster.get("starters", []))
        reserve_ids = compact_player_ids(roster.get("reserve", []))

        position_counts = defaultdict(int)
        starter_position_counts = defaultdict(int)
        ages_by_position = defaultdict(list)

        for pid in all_player_ids:
            pos = get_primary_position(pid, players)
            position_counts[pos] += 1
            age = players.get(pid, {}).get("age")
            if isinstance(age, (int, float)):
                ages_by_position[pos].append(age)

        for pid in starter_ids:
            starter_position_counts[get_primary_position(pid, players)] += 1

        avg_age_by_position = {
            pos: round(sum(ages) / len(ages), 2)
            for pos, ages in ages_by_position.items()
            if ages
        }

        teams.append({
            "roster_id": roster_id,
            "team_name": label["team_name"],
            "owner_name": label["owner_name"],
            "owner_id": roster.get("owner_id"),
            "record": {
                "wins": settings.get("wins", 0),
                "losses": settings.get("losses", 0),
                "ties": settings.get("ties", 0),
                "points_for": settings.get("fpts", 0),
                "points_for_decimal": settings.get("fpts_decimal", 0),
                "points_against": settings.get("fpts_against", 0),
                "points_against_decimal": settings.get("fpts_against_decimal", 0),
                "potential_points": settings.get("ppts"),
                "potential_points_decimal": settings.get("ppts_decimal"),
            },
            "waivers": {
                "waiver_position": settings.get("waiver_position"),
                "waiver_budget_used": settings.get("waiver_budget_used"),
            },
            "team_summary": {
                "total_players": len(all_player_ids),
                "starter_count": len(starter_ids),
                "reserve_count": len(reserve_ids),
                "position_counts": dict(sorted(position_counts.items())),
                "starter_position_counts": dict(sorted(starter_position_counts.items())),
                "average_age_by_position": avg_age_by_position,
            },
            "players_by_position": group_player_ids_by_position(all_player_ids, players),
            "starters": starter_ids,
            "reserve": reserve_ids,
            "settings": settings,
        })

    return sorted(teams, key=lambda t: t["roster_id"] or 0)


def summarize_matchups(matchups_by_week, roster_maps):
    weekly_results = {}

    for week, matchups in matchups_by_week.items():
        grouped = defaultdict(list)

        for matchup in matchups:
            matchup_id = matchup.get("matchup_id")
            key = str(matchup_id) if matchup_id is not None else "no_matchup_id"
            roster_id = matchup.get("roster_id")
            label = roster_label(roster_id, roster_maps)

            grouped[key].append({
                "roster_id": roster_id,
                "team_name": label["team_name"],
                "owner_name": label["owner_name"],
                "points": matchup.get("points"),
                "custom_points": matchup.get("custom_points"),
                "starters": compact_player_ids(matchup.get("starters", [])),
                "players": compact_player_ids(matchup.get("players", [])),
                "starters_points": matchup.get("starters_points", []),
                "players_points": matchup.get("players_points", {}),
            })

        weekly_results[str(week)] = dict(grouped)

    return weekly_results


def summarize_transactions(transactions_by_week, roster_maps):
    output = {}

    for week, transactions in transactions_by_week.items():
        clean = []

        for tx in transactions:
            adds = tx.get("adds") or {}
            drops = tx.get("drops") or {}

            clean.append({
                "transaction_id": tx.get("transaction_id"),
                "type": tx.get("type"),
                "status": tx.get("status"),
                "created": tx.get("created"),
                "creator": tx.get("creator"),
                "roster_ids": tx.get("roster_ids", []),
                "teams": [
                    roster_label(rid, roster_maps)
                    for rid in tx.get("roster_ids", [])
                ],
                "adds": [
                    {
                        "player_id": str(pid),
                        "to": roster_label(rid, roster_maps),
                    }
                    for pid, rid in adds.items()
                ],
                "drops": [
                    {
                        "player_id": str(pid),
                        "from": roster_label(rid, roster_maps),
                    }
                    for pid, rid in drops.items()
                ],
                "draft_picks": sanitize(tx.get("draft_picks", [])),
                "waiver_budget": sanitize(tx.get("waiver_budget", [])),
                "settings": sanitize(tx.get("settings", {})),
                "metadata": sanitize(tx.get("metadata", {})),
                "consenter_ids": tx.get("consenter_ids", []),
            })

        output[str(week)] = clean

    return output


def summarize_drafts(drafts, draft_details, draft_picks, draft_traded_picks, roster_maps, user_maps):
    draft_room = {
        "drafts": [],
    }

    for draft in drafts:
        draft_id = draft.get("draft_id")
        details = sanitize(draft_details.get(draft_id, draft))
        picks = draft_picks.get(draft_id, [])
        traded = sanitize(draft_traded_picks.get(draft_id, []))

        rounds = defaultdict(list)

        for pick in picks:
            roster_id = pick.get("roster_id")
            picked_by = pick.get("picked_by")

            rounds[str(pick.get("round"))].append({
                "pick_no": pick.get("pick_no"),
                "round": pick.get("round"),
                "draft_slot": pick.get("draft_slot"),
                "player_id": str(pick.get("player_id")) if pick.get("player_id") else None,
                "roster": roster_label(roster_id, roster_maps),
                "picked_by_user_id": picked_by,
                "picked_by_name": user_maps["display_name_by_user_id"].get(picked_by, picked_by),
                "metadata": sanitize(pick.get("metadata", {})),
                "is_keeper": pick.get("is_keeper"),
                "picked_at": pick.get("picked_at"),
            })

        sorted_rounds = {
            round_no: sorted(items, key=lambda x: x.get("pick_no") or 0)
            for round_no, items in sorted(rounds.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 999)
        }

        draft_room["drafts"].append({
            "draft_id": draft_id,
            "season": details.get("season"),
            "status": details.get("status"),
            "type": details.get("type"),
            "sport": details.get("sport"),
            "start_time": details.get("start_time"),
            "created": details.get("created"),
            "last_picked": details.get("last_picked"),
            "settings": sanitize(details.get("settings", {})),
            "metadata": sanitize(details.get("metadata", {})),
            "draft_order": details.get("draft_order", {}),
            "slot_to_roster_id": details.get("slot_to_roster_id", {}),
            "rounds": sorted_rounds,
            "traded_picks": traded,
        })

    return draft_room


def summarize_traded_future_picks(traded_picks, roster_maps):
    by_current_owner = defaultdict(list)

    for pick in traded_picks:
        current_owner_roster_id = pick.get("owner_id")
        original_owner_roster_id = pick.get("roster_id")
        previous_owner_roster_id = pick.get("previous_owner_id")
        current = roster_label(current_owner_roster_id, roster_maps)

        by_current_owner[current["team_name"]].append({
            "season": pick.get("season"),
            "round": pick.get("round"),
            "current_owner": current,
            "original_owner": roster_label(original_owner_roster_id, roster_maps),
            "previous_owner": roster_label(previous_owner_roster_id, roster_maps),
        })

    return dict(by_current_owner)


def summarize_trending(trending):
    return {
        trend_type: [
            {
                "player_id": str(row.get("player_id")),
                "count": row.get("count"),
            }
            for row in rows
        ]
        for trend_type, rows in trending.items()
    }


def collect_referenced_player_ids(
    rosters,
    matchups_by_week,
    transactions_by_week,
    drafts_picks,
    trending,
) -> List[str]:
    ids = set()

    for roster in rosters:
        ids.update(compact_player_ids(roster.get("players", [])))
        ids.update(compact_player_ids(roster.get("starters", [])))
        ids.update(compact_player_ids(roster.get("reserve", [])))

    for matchups in matchups_by_week.values():
        for matchup in matchups:
            ids.update(compact_player_ids(matchup.get("players", [])))
            ids.update(compact_player_ids(matchup.get("starters", [])))
            ids.update(str(pid) for pid in (matchup.get("players_points") or {}).keys())

    for transactions in transactions_by_week.values():
        for tx in transactions:
            ids.update(str(pid) for pid in (tx.get("adds") or {}).keys())
            ids.update(str(pid) for pid in (tx.get("drops") or {}).keys())

    for picks in drafts_picks.values():
        for pick in picks:
            if pick.get("player_id"):
                ids.add(str(pick.get("player_id")))

    for rows in trending.values():
        for row in rows:
            if row.get("player_id"):
                ids.add(str(row.get("player_id")))

    return sorted(ids)


def endpoint_ok(value: Any) -> bool:
    return not (isinstance(value, dict) and value.get("_error"))


def fetch_all_sleeper_data(
    league_id: str,
    weeks: Optional[List[int]],
    include_trending: bool,
    trending_hours: int,
    trending_limit: int,
) -> Dict[str, Any]:

    nfl_state = sleeper_get("state/nfl", default={})
    league = sleeper_get(f"league/{league_id}", default={})
    users = sleeper_get(f"league/{league_id}/users", default=[])
    rosters = sleeper_get(f"league/{league_id}/rosters", default=[])
    players = sleeper_get("players/nfl", default={})

    season = league.get("season") or nfl_state.get("season")
    current_week = nfl_state.get("week") or nfl_state.get("display_week")

    if weeks is None:
        weeks = list(range(1, int(current_week) + 1)) if current_week else list(range(1, 18))

    user_maps = build_user_maps(users)
    roster_maps = build_roster_maps(rosters, user_maps)

    matchups_by_week = {}
    transactions_by_week = {}

    for week in weeks:
        matchups_by_week[str(week)] = sleeper_get(f"league/{league_id}/matchups/{week}", default=[])
        transactions_by_week[str(week)] = sleeper_get(f"league/{league_id}/transactions/{week}", default=[])

    winners_bracket = sleeper_get(f"league/{league_id}/winners_bracket", default=[])
    losers_bracket = sleeper_get(f"league/{league_id}/losers_bracket", default=[])
    league_traded_picks = sleeper_get(f"league/{league_id}/traded_picks", default=[])
    drafts = sleeper_get(f"league/{league_id}/drafts", default=[])

    draft_details = {}
    draft_picks = {}
    draft_traded_picks = {}

    for draft in drafts:
        draft_id = draft.get("draft_id")
        if not draft_id:
            continue

        draft_details[draft_id] = sleeper_get(f"draft/{draft_id}", default={})
        draft_picks[draft_id] = sleeper_get(f"draft/{draft_id}/picks", default=[])
        draft_traded_picks[draft_id] = sleeper_get(f"draft/{draft_id}/traded_picks", default=[])

    trending = {}
    if include_trending:
        trending["adds"] = sleeper_get(
            f"players/nfl/trending/add?lookback_hours={trending_hours}&limit={trending_limit}",
            default=[],
        )
        trending["drops"] = sleeper_get(
            f"players/nfl/trending/drop?lookback_hours={trending_hours}&limit={trending_limit}",
            default=[],
        )

    referenced_player_ids = collect_referenced_player_ids(
        rosters=rosters,
        matchups_by_week=matchups_by_week,
        transactions_by_week=transactions_by_week,
        drafts_picks=draft_picks,
        trending=trending,
    )

    return {
        "read_me_first": {
            "purpose": "ChatGPT-optimized Sleeper fantasy football league export.",
            "generated_at": utc_now(),
            "league_id": league_id,
            "season": season,
            "weeks_included": weeks,
            "current_week": current_week,
            "how_to_read": [
                "Use league_context first for scoring, roster format, and settings.",
                "Use teams for roster construction, records, nicknames, and team-level summaries.",
                "Use players_lookup to resolve player_ids found throughout the file.",
                "Use draft_room for draft history and traded draft picks.",
                "Use weekly_results for matchups, scores, starters, and player scoring.",
                "Use transactions for trades, waivers, free-agent moves, FAAB, and picks.",
            ],
            "excluded_sections": [
                "birth date",
                "high school",
                "hometown",
                "physical attributes",
                "athletic testing",
                "headshots and visuals",
                "avatars and media",
                "taxi squad",
                "raw Sleeper payload dumps",
            ],
        },
        "league_context": summarize_league(league, nfl_state),
        "users": user_maps["by_user_id"],
        "teams": summarize_teams(rosters, players, roster_maps),
        "draft_room": {
            **summarize_drafts(
                drafts,
                draft_details,
                draft_picks,
                draft_traded_picks,
                roster_maps,
                user_maps,
            ),
            "future_traded_picks_by_current_owner": summarize_traded_future_picks(
                league_traded_picks,
                roster_maps,
            ),
        },
        "weekly_results": summarize_matchups(matchups_by_week, roster_maps),
        "transactions": summarize_transactions(transactions_by_week, roster_maps),
        "playoff_brackets": {
            "winners": sanitize(winners_bracket),
            "losers": sanitize(losers_bracket),
        },
        "trending_players": summarize_trending(trending) if include_trending else {},
        "players_lookup": build_players_lookup(referenced_player_ids, players),
        "data_quality": {
            "source": "Sleeper API",
            "endpoints_checked": {
                "state_nfl": endpoint_ok(nfl_state),
                "league": endpoint_ok(league),
                "league_users": endpoint_ok(users),
                "league_rosters": endpoint_ok(rosters),
                "players_nfl": endpoint_ok(players),
                "matchups_by_week": {
                    week: endpoint_ok(data)
                    for week, data in matchups_by_week.items()
                },
                "transactions_by_week": {
                    week: endpoint_ok(data)
                    for week, data in transactions_by_week.items()
                },
                "winners_bracket": endpoint_ok(winners_bracket),
                "losers_bracket": endpoint_ok(losers_bracket),
                "league_traded_picks": endpoint_ok(league_traded_picks),
                "drafts": endpoint_ok(drafts),
                "trending": {
                    key: endpoint_ok(value)
                    for key, value in trending.items()
                },
            },
            "known_limitations": [
                "Sleeper exposes traded future picks, but not a clean endpoint for every untraded future pick owned by each team.",
                "Derived rankings, dynasty trade values, projections, and expert rankings are not provided by Sleeper.",
                "Team names are taken from Sleeper user metadata team_name or nickname when available.",
            ],
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description="Export Sleeper league data into a ChatGPT-optimized JSON file."
    )

    parser.add_argument("--league", default=DEFAULT_LEAGUE_ID, help="Sleeper league ID")
    parser.add_argument("--weeks", default=None, help="Weeks to pull, e.g. 1,2,3 or 1-17")
    parser.add_argument("--out", default="sleeper_chatgpt.json", help="Output JSON file")

    parser.add_argument(
        "--include-trending",
        action="store_true",
        help="Include trending adds and drops.",
    )

    parser.add_argument("--trending-hours", type=int, default=24)
    parser.add_argument("--trending-limit", type=int, default=50)

    args = parser.parse_args()

    if os.getenv("GITHUB_ACTIONS") == "true":
        print("Running inside GitHub Actions CI pipeline")

    data = fetch_all_sleeper_data(
        league_id=args.league,
        weeks=parse_weeks(args.weeks),
        include_trending=args.include_trending,
        trending_hours=args.trending_hours,
        trending_limit=args.trending_limit,
    )

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=False)

    print(f"Saved ChatGPT-optimized Sleeper export to {args.out}")


if __name__ == "__main__":
    main()