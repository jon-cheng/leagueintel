# src/leagueintel/reporting/pages/WAR.py — new page, same shape as Draft_ROI.py
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from leagueintel.analytics.war import (
    get_season_war,
    join_draft_price,
    join_draft_order,
    war_price_regression,
)
from leagueintel.analytics.availability import SeasonNotReadyError
from leagueintel.analytics.draft import get_draft_type
from leagueintel.config import ALL_SEASONS
from leagueintel.reporting.home import shared_sidebar
from leagueintel.reporting.style import TOKENS, inject_fonts

st.set_page_config(page_title="leagueintel — WAR", page_icon="🏈", layout="wide")

if not st.session_state.get("authenticated"):
    st.switch_page("home.py")
    st.stop()

shared_sidebar()
inject_fonts()

season = st.session_state.get("selected_season", max(ALL_SEASONS))

st.title("🏈 leagueintel")
st.header(f"Wins Above Replacement: {season}")
st.caption(
    "Season WAR converts every started week into a win-probability swing "
    "against a real bench-level alternative at that position that week, "
    "summed across the weeks a manager actually kept starting that player."
)

with st.spinner("Computing season WAR..."):
    try:
        war = get_season_war(season=season)
    except SeasonNotReadyError as e:
        st.info(str(e))
        st.stop()

# ── draft-type dispatch ──────────────────────────────────────────────────────
# Explicit three-way dispatch on the actual draft_type value, matching
# draft.py's get_draft_roi treating an unrecognized value as a hard failure
# rather than silently guessing which view to render.

draft_type = get_draft_type(season)

if draft_type == "AUCTION":
    # ── price vs WAR scatter with per-position trend lines ──────────────────
    priced = join_draft_price(war, season)
    drafted = priced[priced["bid_amount"].notna()]

    col1, col2, col3, col4 = st.columns(4)
    for col, pos in zip((col1, col2, col3, col4), ["QB", "RB", "WR", "TE"]):
        reg = war_price_regression(priced, pos)
        with col:
            st.metric(f"{pos} price → WAR R²", f"{reg['r2']:.3f}" if reg["r2"] is not None else "n/a")

    fig = px.scatter(
        drafted,
        x="bid_amount",
        y="season_war",
        color="position",
        color_discrete_map=TOKENS["position_colors"],
        hover_data=["player_name", "weeks_started", "total_points"],
        labels={"bid_amount": "Draft Price ($)", "season_war": "Season WAR"},
        height=600,
    )
    for pos in ["QB", "RB", "WR", "TE"]:
        reg = war_price_regression(priced, pos)
        if reg["slope"] is None:
            continue
        pos_rows = drafted[drafted["position"] == pos]
        x_range = [pos_rows["bid_amount"].min(), pos_rows["bid_amount"].max()]
        y_range = [reg["slope"] * x + reg["intercept"] for x in x_range]
        fig.add_trace(
            go.Scatter(
                x=x_range,
                y=y_range,
                mode="lines",
                line=dict(dash="dash", color=TOKENS["position_colors"][pos]),
                name=f"{pos} fit",
                showlegend=False,
            )
        )
    fig.add_hline(y=0, line_dash="dot", line_color=TOKENS["text_dim"])
    st.plotly_chart(fig, use_container_width=True)

elif draft_type == "SNAKE":
    # ── diverging bar against original draft order ──────────────────────────
    # x-axis = overall_pick_number (no bid_amount exists for a snake draft),
    # y-axis = season WAR, bars colored by sign. A player drafted early with
    # a deeply negative bar is the real bust signal — in wins, not raw points.
    #
    # NOTE: not yet verified against a real snake-draft season's data — this
    # league's ingested history may not include one. Flag any rendering
    # oddities (e.g. sparse/duplicate pick numbers, extreme outliers) if you
    # see them on first real use.
    ordered = join_draft_order(war, season).dropna(subset=["overall_pick_number"])
    ordered = ordered.sort_values("overall_pick_number")
    bar_colors = [
        TOKENS["war_positive"] if w >= 0 else TOKENS["war_negative"]
        for w in ordered["season_war"]
    ]
    fig = go.Figure(
        go.Bar(
            x=ordered["overall_pick_number"],
            y=ordered["season_war"],
            marker_color=bar_colors,
            customdata=ordered[["player_name", "position"]],
            hovertemplate="Pick %{x}: %{customdata[0]} (%{customdata[1]})<br>WAR %{y:.2f}<extra></extra>",
        )
    )
    fig.update_layout(
        title="Season WAR by original draft position",
        xaxis_title="Overall pick number",
        yaxis_title="Season WAR",
        height=500,
    )
    fig.add_hline(y=0, line_color=TOKENS["text_dim"])
    st.plotly_chart(fig, use_container_width=True)

else:
    st.error(
        f"Unrecognized draft_type {draft_type!r} for season {season} — "
        "can't determine which WAR view to show."
    )
    st.stop()

# ── everyone: full ranked view including undrafted waiver pickups ───────────
# Worth keeping regardless of draft_type — the price/pick-order chart
# above says nothing about a player who was never drafted at all.

st.subheader("Ranked WAR (all started players, drafted + waiver)")

ranked = war.sort_values("season_war", ascending=False).reset_index(drop=True)
n_players = len(ranked)

top_n = st.slider(
    "Players to show (top N by WAR)",
    min_value=min(10, n_players),
    max_value=n_players,
    value=min(30, n_players),
)
shown = ranked.head(top_n)

bar_colors = [TOKENS["war_positive"] if w >= 0 else TOKENS["war_negative"] for w in shown["season_war"]]
fig_bar = go.Figure(
    go.Bar(
        x=shown["player_name"],
        y=shown["season_war"],
        marker_color=bar_colors,
        customdata=shown[["position", "weeks_started", "total_points"]],
        hovertemplate=(
            "%{x} (%{customdata[0]})<br>WAR %{y:.2f}"
            "<br>%{customdata[1]} weeks started, %{customdata[2]:.1f} pts"
            "<extra></extra>"
        ),
    )
)
fig_bar.update_layout(
    title=f"Season WAR, top {top_n} of {n_players} started players",
    xaxis_title=None,
    yaxis_title="Season WAR",
    height=420,
)
fig_bar.update_xaxes(tickangle=-45)
st.plotly_chart(fig_bar, use_container_width=True)

st.subheader("Full table")
st.dataframe(
    war[["player_name", "position", "weeks_started", "total_points", "season_war"]],
    use_container_width=True,
    hide_index=True,
)
