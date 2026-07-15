# src/leagueintel/reporting/pages/Podium.py
import pandas as pd
import streamlit as st
from leagueintel.analytics.consolation import (
    get_arbys_winner,
    get_medal_standings,
    get_toilet_bowl_loser,
)
from leagueintel.config import ALL_SEASONS
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
        arbys = get_arbys_winner(season)
        toilet_bowl = get_toilet_bowl_loser(season)
    except Exception:
        return None

    return {
        "season": season,
        "🥇 Gold": medals["first"],
        "🥈 Silver": medals["second"],
        "🥉 Bronze": medals["third"],
        "🍗 Arby's": arbys["arbys_winner"],
        "💩 Toilet Bowl": toilet_bowl["last_place"],
    }


rows = [row for season in sorted(ALL_SEASONS, reverse=True) if (row := _season_row(season))]

# ── page ──────────────────────────────────────────────────────────────────────

st.title("Podium")
st.caption(
    "Gold, silver, bronze from the playoff bracket; "
    "🍗 Arby's is best finish among non-playoff teams; "
    "💩 Toilet Bowl is the consolation bracket's last place."
)

with st.spinner("Loading medal history..."):
    df = pd.DataFrame(rows)

st.dataframe(df, use_container_width=True, hide_index=True)
