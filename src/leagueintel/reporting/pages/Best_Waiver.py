# src/leagueintel/reporting/pages/Best_Waiver.py
import numpy as np
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from leagueintel.analytics.waiver import get_waiver_scores_with_population, get_acquisition_history
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
    # plotly stacks bars that share the same (y, color) pair instead of
    # erroring, so two different managers picking up the same player in
    # the same season would silently sum into one bar exceeding 100 —
    # label includes the manager to keep every row's bar unique.
    df = df.assign(label=df["player_name"] + " (" + df["owner_name"] + ")")

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
        y="label",
        color="position",
        orientation="h",
        hover_data=["owner_name", "acquisition_week", "total_points"],
        title="Top Waiver Pickups by Waiver Score",
        labels={"waiver_score": "Waiver Score (percentile)", "label": ""},
        height=600,
    )
    fig.update_layout(
        yaxis={
            "categoryorder": "array",
            "categoryarray": ordered["label"].tolist(),
        }
    )
    return fig


_HOVERTEMPLATE = (
    "Player=%{customdata[0]}<br>"
    "Manager=%{customdata[1]}<br>"
    "Total points over these weeks=%{customdata[2]:.1f}<br>"
    "PPG over these weeks=%{customdata[3]:.1f}"
    "<extra></extra>"
)
_HOVER_COLUMNS = [
    "comparison_player_name",
    "comparison_owner_name",
    "comparison_total",
    "comparison_ppg",
]


def plot_comparison_population(population, player_name):
    """
    Violin (median/IQR + full distribution shape) with the individual
    comparison players jittered on top as light grey dots and the
    selected pickup's own dot highlighted in red — the field this
    pickup's waiver_score/median_total_points were computed from, made
    visible instead of only shown as an aggregate.

    x-axis is TOTAL points, matching exactly what waiver_score itself
    compares (scored_less = comparison_total < total_points) — a dot's
    position here is directly the thing that determined the percentile.
    PPG (each comparison player's own rate over the weeks they were
    actually rostered — see comparison_ppg in stint_scoring.py) is
    available via hover for context, but deliberately isn't the axis:
    PPG erases games-played differences that totals (and therefore
    scored_less) depend on, so a PPG axis can visually rank a short,
    hot stretch above a long, steady one even though the score doesn't.

    The reference line is median_total_points — the SAME number
    displayed in the table, and the one actually consistent with
    waiver_score's percentile (see stint_scoring.py's comment on
    median_total_points for why).
    """
    comparison = population[~population["is_query_player"]]
    query_row = population[population["is_query_player"]]

    # fixed seed so a player's dots land in the same relative spot on
    # every rerun (Streamlit reruns the whole script on each interaction)
    # instead of visibly jumping around
    rng = np.random.default_rng(42)
    jitter = rng.uniform(-0.3, 0.3, size=len(comparison))

    fig = go.Figure()
    fig.add_trace(
        go.Violin(
            x=population["comparison_total"],
            y=[0] * len(population),
            orientation="h",
            width=1.4,  # ~40% fatter than Plotly's default (width=1)
            box_visible=True,
            meanline_visible=False,
            points=False,
            line_color="#B0B0B0",
            fillcolor="rgba(76, 120, 168, 0.15)",
            opacity=0.6,
            name="",
            showlegend=False,
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=comparison["comparison_total"],
            y=jitter,
            mode="markers",
            marker=dict(color="lightgrey", size=8, opacity=0.8),
            name="Comparison field",
            customdata=comparison[_HOVER_COLUMNS],
            hovertemplate=_HOVERTEMPLATE,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=query_row["comparison_total"],
            y=[0] * len(query_row),
            mode="markers",
            marker=dict(color="#E45756", size=12, line=dict(color="white", width=1)),
            name="This pickup",
            hoverlabel=dict(bgcolor="#E45756", font=dict(color="white")),
            customdata=query_row[_HOVER_COLUMNS],
            hovertemplate=_HOVERTEMPLATE,
        )
    )
    median_total_points = population["median_total_points"].iloc[0]
    fig.add_vline(
        x=median_total_points,
        line_dash="dot",
        line_color="grey",
        annotation_text=f"Median: {median_total_points:.1f} total points",
        annotation_position="top",
    )
    fig.update_layout(
        title=f"Comparison field: {player_name}",
        xaxis_title="Total points over these weeks",
        yaxis=dict(visible=False, range=[-1, 1]),
        legend_title_text="",
        height=280,
    )
    return fig


@st.cache_data(show_spinner=False)
def _load_waiver_data(season):
    return get_waiver_scores_with_population(season)


@st.cache_data(show_spinner=False)
def _load_acquisition_history(season):
    return get_acquisition_history(season)


# ── page ──────────────────────────────────────────────────────────────────────

st.title(f"Best Waiver Pickup: {season}")
st.caption("Position-normalized percentile score")

