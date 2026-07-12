# src/leagueintel/reporting/pages/Season_Overview.py
import streamlit as st
import streamlit.components.v1 as components
from leagueintel.analytics.consolation import get_arbys_winner, get_toilet_bowl_loser
from leagueintel.analytics.standings import get_standings
from leagueintel.config import ALL_SEASONS
from leagueintel.reporting.consolation_card import render_matchup_card
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
        "team_name": "Team",
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

st.header("Arby's Bowl")
try:
    arbys = get_arbys_winner(season)
    card = render_matchup_card(
        title=f"{season} Consolation Ladder Championship",
        emoji="🥩",
        name_top=arbys["arbys_winner"],
        score_top=arbys["winner_score"],
        name_bot=arbys["opponent"],
        score_bot=arbys["loser_score"],
        highlight="top",
        color="green",
    )
    components.html(card, height=150)
except Exception:
    st.info("Arby's Bowl data not available for this season")

st.header("Toilet Bowl")
try:
    toilet_bowl = get_toilet_bowl_loser(season)
    card = render_matchup_card(
        title=f"{season} Last Place Game",
        emoji="🚽",
        name_top=toilet_bowl["last_place"],
        score_top=toilet_bowl["last_place_score"],
        name_bot=toilet_bowl["opponent"],
        score_bot=toilet_bowl["opponent_score"],
        highlight="top",
        color="red",
    )
    components.html(card, height=150)
except Exception:
    st.info("Toilet Bowl data not available for this season")
