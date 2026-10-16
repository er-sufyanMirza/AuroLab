"""dashboard/pages/13_reflect.py — LLM Reflection & Auto-Fix"""
import sys
from pathlib import Path
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'dashboard'))
from shared import inject_css, render_nav, hero, api_get, api_post, kpi_row, divider, section_label, badge, render_step_card

st.set_page_config(page_title="Reflect — AuroLab", page_icon="⚗", layout="wide",
                   initial_sidebar_state="collapsed")
inject_css()
render_nav("reflect")

hero("LLM REFLECTION",
     "When simulation fails, the LLM diagnoses the cause and generates a corrected protocol automatically",
     accent="#f87171", tag="Diagnose · Correct · Re-simulate")

history = st.session_state.get("protocol_history", [])
if not history:
    st.markdown("""
    <div style="text-align:center;padding:4rem;color:rgba(160,185,205,0.4);">
        <div style="font-size:2rem;margin-bottom:1rem;">🔄</div>
        <div style="font-family:'JetBrains Mono',monospace;">Generate and simulate a protocol first</div>
    </div>""", unsafe_allow_html=True)
    st.stop()

opts = {f"{p.get('title','?')} — {p.get('protocol_id','')[:8]}": p for p in history}
ca, cb = st.columns([3, 1])
with ca:
    sel = st.selectbox("Protocol to reflect on", list(opts.keys()), label_visibility="collapsed")
with cb:
    sim_mode = st.selectbox("Sim mode", ["mock","pybullet"], label_visibility="collapsed")

protocol = opts[sel]

# Show last sim result if available
last_sim = st.session_state.get("last_sim_result")
has_failure = last_sim and not last_sim.get("passed", last_sim.get("simulation_passed", True))

if has_failure:
    st.markdown(f"""
    <div style="background:rgba(248,113,113,0.07);border:1px solid rgba(248,113,113,0.2);
        border-radius:10px;padding:12px 16px;margin:1rem 0;">
        <span style="font-family:'JetBrains Mono',monospace;font-size:0.72rem;color:#f87171;">
            ✗ LAST SIMULATION FAILED</span><br>
        <span style="font-size:0.82rem;color:rgba(208,228,240,0.6);">
            Commands executed: {last_sim.get('commands_executed','?')} · Engine: {last_sim.get('sim_mode','?')}</span>
    </div>""", unsafe_allow_html=True)

run_btn = st.button("⚡ Run LLM Reflection", type="primary", use_container_width=False)

if run_btn:
    sim_result = last_sim or {"passed": False, "errors": [{"message": "Requested manual reflection"}],
                               "collision_detected": False, "telemetry": {}}

    # Run reflection
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    try:
        from services.translation_service.core.llm_engine import AurolabLLMEngine
        from services.translation_service.core.rag_engine import AurolabRAGEngine
        import os

        # Try to get LLM engine from app state via API
        with st.spinner("// DIAGNOSING FAILURE..."):
            reflect_result = api_post("/api/v1/reflect", json={
                "protocol_id": protocol.get("protocol_id",""),
                "sim_result":  sim_result,
                "sim_mode":    sim_mode,
            }, silent=True)

        if reflect_result is None:
            # Fallback: run locally if API endpoint not available
            st.warning("Reflection API endpoint not available — showing heuristic analysis")
            reflect_result = {
                "diagnosis": "Simulation failed — likely missing tip pickup or volume overflow",
                "corrections": [
                    "Add explicit pick_up_tip step before first aspirate",
                    "Reduce flow rate to 100 µL/s to prevent tip collision",
                    "Add home command at start of protocol",
                ],
                "revised_sim_passed": False,
                "reflection_ms": 0,
            }

        st.session_state.reflection_result = reflect_result

    except Exception as e:
        st.error(f"Reflection error: {e}")

divider()

# Display result
if "reflection_result" in st.session_state:
    r = st.session_state.reflection_result

    passed = r.get("revised_sim_passed", False)
    status_color = "#4ade80" if passed else "#ffd33d"
    status_text  = "REVISION PASSED SIMULATION" if passed else "REVISION GENERATED — RE-SIMULATE TO VERIFY"

    kpi_row([
        ("PASS" if passed else "PENDING", "Revised sim",    "#4ade80" if passed else "#ffd33d"),
        (f"{r.get('reflection_ms',0):.0f}ms", "Reflection time", "#00b8ff"),
        (str(len(r.get("corrections",[]))), "Corrections",    "#a89ef8"),
    ])

    divider()
    section_label("Diagnosis")
    st.markdown(f"""
    <div style="background:rgba(248,113,113,0.04);border:1px solid rgba(248,113,113,0.12);
        border-radius:8px;padding:12px 16px;margin-bottom:1rem;">
        <span style="font-size:0.88rem;color:#d0e4f0;">{r.get("diagnosis","No diagnosis available")}</span>
    </div>""", unsafe_allow_html=True)

    corrections = r.get("corrections", [])
    if corrections:
        section_label("Corrections applied")
        for i, c in enumerate(corrections, 1):
            st.markdown(f"""
            <div style="display:flex;gap:10px;padding:7px 0;border-bottom:1px solid rgba(0,240,200,0.05);">
                <span style="font-family:'Orbitron',monospace;font-size:0.65rem;color:#6c4cdc;min-width:20px;">{i:02d}</span>
                <span style="font-size:0.84rem;color:#c0d8e8;">{c}</span>
            </div>""", unsafe_allow_html=True)

    # Revised protocol
    revised = r.get("revised_protocol") or {}
    if revised and revised.get("steps"):
        divider()
        section_label("Revised protocol")
        note = revised.get("reflection_note","")
        if note:
            st.markdown(f"""
            <div style="background:rgba(108,76,220,0.06);border:1px solid rgba(108,76,220,0.15);
                border-radius:8px;padding:10px 14px;margin-bottom:1rem;font-size:0.82rem;color:#c0b8ff;">
                💡 {note}
            </div>""", unsafe_allow_html=True)

        for step in revised.get("steps", []):
            render_step_card(step)

        divider()
        # Save revised to history
        if st.button("✓ Save revised protocol to history", type="primary"):
            if "protocol_history" not in st.session_state:
                st.session_state.protocol_history = []
            st.session_state.protocol_history.insert(0, revised)
            st.session_state.last_protocol = revised
            st.success("Saved — view on Generate or History page")