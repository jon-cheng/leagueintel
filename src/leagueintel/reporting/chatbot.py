# src/leagueintel/reporting/chatbot.py
"""
leagueintel chatbot — natural language interface over league data.
Uses Claude's tool use API to generate SQL and visualizations.
"""

import sqlite3
import pandas as pd
import plotly.express as px
import anthropic
from loguru import logger

from leagueintel.config import (
    DEFAULT_DB_PATH,
    ANTHROPIC_API_KEY,
    ALL_SEASONS,
    ENABLE_PROMPT_CACHING,
)
from leagueintel.ingestion.espn import get_scoring_description, get_league_context
from leagueintel.reporting.turso_client import (
    log_question,
    check_daily_budget,
)
from espn_api.football import League
from leagueintel.config import LEAGUE_ID, ESPN_S2, SWID


def _load_league_context() -> str:
    try:
        league = League(
            league_id=int(LEAGUE_ID), year=max(ALL_SEASONS), espn_s2=ESPN_S2, swid=SWID
        )
        return get_league_context(league)
    except Exception:
        return "League: private 12-team ESPN fantasy football league"


def _load_scoring_description() -> str:
    try:
        league = League(
            league_id=int(LEAGUE_ID), year=max(ALL_SEASONS), espn_s2=ESPN_S2, swid=SWID
        )
        return get_scoring_description(league, verbose=False)
    except Exception:
        return "League scoring: H2H_POINTS — Half PPR (0.5 per reception)"


SEASONS_STR = f"{min(ALL_SEASONS)}-{max(ALL_SEASONS)}"
LEAGUE_CONTEXT = _load_league_context()
SCORING_DESCRIPTION = _load_scoring_description()

# ── schema description ────────────────────────────────────────────────────────

