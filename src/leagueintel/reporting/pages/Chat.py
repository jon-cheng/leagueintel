# src/leagueintel/reporting/pages/Chat.py
"""
Chatbot UI page for leagueintel.
Wires the chatbot engine (chatbot.py) into Streamlit's chat interface.
"""

import re
import streamlit as st
from leagueintel.reporting.chatbot import ask
from leagueintel.reporting.home import shared_sidebar

st.set_page_config(page_title="leagueintel — Chat", page_icon="🏈", layout="wide")

# ── auth gate ─────────────────────────────────────────────────────────────────

if not st.session_state.get("authenticated"):
    st.switch_page("home.py")
    st.stop()

shared_sidebar()

# ── helpers ───────────────────────────────────────────────────────────────────


def clean_response(text: str) -> str:
    """
    Clean LLM response for safe Streamlit markdown rendering.

    Fixes three Streamlit rendering quirks:
      1. Backticks around non-code content → render as ugly monospace
      2. Dollar signs in prose → Streamlit interprets as LaTeX math
      3. Emojis → can trigger unexpected color/block rendering

    Table rows (lines starting with |) are left untouched — dollar signs
    and content inside tables render correctly as plain markdown.
    """
    # 1. strip single backtick pairs (not triple backticks for code blocks)
    text = re.sub(r"(?<!`)`(?!``)([^`\n]+)`(?!`)", r"\1", text)

    # 2. escape dollar signs in prose, preserve in table rows
    lines = []
    for line in text.split("\n"):
        if line.strip().startswith("|"):
            # table row — leave as-is
            lines.append(line)
        else:
            # prose — escape $ to prevent LaTeX rendering
            lines.append(line.replace("$", r"\$"))
    text = "\n".join(lines)

    # 3. strip emojis via unicode ranges
    text = re.sub(
        r"[\U0001F300-\U0001F9FF"
        r"\U0001FA00-\U0001FA9F"
        r"\U00002600-\U000027BF"
        r"\U0001F600-\U0001F64F"
        r"✀-➿"
        r"⌀-⏿]+",
        "",
        text,
    )

    return text


# ── page ──────────────────────────────────────────────────────────────────────

st.title("💬 Ask leagueintel")
st.caption("Ask anything about your fantasy league — 6 seasons of data")

with st.expander("ℹ️ How to get the best results", expanded=False):
    st.markdown("""
    **Works well:**
    - "How much FAAB did Manager A spend in 2025?"
    - "What's my all-time record against Manager B?"
    - "Who were the best waiver pickups in 2025?"
    - "Show me draft ROI for 2025"
    - "Who had the most regrettable drop of 2025?"

    **Pre-built analyses (always reliable):**
    Waiver scores and draft ROI use validated logic —
    ask for these by name and the chatbot routes automatically.

    **For surprising results:**
    Verify against the ESPN league UI — that is the source of truth.
    Complex temporal questions (before/after events) are best-effort.
    """)

# ── chat history ──────────────────────────────────────────────────────────────

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# display existing messages
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(clean_response(msg["content"]))
        if msg.get("fig"):
            st.plotly_chart(msg["fig"], use_container_width=True)

# ── input ─────────────────────────────────────────────────────────────────────

# handle FAQ sidebar click
pending = st.session_state.pop("pending_question", None)
prompt = st.chat_input("Ask about your league...") or pending

if prompt:
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.chat_history.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            text, fig = ask(prompt)
        st.markdown(clean_response(text))
        if fig:
            st.plotly_chart(fig, use_container_width=True)

    st.session_state.chat_history.append(
        {
            "role": "assistant",
            "content": text,
            "fig": fig,
        }
    )
