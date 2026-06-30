# src/leagueintel/reporting/dashboard.py
import streamlit as st
import plotly.express as px
from leagueintel.analytics.draft import get_draft_roi
from leagueintel.config import ALL_SEASONS

import time


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
    )
    fig.add_hline(
        y=avg,
        line_dash="dash",
        line_color="gray",
        annotation_text=f"League avg: {avg:.1f}",
        annotation_position="bottom right",
    )
    return fig


def main():
    st.set_page_config(page_title="leagueintel", page_icon="🏈", layout="wide")
    st.title("🏈 leagueintel")
    st.caption("Fantasy football analytics and competitive intelligence")

    season = st.sidebar.selectbox(
        "Season", options=sorted(ALL_SEASONS, reverse=True), index=0
    )

    st.header("Draft ROI")
    st.caption("Bid amount vs points per game started (min 8 starts)")

    with st.spinner("Loading draft data..."):
        df = get_draft_roi(season=season)  # ← calls your analytics function

    fig = plot_draft_roi(df)
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


if __name__ == "__main__":
    main()
