"""
ESPN API ingestion layer.
Fetches raw transaction data and saves as JSON.
"""

import json
import time
import requests
from pathlib import Path
from espn_api.football import League
from espn_api.football.team import Team
from loguru import logger

from leagueintel.config import (
    LEAGUE_ID,
    ESPN_S2,
    SWID,
    ALL_SEASONS,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_MAX_WEEK,
    BASE_URL,
)
from leagueintel.storage.database import get_connection, create_tables
from leagueintel.storage.writer import (
    write_teams,
    write_players,
    write_box_scores,
    write_matchups,
)


def _get_weeks(max_week: int = DEFAULT_MAX_WEEK) -> list[int]:
    return list(range(1, max_week + 1))


def _fetch_week(year: int, week: int) -> dict:
    """Fetch raw transaction data from ESPN API for a given year and week."""
    url = BASE_URL.format(year=year, league_id=LEAGUE_ID)
    params = {"scoringPeriodId": week, "view": "mTransactions2"}
    cookies = {"espn_s2": ESPN_S2, "SWID": SWID}
    response = requests.get(url, params=params, cookies=cookies, timeout=10)
    response.raise_for_status()
    return response.json()


def _save_raw(data: dict, year: int, week: int, output_dir: str) -> str:
    """Save raw JSON response to disk or S3."""
    filename = f"week{week:02d}.json"
    content = json.dumps(data, indent=2)

    if str(output_dir).startswith("s3://"):
        raise NotImplementedError("S3 support coming soon")

    path = Path(output_dir) / str(year) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return str(path)


def _summarize(transactions: list) -> tuple[int, int, int]:
    """Return counts of executed waivers, failed waivers, and draft picks."""
    waiver_executed = sum(
        1
        for t in transactions
        if t.get("type") == "WAIVER" and t.get("status") == "EXECUTED"
    )
    waiver_failed = sum(
        1
        for t in transactions
        if t.get("type") == "WAIVER" and t.get("status", "").startswith("FAILED")
    )
    draft = sum(1 for t in transactions if t.get("type") == "DRAFT")
    return waiver_executed, waiver_failed, draft


def fetch_transactions_all(
    year: int = None,
    week: int = None,
    max_week: int = DEFAULT_MAX_WEEK,
    output_dir: str = None,
) -> None:
    """Fetch ESPN transaction data for given year/week and save as raw JSON."""
    if not all([LEAGUE_ID, ESPN_S2, SWID]):
        logger.error(
            "Missing credentials. Ensure LEAGUE_ID, ESPN_S2, SWID "
            "are set in your .env file."
        )
        return

    years = [year] if year else ALL_SEASONS
    weeks = [week] if week else _get_weeks(max_week)
    output_dir = output_dir or DEFAULT_OUTPUT_DIR

    logger.info(
        f"Fetching {len(years)} season(s) × {len(weeks)} week(s) "
        f"= {len(years) * len(weeks)} requests"
    )
    logger.info(f"Output directory: {output_dir}")

    success, errors = 0, 0

    for y in years:
        logger.info(f"=== Season {y} ===")
        for w in weeks:
            try:
                data = _fetch_week(y, w)
                path = _save_raw(data, y, w, output_dir)
                transactions = data.get("transactions", [])
                waiver_executed, waiver_failed, draft = _summarize(transactions)
                logger.info(
                    f"week {w:02d}: {len(transactions)} total | "
                    f"{waiver_executed} waiver wins | "
                    f"{waiver_failed} waiver losses | "
                    f"{draft} draft | "
                    f"saved → {Path(path).name}"
                )
                success += 1
                time.sleep(0.5)

            except requests.HTTPError as e:
                logger.warning(f"week {w:02d}: HTTP ERROR {e.response.status_code}")
                errors += 1
            except requests.Timeout:
                logger.warning(f"week {w:02d}: TIMEOUT")
                errors += 1
            except NotImplementedError as e:
                logger.error(f"week {w:02d}: {e}")
                errors += 1
            except Exception as e:
                logger.error(f"week {w:02d}: ERROR — {e}")
                errors += 1

    logger.info(f"Done. {success} succeeded, {errors} failed.")

    if errors > 0:
        logger.warning(f"{errors} week(s) failed — check logs above")
        raise SystemExit(1)


# ── Teams ─────────────────────────────────────────────────────────────────────


def _extract_team(team: Team, season: int) -> dict:
    return {
        "season": season,
        "team_id": team.team_id,
        "team_name": team.team_name,
        "team_abbrev": team.team_abbrev,
        "owner_name": (
            f"{team.owners[0]['firstName']} {team.owners[0]['lastName']}"
            if team.owners
            else None
        ),
    }


def fetch_teams(league: League, season: int) -> list[dict]:
    """Fetch team data from espn_api League object."""
    return [_extract_team(team, season) for team in league.teams]


