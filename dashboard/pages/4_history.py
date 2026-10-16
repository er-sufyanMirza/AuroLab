"""dashboard/pages/4_history.py — Protocol History"""
import json
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'dashboard'))
from shared import (inject_css, render_nav, hero, api_get, kpi_row,
                    divider, section_label, badge, PLOTLY_DARK)

st.set_page_config(page_title="History — AuroLab", page_icon="⚗",
                   layout="wide", initial_sidebar_state="collapsed")
inject_css()
render_nav("history")

hero("PROTOCOL HISTORY",
     "Search, filter, compare and export all generated protocols",
     accent="#6c4cdc", tag="Search · Filter · Export · Delete")

history = st.session_state.get("protocol_history", [])

# ── Also fetch from API (persisted across restarts) ──────────────────────────
api_protos = api_get("/api/v1/protocols/", silent=True)
if api_protos and api_protos.get("protocols"):
    api_ids = {p.get("protocol_id") for p in history}
    for p in api_protos["protocols"]:
        if p.get("protocol_id") not in api_ids:
            history.append(p)

kpi_row([
    (len(history), "Protocols", "#6c4cdc"),
    (sum(1 for p in history if p.get("safety_level") == "safe"),   "Safe",    "#4ade80"),
    (sum(1 for p in history if p.get("safety_level") == "warning"),"Warning", "#ffd33d"),
    (f"{sum(p.get('confidence_score',0) for p in history)/max(len(history),1):.0%}",
     "Avg confidence", "#00f0c8"),
])
divider()

# ── Filter bar ───────────────────────────────────────────────────────────────
fa, fb, fc, fd = st.columns([3, 2, 2, 1])
with fa:
    q = st.text_input("Search", placeholder="Title, reagent, or keyword...",
                      label_visibility="collapsed")
with fb:
    safety_f = st.selectbox("Safety", ["All", "safe", "warning", "blocked"],
                             label_visibility="collapsed")
with fc:
    sort_by = st.selectbox("Sort by",
                           ["Newest first", "Confidence ↓", "Steps ↓", "Safety"],
                           label_visibility="collapsed")
with fd:
    compare_mode = st.checkbox("Compare")

# Apply filters
filtered = history
if q:
    ql = q.lower()
    filtered = [p for p in filtered if
                ql in p.get("title","").lower() or
                ql in p.get("description","").lower() or
                any(ql in r.lower() for r in p.get("reagents",[])) or
                any(ql in s.get("instruction","").lower()
                    for s in p.get("steps",[]))]
if safety_f != "All":
    filtered = [p for p in filtered if p.get("safety_level") == safety_f]

# Sort
if sort_by == "Confidence ↓":
    filtered = sorted(filtered, key=lambda p: p.get("confidence_score",0), reverse=True)
elif sort_by == "Steps ↓":
    filtered = sorted(filtered, key=lambda p: len(p.get("steps",[])), reverse=True)
elif sort_by == "Safety":
    order = {"safe":0,"caution":1,"warning":2,"blocked":3}
    filtered = sorted(filtered, key=lambda p: order.get(p.get("safety_level","safe"),4))

if not filtered:
    st.markdown("""
    <div style="text-align:center;padding:4rem;color:rgba(160,185,205,0.4);">
        <div style="font-size:2rem;margin-bottom:1rem;">🔍</div>
        <div style="font-family:'JetBrains Mono',monospace;">No protocols match your search</div>
    </div>""", unsafe_allow_html=True)
    st.stop()

section_label(f"{'Filtered' if q or safety_f!='All' else 'All'} protocols ({len(filtered)})")

# ── Protocol list ─────────────────────────────────────────────────────────────
compare_ids = st.session_state.get("compare_selection", [])

