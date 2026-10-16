"""
dashboard/pages/6_vision.py — Vision / Lab State
"""

import streamlit as st
import httpx
import plotly.graph_objects as go

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'dashboard'))
from shared import inject_css, render_nav, hero, api_get, api_post, api_delete, kpi_row, divider, section_label, badge, stats_strip, neon_card, render_step_card, render_protocol_header, export_buttons, PLOTLY_DARK


st.set_page_config(page_title="Vision — AuroLab", page_icon="⚗", layout="wide", initial_sidebar_state="collapsed")
inject_css()
render_nav("vision")


API_BASE = "http://localhost:8080"
FILL_CLASSES = {
    "full": "fill-full", "high": "fill-high", "medium": "fill-medium",
    "low": "fill-low", "critical": "fill-critical", "empty": "fill-empty",
    "unknown": "fill-empty",
}
FILL_SYMBOLS = {
    "full": "████", "high": "███░", "medium": "██░░",
    "low": "█░░░", "critical": "▌░░░", "empty": "░░░░", "unknown": "????",
}

def slot_css_class(slot_num: int, state: dict) -> str:
    lmap = state.get("labware_map", {})
    attn = state.get("attention_slots", [])
    if slot_num in attn:
        return "slot-card slot-attention"
    if str(slot_num) in lmap or slot_num in lmap:
        return "slot-card slot-occupied"
    return "slot-card slot-empty"

# ---------------------------------------------------------------------------
st.markdown("## Vision — Lab State Detection")
st.markdown("Detect and inspect what labware is currently on the robot deck. Upload a real image or inject a mock scenario.")
st.markdown('<hr class="divider">', unsafe_allow_html=True)

left_col, right_col = st.columns([2, 3], gap="large")

with left_col:
    st.markdown("#### Detect lab state")

    tab1, tab2 = st.tabs(["Upload image", "Mock scenario"])

    with tab1:
        uploaded = st.file_uploader("Upload deck image", type=["jpg","jpeg","png"],
                                    label_visibility="collapsed")
        if uploaded and st.button("Run detection", use_container_width=True):
            with st.spinner("Running vision detection..."):
                result = api_post("/api/v1/vision/detect",
                                  files={"file": (uploaded.name, uploaded.read(), uploaded.type)})
            if result:
                st.session_state.vision_state = result
                st.success("Detection complete")
                st.rerun()

    with tab2:
        scenarios_data = api_get("/api/v1/vision/scenarios") or {}
        scenarios = scenarios_data.get("scenarios", ["bca_assay", "pcr", "low_tips_warning"])
        backend = scenarios_data.get("current_backend", "mock")

        badge_cls = {"groq": "badge-groq", "llava": "badge-llava", "mock": "badge-mock"}.get(backend, "badge-mock")
        st.markdown(f"Backend: <span class='{badge_cls}'>{backend.upper()}</span>", unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)

        scenario = st.selectbox("Scenario", scenarios, label_visibility="collapsed")
        if st.button("Inject scenario", use_container_width=True):
            result = api_post("/api/v1/vision/mock", json={"scenario": scenario})
            if result:
                st.session_state.vision_state = result
                st.success(f"Scenario '{scenario}' injected")
                st.rerun()

    if st.button("Refresh current state", use_container_width=True):
        result = api_get("/api/v1/vision/current")
        if result:
            st.session_state.vision_state = result
            st.rerun()

    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown("#### How it works")
    st.markdown("""
    <div style='font-size:0.84em; color:#888898; line-height:1.9;'>
    <b style='color:#a78bfa;'>Mock mode</b> — deterministic synthetic detections, no model needed.<br>
    <b style='color:#a78bfa;'>Groq vision</b> — Llama 4 Scout with vision capability via Groq API.<br>
    <b style='color:#a78bfa;'>LLaVA</b> — local open-source VLM via Ollama, no cloud needed.<br><br>
    All backends produce the same typed <code>LabState</code> output,<br>
    which feeds directly into the execution layer as the live labware map.
    </div>
    """, unsafe_allow_html=True)

