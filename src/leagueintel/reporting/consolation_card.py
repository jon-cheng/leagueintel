# src/leagueintel/reporting/consolation_card.py
"""
Single-matchup card for consolation bracket outcomes (Arby's Bowl, Toilet Bowl).
Styled to match the playoff bracket's card look (see playoff_bracket.py).
"""

_COLORS = {
    "green": {"bg": "#f0faf4", "text": "#1a7a45", "bg_dark": "#0d2e1a", "text_dark": "#4ade80"},
    "red": {"bg": "#fdf0f0", "text": "#b91c1c", "bg_dark": "#2e0d0d", "text_dark": "#f87171"},
}


def render_matchup_card(
    title: str,
    emoji: str,
    name_top: str,
    score_top: float,
    name_bot: str,
    score_bot: float,
    highlight: str,
    color: str,
) -> str:
    """
    Build a self-contained HTML matchup card for st.components.v1.html().

    highlight: "top" or "bot" — which row gets the colored callout.
    color: "green" or "red".
    """
    c = _COLORS[color]

    def row(name, score, highlighted):
        cls = "hl" if highlighted else ""
        return (
            f'<div class="team {cls}">'
            f'<span class="tname">{name}</span>'
            f'<span class="tscore">{score:.1f}</span>'
            f"</div>"
        )

    top_html = row(name_top, score_top, highlight == "top")
    bot_html = row(name_bot, score_bot, highlight == "bot")

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
    padding: 4px 8px;
  }}
  h2.title {{
    font-size: 14px;
    font-weight: 500;
    color: #888;
    margin-bottom: 10px;
    letter-spacing: 0.03em;
  }}
  .card {{
    display: flex;
    align-items: center;
    gap: 12px;
  }}
  .emoji {{ font-size: 28px; }}
  .matchup {{
    border: 1px solid #e2e2e2;
    border-radius: 8px;
    overflow: hidden;
    background: #fff;
    min-width: 260px;
    max-width: 360px;
  }}
  .team {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    font-size: 13px;
    gap: 10px;
    border-bottom: 1px solid #f0f0f0;
  }}
  .team:last-child {{ border-bottom: none; }}
  .team.hl {{ background: {c["bg"]}; }}
  .team.hl .tname, .team.hl .tscore {{ color: {c["text"]}; font-weight: 600; }}
  .tname {{ flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .tscore {{ font-size: 12px; min-width: 40px; text-align: right; font-variant-numeric: tabular-nums; }}

  @media (prefers-color-scheme: dark) {{
    .matchup {{ background: #1e1e1e; border-color: #333; }}
    .team {{ border-bottom-color: #2a2a2a; }}
    .team.hl {{ background: {c["bg_dark"]}; }}
    .team.hl .tname, .team.hl .tscore {{ color: {c["text_dark"]}; }}
    h2.title {{ color: #666; }}
  }}
</style>
</head>
<body>
  <h2 class="title">{title}</h2>
  <div class="card">
    <div class="emoji">{emoji}</div>
    <div class="matchup">{top_html}{bot_html}</div>
  </div>
</body>
</html>
"""
