"""dashboard/pages/5_health.py — System Health Monitor"""
import sys
import time
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'dashboard'))
from shared import (inject_css, render_nav, hero, kpi_row,
                    divider, section_label, badge, API_BASE, PLOTLY_DARK)

st.set_page_config(page_title="Health — AuroLab", page_icon="⚗",
                   layout="wide", initial_sidebar_state="collapsed")
inject_css()
render_nav("health")

hero("SYSTEM HEALTH",
     "Live endpoint probing, latency tracking, RAG stats, extension status",
     accent="#4ade80", tag="API · RAG · Extensions · Latency")

import httpx
from datetime import datetime

def probe(path: str, method: str = "GET", body: dict = None):
    t0 = time.perf_counter()
    try:
        if method == "POST":
            r = httpx.post(f"{API_BASE}{path}", json=body or {}, timeout=8.0)
        else:
            r = httpx.get(f"{API_BASE}{path}", timeout=8.0)
        ms = round((time.perf_counter() - t0) * 1000)
        ok = r.status_code < 400
        try:    data = r.json()
        except: data = {}
        return ok, ms, data
    except Exception as e:
        ms = round((time.perf_counter() - t0) * 1000)
        return False, ms, {"error": str(e)}

ENDPOINTS = [
    ("/health",               "API gateway",          "GET"),
    ("/api/v1/protocols/",    "Protocol list",        "GET"),
    ("/api/v1/documents/",    "Document list",        "GET"),
    ("/api/v1/rag/stats",     "RAG stats",            "GET"),
    ("/api/v1/inventory/",    "Inventory",            "GET"),
    ("/api/v1/templates/",    "Templates",            "GET"),
    ("/api/v1/workflows/",    "Workflows",            "GET"),
    ("/api/v1/extensions/status", "Extensions",       "GET"),
    ("/api/v1/scheduler/jobs","Scheduler jobs",       "GET"),
    ("/api/v1/starred",       "Starred protocols",    "GET"),
]

# ── Probe all endpoints ───────────────────────────────────────────────────────
with st.spinner("Probing endpoints..."):
    results = {}
    for path, label, method in ENDPOINTS:
        ok, ms, data = probe(path, method)
        results[label] = {"ok": ok, "ms": ms, "data": data, "path": path}

health_d = results.get("API gateway", {}).get("data", {})
rag      = health_d.get("rag", {})
ext      = health_d.get("extensions", {})
services = health_d.get("services", {})

ok_count  = sum(1 for v in results.values() if v["ok"])
avg_ms    = round(sum(v["ms"] for v in results.values()) / max(len(results), 1))
api_online = results.get("API gateway", {}).get("ok", False)

# ── KPIs ─────────────────────────────────────────────────────────────────────
kpi_row([
    (f"{ok_count}/{len(results)}", "Endpoints OK",   "#4ade80" if ok_count == len(results) else "#ffd33d"),
    (f"{avg_ms}ms",               "Avg latency",     "#4ade80" if avg_ms < 200 else "#ffd33d"),
    (rag.get("total_chunks","—"), "KB Chunks",       "#00f0c8"),
    ("ONLINE" if api_online else "OFFLINE", "API status",
     "#4ade80" if api_online else "#f87171"),
])
divider()

# ── Latency chart ─────────────────────────────────────────────────────────────
section_label("Endpoint latency")
labels = [v for v in results.keys()]
ms_vals = [results[v]["ms"] for v in labels]
colors  = ["#4ade80" if results[v]["ok"] else "#f87171" for v in labels]

fig = go.Figure(go.Bar(
    x=labels, y=ms_vals,
    marker_color=colors, marker_line_width=0,
    text=[f"{m}ms" for m in ms_vals],
    textposition="outside",
    textfont=dict(color="rgba(160,185,205,0.6)", size=9, family="JetBrains Mono"),
))
fig.add_hline(y=200, line=dict(color="rgba(255,211,61,0.4)", width=1, dash="dot"),
              annotation_text="200ms threshold",
              annotation_font_color="rgba(255,211,61,0.5)")
fig.update_layout(
    **PLOTLY_DARK,
    xaxis=dict(tickfont=dict(size=9)),
    yaxis=dict(title="ms", gridcolor="rgba(0,240,200,0.05)"),
    height=260, margin=dict(l=8,r=8,t=32,b=8),
    title=dict(text="Response time per endpoint",
               font=dict(color="rgba(160,185,205,0.5)",size=11)),
)
st.plotly_chart(fig, use_container_width=True)
divider()

