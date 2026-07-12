# src/leagueintel/reporting/pages/Season_Overview.py
import streamlit as st
import streamlit.components.v1 as components
from leagueintel.analytics.standings import get_standings
from leagueintel.config import ALL_SEASONS
from leagueintel.reporting.home import shared_sidebar
from leagueintel.reporting.playoff_bracket import bracket_height, render_playoff_bracket

st.set_page_config(
    page_title="leagueintel — Season Overview", page_icon="🏈", layout="wide"
)

# ── auth gate ─────────────────────────────────────────────────────────────────

if not st.session_state.get("authenticated"):
    st.switch_page("home.py")
    st.stop()

shared_sidebar()

season = st.session_state.get("selected_season", max(ALL_SEASONS))

# ── page ──────────────────────────────────────────────────────────────────────

st.title(f"Season Overview — {season}")

st.header("Standings")
standings = get_standings(season)
st.dataframe(
    standings,
    use_container_width=True,
    hide_index=True,
    column_config={
        "manager": "Manager",
        "wins": st.column_config.NumberColumn("W"),
        "losses": st.column_config.NumberColumn("L"),
        "ties": st.column_config.NumberColumn("T"),
        "points_for": st.column_config.NumberColumn("PF", format="%.1f"),
        "points_against": st.column_config.NumberColumn("PA", format="%.1f"),
        "point_diff": st.column_config.NumberColumn("Diff", format="%+.1f"),
    },
)

st.header("Playoff Bracket")
components.html(render_playoff_bracket(season), height=bracket_height(season))

st.header("Last Place")
st.info("Last place tracker coming soon")
