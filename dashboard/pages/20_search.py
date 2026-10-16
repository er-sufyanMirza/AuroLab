"""dashboard/pages/20_search.py — Semantic Protocol Search"""
import sys
from pathlib import Path
import streamlit as st
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'dashboard'))
from shared import inject_css, render_nav, hero, api_get, kpi_row, divider, section_label, badge

st.set_page_config(page_title="Search — AuroLab", page_icon="⚗", layout="wide", initial_sidebar_state="collapsed")
inject_css(); render_nav("search")
hero("PROTOCOL SEARCH", "Semantic search across all generated protocols — find by keyword, reagent, or technique", accent="#00b8ff", tag="Search · Filter · Discover")

ca, cb, cc = st.columns([4,1,1])
with ca: q = st.text_input("Search", placeholder="BCA protein assay, PCR, 37°C incubation...", label_visibility="collapsed")
with cb: safety_f = st.selectbox("Safety", ["All","safe","warning","blocked"], label_visibility="collapsed")
with cc: limit = st.selectbox("Results", [10,25,50], label_visibility="collapsed")

if q and len(q.strip()) >= 2:
    params = {"q": q.strip(), "limit": limit}
    if safety_f != "All": params["safety"] = safety_f
    results = api_get(f"/api/v1/search?q={q.strip()}&limit={limit}" + (f"&safety={safety_f}" if safety_f!="All" else ""), silent=True)

    if results:
        total = results.get("total", 0)
        hits  = results.get("results", [])
        kpi_row([(total, "Matches", "#00b8ff"), (len(hits), "Shown", "#00f0c8"),
                 (f"{hits[0]['relevance_score']:.3f}" if hits else "—", "Top score", "#ffd33d")])
        divider()
        if not hits:
            st.markdown("<div style='text-align:center;padding:3rem;color:rgba(160,185,205,0.4);font-family:JetBrains Mono,monospace;'>No protocols match your query</div>", unsafe_allow_html=True)
        else:
            section_label(f"Results for \"{q}\"")
            for r in hits:
                score = r.get("relevance_score", 0)
                safety = r.get("safety_level","safe")
                bar = int(min(score / 2.0, 1.0) * 100)
                st.markdown(f"""
                <div style="background:rgba(0,184,255,0.02);border:1px solid rgba(0,184,255,0.1);
                    border-left:2px solid #00b8ff;border-radius:0 10px 10px 0;padding:0.9rem 1.1rem;margin:6px 0;">
                    <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">
                        <div style="font-family:'Orbitron',monospace;font-size:0.8rem;font-weight:700;color:#e8f4ff;flex:1;">{r.get('title','?')}</div>
                        {badge(safety.upper(), safety)}
                        <span style="font-family:'JetBrains Mono',monospace;font-size:0.65rem;color:#00b8ff;">{score:.3f}</span>
                    </div>
                    <div style="font-size:0.78rem;color:rgba(160,185,205,0.5);margin-bottom:6px;">{r.get('description','')[:120]}</div>
                    <div style="display:flex;gap:14px;font-family:'JetBrains Mono',monospace;font-size:0.62rem;color:rgba(160,185,205,0.35);">
                        <span>{r.get('steps',0)} steps</span>
                        <span>{r.get('confidence',0):.0%} confidence</span>
                        <span style="font-family:'JetBrains Mono',monospace;font-size:0.58rem;color:rgba(160,185,205,0.2);">ID:{r.get('protocol_id','')[:8]}</span>
                    </div>
                    <div style="background:rgba(255,255,255,0.04);border-radius:2px;height:3px;margin-top:8px;overflow:hidden;">
                        <div style="background:#00b8ff;height:100%;width:{bar}%;box-shadow:0 0 6px #00b8ff;"></div>
                    </div>
                </div>""", unsafe_allow_html=True)
                if st.button("Load →", key=f"load_{r.get('protocol_id','')[:8]}", use_container_width=False):
                    detail = api_get(f"/api/v1/protocols/{r.get('protocol_id','')}", silent=True)
                    if detail:
                        if "protocol_history" not in st.session_state: st.session_state.protocol_history = []
                        st.session_state.protocol_history.insert(0, detail)
                        st.session_state.last_protocol = detail
                        st.success("Loaded — view on Generate page")
    else:
        st.info("Backend offline or no results — start uvicorn first")
else:
    history = st.session_state.get("protocol_history", [])
    kpi_row([(len(history),"Local protocols","#00f0c8"),(0,"API results","#00b8ff")])
    if history:
        divider(); section_label("Recent protocols (local)")
        for p in history[:8]:
            safety = p.get("safety_level","safe")
            st.markdown(f"""
            <div style="display:flex;align-items:center;gap:10px;padding:8px 12px;
                background:rgba(0,240,200,0.015);border:1px solid rgba(0,240,200,0.07);border-radius:8px;margin:4px 0;">
                <div style="flex:1;font-size:0.85rem;color:#d0e4f0;">{p.get('title','?')}</div>
                <span style="font-family:'JetBrains Mono',monospace;font-size:0.68rem;color:rgba(160,185,205,0.35);">{p.get('confidence_score',0):.0%}</span>
                {badge(safety.upper(), safety)}
            </div>""", unsafe_allow_html=True)