"""
Sleeper → ChatGPT Exporter + GitHub Uploader

Creates:
1. sleeper_chatgpt.json
2. sleeper_chatgpt_team_roster_and_picks_summary.json

Optional GitHub push:
Set GITHUB_TOKEN, then run with --push-github

Example:
python revised_sleeper_to_chatgpt.py --push-github
"""

import argparse
import base64
import json
import os
import time
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests


DEFAULT_LEAGUE_ID = "1312581067286282240"
BASE_URL = "https://api.sleeper.app/v1"

DEFAULT_GITHUB_REPO = "jdwander89/Sleeper-Data-Pull"
DEFAULT_GITHUB_BRANCH = "main"


def sleeper_get(path: str, retries: int = 3) -> Any:
    url = f"{BASE_URL}{path}"
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, timeout=30)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_error = exc
            time.sleep(0.5 * attempt)

    raise RuntimeError(f"Failed Sleeper GET {url}: {last_error}")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def write_json(path: str, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=False)


def normalize_player(player_id: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    first = raw.get("first_name") or ""
    last = raw.get("last_name") or ""
    full_name = raw.get("full_name") or f"{first} {last}".strip()

    return {
        "player_id": str(player_id),
        "full_name": full_name or str(player_id),
        "first_name": raw.get("first_name"),
        "last_name": raw.get("last_name"),
        "position": raw.get("position"),
        "team": raw.get("team"),
        "status": raw.get("status"),
        "injury_status": raw.get("injury_status"),
        "years_exp": raw.get("years_exp"),
        "age": raw.get("age"),
        "fantasy_positions": raw.get("fantasy_positions"),
        "depth_chart_position": raw.get("depth_chart_position"),
        "depth_chart_order": raw.get("depth_chart_order"),
        "college": raw.get("college"),
        "search_rank": raw.get("search_rank"),
    }


def player_display_name(player_id: Any, players_lookup: Dict[str, Dict[str, Any]]) -> str:
    player_id = str(player_id)
    p = players_lookup.get(player_id, {})

    name = p.get("full_name")
    if not name:
        first = p.get("first_name") or ""
        last = p.get("last_name") or ""
        name = f"{first} {last}".strip() or player_id

    details = []
    if p.get("position"):
        details.append(str(p["position"]))
    if p.get("team"):
        details.append(str(p["team"]))

    return f"{name} ({', '.join(details)})" if details else name


def build_users_map(users: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    output = {}

    for u in users or []:
        user_id = str(u.get("user_id"))
        metadata = u.get("metadata") or {}
        display_name = u.get("display_name") or u.get("username") or user_id
        team_name = metadata.get("team_name") or display_name

        output[user_id] = {
            "user_id": user_id,
            "username": u.get("username"),
            "display_name": display_name,
            "team_name": team_name,
            "metadata": metadata,
            "is_bot": u.get("is_bot"),
        }

    return output


def get_owner_name(owner_id: Any, users_map: Dict[str, Dict[str, Any]]) -> str:
    owner_id = str(owner_id)
    return users_map.get(owner_id, {}).get("display_name") or owner_id


def get_team_name(owner_id: Any, users_map: Dict[str, Dict[str, Any]]) -> str:
    owner_id = str(owner_id)
    user = users_map.get(owner_id, {})
    return user.get("team_name") or user.get("display_name") or owner_id


def build_players_lookup(player_ids: List[Any], all_players: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    output = {}

    for pid in sorted({str(x) for x in player_ids if x is not None}):
        raw = all_players.get(pid)
        if isinstance(raw, dict):
            output[pid] = normalize_player(pid, raw)
        else:
            output[pid] = {
                "player_id": pid,
                "full_name": pid,
                "position": None,
                "team": None,
            }

    return output


def collect_needed_player_ids(rosters, matchup_weeks, draft_picks_by_draft, transaction_weeks) -> List[str]:
    needed = set()

    for roster in rosters or []:
        for key in ["players", "starters", "reserve"]:
            for pid in roster.get(key) or []:
                needed.add(str(pid))

    for matchups in matchup_weeks.values():
        for matchup in matchups or []:
            for pid in matchup.get("players") or []:
                needed.add(str(pid))
            for pid in matchup.get("starters") or []:
                needed.add(str(pid))
            for pid in (matchup.get("players_points") or {}).keys():
                needed.add(str(pid))

    for picks in draft_picks_by_draft.values():
        for pick in picks or []:
            if pick.get("player_id") is not None:
                needed.add(str(pick["player_id"]))

    for txs in transaction_weeks.values():
        for tx in txs or []:
            for move_map in [tx.get("adds"), tx.get("drops")]:
                for pid in (move_map or {}).keys():
                    needed.add(str(pid))

    return sorted(needed)


def build_team_object(roster, users_map, players_lookup):
    owner_id = roster.get("owner_id")
    settings = roster.get("settings") or {}

    players = [str(p) for p in roster.get("players") or []]
    starters = [str(p) for p in roster.get("starters") or []]
    reserve = [str(p) for p in roster.get("reserve") or []]

    players_by_position = defaultdict(list)
    position_counts = defaultdict(int)
    starter_position_counts = defaultdict(int)
    ages_by_position = defaultdict(list)

    for pid in players:
        p = players_lookup.get(pid, {})
        pos = p.get("position") or "UNKNOWN"
        players_by_position[pos].append(pid)
        position_counts[pos] += 1

        age = p.get("age")
        if isinstance(age, (int, float)):
            ages_by_position[pos].append(age)

    for pid in starters:
        p = players_lookup.get(pid, {})
        pos = p.get("position") or "UNKNOWN"
        starter_position_counts[pos] += 1

    avg_age = {
        pos: round(sum(ages) / len(ages), 2)
        for pos, ages in ages_by_position.items()
        if ages
    }

    return {
        "roster_id": roster.get("roster_id"),
        "team_name": get_team_name(owner_id, users_map),
        "owner_name": get_owner_name(owner_id, users_map),
        "owner_id": str(owner_id),
        "record": {
            "wins": settings.get("wins", 0),
            "losses": settings.get("losses", 0),
            "ties": settings.get("ties", 0),
            "points_for": settings.get("fpts", 0),
            "points_against": settings.get("fpts_against", 0),
            "potential_points": settings.get("ppts"),
        },
        "waivers": {
            "waiver_position": settings.get("waiver_position"),
            "waiver_budget_used": settings.get("waiver_budget_used"),
        },
        "team_summary": {
            "total_players": len(players),
            "starter_count": len(starters),
            "reserve_count": len(reserve),
            "position_counts": dict(sorted(position_counts.items())),
            "starter_position_counts": dict(sorted(starter_position_counts.items())),
            "average_age_by_position": dict(sorted(avg_age.items())),
        },
        "players_by_position": {
            pos: sorted(pids, key=lambda x: player_display_name(x, players_lookup))
            for pos, pids in sorted(players_by_position.items())
        },
        "starters": starters,
        "reserve": reserve,
        "settings": settings,
    }


def team_ref(roster_id: Any, teams_by_roster_id: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    t = teams_by_roster_id.get(str(roster_id), {})
    return {
        "roster_id": safe_int(roster_id),
        "team_name": t.get("team_name") or f"Roster {roster_id}",
        "owner_name": t.get("owner_name"),
    }


def normalize_draft_pick(pick, teams_by_roster_id, users_map):
    metadata = pick.get("metadata") or {}
    roster_id = pick.get("roster_id")

    picked_by_user_id = str(pick.get("picked_by")) if pick.get("picked_by") is not None else None
    picked_by_user = users_map.get(picked_by_user_id, {}) if picked_by_user_id else {}

    picked_by_name = (
        picked_by_user.get("display_name")
        or picked_by_user.get("username")
        or picked_by_user_id
    )

    picked_by_team = picked_by_user.get("team_name") or picked_by_name

    return {
        "pick_no": pick.get("pick_no"),
        "round": pick.get("round"),
        "draft_slot": pick.get("draft_slot"),
        "player_id": str(pick.get("player_id")) if pick.get("player_id") is not None else None,
        "roster": team_ref(roster_id, teams_by_roster_id),
        "picked_by_user_id": picked_by_user_id,
        "picked_by_name": picked_by_name,
        "picked_by_team_name": picked_by_team,
        "metadata": {
            "first_name": metadata.get("first_name"),
            "last_name": metadata.get("last_name"),
            "position": metadata.get("position"),
            "team": metadata.get("team"),
            "status": metadata.get("status"),
            "injury_status": metadata.get("injury_status"),
            "years_exp": metadata.get("years_exp"),
            "number": metadata.get("number"),
            "player_id": metadata.get("player_id"),
            "sport": metadata.get("sport"),
        },
        "is_keeper": pick.get("is_keeper"),
        "picked_at": pick.get("picked_at"),
    }


def group_picks_by_round(picks, teams_by_roster_id, users_map):
    rounds = defaultdict(list)

    for pick in picks or []:
        round_no = str(pick.get("round"))
        rounds[round_no].append(normalize_draft_pick(pick, teams_by_roster_id, users_map))

    return {
        round_no: sorted(items, key=lambda p: safe_int(p.get("pick_no"), 0) or 0)
        for round_no, items in sorted(rounds.items(), key=lambda kv: safe_int(kv[0], 0) or 0)
    }


def normalize_draft(draft, picks, traded_picks, teams_by_roster_id, users_map):
    return {
        "draft_id": draft.get("draft_id"),
        "season": draft.get("season"),
        "status": draft.get("status"),
        "type": draft.get("type"),
        "sport": draft.get("sport"),
        "start_time": draft.get("start_time"),
        "created": draft.get("created"),
        "last_picked": draft.get("last_picked"),
        "settings": draft.get("settings"),
        "metadata": draft.get("metadata"),
        "draft_order": draft.get("draft_order"),
        "slot_to_roster_id": draft.get("slot_to_roster_id"),
        "rounds": group_picks_by_round(picks, teams_by_roster_id, users_map),
        "traded_picks": traded_picks or [],
    }


def normalize_matchup(matchup, teams_by_roster_id):
    roster_id = matchup.get("roster_id")
    return {
        "roster": team_ref(roster_id, teams_by_roster_id),
        "matchup_id": matchup.get("matchup_id"),
        "points": matchup.get("points"),
        "players": [str(p) for p in matchup.get("players") or []],
        "starters": [str(p) for p in matchup.get("starters") or []],
        "players_points": matchup.get("players_points") or {},
        "starters_points": matchup.get("starters_points") or {},
    }


def normalize_transaction(tx, teams_by_roster_id):
    roster_ids = tx.get("roster_ids") or []

    def move_map_to_list(move_map, direction):
        output = []
        for player_id, roster_id in (move_map or {}).items():
            output.append({
                "player_id": str(player_id),
                direction: team_ref(roster_id, teams_by_roster_id),
            })
        return output

    return {
        "transaction_id": tx.get("transaction_id"),
        "type": tx.get("type"),
        "status": tx.get("status"),
        "created": tx.get("created"),
        "creator": str(tx.get("creator")) if tx.get("creator") is not None else None,
        "roster_ids": roster_ids,
        "teams": [team_ref(rid, teams_by_roster_id) for rid in roster_ids],
        "adds": move_map_to_list(tx.get("adds"), "to"),
        "drops": move_map_to_list(tx.get("drops"), "from"),
        "draft_picks": tx.get("draft_picks") or [],
        "waiver_budget": tx.get("waiver_budget") or [],
        "settings": tx.get("settings"),
        "metadata": tx.get("metadata"),
        "consenter_ids": tx.get("consenter_ids"),
    }


def get_team_maps(teams):
    by_roster_id = {}
    for team in teams:
        by_roster_id[str(team["roster_id"])] = {
            "roster_id": team["roster_id"],
            "team_name": team["team_name"],
            "owner_name": team["owner_name"],
            "owner_id": team.get("owner_id"),
        }
    return by_roster_id


def describe_pick(pick, by_roster_id):
    season = str(pick.get("season"))
    round_no = safe_int(pick.get("round"))

    original_roster_id = safe_int(pick.get("roster_id"))
    current_owner_roster_id = safe_int(pick.get("owner_id"))
    previous_owner_roster_id = safe_int(pick.get("previous_owner_id"))

    original_team = by_roster_id.get(str(original_roster_id), {})
    current_owner = by_roster_id.get(str(current_owner_roster_id), {})
    previous_owner = by_roster_id.get(str(previous_owner_roster_id), {})

    original_team_name = original_team.get("team_name") or f"Roster {original_roster_id}"
    current_owner_name = current_owner.get("team_name") or f"Roster {current_owner_roster_id}"
    previous_owner_name = previous_owner.get("team_name") or f"Roster {previous_owner_roster_id}"

    return {
        "season": season,
        "round": round_no,
        "label": f"{season} Round {round_no} from {original_team_name}",
        "original_roster_id": original_roster_id,
        "original_team": original_team_name,
        "current_owner_roster_id": current_owner_roster_id,
        "current_owner_team": current_owner_name,
        "previous_owner_roster_id": previous_owner_roster_id,
        "previous_owner_team": previous_owner_name,
    }


def dedupe_traded_picks(picks):
    seen = set()
    output = []

    for p in picks or []:
        key = (
            str(p.get("season")),
            safe_int(p.get("round"), 0),
            safe_int(p.get("roster_id"), 0),
            safe_int(p.get("owner_id"), 0),
            safe_int(p.get("previous_owner_id"), 0),
        )
        if key not in seen:
            seen.add(key)
            output.append(p)

    return output


def collect_transaction_traded_picks(transactions):
    output = []

    for txs in transactions.values():
        for tx in txs:
            if tx.get("type") == "trade" and tx.get("status") == "complete":
                output.extend(tx.get("draft_picks") or [])

    return output


def build_summary(export_data, future_years):
    teams = export_data["teams"]
    players_lookup = export_data["players_lookup"]
    draft_room = export_data["draft_room"]
    transactions = export_data["transactions"]
    league_context = export_data["league_context"]

    by_roster_id = get_team_maps(teams)

    season = safe_int(league_context.get("season"))
    rounds = safe_int(league_context.get("all_settings", {}).get("draft_rounds"), 5) or 5
    seasons = [season + i for i in range(future_years + 1)] if season else []

    inventory = defaultdict(list)

    for team in teams:
        roster_id = team["roster_id"]
        for yr in seasons:
            for rnd in range(1, rounds + 1):
                inventory[str(roster_id)].append({
                    "season": str(yr),
                    "round": rnd,
                    "label": f"{yr} Round {rnd} own",
                    "original_roster_id": roster_id,
                    "original_team": team["team_name"],
                    "current_owner_roster_id": roster_id,
                    "current_owner_team": team["team_name"],
                    "previous_owner_roster_id": roster_id,
                    "previous_owner_team": team["team_name"],
                })

    traded = []
    for draft in draft_room.get("drafts", []):
        traded.extend(draft.get("traded_picks") or [])
    traded.extend(collect_transaction_traded_picks(transactions))
    traded = dedupe_traded_picks(traded)

    for pick in traded:
        desc = describe_pick(pick, by_roster_id)
        if not desc["original_roster_id"] or not desc["current_owner_roster_id"]:
            continue

        for rid in list(inventory.keys()):
            inventory[rid] = [
                p for p in inventory[rid]
                if not (
                    p["season"] == desc["season"]
                    and p["round"] == desc["round"]
                    and p["original_roster_id"] == desc["original_roster_id"]
                )
            ]

        inventory[str(desc["current_owner_roster_id"])].append(desc)

    traded_away = defaultdict(list)
    for pick in traded:
        desc = describe_pick(pick, by_roster_id)
        if desc["original_roster_id"] != desc["current_owner_roster_id"]:
            traded_away[str(desc["original_roster_id"])].append(desc)

    current_draft_picks_made = defaultdict(list)

    for draft in draft_room.get("drafts", []):
        for picks in (draft.get("rounds") or {}).values():
            for pick in picks:
                roster_id = str((pick.get("roster") or {}).get("roster_id"))
                meta = pick.get("metadata") or {}
                first = meta.get("first_name") or ""
                last = meta.get("last_name") or ""
                name = f"{first} {last}".strip() or str(pick.get("player_id"))
                details = [x for x in [meta.get("position"), meta.get("team")] if x]

                current_draft_picks_made[roster_id].append({
                    "pick_no": pick.get("pick_no"),
                    "round": pick.get("round"),
                    "draft_slot": pick.get("draft_slot"),
                    "player_id": pick.get("player_id"),
                    "player": f"{name} ({', '.join(details)})" if details else name,
                    "picked_by": pick.get("picked_by_name"),
                    "picked_by_team": pick.get("picked_by_team_name"),
                    "picked_by_user_id": pick.get("picked_by_user_id"),
                })

    summary = {
        "generated_from": {
            "league_id": league_context.get("league_id"),
            "league_name": league_context.get("name"),
            "season": league_context.get("season"),
            "source_generated_at": export_data["read_me_first"]["generated_at"],
        },
        "teams": [],
    }

    for team in sorted(teams, key=lambda t: t["roster_id"]):
        rid = str(team["roster_id"])

        roster_by_position = {}
        for pos, pids in (team.get("players_by_position") or {}).items():
            roster_by_position[pos] = [player_display_name(pid, players_lookup) for pid in pids]

        starters = [player_display_name(pid, players_lookup) for pid in team.get("starters") or []]
        reserve = [player_display_name(pid, players_lookup) for pid in team.get("reserve") or []]

        summary["teams"].append({
            "roster_id": team["roster_id"],
            "team_name": team["team_name"],
            "owner_name": team["owner_name"],
            "roster": {
                "summary": deepcopy(team.get("team_summary", {})),
                "roster_by_position": roster_by_position,
                "starters": starters,
                "reserve": reserve,
            },
            "current_and_future_picks_owned": sorted(
                inventory.get(rid, []),
                key=lambda p: (str(p["season"]), safe_int(p["round"], 0), safe_int(p["original_roster_id"], 0)),
            ),
            "picks_traded_away": sorted(
                traded_away.get(rid, []),
                key=lambda p: (str(p["season"]), safe_int(p["round"], 0), safe_int(p["original_roster_id"], 0)),
            ),
            "current_draft_picks_made": sorted(
                current_draft_picks_made.get(rid, []),
                key=lambda p: safe_int(p.get("pick_no"), 0) or 0,
            ),
        })

    return summary


def build_export(league_id, weeks, include_trending, future_years):
    nfl_state = sleeper_get("/state/nfl")
    league = sleeper_get(f"/league/{league_id}")
    if not league:
        raise RuntimeError(f"League not found: {league_id}")

    users = sleeper_get(f"/league/{league_id}/users") or []
    rosters = sleeper_get(f"/league/{league_id}/rosters") or []
    users_map = build_users_map(users)

    matchup_weeks = {}
    transaction_weeks = {}

    for week in weeks:
        matchup_weeks[week] = sleeper_get(f"/league/{league_id}/matchups/{week}") or []
        transaction_weeks[week] = sleeper_get(f"/league/{league_id}/transactions/{week}") or []

    drafts = sleeper_get(f"/league/{league_id}/drafts") or []
    league_traded_picks = sleeper_get(f"/league/{league_id}/traded_picks") or []

    draft_picks_by_draft = {}
    draft_traded_picks_by_draft = {}

    for draft in drafts:
        draft_id = draft.get("draft_id")
        draft_picks_by_draft[draft_id] = sleeper_get(f"/draft/{draft_id}/picks") or []
        draft_traded_picks_by_draft[draft_id] = sleeper_get(f"/draft/{draft_id}/traded_picks") or []

    all_players = sleeper_get("/players/nfl") or {}

    needed_ids = collect_needed_player_ids(
        rosters,
        matchup_weeks,
        draft_picks_by_draft,
        transaction_weeks,
    )
    players_lookup = build_players_lookup(needed_ids, all_players)

    teams = [
        build_team_object(roster, users_map, players_lookup)
        for roster in sorted(rosters, key=lambda r: safe_int(r.get("roster_id"), 0) or 0)
    ]

    teams_by_roster_id = {str(t["roster_id"]): t for t in teams}

    draft_room = {
        "drafts": [
            normalize_draft(
                draft,
                draft_picks_by_draft.get(draft.get("draft_id"), []),
                draft_traded_picks_by_draft.get(draft.get("draft_id"), []),
                teams_by_roster_id,
                users_map,
            )
            for draft in drafts
        ],
        "league_traded_future_picks": league_traded_picks,
    }

    weekly_results = {
        str(week): {
            "week": week,
            "matchups": [normalize_matchup(m, teams_by_roster_id) for m in matchups],
        }
        for week, matchups in matchup_weeks.items()
    }

    transactions = {
        str(week): [normalize_transaction(tx, teams_by_roster_id) for tx in txs]
        for week, txs in transaction_weeks.items()
    }

    export_data = {
        "read_me_first": {
            "purpose": "ChatGPT-optimized Sleeper fantasy football league export.",
            "generated_at": utc_now_iso(),
            "league_id": league_id,
            "season": str(league.get("season")),
            "weeks_included": weeks,
            "current_week": nfl_state.get("week") if isinstance(nfl_state, dict) else None,
            "how_to_read": [
                "Use league_context first.",
                "Use team_roster_and_picks_summary for roster and pick inventory questions.",
            ],
        },
        "league_context": {
            "league_id": league.get("league_id"),
            "name": league.get("name"),
            "season": league.get("season"),
            "season_type": league.get("season_type"),
            "sport": league.get("sport"),
            "status": league.get("status"),
            "total_rosters": league.get("total_rosters"),
            "draft_id": league.get("draft_id"),
            "current_nfl_state": nfl_state,
            "roster_positions": league.get("roster_positions"),
            "scoring_settings": league.get("scoring_settings"),
            "all_settings": league.get("settings") or {},
            "metadata": league.get("metadata") or {},
        },
        "users": users_map,
        "teams": teams,
        "draft_room": draft_room,
        "weekly_results": weekly_results,
        "transactions": transactions,
        "players_lookup": players_lookup,
        "trending": {},
    }

    if include_trending:
        export_data["trending"] = {
            "adds": sleeper_get("/players/nfl/trending/add?lookback_hours=24&limit=50") or [],
            "drops": sleeper_get("/players/nfl/trending/drop?lookback_hours=24&limit=50") or [],
        }

    export_data["team_roster_and_picks_summary"] = build_summary(export_data, future_years)

    return export_data


def github_get_file_sha(repo, path, branch, token):
    url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    response = requests.get(url, headers=headers, timeout=30)
    if response.status_code == 404:
        return None

    response.raise_for_status()
    return response.json().get("sha")


def github_put_file(repo, branch, path, content_text, message, token):
    sha = github_get_file_sha(repo, path, branch, token)

    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    payload = {
        "message": message,
        "content": base64.b64encode(content_text.encode("utf-8")).decode("utf-8"),
        "branch": branch,
    }

    if sha:
        payload["sha"] = sha

    response = requests.put(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()


def push_outputs_to_github(repo, branch, output_path, summary_path, token):
    with open(output_path, "r", encoding="utf-8") as f:
        main_text = f.read()

    with open(summary_path, "r", encoding="utf-8") as f:
        summary_text = f.read()

    github_put_file(
        repo=repo,
        branch=branch,
        path=os.path.basename(output_path),
        content_text=main_text,
        message="Update Sleeper ChatGPT export",
        token=token,
    )

    github_put_file(
        repo=repo,
        branch=branch,
        path=os.path.basename(summary_path),
        content_text=summary_text,
        message="Update Sleeper roster and picks summary",
        token=token,
    )


def parse_weeks(value):
    value = value.strip()

    if not value:
        return [1]

    if "-" in value:
        start, end = value.split("-", 1)
        return list(range(int(start), int(end) + 1))

    return [int(x.strip()) for x in value.split(",") if x.strip()]


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--league-id", default=DEFAULT_LEAGUE_ID)
    parser.add_argument("--output", default="sleeper_chatgpt.json")
    parser.add_argument("--weeks", default="1")
    parser.add_argument("--include-trending", action="store_true")
    parser.add_argument("--future-years", type=int, default=3)

    parser.add_argument("--push-github", action="store_true")
    parser.add_argument("--github-repo", default=DEFAULT_GITHUB_REPO)
    parser.add_argument("--github-branch", default=DEFAULT_GITHUB_BRANCH)
    parser.add_argument("--github-token", default=os.getenv("GITHUB_TOKEN"))

    args = parser.parse_args()

    export_data = build_export(
        league_id=args.league_id,
        weeks=parse_weeks(args.weeks),
        include_trending=args.include_trending,
        future_years=args.future_years,
    )

    output_path = args.output
    base, ext = os.path.splitext(output_path)
    if not ext:
        ext = ".json"

    summary_path = f"{base}_team_roster_and_picks_summary{ext}"

    write_json(output_path, export_data)
    write_json(summary_path, export_data["team_roster_and_picks_summary"])

    if not os.path.exists(output_path):
        raise RuntimeError(f"Main file was not created: {output_path}")

    if not os.path.exists(summary_path):
        raise RuntimeError(f"Summary file was not created: {summary_path}")

    print(f"Wrote main export: {output_path}")
    print(f"Wrote compact summary: {summary_path}")

    if args.push_github:
        if not args.github_token:
            raise RuntimeError(
                "Missing GitHub token. Set GITHUB_TOKEN or pass --github-token."
            )

        push_outputs_to_github(
            repo=args.github_repo,
            branch=args.github_branch,
            output_path=output_path,
            summary_path=summary_path,
            token=args.github_token,
        )

        print(f"Pushed files to GitHub repo: {args.github_repo}")


if __name__ == "__main__":
    main()