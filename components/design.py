"""Small, scoped visual foundation for the Streamlit interface."""

from __future__ import annotations

import streamlit as st


TOKENS = {
    "primary": "#276749", "secondary": "#2B6CB0", "accent": "#D69E2E",
    "background": "#F7FAFC", "surface": "#FFFFFF", "border": "#D9E2EC",
    "text": "#172B4D", "muted": "#52606D", "success": "#276749",
    "warning": "#975A16", "error": "#9B2C2C", "focus": "#2B6CB0",
}


def apply_design_system() -> None:
    """Apply stable, test-id-scoped styling without broad widget selectors."""
    st.markdown(
        f"""
        <style>
          :root {{ --ss-primary: {TOKENS['primary']}; --ss-border: {TOKENS['border']}; --ss-muted: {TOKENS['muted']}; }}
          .stApp {{ background: {TOKENS['background']}; color: {TOKENS['text']}; }}
          [data-testid="stSidebar"] {{ background: {TOKENS['surface']}; border-right: 1px solid var(--ss-border); min-width: 19rem; }}
          [data-testid="stSidebar"] > div:first-child {{ padding-bottom: 8rem; }}
          [data-testid="stMetric"] {{ background: {TOKENS['surface']}; border: 1px solid var(--ss-border); border-radius: 0.75rem; padding: 0.7rem; }}
          [data-testid="stExpander"] {{ background: {TOKENS['surface']}; border: 1px solid var(--ss-border); border-radius: 0.75rem; }}
          [data-testid="stButton"] > button {{ border-radius: 0.55rem; min-height: 2.55rem; }}
          [data-testid="stButton"] > button:focus-visible, input:focus-visible, textarea:focus-visible {{ outline: 3px solid {TOKENS['focus']} !important; outline-offset: 2px; }}
          h1, h2, h3 {{ letter-spacing: -0.02em; }}
        </style>
        """,
        unsafe_allow_html=True,
    )
