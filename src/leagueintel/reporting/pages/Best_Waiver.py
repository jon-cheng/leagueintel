# src/leagueintel/reporting/pages/Best_Waiver.py
import streamlit as st
import plotly.express as px
from leagueintel.analytics.waiver import get_waiver_scores
from leagueintel.analytics.availability import SeasonNotReadyError
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

# ── waiver score chart ────────────────────────────────────────────────────────


def plot_waiver_scores(df):
    top = df.sort_values(
        ["waiver_score", "total_points"], ascending=[False, False]
    ).head(15)

    ordered = top.sort_values(
        ["waiver_score", "total_points"],
        ascending=[True, True],  # ascending for chart (highest at top)
    )

    fig = px.bar(
        ordered,
        x="waiver_score",
        y="player_name",
        color="position",
        orientation="h",
        hover_data=["owner_name", "acquisition_week", "total_points"],
        title="Top Waiver Pickups by Waiver Score",
        labels={"waiver_score": "Waiver Score (percentile)", "player_name": ""},
        height=600,
    )
    fig.update_layout(
        yaxis={
            "categoryorder": "array",
            "categoryarray": ordered["player_name"].tolist(),
        }
    )
    return fig


# ── page ──────────────────────────────────────────────────────────────────────

st.title(f"Best Waiver Pickup: {season}")
st.caption("Position-normalized percentile score")

st.info(
    "💎 Our league awards the manager who picked up the best waiver wire player "
    "with that player's knockoff jersey. To compare pickups fairly across "
    "positions and ownership lengths, each waiver pickup is evaluated based on "
    "the player's best ownership stint. The player's best eight weeks are "
    "compared to the best eight-week performances of all concurrently rostered players at the same "
    "position, producing a percentile (waiver score) that allows waiver "
    "acquisitions across all positions to be compared on a common scale."
)

with st.spinner("Loading waiver data..."):
    try:
        df = get_waiver_scores(season=season)
    except SeasonNotReadyError as e:
        st.info(str(e))
        st.stop()

if df.empty:
    st.info("No eligible waiver pickups found for this season.")
    st.stop()

# ── metric card ───────────────────────────────────────────────────────────────

best = df.iloc[df["waiver_score"].idxmax()]
st.metric(
    "Best Waiver Pickup",
    best["player_name"],
    f"{best['waiver_score']} percentile, {best['owner_name']}",
)

# ── chart ─────────────────────────────────────────────────────────────────────

fig = plot_waiver_scores(df)
_, col, _ = st.columns([1, 4, 1])
with col:
    st.plotly_chart(fig, use_container_width=True)

st.subheader("All Eligible Pickups")
st.dataframe(
    df[
        [
            "player_name",
            "position",
            "owner_name",
            "acquisition_week",
            "num_weeks",
            "total_points",
            "waiver_score",
        ]
    ],
    use_container_width=True,
    hide_index=True,
)