SCHEMA_DESCRIPTION = f"""
## League Context
{LEAGUE_CONTEXT}

Scoring Description
{SCORING_DESCRIPTION}
Seasons available: {SEASONS_STR} ({max(ALL_SEASONS)} is the most recent season)
Always reference managers by owner_name, never by team_id.

## Views (prefer these over raw tables)

### matchups_long
One row per TEAM per game (not one row per game), including bye
weeks as a single row with NULL opponent fields.
Use for: any question about a specific team's matchup history,
results, or scores — who won, team point totals, closest/biggest-
margin games, head-to-head records, week-by-week season results.
Columns: id, season, week, team_id, opponent_team_id, score,
         opponent_score, projected, opponent_projected,
         designation, is_playoff, matchup_type
- Query with a simple WHERE team_id = X — no need to check both
  home_team_id and away_team_id like the raw matchups table
- opponent_team_id/opponent_score/opponent_projected can be NULL
  on bye weeks — handle that case rather than assuming an
  opponent always exists
- Prefer this over matchups for team-centric questions. Getting
  the home/away pairing wrong when using matchups directly is a
  known source of incorrect winner/score attribution — default
  to matchups_long unless you specifically need both teams' info
  in the same row (e.g. event-level facts not tied to one team's
  perspective)

### draft_box_scores
One row per drafted player per week.
Use for: draft ROI, bid amount vs performance.
Columns: player_name, bid_amount, season, owner_name, team_name,
         position, points, lineup_slot, week
- lineup_slot: QB/RB/WR/TE/RB-WR-TE=started, BE=bench, IR=injured
- Excludes K and D/ST

### draft_picks
One row per draft pick (no box score data).
Use for: draft order, spend by manager, pick numbers.
Columns: season, bid_amount, team_name, owner_name, player_name,
         overall_pick_number, position

### waiver_stints
One row per continuous roster stint for a player picked up off waivers
(drafted players are excluded — see draft_picks/draft_box_scores instead).
Use for: ad hoc questions specifically about WAIVER roster tenure, e.g.
how long a waiver pickup was rostered, or which waiver stints were
short-lived. For "regrettable drop" questions spanning any acquisition
type (draft, waiver, free agent, trade), use roster_stints instead.
Columns: player_id, team_id, season, acquisition_week, drop_week, duration_weeks
- acquisition_week: week the player was added via waiver
- drop_week: week the player was dropped by that SAME team, or 18 if
  never dropped by that team
- duration_weeks: drop_week - acquisition_week
- duration_weeks = 0 means the team added and dropped the player in the
  SAME scoring week — a real, deliberate stint, not a data artifact.
  For normal tenure questions, filter duration_weeks > 0 to exclude
  these same-week stints.
- No player_name/owner_name columns — join players on player_id and
  teams on (team_id, season) if you need those
- For "best waiver pickup" style questions use
  run_analysis(analysis='best_waiver_player') instead of querying this
  directly — see Tool selection rules below

### roster_stints
One row per continuous roster stint for a player on a team, across EVERY
acquisition path — draft, waiver, free agent, and trade. Unlike
waiver_stints, drafted players ARE included here.
Use for: roster tenure or "regrettable drop"/"regrettable move" questions
that should span all acquisition types, e.g. a team drafting a player and
cutting him before Week 1, not just waiver pickups.
Columns: player_id, team_id, season, acquisition_type, acquisition_week,
         drop_week, duration_weeks
- acquisition_type: 'DRAFT', 'WAIVER', 'FREEAGENT', or 'TRADE' — how the
  player arrived on this team
- acquisition_week: week the player arrived. Drafted players always show
  acquisition_week = 1.
- drop_week: week the SAME team's next departure (drop OR traded away)
  happened, or 18 if the team still has the player
- duration_weeks: drop_week - acquisition_week
- duration_weeks = 0 means the team acquired and gave up the player in
  the SAME scoring week — e.g. drafted and immediately cut before Week 1
  games, or a same-week waiver add/drop. This is the general
  "regrettable move" signal — filter duration_weeks = 0 for these
  questions, regardless of acquisition_type. For normal tenure
  questions, filter duration_weeks > 0.
- No player_name/owner_name columns — join players on player_id and
  teams on (team_id, season) if you need those
- For waiver-pickup VALUE/eligibility questions (which must exclude
  drafted players) use waiver_stints or
  run_analysis(analysis='best_waiver_player') instead — see Tool
  selection rules below

## Raw Tables

### transactions
One row per transaction event.
Columns: id, season, transaction_type, status, bid_amount,
         team_id, scoring_period_id, related_transaction_id
- transaction_type: WAIVER, DRAFT, FREEAGENT, ROSTER, and for trades:
  TRADE_PROPOSAL, TRADE_ACCEPT, TRADE_UPHOLD, TRADE_DECLINE, TRADE_VETO
- status: EXECUTED=won, FAILED_PLAYERALREADYDROPPED=lost bid,
          CANCELED, PENDING
- related_transaction_id: on losing bids, links to winning bid id.
  For trades, links TRADE_ACCEPT/TRADE_UPHOLD legs back to the same
  proposal — do not rely on this to find trade contents, see below
- TRADE_ACCEPT's own status is often NULL even for a real, completed
  trade (ESPN never marks that leg EXECUTED) — treat NULL as executed
  for trades: COALESCE(status, 'EXECUTED') = 'EXECUTED'

Common patterns:
  Successful waiver adds: transaction_type='WAIVER' AND status='EXECUTED'
  All bids on a player:   transaction_type='WAIVER' AND status != 'CANCELED'
  Losing bids only:       status LIKE 'FAILED%'
  Completed trades:       transaction_type IN ('TRADE_ACCEPT','TRADE_UPHOLD')
                          AND COALESCE(status,'EXECUTED')='EXECUTED'
                          — but prefer roster_stints (acquisition_type=
                          'TRADE') over querying trades from raw tables
                          directly, it already handles these gotchas

### transaction_moves
One row per player movement within a transaction.
Columns: transaction_id, item_type, player_id,
         from_team_id, to_team_id, overall_pick_number, source
- item_type: ADD, DROP, DRAFT, TRADE
- from_team_id/to_team_id: 0 = free agency
- source: 'ESPN' (from the API directly) or 'INFERRED' (ESPN dropped the
  trade's player data after it resolved; reconstructed by diffing
  rosters week-over-week). If a trade question turns on INFERRED rows,
  mention the trade detail is reconstructed, not directly from ESPN

### box_scores
One row per player per week per fantasy team.
Includes both started AND benched players.
Columns: season, week, team_id, player_id, player_name,
         position, lineup_slot, points, projected_points,
         on_bye_week, game_played
- lineup_slot: started = QB/RB/WR/TE/RB-WR-TE, bench = BE, injured = IR
- game_played: 0-100, percentage of game played (0 = DNP)

Common patterns:
  Started only:     lineup_slot NOT IN ('BE', 'IR')
  Points left on bench: lineup_slot = 'BE'
  Did not play:     game_played = 0 AND on_bye_week = 0

### matchups
One row per matchup per week. Use only when you need event-level
facts not tied to one team's perspective (both teams' info in the
same row) — for team-centric questions use matchups_long instead.
Columns: season, week, home_team_id, away_team_id,
         home_score, away_score, home_projected, away_projected,
         is_playoff, matchup_type
- away_team_id: NULL = bye week
- matchup_type: NONE=regular season, WINNERS_BRACKET=championship,
                WINNERS_CONSOLATION_LADDER=3rd-6th,
                LOSERS_CONSOLATION_LADDER=toilet bowl

Common patterns:
  Regular season only: matchup_type = 'NONE'
  Exclude byes:        away_team_id IS NOT NULL
  Championship games:  matchup_type = 'WINNERS_BRACKET' AND week = 17

### teams
Columns: team_id, season, team_name, team_abbrev, owner_name
- owner_name: USE THIS to refer to managers, not team_id

### players
Columns: player_id, full_name
"""

