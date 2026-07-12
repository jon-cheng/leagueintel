# src/leagueintel/reporting/pages/3_📈_Best_Waiver.py
import pandas as pd
import streamlit as st
from leagueintel.config import ALL_SEASONS
from leagueintel.reporting.home import shared_sidebar

st.set_page_config(page_title="leagueintel — Best Waiver", page_icon="🏈", layout="wide")

# ── auth gate ─────────────────────────────────────────────────────────────────

if not st.session_state.get("authenticated"):
    st.switch_page("home.py")
    st.stop()

shared_sidebar()

season = st.session_state.get("selected_season", max(ALL_SEASONS))

# ── page ──────────────────────────────────────────────────────────────────────

st.title("Best Waiver Pickup")
st.caption("Position-normalized percentile score")

st.info("Waiver score analytics coming soon")

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
