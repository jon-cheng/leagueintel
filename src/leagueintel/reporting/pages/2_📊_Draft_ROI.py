# src/leagueintel/reporting/pages/2_📊_Draft_ROI.py
import streamlit as st
import plotly.express as px
from leagueintel.analytics.draft import get_draft_roi
from leagueintel.config import ALL_SEASONS
from leagueintel.reporting.home import shared_sidebar

st.set_page_config(page_title="leagueintel — Draft ROI", page_icon="🏈", layout="wide")

# ── auth gate ─────────────────────────────────────────────────────────────────

if not st.session_state.get("authenticated"):
    st.switch_page("home.py")
    st.stop()

shared_sidebar()

season = st.session_state.get("selected_season", max(ALL_SEASONS))

# ── draft ROI plot ────────────────────────────────────────────────────────────


def plot_draft_roi(df):
    avg = df["points_per_game"].mean()
    fig = px.scatter(
        df,
        x="bid_amount",
        y="points_per_game",
        color="position",
        hover_data=["player_name", "owner_name", "games_started", "total_points"],
        title="Draft ROI: Bid Amount vs Points Per Game Started (min 8 starts)",
        labels={
            "bid_amount": "Draft Price ($)",
            "points_per_game": "Points Per Game Started",
        },
        height=600,
    )
    fig.add_hline(
        y=avg,
        line_dash="dash",
        line_color="gray",
        annotation_text=f"League avg: {avg:.1f}",
        annotation_position="bottom right",
    )
    return fig


# ── page ──────────────────────────────────────────────────────────────────────

st.title("🏈 leagueintel")
st.header("Draft ROI")
st.caption("Bid amount vs points per game started (min 8 starts)")

with st.spinner("Loading draft data..."):
    df = get_draft_roi(season=season)

# ── metric cards ──────────────────────────────────────────────────────────────

value_pick = df.loc[df["points_per_game"].idxmax()]
cost_per_point = df["bid_amount"] / df["points_per_game"]
overpay = df.loc[cost_per_point.idxmax()]
league_avg_ppg = df["points_per_game"].mean()

col1, col2, col3 = st.columns(3)
with col1:
    st.metric(
        "Top Value Pick",
        value_pick["player_name"],
        f"{value_pick['points_per_game']} ppg for ${value_pick['bid_amount']}",
    )
with col2:
    st.metric(
        "Biggest Overpay",
        overpay["player_name"],
        f"${overpay['bid_amount']} for {overpay['points_per_game']} ppg",
    )
with col3:
    st.metric("League Avg PPG", f"{league_avg_ppg:.2f}")

# ── chart ─────────────────────────────────────────────────────────────────────

fig = plot_draft_roi(df)
_, col, _ = st.columns([1, 4, 1])
with col:
    st.plotly_chart(fig, use_container_width=True)

st.subheader("Data")
st.dataframe(
    df[
        [
            "player_name",
            "position",
            "owner_name",
            "bid_amount",
            "games_started",
            "total_points",
            "points_per_game",
        ]
    ],
    use_container_width=True,
    hide_index=True,
)