# ── system prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = f"""
You are a fantasy football analytics assistant for a private ESPN league.
You have access to historical data from {min(ALL_SEASONS)} to {max(ALL_SEASONS)}.

{SCHEMA_DESCRIPTION}

Rules:
- Only generate SELECT queries, never INSERT/UPDATE/DELETE/DROP
- Always filter by season when the question implies a specific year
- The most recent season is {max(ALL_SEASONS)} — use this when no season is specified
- Reference managers by owner_name, not team_id
- For questions outside fantasy football or this league, politely decline
- Explain findings conversationally — not just raw numbers
- When showing rankings always include the manager name alongside player/stat
- Never use emojis in responses — they cause rendering issues in the UI
- NEVER use backticks in prose responses under any circumstances
  Backticks render as ugly code blocks in the UI and ruin the formatting
  WRONG: "won with a `48 bid, comfortably topping the next bidder's` 37"
  RIGHT: "won with a $48 bid, comfortably topping the next bidder's $37"
- NEVER place asterisks directly adjacent to numbers or dollar signs
  WRONG: "from *12*to*48*" or "$48*bid*"
  RIGHT: "from $12 to $48" or "a **$48 bid**"
- For emphasis use **double asterisks** with spaces around the word only
- All numbers, dollar amounts, scores, and bid values must be plain text

Tool selection rules:
- waiver value, best waiver pickup, waiver score, top waiver adds,
  who killed it on waivers, best undrafted player
  → ALWAYS use run_analysis(analysis='best_waiver_player')
  → NEVER use query_db for this
- draft ROI, draft value, draft efficiency, bid vs performance,
  best draft pick, draft steals, who overpaid in the draft
  → ALWAYS use run_analysis(analysis='draft_roi')
  → NEVER use query_db for this
- was acquiring a specific player worth it regardless of how they were
  acquired, value of one draft pick or trade, "was X a good pickup/
  trade/pick", "did we get fleeced/robbed in that trade", "how good
  was picking up X", "value of that trade for X", who won a trade,
  best/worst move of the season, smartest/dumbest add
  → ALWAYS use run_analysis(analysis='roster_value')
  → NEVER use query_db for this
- who finished first place, who won the league, who was the champion,
  final standings, playoff finish, medal standings
  → ALWAYS use run_analysis(analysis='medal_standings')
  → This is the PLAYOFF result (championship + 3rd place game), NOT
    regular-season record — the two often differ (in this league,
    6 of 7 seasons had a different regular-season leader vs. champion)
  → Only use query_db instead if the user explicitly says "regular
    season" standings/record
