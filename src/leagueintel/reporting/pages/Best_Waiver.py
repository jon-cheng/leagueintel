# src/leagueintel/reporting/pages/Best_Waiver.py
import pandas as pd
import streamlit as st
from leagueintel.config import ALL_SEASONS
from leagueintel.reporting.home import shared_sidebar

st.set_page_config(
    page_title="leagueintel — Best Waiver", page_icon="🏈", layout="wide"
)

# ── auth gate ─────────────────────────────────────────────────────────────────

if not st.session_state.get("authenticated"):
    st.switch_page("home.py")
    st.stop()

shared_sidebar()

season = st.session_state.get("selected_season", max(ALL_SEASONS))

# ── page ──────────────────────────────────────────────────────────────────────

st.title(f"Best Waiver Pickup: {season}")
st.caption("Position-normalized percentile score")

st.info(
    "💎 Our league awards the manager who picked up the best waiver wire player "
    "with that player's knockoff jersey. To compare pickups fairly across "
    "positions and ownership lengths, each waiver pickup is evaluated based on "
    "the player's best ownership stint. The player's best eight weeks are "
    "compared to the best eight-week performances of players at the same "
    "position, producing a percentile (waiver score) that allows waiver "
    "acquisitions across all positions to be compared on a common scale."
)

st.dataframe(
    pd.DataFrame(
        columns=[
            "player_name",
            "position",
            "owner_name",
            "acquisition_week",
            "waiver_score",
        ]
    ),
    use_container_width=True,
    hide_index=True,
)