st.info(
    "💎 **How Best Waiver scoring works**\n\n"
    "- **Eligibility**: only players not drafted, rostered via waiver for "
    "at least 8 weeks in the window being scored.\n"
    "- **Best window**: each manager's best 8 scoring weeks with that "
    "player are used — pooled across every stint of the same acquisition "
    "type they had with them, even if the stints weren't back-to-back "
    "(e.g. waiver-added, dropped, re-added still counts as one combined "
    "8-week sample for that manager).\n"
    "- **Waiver Score (percentile)**: the player's total points over "
    "those 8 weeks is compared against every other player rostered at "
    "the same position over the same weeks — the percentile is the "
    "share of that field they outscored. Comparing within the same "
    "position keeps the peer group realistic, and since scoring varies "
    "a lot by position, this percentile is what makes it fair to rank "
    "the best pickups across every position on one common scale.\n"
    "- **Median Total Points**: the comparison field's median total over "
    "those same weeks — deliberately not converted to PPG, because it's "
    "the number actually consistent with the percentile (score above "
    "the median ⇒ beat more than half the field). PPG columns are shown "
    "separately for readability, but the score itself is computed on "
    "totals.\n"
    "- **Comparison Field plot**: click a row to see the full comparison "
    "population — a violin (shape + median/IQR) with every comparison "
    "player's total plotted as a dot, this pickup highlighted in red. "
    "Hover for each player's own points-per-game.\n"
    "- **History column**: every manager who has ever held this player "
    "this season, via any acquisition type (Draft, Waiver, Free Agent, "
    "Trade) — with price when one applies (FAAB bid or auction price) "
    "and the week range each manager held them."
)

with st.spinner("Loading waiver data..."):
    try:
        df, population = _load_waiver_data(season)
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

header_col, filter_col = st.columns([10, 1])
with header_col:
    st.subheader("All Eligible Pickups")

acquisition_history = _load_acquisition_history(season)
table = df.assign(
    ppg=(df["total_points"] / df["num_weeks"]).round(1),
    best_weeks=df["weeks"].apply(lambda ws: ", ".join(str(w) for w in ws)),
).merge(acquisition_history, on="player_id", how="left").reset_index(drop=True)
table["history"] = table["history"].fillna("—")

positions = sorted(table["position"].unique())
with filter_col:
    with st.popover("⋮"):
        st.caption("Filter by position")
        selected_positions = [
            p for p in positions if st.checkbox(p, value=True, key=f"position_filter_{p}")
        ]

table = table[table["position"].isin(selected_positions)].reset_index(drop=True)

if table.empty:
    st.info("No pickups match the selected position filter.")
    st.stop()

display_columns = [
    "plot_comparison",
    "player_name",
    "position",
    "owner_name",
    "total_points",
    "best_weeks",
    "ppg",
    "median_total_points",
    "waiver_score",
    "history",
]

# single-selection checkbox column, tracked across reruns via session_state
# so checking a new row's box un-checks the previous one (st.data_editor
# has no native single-select checkbox mode) — index resets whenever the
# filtered table changes shape, since a stale index could point at a
# different row after re-filtering.
if st.session_state.get("plot_comparison_table_len") != len(table):
    st.session_state.plot_comparison_idx = None
    st.session_state.plot_comparison_table_len = len(table)

table = table.assign(plot_comparison=False)
selected_idx = st.session_state.get("plot_comparison_idx")
if selected_idx is not None and selected_idx in table.index:
    table.loc[selected_idx, "plot_comparison"] = True

# st.data_editor retains a cell's edit history against its `key` across
# reruns, ignoring the freshly-rebuilt dataframe for any cell the user
# already touched — so a naive rebuild-from-session_state approach can
# leave two rows visibly checked at once. Keying the widget on the
# current selection forces a brand-new widget (no retained history)
# whenever the selection changes, and the explicit rerun below makes
# that new widget render immediately instead of one interaction late.
editor_key = f"waiver_pickups_editor_{selected_idx}"
edited = st.data_editor(
    table[display_columns].rename(
        columns={
            "plot_comparison": "Plot Comparison",
            "owner_name": "manager_name",
            "best_weeks": "Best Weeks",
            "ppg": "PPG",
            "median_total_points": "Median Total Points (same weeks)",
            "history": "History",
        }
    ),
    column_config={
        "Plot Comparison": st.column_config.CheckboxColumn(
            "Plot Comparison", help="Select to plot this pickup's comparison field below"
        ),
    },
    disabled=[c for c in table[display_columns].columns if c != "plot_comparison"],
    use_container_width=True,
    hide_index=True,
    key=editor_key,
)

checked = edited.index[edited["Plot Comparison"]].tolist()
# clicking a NEW row's checkbox should replace the previous selection, not
# add to it — pick whichever checked row wasn't already selected
newly_checked = [i for i in checked if i != selected_idx]
new_idx = newly_checked[0] if newly_checked else (checked[0] if len(checked) == 1 else None)
if new_idx != selected_idx:
    st.session_state.plot_comparison_idx = new_idx
    st.rerun()

# ── comparison field drilldown ────────────────────────────────────────────────

st.subheader("Comparison Field")
if st.session_state.plot_comparison_idx is None:
    st.caption("Select a row's checkbox above to see that pickup's comparison field.")
else:
    selected = table.iloc[st.session_state.plot_comparison_idx]
    player_population = population[
        (population["player_id"] == selected["player_id"])
        & (population["team_id"] == selected["team_id"])
        & (population["acquisition_type"] == selected["acquisition_type"])
    ]
    fig = plot_comparison_population(player_population, selected["player_name"])
    st.plotly_chart(fig, use_container_width=True)
