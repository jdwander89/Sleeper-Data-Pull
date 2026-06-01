"""
Sleeper → ChatGPT Full Data Exporter

Creates:
1. sleeper_chatgpt.json
2. sleeper_chatgpt_manifest.json
3. sleeper_chatgpt_league_context_summary.json
4. sleeper_chatgpt_team_roster_and_picks_summary.json
5. sleeper_chatgpt_draft_board_summary.json
6. sleeper_chatgpt_trade_market_summary.json
7. sleeper_chatgpt_transactions_summary.json
8. sleeper_chatgpt_matchups_standings_summary.json
9. sleeper_chatgpt_waiver_summary.json

Optional GitHub push:
- Set GITHUB_TOKEN as an environment variable.
- Run: python revised_sleeper_to_chatgpt.py --push-github

Default League ID:
1312581067286282240
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


# ==========================================================
# BASIC HELPERS
# ==========================================================

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


def sleeper_get(path: str, retries: int = 3, sleep_seconds: float = 0.4) -> Any:
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
            if attempt < retries:
                time.sleep(sleep_seconds * attempt)

    raise RuntimeError(f"Failed GET {url}: {last_error}")


def parse_weeks(value: str) -> List[int]:
    value = value.strip()

    if not value:
        return [1]

    if "-" in value:
        start, end = value.split("-", 1)
        return list(range(int(start), int(end) + 1))

    return [int(x.strip()) for x in value.split(",") if x.strip()]


# ==========================================================
# PLAYER HELPERS
# ==========================================================

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
    if player_id is None:
        return "Unknown"

    player_id = str(player_id)
    p = players_lookup.get(player_id, {})

    name = p.get("full_name")
    if not name:
        first = p.get("first_name") or ""
        last = p.get("last_name") or ""
        name = f"{first} {last}".strip()

    if not name:
        name = player_id

    details = []
    if p.get("position"):
        details.append(str(p["position"]))
    if p.get("team"):
        details.append(str(p["team"]))

    return f"{name} ({', '.join(details)})" if details else name


def make_players_lookup(players: Dict[str, Any], include_all_players: bool) -> Dict[str, Dict[str, Any]]:
    if not include_all_players:
        return {}

    output = {}
    for pid, raw in players.items():
        if isinstance(raw, dict):
            output[str(pid)] = normalize_player(str(pid), raw)

    return output


def build_limited_players_lookup(
    player_ids_needed: List[Any],
    all_players: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    output = {}

    for pid in player_ids_needed:
        if pid is None:
            continue

        pid = str(pid)
        raw = all_players.get(pid)

        if isinstance(raw, dict):
            output[pid] = normalize_player(pid, raw)
        else:
            output[pid] = {
                "player_id": pid,
                "full_name": pid,
                "first_name": None,
                "last_name": None,
                "position": None,
                "team": None,
                "status": None,
                "injury_status": None,
                "years_exp": None,
                "age": None,
                "fantasy_positions": None,
                "depth_chart_position": None,
                "depth_chart_order": None,
                "college": None,
                "search_rank": None,
            }

    return output


# ==========================================================
# USER / TEAM HELPERS
# ==========================================================

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
            "is_bot": u.get("is_bot"),
            "metadata": metadata,
            "team_name": team_name,
        }

    return output


def get_owner_name(owner_id: Any, users_map: Dict[str, Dict[str, Any]]) -> str:
    if owner_id is None:
        return "Unknown"
    owner_id = str(owner_id)
    return users_map.get(owner_id, {}).get("display_name") or owner_id


def get_team_name(owner_id: Any, users_map: Dict[str, Dict[str, Any]]) -> str:
    if owner_id is None:
        return "Unknown"
    owner_id = str(owner_id)
    user = users_map.get(owner_id, {})
    return user.get("team_name") or user.get("display_name") or owner_id


def team_ref(roster_id: Any, teams_by_roster_id: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    roster_id_str = str(roster_id)
    team = teams_by_roster_id.get(roster_id_str, {})

    return {
        "roster_id": safe_int(roster_id),
        "team_name": team.get("team_name") or f"Roster {roster_id}",
        "owner_name": team.get("owner_name"),
    }


def build_team_object(
    roster: Dict[str, Any],
    users_map: Dict[str, Dict[str, Any]],
    players_lookup: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
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

    average_age_by_position = {
        pos: round(sum(ages) / len(ages), 2)
        for pos, ages in ages_by_position.items()
        if ages
    }

    return {
        "roster_id": roster.get("roster_id"),
        "team_name": get_team_name(owner_id, users_map),
        "owner_name": get_owner_name(owner_id, users_map),
        "owner_id": str(owner_id) if owner_id is not None else None,
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
            "total_players": len(players),
            "starter_count": len(starters),
            "reserve_count": len(reserve),
            "position_counts": dict(sorted(position_counts.items())),
            "starter_position_counts": dict(sorted(starter_position_counts.items())),
            "average_age_by_position": dict(sorted(average_age_by_position.items())),
        },
        "players_by_position": {
            pos: sorted(pids, key=lambda x: player_display_name(x, players_lookup))
            for pos, pids in sorted(players_by_position.items())
        },
        "starters": starters,
        "reserve": reserve,
        "settings": settings,
    }


def get_team_key_maps(teams: List[Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    by_roster_id = {}
    by_team_name = {}

    for team in teams or []:
        roster_id = team.get("roster_id")
        if roster_id is None:
            continue

        roster_id_str = str(roster_id)
        by_roster_id[roster_id_str] = {
            "roster_id": roster_id,
            "team_name": team.get("team_name"),
            "owner_name": team.get("owner_name"),
            "owner_id": team.get("owner_id"),
        }

        if team.get("team_name"):
            by_team_name[team["team_name"]] = by_roster_id[roster_id_str]

    return by_roster_id, by_team_name


# ==========================================================
# DRAFT HELPERS
# ==========================================================

def normalize_draft_pick(
    pick: Dict[str, Any],
    teams_by_roster_id: Dict[str, Dict[str, Any]],
    users_map: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    metadata = pick.get("metadata") or {}
    roster_id = pick.get("roster_id")

    picked_by_user_id = str(pick.get("picked_by")) if pick.get("picked_by") is not None else None
    picked_by_name = None
    picked_by_team_name = None

    if picked_by_user_id and users_map:
        picked_by_user = users_map.get(picked_by_user_id, {})
        picked_by_name = (
            picked_by_user.get("display_name")
            or picked_by_user.get("username")
            or picked_by_user_id
        )
        picked_by_team_name = picked_by_user.get("team_name") or picked_by_name
    elif picked_by_user_id:
        picked_by_name = picked_by_user_id
        picked_by_team_name = picked_by_user_id

    return {
        "pick_no": pick.get("pick_no"),
        "round": pick.get("round"),
        "draft_slot": pick.get("draft_slot"),
        "player_id": str(pick.get("player_id")) if pick.get("player_id") is not None else None,
        "roster": team_ref(roster_id, teams_by_roster_id),
        "picked_by_user_id": picked_by_user_id,
        "picked_by_name": picked_by_name,
        "picked_by_team_name": picked_by_team_name,
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
            "news_updated": metadata.get("news_updated"),
            "team_abbr": metadata.get("team_abbr"),
            "team_changed_at": metadata.get("team_changed_at"),
        },
        "is_keeper": pick.get("is_keeper"),
        "picked_at": pick.get("picked_at"),
    }


def group_picks_by_round(
    picks: List[Dict[str, Any]],
    teams_by_roster_id: Dict[str, Dict[str, Any]],
    users_map: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    rounds = defaultdict(list)

    for pick in picks or []:
        round_no = str(pick.get("round"))
        rounds[round_no].append(
            normalize_draft_pick(
                pick,
                teams_by_roster_id,
                users_map=users_map,
            )
        )

    for round_no in rounds:
        rounds[round_no] = sorted(
            rounds[round_no],
            key=lambda p: safe_int(p.get("pick_no"), 0) or 0,
        )

    return dict(sorted(rounds.items(), key=lambda kv: safe_int(kv[0], 0) or 0))


def normalize_draft(
    draft: Dict[str, Any],
    picks: List[Dict[str, Any]],
    traded_picks: List[Dict[str, Any]],
    teams_by_roster_id: Dict[str, Dict[str, Any]],
    users_map: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
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
        "rounds": group_picks_by_round(
            picks,
            teams_by_roster_id,
            users_map=users_map,
        ),
        "traded_picks": traded_picks or [],
    }


def flatten_completed_draft_picks(draft_room: Dict[str, Any]) -> List[Dict[str, Any]]:
    picks_out = []

    for draft in draft_room.get("drafts", []):
        for _, picks in (draft.get("rounds") or {}).items():
            for pick in picks or []:
                metadata = pick.get("metadata") or {}
                first = metadata.get("first_name") or ""
                last = metadata.get("last_name") or ""
                name = f"{first} {last}".strip() or str(pick.get("player_id"))
                details = [x for x in [metadata.get("position"), metadata.get("team")] if x]

                picks_out.append({
                    "draft_id": draft.get("draft_id"),
                    "pick_no": pick.get("pick_no"),
                    "round": pick.get("round"),
                    "draft_slot": pick.get("draft_slot"),
                    "player_id": pick.get("player_id"),
                    "player": f"{name} ({', '.join(details)})" if details else name,
                    "roster": pick.get("roster"),
                    "picked_by": pick.get("picked_by_name"),
                    "picked_by_team": pick.get("picked_by_team_name"),
                    "picked_by_user_id": pick.get("picked_by_user_id"),
                })

    return sorted(picks_out, key=lambda p: safe_int(p.get("pick_no"), 0) or 0)


# ==========================================================
# MATCHUP / TRANSACTION HELPERS
# ==========================================================

def normalize_matchup(
    matchup: Dict[str, Any],
    teams_by_roster_id: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    roster_id = matchup.get("roster_id")

    return {
        "roster": team_ref(roster_id, teams_by_roster_id),
        "matchup_id": matchup.get("matchup_id"),
        "points": matchup.get("points"),
        "custom_points": matchup.get("custom_points"),
        "players": [str(p) for p in matchup.get("players") or []],
        "starters": [str(p) for p in matchup.get("starters") or []],
        "players_points": matchup.get("players_points") or {},
        "starters_points": matchup.get("starters_points") or {},
    }


def normalize_transaction(
    tx: Dict[str, Any],
    teams_by_roster_id: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    roster_ids = tx.get("roster_ids") or []

    def normalize_player_move_map(move_map: Optional[Dict[str, Any]], direction: str) -> List[Dict[str, Any]]:
        output = []
        if not move_map:
            return output

        for player_id, roster_id in move_map.items():
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
        "adds": normalize_player_move_map(tx.get("adds"), "to"),
        "drops": normalize_player_move_map(tx.get("drops"), "from"),
        "draft_picks": tx.get("draft_picks") or [],
        "waiver_budget": tx.get("waiver_budget") or [],
        "settings": tx.get("settings"),
        "metadata": tx.get("metadata"),
        "consenter_ids": tx.get("consenter_ids"),
    }


# ==========================================================
# PICK INVENTORY HELPERS
# ==========================================================

def describe_pick(
    pick: Dict[str, Any],
    by_roster_id: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
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


def build_default_pick_inventory(
    teams: List[Dict[str, Any]],
    seasons: List[int],
    rounds: int,
) -> Dict[str, List[Dict[str, Any]]]:
    inventory = defaultdict(list)

    for team in teams or []:
        roster_id = team.get("roster_id")
        team_name = team.get("team_name")

        if roster_id is None:
            continue

        for season in seasons:
            for round_no in range(1, rounds + 1):
                inventory[str(roster_id)].append({
                    "season": str(season),
                    "round": round_no,
                    "label": f"{season} Round {round_no} own",
                    "original_roster_id": roster_id,
                    "original_team": team_name,
                    "current_owner_roster_id": roster_id,
                    "current_owner_team": team_name,
                    "previous_owner_roster_id": roster_id,
                    "previous_owner_team": team_name,
                })

    return inventory


def flatten_draft_room_traded_picks(draft_room: Dict[str, Any]) -> List[Dict[str, Any]]:
    traded = []

    for draft in (draft_room or {}).get("drafts", []):
        traded.extend(draft.get("traded_picks") or [])

    return traded


def collect_transaction_traded_picks(transactions: Any) -> List[Dict[str, Any]]:
    traded = []

    if isinstance(transactions, dict):
        tx_groups = transactions.values()
    else:
        tx_groups = transactions or []

    for group in tx_groups:
        tx_list = group if isinstance(group, list) else group.get("transactions", [])

        for tx in tx_list:
            if not isinstance(tx, dict):
                continue
            if tx.get("type") != "trade":
                continue
            if tx.get("status") != "complete":
                continue

            traded.extend(tx.get("draft_picks") or [])

    return traded


def dedupe_traded_picks(picks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    output = []

    for p in picks or []:
        key = (
            str(p.get("season")),
            safe_int(p.get("round"), 0) or 0,
            safe_int(p.get("roster_id"), 0) or 0,
            safe_int(p.get("owner_id"), 0) or 0,
            safe_int(p.get("previous_owner_id"), 0) or 0,
        )

        if key in seen:
            continue

        seen.add(key)
        output.append(p)

    return output


def apply_traded_picks_to_inventory(
    inventory: Dict[str, List[Dict[str, Any]]],
    traded_picks: List[Dict[str, Any]],
    by_roster_id: Dict[str, Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    for pick in traded_picks or []:
        desc = describe_pick(pick, by_roster_id)

        season = desc["season"]
        round_no = desc["round"]
        original_roster_id = desc["original_roster_id"]
        current_owner_roster_id = desc["current_owner_roster_id"]

        if original_roster_id is None or current_owner_roster_id is None or round_no is None:
            continue

        for roster_id, picks in inventory.items():
            inventory[roster_id] = [
                p for p in picks
                if not (
                    str(p.get("season")) == str(season)
                    and safe_int(p.get("round")) == round_no
                    and safe_int(p.get("original_roster_id")) == original_roster_id
                )
            ]

        inventory[str(current_owner_roster_id)].append(desc)

    return inventory


def sort_pick_inventory(inventory: Dict[str, List[Dict[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
    sorted_inventory = {}

    for roster_id, picks in inventory.items():
        sorted_inventory[str(roster_id)] = sorted(
            picks,
            key=lambda p: (
                str(p.get("season", "")),
                safe_int(p.get("round"), 0) or 0,
                safe_int(p.get("original_roster_id"), 0) or 0,
            )
        )

    return sorted_inventory


def build_pick_inventory(export_data: Dict[str, Any], future_years: int = 3) -> Tuple[
    Dict[str, List[Dict[str, Any]]],
    Dict[str, List[Dict[str, Any]]],
    List[Dict[str, Any]],
]:
    teams = export_data.get("teams") or []
    draft_room = export_data.get("draft_room") or {}
    transactions = export_data.get("transactions") or {}
    league_context = export_data.get("league_context") or {}

    season = str(league_context.get("season") or export_data.get("read_me_first", {}).get("season") or "")
    current_season_int = safe_int(season)
    rounds = safe_int(league_context.get("all_settings", {}).get("draft_rounds"), 5) or 5

    seasons = [current_season_int + i for i in range(0, future_years + 1)] if current_season_int else []

    by_roster_id, _ = get_team_key_maps(teams)

    draft_room_trades = flatten_draft_room_traded_picks(draft_room)
    transaction_pick_trades = collect_transaction_traded_picks(transactions)
    all_traded_picks = dedupe_traded_picks(draft_room_trades + transaction_pick_trades)

    pick_inventory = build_default_pick_inventory(teams, seasons, rounds)
    pick_inventory = apply_traded_picks_to_inventory(pick_inventory, all_traded_picks, by_roster_id)
    pick_inventory = sort_pick_inventory(pick_inventory)

    traded_away = defaultdict(list)
    for pick in all_traded_picks:
        desc = describe_pick(pick, by_roster_id)
        original_roster_id = desc.get("original_roster_id")
        current_owner_roster_id = desc.get("current_owner_roster_id")

        if (
            original_roster_id is not None
            and current_owner_roster_id is not None
            and original_roster_id != current_owner_roster_id
        ):
            traded_away[str(original_roster_id)].append(desc)

    return pick_inventory, dict(traded_away), all_traded_picks


# ==========================================================
# SUMMARY BUILDERS
# ==========================================================

def build_league_context_summary(export_data: Dict[str, Any]) -> Dict[str, Any]:
    league = export_data.get("league_context") or {}
    draft_room = export_data.get("draft_room") or {}

    drafts = draft_room.get("drafts") or []
    active_draft = drafts[0] if drafts else {}

    return {
        "generated_from": export_data.get("read_me_first", {}),
        "league": {
            "league_id": league.get("league_id"),
            "name": league.get("name"),
            "season": league.get("season"),
            "season_type": league.get("season_type"),
            "sport": league.get("sport"),
            "status": league.get("status"),
            "total_rosters": league.get("total_rosters"),
            "draft_id": league.get("draft_id"),
        },
        "nfl_state": league.get("current_nfl_state"),
        "roster_positions": league.get("roster_positions"),
        "scoring_settings": league.get("scoring_settings"),
        "settings_summary": league.get("settings_summary"),
        "all_settings": league.get("all_settings"),
        "league_metadata": league.get("metadata"),
        "active_draft_settings": {
            "draft_id": active_draft.get("draft_id"),
            "season": active_draft.get("season"),
            "status": active_draft.get("status"),
            "type": active_draft.get("type"),
            "settings": active_draft.get("settings"),
            "metadata": active_draft.get("metadata"),
        },
    }


def build_roster_summary_by_team(
    teams: List[Dict[str, Any]],
    players_lookup: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    output = {}

    for team in teams or []:
        roster_id = str(team.get("roster_id"))
        players_by_position = team.get("players_by_position") or {}

        roster = {}
        for position in sorted(players_by_position.keys()):
            roster[position] = [
                player_display_name(pid, players_lookup)
                for pid in players_by_position.get(position, [])
            ]

        starters = [player_display_name(pid, players_lookup) for pid in team.get("starters", [])]
        reserve = [player_display_name(pid, players_lookup) for pid in team.get("reserve", [])]

        output[roster_id] = {
            "roster_id": team.get("roster_id"),
            "team_name": team.get("team_name"),
            "owner_name": team.get("owner_name"),
            "summary": deepcopy(team.get("team_summary", {})),
            "roster_by_position": roster,
            "starters": starters,
            "reserve": reserve,
        }

    return output


def build_team_roster_and_picks_summary(export_data: Dict[str, Any], future_years: int = 3) -> Dict[str, Any]:
    teams = export_data.get("teams") or []
    players_lookup = export_data.get("players_lookup") or {}

    pick_inventory, traded_away, _ = build_pick_inventory(export_data, future_years)
    roster_summary = build_roster_summary_by_team(teams, players_lookup)

    current_draft_picks_made = defaultdict(list)
    for pick in flatten_completed_draft_picks(export_data.get("draft_room", {})):
        roster_id = str((pick.get("roster") or {}).get("roster_id"))
        current_draft_picks_made[roster_id].append(pick)

    result = {
        "generated_from": export_data.get("read_me_first", {}),
        "teams": [],
    }

    for team in sorted(teams, key=lambda t: safe_int(t.get("roster_id"), 0) or 0):
        roster_id = str(team.get("roster_id"))

        result["teams"].append({
            "roster_id": team.get("roster_id"),
            "team_name": team.get("team_name"),
            "owner_name": team.get("owner_name"),
            "roster": roster_summary.get(roster_id, {}),
            "current_and_future_picks_owned": pick_inventory.get(roster_id, []),
            "picks_traded_away": sorted(
                traded_away.get(roster_id, []),
                key=lambda p: (
                    str(p.get("season", "")),
                    safe_int(p.get("round"), 0) or 0,
                    safe_int(p.get("original_roster_id"), 0) or 0,
                )
            ),
            "current_draft_picks_made": sorted(
                current_draft_picks_made.get(roster_id, []),
                key=lambda p: safe_int(p.get("pick_no"), 0) or 0,
            ),
        })

    return result


def build_draft_board_summary(export_data: Dict[str, Any], future_years: int = 3) -> Dict[str, Any]:
    league = export_data.get("league_context") or {}
    metadata = league.get("metadata") or {}
    users = export_data.get("users") or {}
    teams = export_data.get("teams") or {}
    draft_room = export_data.get("draft_room") or {}

    drafts = draft_room.get("drafts") or []
    active_draft = drafts[0] if drafts else {}

    completed_picks = flatten_completed_draft_picks(draft_room)

    current_pick_no = safe_int(metadata.get("current_pick_no"))
    on_clock_user_id = metadata.get("on_the_clock_user_id")
    on_clock_user = users.get(str(on_clock_user_id), {}) if on_clock_user_id else {}

    picks_by_team = defaultdict(list)
    for pick in completed_picks:
        roster_id = str((pick.get("roster") or {}).get("roster_id"))
        picks_by_team[roster_id].append(pick)

    pick_inventory, _, all_traded_picks = build_pick_inventory(export_data, future_years)

    return {
        "generated_from": export_data.get("read_me_first", {}),
        "draft": {
            "draft_id": active_draft.get("draft_id"),
            "season": active_draft.get("season"),
            "status": active_draft.get("status"),
            "type": active_draft.get("type"),
            "settings": active_draft.get("settings"),
            "metadata": active_draft.get("metadata"),
            "draft_order": active_draft.get("draft_order"),
            "slot_to_roster_id": active_draft.get("slot_to_roster_id"),
        },
        "current_status": {
            "league_status": league.get("status"),
            "current_pick_no": current_pick_no,
            "completed_pick_count": len(completed_picks),
            "latest_completed_pick": completed_picks[-1] if completed_picks else None,
            "on_the_clock_user_id": on_clock_user_id,
            "on_the_clock_display_name": on_clock_user.get("display_name"),
            "on_the_clock_team_name": on_clock_user.get("team_name"),
        },
        "completed_picks": completed_picks,
        "completed_picks_by_roster_id": dict(picks_by_team),
        "current_and_future_pick_inventory_by_roster_id": pick_inventory,
        "traded_picks_raw": all_traded_picks,
    }


def count_picks_by_season_round(picks: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    out = defaultdict(lambda: defaultdict(int))

    for pick in picks:
        season = str(pick.get("season"))
        round_no = str(pick.get("round"))
        out[season][round_no] += 1

    return {season: dict(rounds) for season, rounds in out.items()}


def build_trade_market_summary(export_data: Dict[str, Any], future_years: int = 3) -> Dict[str, Any]:
    teams = export_data.get("teams") or []
    pick_inventory, traded_away, _ = build_pick_inventory(export_data, future_years)

    output = {
        "generated_from": export_data.get("read_me_first", {}),
        "team_trade_profiles": [],
    }

    for team in sorted(teams, key=lambda t: safe_int(t.get("roster_id"), 0) or 0):
        roster_id = str(team.get("roster_id"))
        summary = team.get("team_summary") or {}
        pos_counts = summary.get("position_counts") or {}
        avg_age = summary.get("average_age_by_position") or {}
        owned_picks = pick_inventory.get(roster_id, [])

        needs = []
        surplus = []

        for pos, target in {"QB": 2, "RB": 5, "WR": 7, "TE": 2}.items():
            count = safe_int(pos_counts.get(pos), 0) or 0
            if count < target:
                needs.append(pos)
            elif count >= target + 2:
                surplus.append(pos)

        output["team_trade_profiles"].append({
            "roster_id": team.get("roster_id"),
            "team_name": team.get("team_name"),
            "owner_name": team.get("owner_name"),
            "position_counts": pos_counts,
            "starter_position_counts": summary.get("starter_position_counts"),
            "average_age_by_position": avg_age,
            "likely_needs_by_count": needs,
            "possible_surplus_by_count": surplus,
            "owned_pick_count": len(owned_picks),
            "owned_picks_by_season_round": count_picks_by_season_round(owned_picks),
            "picks_traded_away": traded_away.get(roster_id, []),
            "waiver_position": (team.get("waivers") or {}).get("waiver_position"),
            "waiver_budget_used": (team.get("waivers") or {}).get("waiver_budget_used"),
        })

    return output


def resolve_transaction_players(tx: Dict[str, Any], players_lookup: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    tx = deepcopy(tx)

    for move_key, direction_key in [("adds", "to"), ("drops", "from")]:
        moves = []
        for item in tx.get(move_key) or []:
            pid = item.get("player_id")
            moves.append({
                "player_id": pid,
                "player": player_display_name(pid, players_lookup),
                direction_key: item.get(direction_key),
            })
        tx[move_key] = moves

    return tx


def build_transactions_summary(export_data: Dict[str, Any]) -> Dict[str, Any]:
    players_lookup = export_data.get("players_lookup") or {}
    transactions = export_data.get("transactions") or {}

    by_week = {}
    trades = []
    pick_moves = []
    player_moves = []

    for week, txs in transactions.items():
        by_week[week] = []

        for tx in txs:
            resolved = resolve_transaction_players(tx, players_lookup)
            by_week[week].append(resolved)

            if tx.get("type") == "trade":
                trades.append(resolved)

            for pick in tx.get("draft_picks") or []:
                pick_moves.append({
                    "week": week,
                    "transaction_id": tx.get("transaction_id"),
                    "teams": tx.get("teams"),
                    "pick": pick,
                })

            for move_key in ["adds", "drops"]:
                for move in resolved.get(move_key) or []:
                    player_moves.append({
                        "week": week,
                        "transaction_id": tx.get("transaction_id"),
                        "type": tx.get("type"),
                        "move_type": move_key,
                        "move": move,
                    })

    return {
        "generated_from": export_data.get("read_me_first", {}),
        "transactions_by_week": by_week,
        "trades": trades,
        "draft_pick_movements": pick_moves,
        "player_movements": player_moves,
    }


def build_matchups_standings_summary(export_data: Dict[str, Any]) -> Dict[str, Any]:
    teams = export_data.get("teams") or []
    weekly_results = export_data.get("weekly_results") or {}

    standings = []
    for team in teams:
        record = team.get("record") or {}
        points_for = (safe_int(record.get("points_for"), 0) or 0) + (
            (safe_int(record.get("points_for_decimal"), 0) or 0) / 100
        )

        standings.append({
            "roster_id": team.get("roster_id"),
            "team_name": team.get("team_name"),
            "owner_name": team.get("owner_name"),
            "wins": record.get("wins"),
            "losses": record.get("losses"),
            "ties": record.get("ties"),
            "points_for": points_for,
            "points_against": record.get("points_against"),
            "potential_points": record.get("potential_points"),
        })

    standings = sorted(
        standings,
        key=lambda t: (
            -(safe_int(t.get("wins"), 0) or 0),
            safe_int(t.get("losses"), 0) or 0,
            -(t.get("points_for") or 0),
        )
    )

    return {
        "generated_from": export_data.get("read_me_first", {}),
        "standings": standings,
        "weekly_results": weekly_results,
        "playoff_brackets": export_data.get("playoff_brackets"),
    }


def build_waiver_summary(
    export_data: Dict[str, Any],
    all_players: Dict[str, Any],
    max_available_per_position: int = 40,
) -> Dict[str, Any]:
    rostered_ids = set()

    for team in export_data.get("teams") or []:
        for pids in (team.get("players_by_position") or {}).values():
            rostered_ids.update(str(pid) for pid in pids)

    trending = export_data.get("trending") or {}
    trending_adds = []
    trending_drops = []

    for item in trending.get("adds") or []:
        pid = str(item.get("player_id"))
        raw = all_players.get(pid, {})
        player = normalize_player(pid, raw) if isinstance(raw, dict) else {"player_id": pid}
        player["count"] = item.get("count")
        trending_adds.append(player)

    for item in trending.get("drops") or []:
        pid = str(item.get("player_id"))
        raw = all_players.get(pid, {})
        player = normalize_player(pid, raw) if isinstance(raw, dict) else {"player_id": pid}
        player["count"] = item.get("count")
        trending_drops.append(player)

    available_by_position = defaultdict(list)

    for pid, raw in all_players.items():
        pid = str(pid)
        if pid in rostered_ids:
            continue
        if not isinstance(raw, dict):
            continue

        pos = raw.get("position")
        if pos not in {"QB", "RB", "WR", "TE"}:
            continue

        normalized = normalize_player(pid, raw)
        available_by_position[pos].append(normalized)

    for pos in list(available_by_position.keys()):
        available_by_position[pos] = sorted(
            available_by_position[pos],
            key=lambda p: safe_int(p.get("search_rank"), 999999) or 999999
        )[:max_available_per_position]

    return {
        "generated_from": export_data.get("read_me_first", {}),
        "note": "Available-player sample is based on unrostered QB/RB/WR/TE players sorted by Sleeper search_rank.",
        "waiver_order": [
            {
                "roster_id": team.get("roster_id"),
                "team_name": team.get("team_name"),
                "owner_name": team.get("owner_name"),
                "waiver_position": (team.get("waivers") or {}).get("waiver_position"),
                "waiver_budget_used": (team.get("waivers") or {}).get("waiver_budget_used"),
            }
            for team in sorted(
                export_data.get("teams") or [],
                key=lambda t: safe_int((t.get("waivers") or {}).get("waiver_position"), 999) or 999
            )
        ],
        "trending_adds": trending_adds,
        "trending_drops": trending_drops,
        "available_player_sample_by_position": dict(available_by_position),
    }


def build_all_summaries(
    export_data: Dict[str, Any],
    all_players: Dict[str, Any],
    future_years: int,
) -> Dict[str, Dict[str, Any]]:
    return {
        "league_context_summary": build_league_context_summary(export_data),
        "team_roster_and_picks_summary": build_team_roster_and_picks_summary(export_data, future_years=future_years),
        "draft_board_summary": build_draft_board_summary(export_data, future_years=future_years),
        "trade_market_summary": build_trade_market_summary(export_data, future_years=future_years),
        "transactions_summary": build_transactions_summary(export_data),
        "matchups_standings_summary": build_matchups_standings_summary(export_data),
        "waiver_summary": build_waiver_summary(export_data, all_players),
    }


# ==========================================================
# MAIN EXPORT BUILD
# ==========================================================

def collect_needed_player_ids(
    rosters: List[Dict[str, Any]],
    matchup_weeks: Dict[int, List[Dict[str, Any]]],
    draft_picks_by_draft: Dict[str, List[Dict[str, Any]]],
    transactions_by_week: Dict[int, List[Dict[str, Any]]],
    trending: Dict[str, List[Dict[str, Any]]],
) -> List[str]:
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
                needed.add(str(pick.get("player_id")))

    for txs in transactions_by_week.values():
        for tx in txs or []:
            for move_map in [tx.get("adds"), tx.get("drops")]:
                for pid in (move_map or {}).keys():
                    needed.add(str(pid))

    for group in (trending or {}).values():
        for item in group or []:
            if item.get("player_id") is not None:
                needed.add(str(item.get("player_id")))

    return sorted(needed)


def build_export(
    league_id: str,
    *,
    weeks: List[int],
    include_all_players: bool,
    include_trending: bool,
    future_years: int,
) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]], Dict[str, Any]]:
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

    winners_bracket = sleeper_get(f"/league/{league_id}/winners_bracket") or []
    losers_bracket = sleeper_get(f"/league/{league_id}/losers_bracket") or []

    league_traded_picks = sleeper_get(f"/league/{league_id}/traded_picks") or []
    drafts = sleeper_get(f"/league/{league_id}/drafts") or []

    draft_picks_by_draft = {}
    draft_traded_picks_by_draft = {}

    for draft in drafts or []:
        draft_id = draft.get("draft_id")
        if not draft_id:
            continue
        draft_picks_by_draft[draft_id] = sleeper_get(f"/draft/{draft_id}/picks") or []
        draft_traded_picks_by_draft[draft_id] = sleeper_get(f"/draft/{draft_id}/traded_picks") or []

    trending = {}
    if include_trending:
        trending = {
            "adds": sleeper_get("/players/nfl/trending/add?lookback_hours=24&limit=50") or [],
            "drops": sleeper_get("/players/nfl/trending/drop?lookback_hours=24&limit=50") or [],
        }

    all_players = sleeper_get("/players/nfl") or {}

    needed_player_ids = collect_needed_player_ids(
        rosters,
        matchup_weeks,
        draft_picks_by_draft,
        transaction_weeks,
        trending,
    )

    if include_all_players:
        players_lookup = make_players_lookup(all_players, include_all_players=True)
    else:
        players_lookup = build_limited_players_lookup(needed_player_ids, all_players)

    teams = [
        build_team_object(roster, users_map, players_lookup)
        for roster in sorted(rosters, key=lambda r: safe_int(r.get("roster_id"), 0) or 0)
    ]

    teams_by_roster_id = {str(t["roster_id"]): t for t in teams}

    weekly_results = {}
    for week, matchups in matchup_weeks.items():
        weekly_results[str(week)] = {
            "week": week,
            "matchups": [
                normalize_matchup(m, teams_by_roster_id)
                for m in matchups
            ],
        }

    transactions = {}
    for week, txs in transaction_weeks.items():
        transactions[str(week)] = [
            normalize_transaction(tx, teams_by_roster_id)
            for tx in txs
        ]

    draft_room = {
        "drafts": [
            normalize_draft(
                draft,
                draft_picks_by_draft.get(draft.get("draft_id"), []),
                draft_traded_picks_by_draft.get(draft.get("draft_id"), []),
                teams_by_roster_id,
                users_map=users_map,
            )
            for draft in drafts
        ],
        "league_traded_future_picks": league_traded_picks,
    }

    generated_at = utc_now_iso()

    export_data = {
        "read_me_first": {
            "purpose": "ChatGPT-optimized Sleeper fantasy football league export.",
            "generated_at": generated_at,
            "league_id": league_id,
            "season": str(league.get("season")),
            "weeks_included": weeks,
            "current_week": nfl_state.get("week") if isinstance(nfl_state, dict) else None,
            "summary_files": [
                "league_context_summary",
                "team_roster_and_picks_summary",
                "draft_board_summary",
                "trade_market_summary",
                "transactions_summary",
                "matchups_standings_summary",
                "waiver_summary",
            ],
            "how_to_read": [
                "Use the summary files first for normal analysis.",
                "Use sleeper_chatgpt.json only as the full source-of-truth archive.",
                "Use team_roster_and_picks_summary for roster and pick inventory questions.",
                "Use draft_board_summary for live draft questions.",
                "Use trade_market_summary for trade strategy.",
                "Use transactions_summary for trade/history questions.",
                "Use waiver_summary for waiver/free-agent questions.",
                "Use league_context_summary for scoring/settings questions.",
            ],
            "excluded_sections": [
                "birth date",
                "high school",
                "hometown",
                "physical attributes",
                "athletic testing",
                "headshots and visuals",
                "avatars and media",
                "taxi squad raw objects",
                "raw Sleeper payload dumps",
            ],
        },
        "league_context": {
            "league_id": league.get("league_id"),
            "name": league.get("name"),
            "season": league.get("season"),
            "season_type": league.get("season_type"),
            "sport": league.get("sport"),
            "status": league.get("status"),
            "league_type": league.get("league_type"),
            "total_rosters": league.get("total_rosters"),
            "previous_league_id": league.get("previous_league_id"),
            "draft_id": league.get("draft_id"),
            "current_nfl_state": nfl_state,
            "roster_positions": league.get("roster_positions"),
            "scoring_settings": league.get("scoring_settings"),
            "settings_summary": {
                "teams": league.get("settings", {}).get("num_teams"),
                "playoff_teams": league.get("settings", {}).get("playoff_teams"),
                "trade_deadline": league.get("settings", {}).get("trade_deadline"),
                "waiver_type": league.get("settings", {}).get("waiver_type"),
                "waiver_budget": league.get("settings", {}).get("waiver_budget"),
                "reserve_slots": league.get("settings", {}).get("reserve_slots"),
                "bench_slots": league.get("settings", {}).get("bench_slots"),
                "max_keepers": league.get("settings", {}).get("max_keepers"),
                "best_ball": league.get("settings", {}).get("best_ball"),
                "median_scoring": league.get("settings", {}).get("league_average_match"),
                "daily_waivers": league.get("settings", {}).get("daily_waivers"),
                "draft_rounds": league.get("settings", {}).get("draft_rounds"),
            },
            "all_settings": league.get("settings") or {},
            "metadata": league.get("metadata") or {},
        },
        "users": users_map,
        "teams": teams,
        "draft_room": draft_room,
        "weekly_results": weekly_results,
        "transactions": transactions,
        "playoff_brackets": {
            "winners": winners_bracket,
            "losers": losers_bracket,
        },
        "players_lookup": players_lookup,
        "trending": trending,
    }

    summaries = build_all_summaries(export_data, all_players, future_years=future_years)

    return export_data, summaries, all_players


# ==========================================================
# FILE WRITING / GITHUB PUSH
# ==========================================================

def build_output_paths(main_output: str) -> Dict[str, str]:
    base, ext = os.path.splitext(main_output)
    if not ext:
        ext = ".json"

    return {
        "main": main_output,
        "manifest": f"{base}_manifest{ext}",
        "league_context_summary": f"{base}_league_context_summary{ext}",
        "team_roster_and_picks_summary": f"{base}_team_roster_and_picks_summary{ext}",
        "draft_board_summary": f"{base}_draft_board_summary{ext}",
        "trade_market_summary": f"{base}_trade_market_summary{ext}",
        "transactions_summary": f"{base}_transactions_summary{ext}",
        "matchups_standings_summary": f"{base}_matchups_standings_summary{ext}",
        "waiver_summary": f"{base}_waiver_summary{ext}",
    }


def write_all_outputs(
    output_paths: Dict[str, str],
    export_data: Dict[str, Any],
    summaries: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    write_json(output_paths["main"], export_data)

    manifest = {
        "generated_at": export_data.get("read_me_first", {}).get("generated_at"),
        "league_id": export_data.get("read_me_first", {}).get("league_id"),
        "season": export_data.get("read_me_first", {}).get("season"),
        "files": {
            "main": output_paths["main"],
            "league_context_summary": output_paths["league_context_summary"],
            "team_roster_and_picks_summary": output_paths["team_roster_and_picks_summary"],
            "draft_board_summary": output_paths["draft_board_summary"],
            "trade_market_summary": output_paths["trade_market_summary"],
            "transactions_summary": output_paths["transactions_summary"],
            "matchups_standings_summary": output_paths["matchups_standings_summary"],
            "waiver_summary": output_paths["waiver_summary"],
        },
        "recommended_usage": {
            "start_here": output_paths["manifest"],
            "settings": output_paths["league_context_summary"],
            "team_rosters_and_picks": output_paths["team_roster_and_picks_summary"],
            "draft_monitoring": output_paths["draft_board_summary"],
            "trade_analysis": output_paths["trade_market_summary"],
            "transaction_history": output_paths["transactions_summary"],
            "standings_and_matchups": output_paths["matchups_standings_summary"],
            "waivers": output_paths["waiver_summary"],
        },
    }

    write_json(output_paths["manifest"], manifest)

    for key, data in summaries.items():
        write_json(output_paths[key], data)

    for path in output_paths.values():
        if not os.path.exists(path):
            raise RuntimeError(f"Expected output file was not created: {path}")

    return manifest


def github_get_file_sha(repo: str, path: str, branch: str, token: str) -> Optional[str]:
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


def github_put_file(
    repo: str,
    branch: str,
    path: str,
    content_text: str,
    message: str,
    token: str,
) -> None:
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


def push_outputs_to_github(
    repo: str,
    branch: str,
    output_paths: Dict[str, str],
    token: str,
) -> None:
    for label, local_path in output_paths.items():
        with open(local_path, "r", encoding="utf-8") as f:
            content_text = f.read()

        github_put_file(
            repo=repo,
            branch=branch,
            path=os.path.basename(local_path),
            content_text=content_text,
            message=f"Update Sleeper export file: {os.path.basename(local_path)}",
            token=token,
        )


# ==========================================================
# CLI
# ==========================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export Sleeper fantasy football league data to ChatGPT-friendly JSON files."
    )

    parser.add_argument("--league-id", default=DEFAULT_LEAGUE_ID)
    parser.add_argument("--output", default="sleeper_chatgpt.json")
    parser.add_argument("--weeks", default="1")
    parser.add_argument("--include-all-players", action="store_true")
    parser.add_argument("--include-trending", action="store_true")
    parser.add_argument("--future-years", type=int, default=3)

    parser.add_argument("--push-github", action="store_true")
    parser.add_argument("--github-repo", default=DEFAULT_GITHUB_REPO)
    parser.add_argument("--github-branch", default=DEFAULT_GITHUB_BRANCH)
    parser.add_argument("--github-token", default=os.getenv("GITHUB_TOKEN"))

    args = parser.parse_args()

    weeks = parse_weeks(args.weeks)

    export_data, summaries, _ = build_export(
        args.league_id,
        weeks=weeks,
        include_all_players=args.include_all_players,
        include_trending=args.include_trending,
        future_years=args.future_years,
    )

    output_paths = build_output_paths(args.output)
    manifest = write_all_outputs(output_paths, export_data, summaries)

    print("Wrote Sleeper export files:")
    for label, path in output_paths.items():
        print(f"- {label}: {path}")

    if args.push_github:
        if not args.github_token:
            raise RuntimeError("Missing GitHub token. Set GITHUB_TOKEN or pass --github-token.")

        push_outputs_to_github(
            repo=args.github_repo,
            branch=args.github_branch,
            output_paths=output_paths,
            token=args.github_token,
        )

        print(f"Pushed all export files to GitHub repo: {args.github_repo}")

    print("Recommended file for ChatGPT to inspect first:")
    print(f"- {manifest['recommended_usage']['start_here']}")


if __name__ == "__main__":
    main()
