# src/leagueintel/reporting/home.py
import os
import boto3
import streamlit as st
from leagueintel.config import (
    ALL_SEASONS,
    CURRENT_YEAR,
    DEFAULT_DB_PATH,
    S3_BUCKET,
    S3_KEY,
)
from leagueintel.storage.database import get_connection, get_max_ingested_week
from leagueintel.analytics.availability import get_default_season
from leagueintel.ingestion.espn import discover_seasons

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


@st.cache_resource
def get_available_seasons() -> list[int]:
    """
    League history, discovered from ESPN rather than assuming this
    codebase's original 2019 founding year. Cached per process lifetime,
    same as initialize_db — a league's history doesn't change mid-session.
    Falls back to ALL_SEASONS if ESPN is unreachable.
    """
    try:
        return discover_seasons()
    except Exception:
        return ALL_SEASONS


# ── password gate ─────────────────────────────────────────────────────────────


def _get_league_password() -> str:
    league_password = os.getenv("LEAGUE_PASSWORD")
    if league_password:
        return league_password
    # st.secrets.get() raises StreamlitSecretNotFoundError (not just a
    # missing-key default) when no secrets.toml exists anywhere — the
    # normal case for a fresh fork with no LEAGUE_PASSWORD set.
    try:
        return st.secrets.get("LEAGUE_PASSWORD")
    except Exception:
        return None


def check_password() -> bool:
    """Simple password gate for league access. Always required — if
    LEAGUE_PASSWORD isn't configured, access is blocked outright rather
    than silently letting everyone in."""
    if st.session_state.get("authenticated"):
        return True

    league_password = _get_league_password()
    if not league_password:
        st.error(
            "LEAGUE_PASSWORD is not set. Set it in .env (or secrets.toml) "
            "before this app can be accessed."
        )
        return False

    with st.form("login_form"):
        password = st.text_input(
            "Enter league password", type="password", placeholder="ask the developer"
        )
        submitted = st.form_submit_button("Enter")

    if submitted:
        if password == league_password:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Wrong password")

    return False


# ── shared sidebar ────────────────────────────────────────────────────────────

FAQ = {
    "Most regrettable drop": "Who had the most regrettable drop in 2025?",
    "Highest scoring week": "What was the highest scoring week ever?",
    "Luckiest manager": "Which manager was luckiest in 2025 based on points against?",
}


def shared_sidebar() -> None:
    """Render the sidebar shared across all authenticated pages."""
    # hide Streamlit's auto-generated page nav — shared_sidebar() below
    # is the only navigation we want shown
    st.markdown(
        "<style>[data-testid='stSidebarNav'] {display: none;}</style>",
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.title("🏈 leagueintel")
        st.caption("your league's historian and intelligence layer")

        if st.button("💬 Chat", use_container_width=True, type="primary"):
            st.switch_page("pages/Chat.py")

        with st.expander("Quick Questions", expanded=False):
            for label, question in FAQ.items():
                if st.button(label, use_container_width=True, key=f"faq_{label}"):
                    st.session_state.pending_question = question
                    st.switch_page("pages/Chat.py")

        st.divider()

        season_options = sorted(get_available_seasons(), reverse=True)
        conn = get_connection()
        default_season = get_default_season(get_max_ingested_week(conn, CURRENT_YEAR))
        conn.close()

        st.selectbox(
            "Season",
            options=season_options,
            index=season_options.index(default_season),
            key="selected_season",
        )

        st.subheader("Season Overview")
        st.page_link("pages/Season_Overview.py", label="🏆 Season Overview")

        st.subheader("Analytics")
        st.page_link("pages/Draft_ROI.py", label="🎯 Draft ROI")
        st.page_link("pages/Best_Waiver.py", label="💎 Best Waiver")

        st.subheader("History")
        st.page_link("pages/Head_to_Head.py", label="⚔️ Head to Head")
        st.page_link("pages/Podium.py", label="🥇 Podium")


# ── landing page ──────────────────────────────────────────────────────────────


def _landing_hero() -> None:
    seasons = get_available_seasons()
    st.title("🏈 leagueintel")
    st.subheader("Your fantasy league's historian and intelligence layer")
    st.caption(
        f"{min(seasons)}–{max(seasons)} seasons of data. "
        "Queryable in plain English. Knows your real manager names."
    )

    left, right = st.columns(2)
    with right:
        st.markdown("**Try asking:**")
        st.markdown(
            '- "What was our most regrettable drop of all time?"\n'
            '- "Did Manager A get fleeced in that trade with Manager B?"\n'
            '- "Roast everyone\'s team names of all time"\n'
            '- "What were closest games between Manager A and Manager C?"'
        )
    with left:
        st.markdown("**What data is available:**")
        st.markdown(
            f"- All league data {min(seasons)}–{max(seasons)}\n"
            "- Draft results & bid amounts, including draft pick order\n"
            "- Weekly matchups, scores, including players projected and actual scores\n"
            "- Roster status (starter/bench/IR) and weekly participation, but not pre-week injury designations\n"
            "- Waiver/FAAB transactions and trade history\n"
            "- Playoff brackets\n"
            "- League current scoring rules\n"
            "- Manager and fantasy team names\n"
            "- Multi-season player performance across their time in the league\n"
        )

    st.markdown("**Ready-made analyses available:**")
    st.markdown(
        "- 🏆 Season Overview\n"
        "- 🎯 Draft ROI\n"
        "- 💎 Best Waiver\n"
        "- ⚔️ Head to Head\n"
        "- 🥇 Podium"
    )


def main() -> None:
    st.set_page_config(page_title="leagueintel", page_icon="🏈", layout="wide")

    # initialize DB (downloads from S3 if in cloud, no-op locally)
    initialize_db()

    if st.session_state.get("authenticated"):
        st.switch_page("pages/Chat.py")

    # hide sidebar nav entirely pre-login — there's nothing to navigate to yet
    st.markdown(
        "<style>[data-testid='stSidebar'] {display: none;}</style>",
        unsafe_allow_html=True,
    )

    _landing_hero()

    if check_password():
        st.switch_page("pages/Chat.py")


if __name__ == "__main__":
    main()
