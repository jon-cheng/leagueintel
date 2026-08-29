# src/leagueintel/reporting/pages/Podium.py
import pandas as pd
import streamlit as st
from leagueintel.analytics.consolation import (
    get_consolation_ladder_winner,
    get_medal_standings,
    get_toilet_bowl_loser,
)
from leagueintel.config import ALL_SEASONS, CONSOLATION_LADDER_WINNER_LABEL, LAST_PLACE_LABEL
from leagueintel.reporting.home import shared_sidebar

st.set_page_config(
    page_title="leagueintel — Podium", page_icon="🏈", layout="wide"
)

# ── auth gate ─────────────────────────────────────────────────────────────────

if not st.session_state.get("authenticated"):
    st.switch_page("home.py")
    st.stop()

shared_sidebar()

# ── data ──────────────────────────────────────────────────────────────────────


def _season_row(season: int) -> dict | None:
    """
    Build one season's medal row, or None if the season lacks complete
    playoff/consolation data (e.g. bracket format changed, or the
    season hasn't finished yet).
    """
    try:
        medals = get_medal_standings(season)
        ladder_winner = get_consolation_ladder_winner(season)
        toilet_bowl = get_toilet_bowl_loser(season)
    except Exception:
        return None

    return {
        "season": season,
        "🥇 Gold": medals["first"],
        "🥈 Silver": medals["second"],
        "🥉 Bronze": medals["third"],
        f"🍗 {CONSOLATION_LADDER_WINNER_LABEL}": ladder_winner["winner"],
        f"💩 {LAST_PLACE_LABEL}": toilet_bowl["last_place"],
    }


rows = [row for season in sorted(ALL_SEASONS, reverse=True) if (row := _season_row(season))]

# ── page ──────────────────────────────────────────────────────────────────────

st.title("Podium")
st.caption(
    f"Gold, silver, bronze from the playoff bracket; "
    f"🍗 {CONSOLATION_LADDER_WINNER_LABEL} is best finish among non-playoff teams; "
    f"💩 {LAST_PLACE_LABEL} is the consolation bracket's last place."
)

with st.spinner("Loading medal history..."):
    df = pd.DataFrame(rows)

st.dataframe(df, use_container_width=True, hide_index=True)