- most regrettable drop, worst drop, biggest drop mistake, "who cut a
  player who then blew up elsewhere"
  → TWO acquisition patterns both count as "regrettable" — check both:
    1. Same-week regret (added/drafted and cut before ever playing a
       week): query_db against roster_stints WHERE duration_weeks = 0.
       No further steps needed — the drop itself IS the regret, there's
       no "did well elsewhere" to measure.
    2. Cut-then-thrived regret (a normal stint, duration_weeks > 0,
       where the player was dropped and went on to score well for
       ANOTHER team): this needs two tool calls combined —
       a. query_db against roster_stints to find the drop event
          (team_id, player_id, drop_week) and that same player's NEXT
          stint (next acquisition_week for that player_id in a later
          team_id, same season)
       b. run_analysis(analysis='roster_value') for that season, then
          look up that player's value_score for the NEXT stint you
          found in step a — a high value_score there means the drop
          was regrettable
    Consider both patterns unless the question clearly means only one
    (e.g. "same-week cut" implies only pattern 1)
- best team, most impressive season, most dominant team, greatest
  team of a season (open-ended "best," NOT "first place"/"champion" —
  those have one right answer, see the medal_standings rule above)
  → genuinely ambiguous, no single correct answer — gather MULTIPLE
    signals rather than picking one:
    a. query_db for regular-season record and scoring
    b. run_analysis(analysis='medal_standings') for the actual playoff
       result
  → present both; do not silently omit the playoff outcome just
    because the highest scorer or record leader didn't win it
- everything else → use query_db

Accuracy rules:
- For complex temporal questions add a brief note to verify
  surprising results against the ESPN league UI — source of truth
- Never say verify against memory — use the ESPN UI
- run_analysis(analysis='roster_value') results can be based on very
  few weeks (as little as 1) since it scores any single acquisition,
  not just established waiver pickups. Check the num_weeks value for
  each result you cite: if num_weeks is small (well below 8), ALWAYS
  add a brief caveat noting the small sample size in your response
  (e.g. "based on just 2 weeks, so this could be noisy") — do not
  present a low-num_weeks score with the same confidence as a
  full-season one
