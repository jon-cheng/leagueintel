# tests/reporting/test_page_smoke.py
"""
Smoke tests for leagueintel's Streamlit pages: each page renders without
crashing against the real leagueintel.db.

This only proves EXISTING behavior is preserved (no exception on render)
before the generalization refactor (GENERALIZATION_PLAN.md step 4+)
touches the underlying analytics logic — it is not a correctness check,
and does not cover alternate league rule shapes (no consolation ladder,
different playoff sizes, etc.). That's deliberately deferred to whichever
later step actually introduces settings-driven behavior — a synthetic
fixture only earns its keep once there's a second code path for it to
distinguish.

Every page shares the same auth gate:
    if not st.session_state.get("authenticated"):
        st.switch_page("home.py")
        st.stop()
so at.session_state["authenticated"] = True must be set before at.run().

Chat.py imports chatbot.py at module level, which runs a real ESPN API
call at import time (LEAGUE_CONTEXT = _load_league_context(),
chatbot.py:49) inside a bare except-Exception fallback. This is left
unmocked here, matching the precedent already set by
test_chatbot_throttling.py and test_golden_questions.py, which import
chatbot.py with no special handling either — it either succeeds (slow)
or falls back to a hardcoded string (safe), but doesn't crash at.run().
"""

import pytest
from streamlit.testing.v1 import AppTest

pytestmark = pytest.mark.regression  # needs the real leagueintel.db; CI has no DB file

HOME_PATH = "src/leagueintel/reporting/home.py"

PAGES = [
    "Podium.py",
    "Season_Overview.py",
    "Draft_ROI.py",
    "Best_Waiver.py",
    "Head_to_Head.py",
    "Chat.py",
    "WAR.py",
]


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_without_crashing(page):
    # st.page_link (used by shared_sidebar()) only resolves correctly
    # within the multi-page app's registry, which AppTest only builds
    # when it starts from the main script and navigates via
    # switch_page() — AppTest.from_file(pages/X.py) directly leaves the
    # registry empty and page_link raises KeyError('url_pathname').
    at = AppTest.from_file(HOME_PATH, default_timeout=30)
    at.session_state["authenticated"] = True
    at.switch_page(f"pages/{page}")
    at.run()
    assert at.exception == [], f"{page} raised: {[e.value for e in at.exception]}"


def test_home_renders_without_crashing():
    at = AppTest.from_file("src/leagueintel/reporting/home.py", default_timeout=30)
    at.run()
    assert at.exception == [], f"home.py raised: {[e.value for e in at.exception]}"
