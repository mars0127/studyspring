"""Small, reusable Streamlit building blocks based on StudySpring design tokens."""

from __future__ import annotations

import streamlit as st


def resolve_page(requested: object, destinations: list[str]) -> str:
    """Keep navigation stable when a rerun receives missing or stale state."""
    return str(requested) if requested in destinations else destinations[0]


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
    current = resolve_page(st.session_state.get("active_page"), items)
    if st.session_state.get("primary_navigation") not in items:
        st.session_state["primary_navigation"] = current
    selected = st.radio("StudySpring navigation", items, index=items.index(current), horizontal=True, label_visibility="collapsed", key="primary_navigation")
    st.session_state["active_page"] = selected
    return selected


def open_course(course_id: int) -> None:
    """Apply course selection before the next navigation widget is constructed."""
    st.session_state["selected_course_id"] = course_id
    st.session_state["active_page"] = "Learn"
    st.session_state["primary_navigation"] = "Learn"
    st.query_params["course"] = str(course_id)
