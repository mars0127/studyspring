"""Small, reusable Streamlit building blocks based on StudySpring design tokens."""

from __future__ import annotations

import streamlit as st


def page_header(title: str, description: str) -> None:
    st.title(title)
    st.caption(description)


def status_banner(kind: str, message: str) -> None:
    {"success": st.success, "warning": st.warning, "error": st.error, "info": st.info}.get(kind, st.info)(message)


def empty_state(title: str, message: str) -> None:
    st.markdown(f"### {title}")
    st.caption(message)


def course_card(course: dict[str, object], selected: bool = False) -> None:
    marker = "Selected" if selected else "Course"
    st.markdown(f"**{course['name']}**  ")
    st.caption(f"{course['subject']} · {marker}")


def page_navigation(items: list[str]) -> str:
    """Compact top-level navigation that avoids a crowded sidebar."""
    current = st.session_state.get("active_page", items[0])
    if current not in items:
        current = items[0]
    selected = st.radio("StudySpring navigation", items, index=items.index(current), horizontal=True, label_visibility="collapsed")
    st.session_state["active_page"] = selected
    return selected
