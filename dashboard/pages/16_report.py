"""dashboard/pages/16_report.py — Protocol Report Export"""
import sys
from pathlib import Path
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'dashboard'))
from shared import inject_css, render_nav, hero, api_get, kpi_row, divider, section_label, badge

st.set_page_config(page_title="Report — AuroLab", page_icon="⚗", layout="wide",
                   initial_sidebar_state="collapsed")
inject_css()
render_nav("report")

hero("PROTOCOL REPORT",
     "Export any protocol as a self-contained HTML report or Markdown document — ready to print, archive, or share",
     accent="#ffd33d", tag="HTML · Markdown · Print-ready")

history = st.session_state.get("protocol_history", [])
if not history:
    st.markdown("""
    <div style="text-align:center;padding:5rem;color:rgba(160,185,205,0.4);">
        <div style="font-size:2rem;margin-bottom:1rem;">📄</div>
        <div style="font-family:'JetBrains Mono',monospace;">Generate a protocol first</div>
    </div>""", unsafe_allow_html=True)
    st.stop()

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from services.translation_service.core.report_generator import (
    generate_html_report, generate_markdown_report)

opts = {f"{p.get('title','?')} — {p.get('protocol_id','')[:8]}": p for p in history}
ca, cb = st.columns([3, 1])
with ca:
    sel = st.selectbox("Protocol", list(opts.keys()), label_visibility="collapsed")
with cb:
    fmt = st.selectbox("Format", ["HTML", "Markdown"], label_visibility="collapsed")

protocol = opts[sel]
last_sim = st.session_state.get("last_sim_result")
analytics = st.session_state.get(f"ana_{protocol.get('protocol_id','')}")

divider()

# Protocol summary card
conf   = protocol.get("confidence_score", 0)
safety = protocol.get("safety_level", "safe")
steps  = len(protocol.get("steps", []))
sources= len(protocol.get("sources_used", []))

kpi_row([
    (steps,             "Steps",        "#00f0c8"),
    (f"{conf:.0%}",     "Confidence",   "#4ade80" if conf>0.8 else "#ffd33d"),
    (sources,           "Sources",      "#6c4cdc"),
    (len(protocol.get("reagents",[])), "Reagents", "#00b8ff"),
])

# Options
divider()
section_label("Report options")
oc1, oc2 = st.columns(2)
with oc1:
    include_prov = st.checkbox("Include generation provenance", value=True)
    include_sim  = st.checkbox("Include simulation result", value=last_sim is not None)
with oc2:
    include_ana  = st.checkbox("Include analytics", value=analytics is not None)

divider()

# Generate and download
sim_data = last_sim if include_sim else None
ana_data = analytics if include_ana else None

if fmt == "HTML":
    report = generate_html_report(
        protocol,
        analytics=ana_data,
        sim_result=sim_data,
        include_provenance=include_prov,
    )
    fname = f"aurolab_report_{protocol.get('protocol_id','x')[:8]}.html"
    mime  = "text/html"
    icon  = "📄"
    size  = f"{len(report):,} chars"
else:
    report = generate_markdown_report(protocol)
    fname  = f"aurolab_report_{protocol.get('protocol_id','x')[:8]}.md"
    mime   = "text/markdown"
    icon   = "📝"
    size   = f"{len(report):,} chars"

dc1, dc2, _ = st.columns([1, 1, 3])
with dc1:
    st.download_button(
        f"⬇ Download {fmt} Report",
        data=report,
        file_name=fname,
        mime=mime,
        type="primary",
        use_container_width=True,
    )
with dc2:
    st.markdown(f"""
    <div style="font-family:'JetBrains Mono',monospace;font-size:0.65rem;
        color:rgba(160,185,205,0.35);padding-top:10px;">
        {icon} {fname}<br>{size}
    </div>""", unsafe_allow_html=True)

# Preview
divider()
section_label("Preview")

if fmt == "HTML":
    # Show key sections as native Streamlit
    st.markdown(f"""
    <div style="background:rgba(255,255,255,0.02);border:1px solid rgba(0,240,200,0.08);
        border-radius:12px;padding:1.5rem;">
        <div style="font-family:'Orbitron',monospace;font-size:1.1rem;font-weight:700;
            color:#e8f4ff;margin-bottom:6px;">{protocol.get('title','')}</div>
        <div style="font-size:0.85rem;color:rgba(160,185,205,0.5);margin-bottom:12px;">{protocol.get('description','')}</div>
        <div style="display:flex;gap:8px;">
            {badge(safety.upper(), safety)}
            {badge(f"{conf:.0%} CONFIDENCE", "safe" if conf>0.8 else "warning")}
            {badge(f"{steps} STEPS", "idle")}
            {badge(f"{sources} SOURCES", "default")}
        </div>
    </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    section_label("Steps preview")
    for step in protocol.get("steps", [])[:5]:
        cite = ", ".join(step.get("citations",[])) or "GENERAL"
        st.markdown(f"""
        <div style="background:rgba(0,240,200,0.015);border:1px solid rgba(0,240,200,0.07);
            border-left:2px solid #00f0c8;border-radius:0 8px 8px 0;
            padding:8px 12px;margin:4px 0;">
            <div style="font-family:'JetBrains Mono',monospace;font-size:0.6rem;
                color:#00f0c8;margin-bottom:3px;">STEP {step.get('step_number','?')} · {cite}</div>
            <div style="font-size:0.85rem;color:#d0e4f0;">{step.get('instruction','')}</div>
        </div>""", unsafe_allow_html=True)

    if len(protocol.get("steps",[])) > 5:
        st.markdown(f"<div style='font-family:JetBrains Mono,monospace;font-size:0.68rem;color:rgba(160,185,205,0.35);padding:6px 0;'>... and {len(protocol.get('steps',[]))-5} more steps in the full report</div>",
                    unsafe_allow_html=True)
else:
    # Markdown preview
    st.code(report[:2000] + ("..." if len(report) > 2000 else ""), language="markdown")