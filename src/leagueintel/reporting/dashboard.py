# src/leagueintel/reporting/dashboard.py
import os
import boto3
import streamlit as st
import plotly.express as px
from leagueintel.analytics.draft import get_draft_roi, get_draft_selections
from leagueintel.config import ALL_SEASONS, DEFAULT_DB_PATH, S3_BUCKET, S3_KEY

# ── S3 download ───────────────────────────────────────────────────────────────


@st.cache_resource
def initialize_db() -> None:
    """
    Download DB from S3 on cold start if running in cloud.
    Cached indefinitely — only runs once per process lifetime.
    DB only changes on weekly refresh, no need to re-download.
    """
    db_path = str(DEFAULT_DB_PATH)

    # only download if DB_PATH points to /tmp (cloud deployment)
    # local development uses the repo's leagueintel.db directly
    if db_path.startswith("/tmp"):
        s3 = boto3.client(
            "s3",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("AWS_DEFAULT_REGION", "us-west-2"),
        )
        s3.download_file(S3_BUCKET, S3_KEY, db_path)


# ── password gate ─────────────────────────────────────────────────────────────


def check_password() -> bool:
    """Simple password gate for league access."""
    if st.session_state.get("authenticated"):
        return True

    st.title("🏈 leagueintel")
    st.caption("Fantasy football analytics — sponsored by seltzerdads")

    with st.form("login_form"):
        password = st.text_input(
            "Enter league password", type="password", placeholder="ask the commissioner"
        )
        submitted = st.form_submit_button("Enter")

    if submitted:
        league_password = os.getenv("LEAGUE_PASSWORD") or st.secrets.get(
            "LEAGUE_PASSWORD"
        )
        if password == league_password:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Wrong password")

    return False


# ── draft ROI plot ────────────────────────────────────────────────────────────


def plot_draft_roi(df):
    avg = df["points_per_game"].mean()
    fig = px.scatter(
        df,
        x="bid_amount",
        y="points_per_game",
        color="position",
        hover_data=["player_name", "owner_name", "games_started", "total_points"],
        title="Draft ROI: Bid Amount vs Points Per Game Started",
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


# ── main ──────────────────────────────────────────────────────────────────────


def main():
    st.set_page_config(page_title="leagueintel", page_icon="🏈", layout="wide")

    # initialize DB (downloads from S3 if in cloud, no-op locally)
    initialize_db()

    # password gate — stop here if not authenticated
    if not check_password():
        st.stop()

    st.title("🏈 leagueintel")
    st.caption("Fantasy football analytics and competitive intelligence")

    season = st.sidebar.selectbox(
        "Season", options=sorted(ALL_SEASONS, reverse=True), index=0
    )

    st.header("Draft ROI")
    st.caption(
        "Auction draft return on investment (ROI) as measured by points per game, "
        "min 8 starts"
    )

    with st.spinner("Loading draft data..."):
        df = get_draft_roi(season=season)
        all_selections = get_draft_selections(season=season)

    fig = plot_draft_roi(df)
    _, col, _ = st.columns([1, 4, 1])
    with col:
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Draft Selections")
    st.dataframe(
        all_selections[
            [
                "player_name",
                "position",
                "owner_name",
                "bid_amount",
                "games_started",
                "total_points",
                "points_per_game",
            ]
        ].sort_values("bid_amount", ascending=False),
        use_container_width=True,
        hide_index=True,
    )


if __name__ == "__main__":
    main()