"""

# ── tools ─────────────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "query_db",
        "description": "Run a SQL SELECT query against the leagueintel database and return results",
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "A valid SQLite SELECT query"}
            },
            "required": ["sql"],
        },
    },
    {
        "name": "run_analysis",
        "description": """Run a pre-built validated analysis pipeline.

        Use this INSTEAD of query_db for these specific questions:

        - best waiver pickup, waiver value, waiver score,
          who killed it on waivers, top waiver adds,
          best undrafted player, waiver wire rankings
          → analysis='best_waiver_player'

        - draft ROI, best draft value, draft efficiency,
          who got value in the draft, draft steals, bid vs performance
          → analysis='draft_roi'

        - was acquiring a specific player a good move regardless of HOW
          they were acquired (drafted, waiver, free agent, or traded for),
          value of a single draft pick or trade, comparing acquisition
          value across different acquisition types, who won a trade,
          "did we get fleeced/robbed in that trade", best/worst move
          of the season, smartest/dumbest add
          → analysis='roster_value'
          Unlike best_waiver_player, this includes drafted and traded
          players and scores stints with as little as 1 qualifying week —
          use it for single-player/single-move questions, not for ranking
          the best waiver pickups of the season (use best_waiver_player
          for that instead, since it's the validated, larger-sample view).

        - who finished in first/second/third place, who won the league,
          who was the champion, final standings, medal standings
          → analysis='medal_standings'
          This is the PLAYOFF result (championship game + 3rd place
          game), not regular-season record — the two often differ.
          Only skip this and use query_db instead if the user explicitly
          asks about "regular season" standings/record.

        Do NOT try to write SQL for these via query_db —
        the logic is complex, validated, and handles known edge cases
        (IR exclusion, stint deduplication, position normalization).
        """,
        "input_schema": {
            "type": "object",
            "properties": {
                "analysis": {
                    "type": "string",
                    "enum": [
                        "best_waiver_player",
                        "draft_roi",
                        "roster_value",
                        "medal_standings",
                    ],
                    "description": "Which pre-built analysis to run",
                },
                "season": {
                    "type": "integer",
                    "description": "NFL season year e.g. 2025",
                },
            },
            "required": ["analysis", "season"],
        },
    },
    {
        "name": "make_plot",
        "description": """Generate a visualization from the most recent query result.
        Choose plot_type based on what the question asks for:
        - bar: rankings or comparing categories (best players, spend by manager)
        - scatter: two numeric variables (bid amount vs points scored)
        - line: trends over time (weekly scoring trends, cumulative FAAB)
        - histogram: distribution of one variable (bid amount distribution)
        """,
        "input_schema": {
            "type": "object",
            "properties": {
                "plot_type": {
                    "type": "string",
                    "enum": ["bar", "scatter", "line", "histogram"],
                },
                "x": {"type": "string", "description": "Column name for x axis"},
                "y": {
                    "type": "string",
                    "description": "Column name for y axis (not needed for histogram)",
                },
                "color": {
                    "type": "string",
                    "description": "Column name for color grouping (optional)",
                },
                "title": {"type": "string", "description": "Chart title"},
            },
            "required": ["plot_type", "x", "title"],
        },
    },
]

# ── tool implementations ──────────────────────────────────────────────────────


def query_db(sql: str) -> tuple[str, pd.DataFrame | None]:
    """
    Execute a read-only SQL query.
    Returns (json_string_for_llm, dataframe_for_plotting).
    """
    logger.debug(f"SQL generated:\n{sql}")
    sql_upper = sql.strip().upper()
    if not sql_upper.startswith(("SELECT", "WITH")):
        return "Error: only SELECT queries are allowed", None
    try:
        conn = sqlite3.connect(f"file:{DEFAULT_DB_PATH}?mode=ro", uri=True)
        df = pd.read_sql(sql, conn)
        conn.close()
        return df.to_json(orient="records"), df
    except Exception as e:
        return f"Error: {str(e)}", None


def run_analysis(
    analysis: str,
    season: int,
) -> tuple[str, pd.DataFrame | None]:
    """
    Run a pre-built validated analytics function.
    Returns (json_string_for_llm, dataframe_for_plotting).
    """
    logger.debug(f"run_analysis: {analysis}, season={season}")
    try:
        if analysis == "best_waiver_player":
            from leagueintel.analytics.waiver import get_waiver_scores

            df = get_waiver_scores(season=season)
            return df.to_json(orient="records"), df

        elif analysis == "draft_roi":
            from leagueintel.analytics.draft import get_draft_roi

            df = get_draft_roi(season=season)
            return df.to_json(orient="records"), df

        elif analysis == "roster_value":
            from leagueintel.analytics.roster_value import get_roster_value_scores

            df = get_roster_value_scores(season=season)
            return df.to_json(orient="records"), df

        elif analysis == "medal_standings":
            from leagueintel.analytics.consolation import get_medal_standings

            df = pd.DataFrame([get_medal_standings(season=season)])
            return df.to_json(orient="records"), df

        else:
            return f"Error: unknown analysis '{analysis}'", None

    except Exception as e:
        msg = f"Error running analysis '{analysis}': {str(e)}"
        logger.error(msg)
        return msg, None


def make_plot(
    df: pd.DataFrame,
    plot_type: str,
    x: str,
    title: str,
    y: str = None,
    color: str = None,
) -> tuple[object | None, str]:
    """
    Generate a Plotly figure from a DataFrame.
    Returns (figure, message) — figure is None if an error occurred.
    The message is returned to the LLM so it can self-correct on failure.
    """
    available_cols = df.columns.tolist()

    # validate all requested columns exist before attempting to plot
    for col_name, col_val in [("x", x), ("y", y), ("color", color)]:
        if col_val and col_val not in available_cols:
            msg = (
                f"Error: column '{col_val}' not found in data. "
                f"Available columns: {available_cols}. "
                f"Please adjust the plot columns to match the query result."
            )
            logger.warning(msg)
            return None, msg

    try:
        if plot_type == "bar":
            fig = px.bar(df, x=x, y=y, color=color, title=title)
        elif plot_type == "scatter":
            fig = px.scatter(
                df, x=x, y=y, color=color, title=title, hover_data=available_cols
            )
        elif plot_type == "line":
            fig = px.line(df, x=x, y=y, color=color, title=title)
        elif plot_type == "histogram":
            fig = px.histogram(df, x=x, color=color, title=title)
        else:
            return None, f"Error: unknown plot_type '{plot_type}'"

        return fig, "Plot generated successfully"

    except Exception as e:
        msg = f"Error generating plot: {str(e)}"
        logger.error(msg)
        return None, msg


# ── agent loop ────────────────────────────────────────────────────────────────


def _get_client() -> anthropic.Anthropic:
    """
    Lazy client instantiation — reads API key at call time not import time.
    Required for Streamlit Cloud where secrets aren't available at import.
    """
    import os

    api_key = os.getenv("ANTHROPIC_API_KEY") or ANTHROPIC_API_KEY
    return anthropic.Anthropic(api_key=api_key)


def _build_system_param():
    """
    Return the system prompt, marked with a cache breakpoint when caching
    is enabled. Because tools/system/messages are cached as one prefix up
    to the breakpoint, marking this block also covers TOOLS for free —
    both are static across every question, so this is the biggest win.
    """
    if ENABLE_PROMPT_CACHING:
        return [
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    return SYSTEM_PROMPT


def _add_cache_breakpoint(messages: list) -> list:
    """
    Return a copy of `messages` with a cache breakpoint on the last
    content block of the last message. This lets the growing agent-loop
    conversation (tool calls + results) be read from cache on each
    subsequent round trip within the same question, instead of
    reprocessing everything from scratch each time.

    Does not mutate `messages` — the caller keeps appending plain
    dicts/blocks to the real list; this is only applied to the copy
    handed to messages.create().
    """
    if not ENABLE_PROMPT_CACHING or not messages:
        return messages

    messages = list(messages)
    last = dict(messages[-1])
    content = last["content"]

    if isinstance(content, str):
        content = [
            {
                "type": "text",
                "text": content,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    else:
        content = [dict(block) for block in content]
        content[-1]["cache_control"] = {"type": "ephemeral"}

    last["content"] = content
    messages[-1] = last
    return messages


def ask(question: str) -> tuple[str, object | None]:
    """
    Run one question through the chatbot agent loop.
    Returns (text_response, plotly_figure or None).
    """
    # check daily token budget before making any API call
    within_budget, tokens_used = check_daily_budget()
    if not within_budget:
        logger.warning(
            f"Daily token budget exceeded: {tokens_used:,} tokens used today"
        )
        return (
            "The daily question limit has been reached. "
            "Come back tomorrow — the limit resets at midnight UTC.",
            None,
        )

    messages = [{"role": "user", "content": question}]
    last_df = None  # track most recent query result for plotting
    fig = None  # track any generated plot
    total_input = 0
    total_output = 0
    total_cache_write = 0
    total_cache_read = 0
    last_tool_used = None
    last_analysis_used = None

    while True:
        request_kwargs = dict(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=_build_system_param(),
            tools=TOOLS,
            messages=_add_cache_breakpoint(messages),
        )
        response = _get_client().messages.create(**request_kwargs)

        u = response.usage
        total_input += u.input_tokens
        total_output += u.output_tokens
        total_cache_write += getattr(u, "cache_creation_input_tokens", 0) or 0
        total_cache_read += getattr(u, "cache_read_input_tokens", 0) or 0

        if response.stop_reason == "tool_use":
            tool_results = []

            for block in response.content:
                if block.type == "tool_use":

                    if block.name in ("query_db", "run_analysis", "make_plot"):
                        last_tool_used = block.name

                    if block.name == "query_db":
                        result, last_df = query_db(block.input["sql"])

                    elif block.name == "run_analysis":
                        last_analysis_used = block.input.get("analysis")
                        result, last_df = run_analysis(
                            analysis=block.input["analysis"],
                            season=block.input["season"],
                        )

                    elif block.name == "make_plot":
                        if last_df is not None:
                            fig, result = make_plot(
                                df=last_df,
                                plot_type=block.input["plot_type"],
                                x=block.input["x"],
                                y=block.input.get("y"),
                                color=block.input.get("color"),
                                title=block.input.get("title", ""),
                            )
                            # if fig is None, result contains the error message
                            # the LLM will see it and can self-correct on next turn
                        else:
                            fig = None
                            result = (
                                "Error: no data available to plot — run a query first"
                            )

                    else:
                        result = f"Error: unknown tool {block.name}"

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        }
                    )

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        else:
            text = next(
                block.text for block in response.content if hasattr(block, "text")
            )
            # log total usage across every tool-use round trip for this
            # question, not just the final turn — best effort, never
            # blocks the response
            log_question(
                tool_used=last_tool_used,
                analysis_used=last_analysis_used,
                tokens_input=total_input,
                tokens_output=total_output,
                cache_write_tokens=total_cache_write,
                cache_read_tokens=total_cache_read,
            )
            return text, fig