def fetch_teams_all(seasons: list[int] = None) -> None:
    """Fetch team data for all seasons and write to SQLite."""
    seasons = seasons or ALL_SEASONS
    conn = get_connection()
    create_tables(conn)

    logger.info(f"Fetching teams for {len(seasons)} seasons")
    for year in seasons:
        league = League(league_id=LEAGUE_ID, year=year, espn_s2=ESPN_S2, swid=SWID)
        teams = fetch_teams(league, season=year)
        write_teams(teams, conn)
        logger.info(f"Season {year}: wrote {len(teams)} teams")

    conn.close()


# ── Players ───────────────────────────────────────────────────────────────────


def fetch_players(league: League) -> list[dict]:
    """Fetch all players from ESPN player_map for a given league season."""
    return [
        {"player_id": pid, "full_name": str(name)}
        for pid, name in league.player_map.items()
        if isinstance(pid, int)
    ]


def fetch_players_all(seasons: list[int] = None) -> None:
    """Fetch player map across all seasons and write to SQLite."""
    seasons = seasons or ALL_SEASONS
    conn = get_connection()
    create_tables(conn)

    all_players = {}

    logger.info(f"Fetching players across {len(seasons)} seasons")
    for year in seasons:
        league = League(league_id=LEAGUE_ID, year=year, espn_s2=ESPN_S2, swid=SWID)
        players = fetch_players(league)
        for p in players:
            if p["player_id"] not in all_players:
                all_players[p["player_id"]] = p
        logger.info(
            f"Season {year}: {len(players)} players in map, "
            f"{len(all_players)} unique total"
        )

    write_players(list(all_players.values()), conn)
    conn.close()


# ── Box scores ────────────────────────────────────────────────────────────────


def _extract_player_week(player, team_id: int, week: int, season: int) -> dict:
    """Extract box score fields from a single player in a lineup."""
    return {
        "season": season,
        "week": week,
        "team_id": team_id,
        "player_id": player.playerId,
        "player_name": player.name,
        "position": player.position,
        "lineup_slot": player.lineupSlot,
        "pro_team": player.proTeam,
        "points": player.points,
        "projected_points": player.projected_points,
        "on_bye_week": int(player.on_bye_week),
        "game_played": player.game_played,
    }


def fetch_box_scores(league: League, week: int, season: int) -> list[dict]:
    """Fetch all player box score records for a given week."""
    rows = []
    for matchup in league.box_scores(week):
        for player in matchup.home_lineup:
            rows.append(
                _extract_player_week(player, matchup.home_team.team_id, week, season)
            )
        if matchup.away_team != 0:
            for player in matchup.away_lineup:
                rows.append(
                    _extract_player_week(
                        player, matchup.away_team.team_id, week, season
                    )
                )
    return rows


def fetch_box_scores_all(
    seasons: list[int] = None,
) -> None:
    """Fetch box scores for all seasons and weeks and write to SQLite."""
    seasons = seasons or ALL_SEASONS
    conn = get_connection()
    create_tables(conn)

    for year in seasons:
        logger.info(f"=== Season {year} ===")
        league = League(league_id=LEAGUE_ID, year=year, espn_s2=ESPN_S2, swid=SWID)
        weeks = _get_weeks(league.finalScoringPeriod)

        for week in weeks:
            try:
                rows = fetch_box_scores(league, week, year)
                write_box_scores(rows, conn)
                logger.info(f"  week {week:02d}: wrote {len(rows)} player records")
                time.sleep(0.3)
            except Exception as e:
                logger.warning(f"  week {week:02d}: ERROR — {e}")

    conn.close()
    logger.info("Done.")


# ── Matchups ──────────────────────────────────────────────────────────────────


def _extract_matchup(matchup, week: int, season: int) -> dict:
    """Extract matchup-level fields from an espn_api box score matchup object."""
    home_team_id = matchup.home_team.team_id if matchup.home_team else None
    away_team_id = matchup.away_team.team_id if matchup.away_team else None

    return {
        "season": season,
        "week": week,
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "home_score": matchup.home_score,
        "away_score": matchup.away_score,
        "home_projected": matchup.home_projected,
        "away_projected": matchup.away_projected,
        "is_playoff": int(matchup.is_playoff),
        "matchup_type": matchup.matchup_type,
    }


def fetch_matchups(league: League, week: int, season: int) -> list[dict]:
    """Fetch all matchup records for a given week."""
    return [
        _extract_matchup(matchup, week, season)
        for matchup in league.box_scores(week)
        if matchup.home_team  # skip malformed entries with no home team
    ]