for p in filtered:
    pid    = p.get("protocol_id", "")
    title  = p.get("title", "Untitled")
    safety = p.get("safety_level", "safe")
    conf   = p.get("confidence_score", 0)
    steps  = len(p.get("steps", []))
    reagents = p.get("reagents", [])
    ts     = p.get("saved_at") or p.get("generation_ms", 0)
    date_str = ""
    if ts and ts > 1e9:
        date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")

    SAFETY_COL = {"safe":"#4ade80","caution":"#ffd33d",
                  "warning":"#f87171","blocked":"#ef4444"}
    sc = SAFETY_COL.get(safety, "#888898")
    conf_col = "#4ade80" if conf >= 0.8 else ("#ffd33d" if conf >= 0.6 else "#f87171")

    with st.expander(f"{title}  ·  {conf:.0%}  ·  {steps} steps"):
        left, right = st.columns([3, 1])
        with left:
            st.markdown(f"""
            <div style="font-size:0.82rem;color:rgba(160,185,205,0.55);
                margin-bottom:8px;">{p.get('description','')[:200]}</div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px;">
                {badge(safety.upper(), safety)}
                <span style="font-family:'JetBrains Mono',monospace;font-size:0.62rem;
                    color:{conf_col};">{conf:.0%} CONFIDENCE</span>
                <span style="font-family:'JetBrains Mono',monospace;font-size:0.62rem;
                    color:rgba(160,185,205,0.3);">{steps} STEPS · {len(reagents)} REAGENTS</span>
                {f'<span style="font-size:0.62rem;color:rgba(160,185,205,0.25);">· {date_str}</span>' if date_str else ''}
            </div>""", unsafe_allow_html=True)

            # Steps preview
            for step in p.get("steps", [])[:2]:
                st.markdown(f"""
                <div style="font-family:'JetBrains Mono',monospace;font-size:0.65rem;
                    color:rgba(160,185,205,0.35);padding:2px 0;border-bottom:1px solid
                    rgba(0,240,200,0.04);">
                    [{step.get('step_number','?')}] {step.get('instruction','')[:80]}
                </div>""", unsafe_allow_html=True)
            if steps > 2:
                st.markdown(f"<div style='font-size:0.6rem;color:rgba(160,185,205,0.2);'>"
                            f"... +{steps-2} more steps</div>", unsafe_allow_html=True)

        with right:
            # Action buttons
            if st.button("📋 Load", key=f"load_{pid[:8]}", use_container_width=True):
                st.session_state.last_protocol = p
                st.success("Loaded — view on Generate page")

            st.download_button(
                "⬇ JSON", data=json.dumps(p, indent=2),
                file_name=f"protocol_{pid[:8]}.json",
                mime="application/json",
                key=f"dl_{pid[:8]}", use_container_width=True)

            if compare_mode:
                is_sel = pid in compare_ids
                if st.button("✓ Compare" if is_sel else "+ Compare",
                             key=f"cmp_{pid[:8]}", use_container_width=True):
                    if is_sel:
                        compare_ids.remove(pid)
                    elif len(compare_ids) < 2:
                        compare_ids.append(pid)
                    st.session_state.compare_selection = compare_ids
                    st.rerun()

            if st.button("🗑 Delete", key=f"del_{pid[:8]}", use_container_width=True):
                api_get(f"/api/v1/protocols/{pid}", silent=True)
                if pid in [p2.get("protocol_id") for p2 in history]:
                    st.session_state.protocol_history = [
                        p2 for p2 in history if p2.get("protocol_id") != pid]
                st.rerun()

# ── Compare trigger ───────────────────────────────────────────────────────────
if compare_mode and len(compare_ids) == 2:
    divider()
    section_label("Compare selected")
    st.markdown(f"**{compare_ids[0][:8]}** vs **{compare_ids[1][:8]}**")
    if st.button("⚡ Run comparison", type="primary"):
        result = api_get(
            f"/api/v1/protocols/compare?protocol_id_a={compare_ids[0]}"
            f"&protocol_id_b={compare_ids[1]}", silent=True)
        if not result:
            import requests
            result = api_get.__module__ and None
            # fallback: local diff
            pa = next((p for p in history if p.get("protocol_id")==compare_ids[0]), None)
            pb = next((p for p in history if p.get("protocol_id")==compare_ids[1]), None)
            if pa and pb:
                sys.path.insert(0, str(Path(__file__).parent.parent.parent))
                try:
                    from services.translation_service.core.protocol_diff import diff_protocols
                    d = diff_protocols(pa, pb)
                    st.metric("Similarity", f"{d.similarity_score:.0%}")
                    st.metric("Steps added", d.steps_added)
                    st.metric("Steps removed", d.steps_removed)
                    st.info(d.recommendation)
                except Exception:
                    st.info("Start backend for full comparison")

# ── Bulk export ───────────────────────────────────────────────────────────────
divider()
section_label("Bulk export")
bc1, bc2, _ = st.columns([1, 1, 3])
with bc1:
    all_json = json.dumps(filtered, indent=2)
    st.download_button(
        f"⬇ Export all {len(filtered)} as JSON",
        data=all_json,
        file_name="aurolab_protocols_export.json",
        mime="application/json",
        use_container_width=True)
with bc2:
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    try:
        from services.translation_service.core.eln_exporter import export_csv
        import io
        rows = []
        for p in filtered:
            for s in p.get("steps", []):
                rows.append({
                    "protocol_id": p.get("protocol_id","")[:8],
                    "title": p.get("title",""),
                    "step": s.get("step_number",""),
                    "instruction": s.get("instruction",""),
                    "volume_ul": s.get("volume_ul",""),
                    "citations": ";".join(s.get("citations",[])),
                })
        if rows:
            import csv
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=rows[0].keys())
            w.writeheader(); w.writerows(rows)
            st.download_button(
                f"⬇ Export all as CSV",
                data=buf.getvalue(),
                file_name="aurolab_protocols_export.csv",
                mime="text/csv",
                use_container_width=True)
    except ImportError:
        pass