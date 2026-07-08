# src/leagueintel/reporting/playoff_bracket.py
"""
Playoff bracket visualization for leagueintel.
Generates an HTML bracket from the matchups table.
Designed for use with st.components.v1.html() in Streamlit.
"""

import pandas as pd
from leagueintel.storage.database import get_connection


def get_playoff_matchups(season: int) -> pd.DataFrame:
    """Fetch winners bracket matchups for a given season."""
    conn = get_connection()
    df = pd.read_sql(
        """
        SELECT
            m.week,
            m.home_score,
            m.away_score,
            ht.owner_name AS home_owner,
            at.owner_name  AS away_owner
        FROM matchups m
        JOIN teams ht
            ON m.home_team_id = ht.team_id
            AND m.season = ht.season
        LEFT JOIN teams at
            ON m.away_team_id = at.team_id
            AND m.season = at.season
        WHERE m.matchup_type = 'WINNERS_BRACKET'
        AND m.season = :season
        ORDER BY m.week
        """,
        conn,
        params={"season": season},
    )
    conn.close()
    return df


def _matchup_html(
    top_name: str,
    top_score: float | None,
    bot_name: str | None,
    bot_score: float | None,
) -> str:
    """Render one matchup card."""
    top_wins = (
        top_score is not None and bot_score is not None and top_score > bot_score
    ) or bot_name is None
    bot_wins = bot_score is not None and top_score is not None and bot_score > top_score

    def row(name, score, wins, bye=False):
        cls = "winner" if wins else ("bye" if bye else "loser")
        score_str = f"{score:.1f}" if score is not None else "—"
        return (
            f'<div class="team {cls}">'
            f'<span class="tname">{name}</span>'
            f'<span class="tscore">{score_str}</span>'
            f"</div>"
        )

    top_html = row(top_name, top_score, top_wins)
    if bot_name is None:
        bot_html = row("bye", None, False, bye=True)
    else:
        bot_html = row(bot_name, bot_score, bot_wins)

    return f'<div class="matchup">{top_html}{bot_html}</div>'


def _connector(n_pairs: int, gap_px: int) -> str:
    """Vertical connector lines between rounds."""
    pairs_html = ""
    for _ in range(n_pairs):
        pairs_html += (
            f'<div class="pair" style="height:{gap_px}px;">'
            '<div class="vline top"></div>'
            '<div class="hline"></div>'
            '<div class="vline bot"></div>'
            "</div>"
        )
    return f'<div class="connector">{pairs_html}</div>'


