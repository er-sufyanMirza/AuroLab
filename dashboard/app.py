"""dashboard/app.py — AuroLab Home"""
import sys
from pathlib import Path
import streamlit as st
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'dashboard'))
from shared import inject_css, render_nav, hero, api_get, kpi_row, divider, section_label, badge

st.set_page_config(page_title="AuroLab", page_icon="⚗", layout="wide", initial_sidebar_state="collapsed")
inject_css()
render_nav("home")

# Hero
st.markdown("""
<div style="text-align:center;padding:2.5rem 0 1.5rem;">
    <div style="font-family:'Orbitron',monospace;font-size:2.8rem;font-weight:900;
        color:#e8f4ff;letter-spacing:0.08em;line-height:1.1;margin-bottom:0.75rem;">
        AURO<span style="color:#00f0c8;">·</span>LAB
    </div>
    <div style="font-family:'JetBrains Mono',monospace;font-size:0.75rem;letter-spacing:0.3em;
        color:rgba(0,240,200,0.6);text-transform:uppercase;margin-bottom:1.2rem;">
        Autonomous Physical AI · Lab Automation
    </div>
    <div style="font-size:1rem;color:rgba(160,185,205,0.55);max-width:580px;margin:0 auto;line-height:1.7;">
        Natural language → validated robotic protocols in under 3 seconds.
        RAG retrieval · LLM generation · PyBullet simulation · RL optimisation.
    </div>
</div>""", unsafe_allow_html=True)

# Live stats from API
health = api_get("/health", silent=True) or {}
services = health.get("services", {})
rag      = health.get("rag", {})
ext      = health.get("extensions", {})

all_ok = all(services.values()) if services else False
status_color = "#4ade80" if all_ok else ("#ffd33d" if any(services.values()) else "#f87171")
status_text  = "ALL SYSTEMS ONLINE" if all_ok else ("PARTIAL" if any(services.values()) else "OFFLINE")

st.markdown(f"""
<div style="text-align:center;margin-bottom:2rem;">
    <span style="display:inline-flex;align-items:center;gap:8px;
        background:rgba(0,240,200,0.04);border:1px solid {status_color}33;
        border-radius:100px;padding:6px 18px;
        font-family:'JetBrains Mono',monospace;font-size:0.7rem;color:{status_color};">
        <span style="width:7px;height:7px;border-radius:50%;background:{status_color};
            box-shadow:0 0 8px {status_color};"></span>
        SYS · {status_text}
    </span>
</div>""", unsafe_allow_html=True)

kpi_row([
    (rag.get("total_chunks", "—"),      "KB Chunks",      "#00f0c8"),
    (rag.get("total_documents", "—"),   "Documents",       "#6c4cdc"),
    (len(st.session_state.get("protocol_history", [])), "Protocols", "#00b8ff"),
    (sum(1 for v in ext.values() if v is True) if ext else "—", "Extensions", "#4ade80"),
])
divider()

# Pipeline overview
section_label("5-stage pipeline")
stages = [
    ("#6c4cdc","01","HyDE EXPANSION",    "Instruction → hypothetical protocol excerpt → richer embedding"),
    ("#00f0c8","02","HYBRID RETRIEVAL",  "Dense + BM25 · RRF · cross-encoder reranking"),
    ("#00b8ff","03","LLM GENERATION",    "Groq Llama 3.3-70B · [SOURCE_N] citations · JSON schema"),
    ("#ffd33d","04","SAFETY VALIDATION", "Pre/post checks · hazard flags · confidence score"),
    ("#f87171","05","PHYSICS SIMULATION","PyBullet collision detection · command validation"),
]
cols = st.columns(5, gap="small")
for col, (color, num, title, desc) in zip(cols, stages):
    col.markdown(f"""
    <div style="background:rgba(0,240,200,0.015);border:1px solid {color}22;
        border-top:2px solid {color};border-radius:0 0 10px 10px;
        padding:0.9rem 0.8rem;height:140px;">
        <div style="font-family:'Orbitron',monospace;font-size:0.55rem;
            color:{color};margin-bottom:4px;letter-spacing:0.1em;">{num}</div>
        <div style="font-family:'Orbitron',monospace;font-size:0.65rem;font-weight:700;
            color:#e8f4ff;margin-bottom:6px;">{title}</div>
        <div style="font-size:0.68rem;color:rgba(160,185,205,0.45);line-height:1.5;">{desc}</div>
    </div>""", unsafe_allow_html=True)

divider()

# Services status
section_label("Services")
service_labels = {
    "rag_llm":   ("RAG + LLM",   "#00f0c8"),
    "execution": ("Simulation",  "#6c4cdc"),
    "vision":    ("Vision AI",   "#00b8ff"),
    "analytics": ("Analytics",   "#ffd33d"),
    "fleet":     ("Fleet Orch.", "#f87171"),
    "rl":        ("RL Agent",    "#4ade80"),
}
if services:
    scols = st.columns(len(service_labels), gap="small")
    for col, (key, (label, color)) in zip(scols, service_labels.items()):
        ok = services.get(key, False)
        sc = "#4ade80" if ok else "#f87171"
        col.markdown(f"""
        <div style="text-align:center;padding:0.6rem;background:rgba(0,240,200,0.01);
            border:1px solid {sc}22;border-radius:8px;">
            <div style="font-size:1rem;margin-bottom:4px;">{'✓' if ok else '✗'}</div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:0.6rem;color:{sc};">{label}</div>
        </div>""", unsafe_allow_html=True)
else:
    st.markdown("""<div style="font-family:'JetBrains Mono',monospace;font-size:0.75rem;
        color:rgba(160,185,205,0.3);text-align:center;padding:1rem;">
        Start uvicorn to see live service status</div>""", unsafe_allow_html=True)

divider()

# Quick start
section_label("Quick start")
st.code("""# Terminal 1 — Backend
uvicorn main:app --host 0.0.0.0 --port 8080 --reload

# Terminal 2 — Dashboard
streamlit run dashboard/app.py

# Smoke test
python mock_test.py

# Full test suite
pytest tests/test_phase8_extensions.py -v""", language="bash")

# Recent protocols
if st.session_state.get("protocol_history"):
    divider()
    section_label(f"Recent protocols ({len(st.session_state.protocol_history)})")
    for p in st.session_state.protocol_history[:4]:
        safety = p.get("safety_level","safe")
        conf   = p.get("confidence_score",0)
        st.markdown(f"""
        <div style="display:flex;align-items:center;gap:12px;padding:8px 12px;
            background:rgba(0,240,200,0.015);border:1px solid rgba(0,240,200,0.07);
            border-radius:8px;margin:3px 0;">
            <div style="flex:1;font-size:0.85rem;color:#d0e4f0;">{p.get('title','?')}</div>
            <span style="font-family:'JetBrains Mono',monospace;font-size:0.65rem;
                color:rgba(160,185,205,0.35);">{conf:.0%}</span>
            {badge(safety.upper(), safety)}
        </div>""", unsafe_allow_html=True)