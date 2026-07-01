# src/leagueintel/reporting/pages/2_Chat.py
"""
Chatbot UI page for leagueintel.
Wires the chatbot engine (chatbot.py) into Streamlit's chat interface.
"""

import os
import streamlit as st
from leagueintel.reporting.chatbot import ask

st.set_page_config(page_title="leagueintel — Chat", page_icon="💬", layout="wide")

# ── auth gate ─────────────────────────────────────────────────────────────────

if not st.session_state.get("authenticated"):
    st.warning("Please log in from the main page first.")
    st.stop()

# ── page ──────────────────────────────────────────────────────────────────────

st.title("💬 Ask leagueintel")
st.caption("Ask anything about your fantasy league — 6 seasons of data")

with st.expander("ℹ️ How to get the best results", expanded=False):
    st.markdown("""
    **Works well:**
    - *"How much FAAB did Jake spend in 2025?"*
    - *"What's my all-time record against Sam?"*
    - *"Who were the best waiver pickups in 2025?"*
    - *"Show me draft ROI for 2025"*
    - *"Who had the most regrettable drop of 2025?"*

    **Pre-built analyses (always reliable):**
    Waiver scores and draft ROI use validated logic —
    ask for these by name and the chatbot routes automatically.

    **For surprising results:**
    Verify against the ESPN league UI — that's the source of truth.
    Complex temporal questions (before/after events) are best-effort.
    """)

# ── sidebar FAQ buttons ───────────────────────────────────────────────────────

st.sidebar.title("Quick questions")
st.sidebar.caption("Click to ask")

FAQ = {
    "🏆 Best waiver pickups": "Who were the best waiver pickups in 2025?",
    "💰 Draft ROI": "Show me draft ROI for 2025",
    "💀 Most regrettable drop": "Who had the most regrettable drop in 2025?",
    "📊 FAAB spend by manager": "How much FAAB did each manager spend in 2025?",
    "⚔️ Head to head records": "Show me all head to head records for 2025",
    "🏈 Highest scoring week": "What was the highest scoring week ever?",
    "🍀 Luckiest manager": "Which manager was luckiest in 2025 based on points against?",
}

for label, question in FAQ.items():
    if st.sidebar.button(label, use_container_width=True):
        st.session_state.pending_question = question

# ── chat history ──────────────────────────────────────────────────────────────

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# display existing messages
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        if msg.get("fig"):
            st.plotly_chart(msg["fig"], use_container_width=True)

# ── input ─────────────────────────────────────────────────────────────────────

# handle FAQ sidebar click
pending = st.session_state.pop("pending_question", None)

prompt = st.chat_input("Ask about your league...") or pending

if prompt:
    # show user message
    with st.chat_message("user"):
        st.write(prompt)
    st.session_state.chat_history.append({"role": "user", "content": prompt})

    # run chatbot
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            text, fig = ask(prompt)
        st.write(text)
        if fig:
            st.plotly_chart(fig, use_container_width=True)

    st.session_state.chat_history.append(
        {
            "role": "assistant",
            "content": text,
            "fig": fig,
        }
    )