with right_col:
    state = st.session_state.get("vision_state")

    if not state:
        state = api_get("/api/v1/vision/current")
        if state:
            st.session_state.vision_state = state

    if not state:
        st.markdown("""
        <div style='text-align:center; padding:64px; color:#444458;'>
            <div style='font-size:2em; margin-bottom:12px;'>🔬</div>
            <div style='font-family:JetBrains Mono,monospace; font-size:0.85em;'>No lab state detected yet.</div>
            <div style='font-size:0.8em; margin-top:6px;'>Inject a mock scenario or upload an image.</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        conf = state.get("overall_confidence", 0)
        source = state.get("source", "unknown")
        occupied = state.get("occupied_slots", [])
        attention = state.get("attention_slots", [])
        tip_racks = state.get("tip_rack_slots", [])
        warnings = state.get("warnings", [])
        lmap = state.get("labware_map", {})

        # Header metrics
        badge_cls = {"groq": "badge-groq", "llava": "badge-llava", "mock": "badge-mock"}.get(source, "badge-mock")
        st.markdown(f"<span class='{badge_cls}'>{source.upper()}</span> &nbsp; "
                    f"<span style='font-family:JetBrains Mono,monospace; font-size:0.82em; color:#a78bfa;'>{conf:.0%} confidence</span> &nbsp; "
                    f"<span style='font-size:0.82em; color:#555568;'>{len(occupied)} occupied · {len(attention)} need attention</span>",
                    unsafe_allow_html=True)

        # Warnings
        for w in warnings:
            st.markdown(f"<div class='warning-row'>⚠ {w}</div>", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("#### Deck layout")

        # OT-2 deck grid: rows bottom-to-top, cols left-to-right
        # Slots: row1=[1,2,3], row2=[4,5,6], row3=[7,8,9], row4=[10,11,12]
        deck_rows = [[10,11,12], [7,8,9], [4,5,6], [1,2,3]]

        for row in deck_rows:
            cols = st.columns(3)
            for col, slot_num in zip(cols, row):
                slot_ltype = lmap.get(str(slot_num), lmap.get(slot_num, ""))
                is_occupied = bool(slot_ltype)
                is_attention = slot_num in attention
                css = "slot-card " + ("slot-attention" if is_attention else "slot-occupied" if is_occupied else "slot-empty")
                display_type = slot_ltype.replace("_", " ") if slot_ltype else "empty"

                with col:
                    st.markdown(f"""
                    <div class='{css}'>
                        <div class='slot-num'>SLOT {slot_num}</div>
                        <div class='slot-type'>{display_type}</div>
                    </div>
                    """, unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # Confidence bar chart per slot
        if occupied:
            st.markdown("#### Detection confidence per slot")

            # We don't have per-slot confidence in the summary response — show occupancy chart
            slot_labels = [f"Slot {s}" for s in range(1, 13)]
            slot_values = [1 if s in occupied else 0 for s in range(1, 13)]
            slot_colors = ["#f59e0b" if s in attention else "#7c6af7" if s in occupied else "#1a1a22"
                           for s in range(1, 13)]

            fig = go.Figure(go.Bar(
                x=slot_labels,
                y=slot_values,
                marker_color=slot_colors,
                marker_line_color="rgba(0,0,0,0)",
            ))
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="#0a0a0e",
                font=dict(family="JetBrains Mono, monospace", color="#888898", size=10),
                xaxis=dict(gridcolor="#1a1a22", tickfont=dict(color="#555568", size=9)),
                yaxis=dict(visible=False),
                height=160,
                margin=dict(l=0, r=0, t=8, b=0),
                showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True)

        # Labware map table
        if lmap:
            st.markdown("#### Labware map (feeds into simulation)")
            rows = []
            for slot_str, ltype in sorted(lmap.items(), key=lambda x: int(x[0])):
                attn_flag = "⚠" if int(slot_str) in attention else ""
                rows.append(f"<tr><td style='font-family:JetBrains Mono,monospace; color:#7c6af7;'>Slot {slot_str}</td>"
                            f"<td style='color:#c0c0cc;'>{ltype.replace('_',' ')}</td>"
                            f"<td style='color:#f59e0b;'>{attn_flag}</td></tr>")
            st.markdown(f"""
            <table style='width:100%; border-collapse:collapse; font-size:0.84em;'>
                <thead><tr>
                    <th style='background:#111118; color:#666680; padding:6px 12px; text-align:left; border-bottom:1px solid #1f1f28;'>Slot</th>
                    <th style='background:#111118; color:#666680; padding:6px 12px; text-align:left; border-bottom:1px solid #1f1f28;'>Labware</th>
                    <th style='background:#111118; color:#666680; padding:6px 12px; text-align:left; border-bottom:1px solid #1f1f28;'>Flags</th>
                </tr></thead>
                <tbody>{''.join(rows)}</tbody>
            </table>
            """, unsafe_allow_html=True)