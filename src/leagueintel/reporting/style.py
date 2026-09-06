"""
Shared visual identity for leagueintel's Streamlit pages — extracted from
the price-vs-WAR artifact so the same palette/type system can be reused
page by page instead of each page picking its own plotly express defaults.

Two things live here, and they're independently adoptable:
  - TOKENS: the color/font values, plain data, importable anywhere
  - register_plotly_template(): wires TOKENS into a reusable go.layout
    .Template so every chart on every page renders consistently without
    repeating layout kwargs per chart

inject_fonts() is a smaller, separate concern — it only loads the Google
Fonts and applies them to markdown/metric text via CSS. It's deliberately
NOT trying to re-theme Streamlit's own chrome (buttons, dataframes,
sidebar) — Streamlit's internal class names aren't a public API and shift
between versions, so a CSS injection that targets them is exactly the
kind of fragile-until-the-next-upgrade coupling worth avoiding. The
robust, version-safe lever for the base app theme is .streamlit/
config.toml's [theme] table (see the snippet at the bottom of this file)
— reach for the CSS injection only for things config.toml can't reach,
like heading fonts inside st.markdown blocks.
"""

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

TOKENS = {
    "fonts": {
        "display": "Barlow Condensed, sans-serif",
        "body": "IBM Plex Sans, sans-serif",
        "mono": "IBM Plex Mono, monospace",
    },
    "position_colors": {
        "QB": "#3a63b8",
        "RB": "#1f8f5c",
        "WR": "#c15a17",
        "TE": "#7a3fae",
    },
    "war_positive": "#1f8f5c",
    "war_negative": "#c23b34",
    "accent": "#9c6f14",
    "surface": "#ffffff",
    "grid": "#d7ddd6",
    "text": "#1b2420",
    "text_dim": "#5c6a62",
}

GOOGLE_FONTS_IMPORT = (
    "https://fonts.googleapis.com/css2?"
    "family=Barlow+Condensed:wght@500;600;700"
    "&family=IBM+Plex+Sans:wght@400;500;600"
    "&family=IBM+Plex+Mono:wght@400;500;600"
    "&display=swap"
)


def inject_fonts() -> None:
    """Load the shared typefaces and apply them to markdown headings and
    st.metric — call once near the top of a page, after set_page_config."""
    st.markdown(
        f"""
        <link href="{GOOGLE_FONTS_IMPORT}" rel="stylesheet">
        <style>
        h1, h2, h3 {{ font-family: {TOKENS["fonts"]["display"]}; }}
        [data-testid="stMetricValue"] {{ font-family: {TOKENS["fonts"]["mono"]}; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def register_plotly_template() -> None:
    """
    Build a "leagueintel" plotly template from TOKENS and make it the
    default, so px.scatter(...) etc. on every page picks up the same
    fonts/gridlines/background without repeating layout kwargs each time.

    Call once, e.g. from reporting/home.py's shared_sidebar() — plotly
    templates are process-global, so registering it anywhere before a
    chart renders is enough for every page in the same Streamlit process.
    """
    template = go.layout.Template(
        layout=go.Layout(
            font=dict(family=TOKENS["fonts"]["body"], color=TOKENS["text"]),
            paper_bgcolor=TOKENS["surface"],
            plot_bgcolor=TOKENS["surface"],
            xaxis=dict(gridcolor=TOKENS["grid"], zerolinecolor=TOKENS["grid"]),
            yaxis=dict(gridcolor=TOKENS["grid"], zerolinecolor=TOKENS["grid"]),
            colorway=list(TOKENS["position_colors"].values()),
        )
    )
    pio.templates["leagueintel"] = template
    pio.templates.default = "leagueintel"


# ── optional: matching .streamlit/config.toml ────────────────────────────────
# The [theme] table is the version-safe way to set Streamlit's own chrome
# (background, primary color, sidebar) to match this palette. Not written
# automatically — add it yourself if you want the app shell to match too:
#
# [theme]
# primaryColor = "#9c6f14"
# backgroundColor = "#ffffff"
# secondaryBackgroundColor = "#f5f7f4"
# textColor = "#1b2420"
# font = "sans serif"