def render_playoff_bracket(season: int) -> str:
    """
    Build a self-contained HTML playoff bracket for a given season.
    Returns an HTML string suitable for st.components.v1.html().
    """
    df = get_playoff_matchups(season)
    if df.empty:
        return f"<p style='font-family:sans-serif;color:#888'>No playoff data for {season}.</p>"

    weeks = sorted(df["week"].unique())

    # ── build round data ────────────────────────────────────────────────────
    rounds = []
    for wk in weeks:
        wdf = df[df["week"] == wk]
        matchups = []
        for _, row in wdf.iterrows():
            matchups.append(
                {
                    "top": row["home_owner"],
                    "top_score": row["home_score"],
                    "bot": (
                        row["away_owner"] if pd.notna(row.get("away_owner")) else None
                    ),
                    "bot_score": (
                        row["away_score"]
                        if pd.notna(row.get("away_score"))
                        and row.get("away_score", 0) > 0
                        else None
                    ),
                }
            )
        rounds.append({"week": wk, "matchups": matchups})

    # ── round labels ─────────────────────────────────────────────────────────
    n_rounds = len(rounds)
    labels = {0: "quarterfinals", 1: "semifinals", 2: "championship"}
    if n_rounds == 2:
        labels = {0: "semifinals", 1: "championship"}
    elif n_rounds == 1:
        labels = {0: "championship"}

    # ── champion ─────────────────────────────────────────────────────────────
    last = rounds[-1]["matchups"][0]
    champ = (
        last["top"]
        if (last["top_score"] or 0) > (last["bot_score"] or 0)
        else last["bot"]
    )

    # ── HTML ─────────────────────────────────────────────────────────────────
    rounds_html = ""
    for i, rnd in enumerate(rounds):
        label = labels.get(i, f"week {rnd['week']}")
        cards = "".join(
            _matchup_html(m["top"], m["top_score"], m["bot"], m["bot_score"])
            for m in rnd["matchups"]
        )
        rounds_html += f"""
        <div class="round">
          <div class="rlabel">week {rnd['week']} · {label}</div>
          <div class="cards">{cards}</div>
        </div>
        """
        if i < len(rounds) - 1:
            n_pairs = len(rnd["matchups"]) // 2
            pair_h = 88 * (len(rnd["matchups"]) // max(n_pairs, 1))
            rounds_html += _connector(n_pairs, pair_h)

    champ_html = f"""
    <div class="champ-block">
      <div class="trophy">🏆</div>
      <div class="champ-label">champion</div>
      <div class="champ-name">{champ}</div>
    </div>
    """

    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: transparent;
    padding: 16px 8px;
  }}
  h2.title {{
    font-size: 14px;
    font-weight: 500;
    color: #888;
    margin-bottom: 16px;
    letter-spacing: 0.03em;
  }}
  .bracket {{
    display: flex;
    align-items: center;
    gap: 0;
    overflow-x: auto;
  }}
  .round {{
    display: flex;
    flex-direction: column;
    min-width: 160px;
  }}
  .rlabel {{
    font-size: 10px;
    color: #999;
    text-align: center;
    margin-bottom: 10px;
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }}
  .cards {{
    display: flex;
    flex-direction: column;
    gap: 10px;
  }}
  .matchup {{
    border: 1px solid #e2e2e2;
    border-radius: 8px;
    overflow: hidden;
    background: #fff;
  }}
  .team {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 7px 10px;
    font-size: 12px;
    gap: 8px;
    border-bottom: 1px solid #f0f0f0;
  }}
  .team:last-child {{ border-bottom: none; }}
  .team.winner {{ background: #f0faf4; }}
  .team.winner .tname {{ color: #1a7a45; font-weight: 500; }}
  .team.winner .tscore {{ color: #1a7a45; font-weight: 500; }}
  .team.loser .tname {{ color: #aaa; }}
  .team.loser .tscore {{ color: #aaa; }}
  .team.bye .tname {{ color: #bbb; font-style: italic; }}
  .team.bye .tscore {{ color: #bbb; }}
  .tname {{ flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .tscore {{ font-size: 11px; min-width: 36px; text-align: right; font-variant-numeric: tabular-nums; }}
  .connector {{
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    width: 28px;
    padding-top: 32px;
    gap: 0;
  }}
  .pair {{
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    width: 28px;
    position: relative;
  }}
  .vline {{
    width: 1px;
    background: #ddd;
    flex: 1;
    margin-left: 0;
  }}
  .hline {{
    width: 28px;
    height: 1px;
    background: #ddd;
  }}
  .champ-block {{
    text-align: center;
    padding: 8px 16px;
    min-width: 100px;
  }}
  .trophy {{ font-size: 22px; margin-bottom: 6px; }}
  .champ-label {{ font-size: 10px; color: #999; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px; }}
  .champ-name {{ font-size: 14px; font-weight: 500; color: #1a7a45; }}

  @media (prefers-color-scheme: dark) {{
    .matchup {{ background: #1e1e1e; border-color: #333; }}
    .team {{ border-bottom-color: #2a2a2a; }}
    .team.winner {{ background: #0d2e1a; }}
    .team.winner .tname, .team.winner .tscore {{ color: #4ade80; }}
    .team.loser .tname, .team.loser .tscore {{ color: #555; }}
    .team.bye .tname, .team.bye .tscore {{ color: #444; }}
    .vline, .hline {{ background: #444; }}
    .champ-name {{ color: #4ade80; }}
    h2.title, .rlabel, .champ-label {{ color: #666; }}
  }}
</style>
</head>
<body>
  <h2 class="title">{season} playoff bracket</h2>
  <div class="bracket">
    {rounds_html}
    {champ_html}
  </div>
</body>
</html>
"""


def bracket_height(season: int) -> int:
    """Estimate iframe height based on number of quarterfinal matchups."""
    df = get_playoff_matchups(season)
    if df.empty:
        return 100
    qf_count = df[df["week"] == df["week"].min()].shape[0]
    return max(300, qf_count * 100 + 120)