# ── Endpoint status table ─────────────────────────────────────────────────────
section_label("Endpoint status")
for label, v in results.items():
    ok  = v["ok"]
    ms  = v["ms"]
    col = "#4ade80" if ok else "#f87171"
    icon = "✓" if ok else "✗"
    bar_w = min(ms / 5, 100)
    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:12px;padding:7px 12px;
        background:rgba(0,240,200,0.01);border:1px solid rgba(0,240,200,0.06);
        border-radius:8px;margin:3px 0;">
        <span style="font-family:'JetBrains Mono',monospace;font-size:0.75rem;
            color:{col};min-width:18px;">{icon}</span>
        <span style="font-size:0.82rem;color:#d0e4f0;flex:1;">{label}</span>
        <span style="font-family:'JetBrains Mono',monospace;font-size:0.65rem;
            color:rgba(160,185,205,0.35);min-width:80px;text-align:right;">{v['path']}</span>
        <div style="width:80px;background:rgba(255,255,255,0.04);
            border-radius:2px;height:4px;overflow:hidden;">
            <div style="background:{col};height:100%;width:{bar_w}%;
                box-shadow:0 0 4px {col};"></div>
        </div>
        <span style="font-family:'JetBrains Mono',monospace;font-size:0.7rem;
            color:{col};min-width:52px;text-align:right;">{ms}ms</span>
    </div>""", unsafe_allow_html=True)

divider()

# ── RAG + Services status ─────────────────────────────────────────────────────
left, right = st.columns(2, gap="large")

with left:
    section_label("RAG knowledge base")
    rag_items = [
        ("Total chunks",   rag.get("total_chunks", "—")),
        ("Documents",      rag.get("total_documents", "—")),
        ("Embedding model",rag.get("embed_model", "all-MiniLM-L6-v2")),
        ("HyDE enabled",   str(rag.get("hyde_enabled", True))),
        ("Reranker",       str(rag.get("reranker_enabled", True))),
        ("Collection",     rag.get("collection", "aurolab_protocols")),
    ]
    for k, v in rag_items:
        st.markdown(f"""
        <div style="display:flex;justify-content:space-between;padding:5px 0;
            border-bottom:1px solid rgba(0,240,200,0.05);">
            <span style="font-size:0.78rem;color:rgba(160,185,205,0.4);">{k}</span>
            <span style="font-family:'JetBrains Mono',monospace;font-size:0.75rem;
                color:#00f0c8;">{v}</span>
        </div>""", unsafe_allow_html=True)

with right:
    section_label("Backend services")
    svc_labels = {
        "rag_llm":   "RAG + LLM Engine",
        "execution": "Physics Simulation",
        "vision":    "Vision AI",
        "analytics": "Analytics Engine",
        "fleet":     "Fleet Orchestration",
        "rl":        "RL Agent",
    }
    if services:
        for key, label in svc_labels.items():
            ok  = services.get(key, False)
            col = "#4ade80" if ok else "#f87171"
            st.markdown(f"""
            <div style="display:flex;align-items:center;gap:10px;padding:6px 0;
                border-bottom:1px solid rgba(0,240,200,0.05);">
                <span style="color:{col};font-size:0.85rem;">{'●' if ok else '○'}</span>
                <span style="font-size:0.78rem;color:#d0e4f0;flex:1;">{label}</span>
                <span style="font-family:'JetBrains Mono',monospace;font-size:0.65rem;
                    color:{col};">{'ONLINE' if ok else 'OFFLINE'}</span>
            </div>""", unsafe_allow_html=True)
    else:
        st.markdown("<div style='font-family:JetBrains Mono,monospace;font-size:0.75rem;"
                    "color:rgba(160,185,205,0.3);'>Start backend to see service status</div>",
                    unsafe_allow_html=True)

divider()

# ── Extensions status ─────────────────────────────────────────────────────────
section_label("Phase 8+ extensions")
ext_labels = {
    "opentrons":  "Opentrons OT-2 Exporter",
    "diff":       "Protocol Diff Engine",
    "inventory":  "Reagent Inventory",
    "templates":  "Protocol Templates",
    "report":     "Report Generator",
    "workflows":  "Workflow Engine",
    "optimizer":  "Protocol Optimizer",
    "reflection": "LLM Reflection",
    "bundle":     "Export Bundle",
    "batch":      "Batch Generator",
    "notes":      "Lab Notebook",
    "param_validator": "Parameter Validator",
    "eln_exporter":    "ELN Exporter",
    "scheduler":       "Job Scheduler",
}
if ext:
    cols = st.columns(3, gap="small")
    items = list(ext_labels.items())
    per_col = (len(items) + 2) // 3
    for ci, col in enumerate(cols):
        for key, label in items[ci*per_col:(ci+1)*per_col]:
            ok  = ext.get(key, False)
            col_c = "#4ade80" if ok else "#f87171"
            col.markdown(f"""
            <div style="display:flex;align-items:center;gap:6px;padding:4px 0;
                border-bottom:1px solid rgba(0,240,200,0.04);">
                <span style="color:{col_c};font-size:0.75rem;">{'✓' if ok else '✗'}</span>
                <span style="font-size:0.72rem;color:rgba(160,185,205,0.6);">{label}</span>
            </div>""", unsafe_allow_html=True)
else:
    st.markdown("<div style='font-family:JetBrains Mono,monospace;font-size:0.75rem;"
                "color:rgba(160,185,205,0.3);'>Start backend to see extension status</div>",
                unsafe_allow_html=True)

divider()

# ── Refresh button ────────────────────────────────────────────────────────────
rc1, rc2, _ = st.columns([1, 1, 4])
with rc1:
    if st.button("🔄 Refresh all probes", type="primary", use_container_width=True):
        st.rerun()
with rc2:
    st.markdown(f"<div style='font-family:JetBrains Mono,monospace;font-size:0.62rem;"
                f"color:rgba(160,185,205,0.3);padding-top:10px;'>"
                f"Last probe: {datetime.now().strftime('%H:%M:%S')}</div>",
                unsafe_allow_html=True)