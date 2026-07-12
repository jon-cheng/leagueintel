# src/leagueintel/reporting/pages/Head_to_Head.py
import pandas as pd
import streamlit as st
from leagueintel.analytics.head_to_head import get_h2h_matrix
from leagueintel.reporting.home import shared_sidebar

st.set_page_config(
    page_title="leagueintel — Head to Head", page_icon="🏈", layout="wide"
)

# ── auth gate ─────────────────────────────────────────────────────────────────

if not st.session_state.get("authenticated"):
    st.switch_page("home.py")
    st.stop()

shared_sidebar()

# ── win-pct color gradient ────────────────────────────────────────────────────
# Red (losing) -> yellow (even) -> green (winning), blended to a pastel tint of
# the current theme's surface so the W-L-T text stays legible — color is a
# supplementary cue here, never the only carrier of the record.

_RED = (208, 59, 59)
_YELLOW = (250, 178, 25)
_GREEN = (12, 163, 12)

_SURFACE = {"light": (252, 252, 251), "dark": (26, 26, 25)}
_INK = {"light": "#0b0b0b", "dark": "#ffffff"}


def _gradient_rgb(win_pct: float) -> tuple[int, int, int]:
    lo, hi = (_RED, _YELLOW) if win_pct <= 0.5 else (_YELLOW, _GREEN)
    t = (win_pct / 0.5) if win_pct <= 0.5 else ((win_pct - 0.5) / 0.5)
    return tuple(round(lo[i] + (hi[i] - lo[i]) * t) for i in range(3))


def _cell_style(win_pct: float, theme: str, alpha: float = 0.45) -> str:
    if pd.isna(win_pct):
        return ""
    r, g, b = _gradient_rgb(win_pct)
    sr, sg, sb = _SURFACE[theme]
    blended = (
        round(sr * (1 - alpha) + r * alpha),
        round(sg * (1 - alpha) + g * alpha),
        round(sb * (1 - alpha) + b * alpha),
    )
    return f"background-color: rgb{blended}; color: {_INK[theme]};"


def style_matrix(text_matrix: pd.DataFrame, pct_matrix: pd.DataFrame, theme: str):
    """Apply the win-pct gradient to the W-L-T text matrix as a pandas Styler."""
    cell_styles = pct_matrix.map(lambda p: _cell_style(p, theme))
    return text_matrix.style.apply(lambda _: cell_styles, axis=None)


# ── page ──────────────────────────────────────────────────────────────────────

st.title("All-Time Head to Head")
st.caption("Regular season records across all seasons — W-L-T, row manager's perspective")

with st.spinner("Loading head-to-head records..."):
    text_matrix, pct_matrix = get_h2h_matrix()

theme = st.context.theme.type or "light"
st.dataframe(style_matrix(text_matrix, pct_matrix, theme), use_container_width=True)