def fetch_matchups_all(
    seasons: list[int] = None,
) -> None:
    """Fetch matchup results for all seasons and weeks and write to SQLite."""
    seasons = seasons or ALL_SEASONS
    conn = get_connection()
    create_tables(conn)

    for year in seasons:
        logger.info(f"=== Season {year} ===")
        league = League(league_id=LEAGUE_ID, year=year, espn_s2=ESPN_S2, swid=SWID)
        weeks = _get_weeks(league.finalScoringPeriod)

        for week in weeks:
            try:
                rows = fetch_matchups(league, week, year)
                write_matchups(rows, conn)
                logger.info(f"  week {week:02d}: wrote {len(rows)} matchups")
                time.sleep(0.3)
            except Exception as e:
                logger.warning(f"  week {week:02d}: ERROR — {e}")

    conn.close()
    logger.info("Done.")


def get_league_context(league: League) -> str:
    """
    Generate a human-readable league context description
    from ESPN league settings. Fully dynamic — no hardcoded values.
    """
    settings = league.settings

    return f"""
League: {settings.name}
Teams: {settings.team_count} teams
Season structure: {settings.reg_season_count} regular season weeks,
                  top {settings.playoff_team_count} teams make playoffs
FAAB budget: ${settings.acquisition_budget} per season
Scoring: {get_scoring_description(league, verbose=False)}
""".strip()


def get_scoring_description(league: League, verbose: bool = False) -> str:
    """
    Generate scoring description from ESPN league settings.

    verbose=False: concise version for LLM system prompt
    verbose=True:  full version for documentation
    """
    settings = league.settings
    scoring_items = settings.scoring_format

    # always compute these regardless of verbose
    rec_item = next((s for s in scoring_items if s.get("abbr") == "REC"), None)
    rec_pts = rec_item["points"] if rec_item else 0.0
    ppr_type = (
        "Full PPR (1.0 per reception)"
        if rec_pts == 1.0
        else (
            "Half PPR (0.5 per reception)"
            if rec_pts == 0.5
            else (
                "Standard (no PPR)"
                if rec_pts == 0.0
                else f"Custom ({rec_pts} per reception)"
            )
        )
    )

    scoring_lookup = {item["abbr"]: item for item in scoring_items if item.get("abbr")}

    def pts(abbr: str) -> float:
        return scoring_lookup.get(abbr, {}).get("points", 0.0)

    if not verbose:
        # ── concise version for system prompt ────────────────────────
        return f"""League scoring: {settings.scoring_type} — {ppr_type}

Skill position scoring:
  Passing:   {pts('PTD')} pts passing TD, {pts('PY5')} pts per 5 passing yards,
             {pts('INTT')} pts interception thrown
  Rushing:   {pts('RTD')} pts rushing TD, {pts('RY')} pts per rushing yard
  Receiving: {pts('RETD')} pts receiving TD, {pts('REY')} pts per receiving yard,
             {pts('REC')} pts per reception
  Penalties: {pts('FUML')} pts fumble lost

Kicking: {pts('FGY')} pts per FG yard, {pts('FGM')} pt missed FG, {pts('PAT')} pt PAT made

Defense: standard ESPN D/ST scoring — points and yards allowed tiers,
         {pts('SK')} pt per sack, {pts('INT')} pts per INT, {pts('FR')} pts per fumble recovery,
         6 pts per return TD""".strip()

    else:
        # ── full version for documentation ────────────────────────────
        CATEGORIES = {
            "Passing": ["PTD", "PY5", "P400", "INTT", "2PC"],
            "Rushing": ["RTD", "RY", "RY200", "2PR"],
            "Receiving": ["RETD", "REY", "REY200", "REC", "2PRE"],
            "Kicking": ["FGY", "FGM", "PAT"],
            "Defense": [
                "INT",
                "SF",
                "SK",
                "FR",
                "BLKK",
                "BLKKRTD",
                "INTTD",
                "FRTD",
                "PRTD",
                "KRTD",
                "PA0",
                "PA1",
                "PA7",
                "PA14",
                "PA28",
                "PA35",
                "PA46",
                "YA100",
                "YA199",
                "YA299",
                "YA399",
                "YA449",
                "YA499",
                "YA549",
                "YA550",
            ],
            "Miscellaneous": ["FUML", "FTD"],
        }

        categorized = set()
        lines = [f"League scoring: {settings.scoring_type} — {ppr_type}", ""]

        for category, abbrs in CATEGORIES.items():
            category_lines = []
            for abbr in abbrs:
                if abbr in scoring_lookup:
                    item = scoring_lookup[abbr]
                    p = item["points"]
                    if p != 0.0:
                        category_lines.append(f"  {item['label']}: {p:+.1f} pts")
                        categorized.add(abbr)

            if category_lines:
                lines.append(f"{category}:")
                lines.extend(category_lines)
                lines.append("")

        # catch anything not in predefined categories
        uncategorized = [
            item
            for abbr, item in scoring_lookup.items()
            if abbr not in categorized and item["points"] != 0.0
        ]
        if uncategorized:
            lines.append("Other:")
            for item in uncategorized:
                lines.append(f"  {item['label']}: {item['points']:+.1f} pts")

        return "\n".join(lines)
