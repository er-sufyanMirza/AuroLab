"""dashboard/pages/17_optimize.py — Multi-Objective Protocol Optimiser"""
import sys
from pathlib import Path
import streamlit as st
import plotly.graph_objects as go

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'dashboard'))
from shared import inject_css, render_nav, hero, api_get, kpi_row, divider, section_label, badge, PLOTLY_DARK

st.set_page_config(page_title="Optimise — AuroLab", page_icon="⚗", layout="wide",
                   initial_sidebar_state="collapsed")
inject_css()
render_nav("optimize")

hero("PROTOCOL OPTIMISER",
     "Generate 3 alternative protocol variants optimised for speed, cost, and sustainability — compare trade-offs",
     accent="#f87171", tag="Speed · Cost · Green · Trade-off")

history = st.session_state.get("protocol_history", [])
if not history:
    st.info("Generate a protocol first, then return here to create optimised variants.")
    st.stop()

opts = {f"{p.get('title','?')} — {p.get('protocol_id','')[:8]}": p for p in history}
sel = st.selectbox("Base protocol to optimise", list(opts.keys()), label_visibility="collapsed")
protocol = opts[sel]

st.markdown(f"""
<div style="background:rgba(248,113,113,0.05);border:1px solid rgba(248,113,113,0.15);
    border-radius:10px;padding:10px 16px;margin:0.5rem 0 1rem;font-size:0.82rem;color:rgba(208,228,240,0.7);">
    ⚡ This calls the LLM 3 times (once per objective). Takes ~15-30 seconds.
    Requires the backend to be running.
</div>""", unsafe_allow_html=True)

run_btn = st.button("⚡ Generate 3 Optimised Variants", type="primary")

if run_btn:
    result = api_get(f"/api/v1/optimise/{protocol.get('protocol_id','')}")
    if result:
        st.session_state.optimise_result = result
        st.rerun()
    else:
        # Client-side heuristic fallback when API not available
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))
        try:
            from services.translation_service.core.protocol_optimizer import ProtocolOptimiser, _estimate_time, _estimate_cost, _estimate_plastic
            # Show heuristic estimates without LLM
            orig_time    = _estimate_time(protocol)
            orig_cost    = _estimate_cost(protocol)
            orig_plastic = _estimate_plastic(protocol)
            st.session_state.optimise_result = {
                "original_protocol_id": protocol.get("protocol_id",""),
                "variants": [
                    {"objective":"speed",  "success":False, "error":"API offline",
                     "estimated_time_min": orig_time*0.72, "estimated_cost_usd":orig_cost*1.05,
                     "estimated_plastic_g":orig_plastic*1.1,
                     "optimisation_notes":"Run backend to generate real LLM variant"},
                    {"objective":"cost",   "success":False, "error":"API offline",
                     "estimated_time_min": orig_time*1.1,  "estimated_cost_usd":orig_cost*0.65,
                     "estimated_plastic_g":orig_plastic*0.9,
                     "optimisation_notes":"Run backend to generate real LLM variant"},
                    {"objective":"green",  "success":False, "error":"API offline",
                     "estimated_time_min": orig_time*1.05, "estimated_cost_usd":orig_cost*0.95,
                     "estimated_plastic_g":orig_plastic*0.55,
                     "optimisation_notes":"Run backend to generate real LLM variant"},
                ],
                "tradeoff_analysis": "Backend offline — showing heuristic estimates only.",
                "total_ms": 0,
            }
            st.session_state.optimise_original = {
                "time": orig_time, "cost": orig_cost, "plastic": orig_plastic
            }
            st.rerun()
        except ImportError:
            st.error("Backend offline and optimizer module not found locally.")

divider()

result = st.session_state.get("optimise_result")
if not result:
    st.markdown("""
    <div style="text-align:center;padding:3rem;color:rgba(160,185,205,0.35);">
        <div style="font-size:2rem;margin-bottom:0.8rem;">⚡</div>
        <div style="font-family:'JetBrains Mono',monospace;">Click Generate to create optimised variants</div>
    </div>""", unsafe_allow_html=True)
    st.stop()

variants = result.get("variants", [])
OBJ_COLORS = {"speed":"#00b8ff","cost":"#4ade80","green":"#00f0c8"}
OBJ_ICONS  = {"speed":"⚡","cost":"💰","green":"🌿"}

orig = st.session_state.get("optimise_original", {})
orig_time    = orig.get("time",    result.get("orig_time_min",    60))
orig_cost    = orig.get("cost",    result.get("orig_cost_usd",    0.1))
orig_plastic = orig.get("plastic", result.get("orig_plastic_g",   0.5))

# ── KPI comparison ──────────────────────────────────────────────────────────
section_label("Variant comparison")
v_cols = st.columns(3, gap="large")
for col, v in zip(v_cols, variants):
    obj   = v.get("objective","?")
    color = OBJ_COLORS.get(obj,"#888898")
    icon  = OBJ_ICONS.get(obj,"")
    t     = v.get("estimated_time_min",0)
    c     = v.get("estimated_cost_usd",0)
    p     = v.get("estimated_plastic_g",0)
    ok    = v.get("success", True)

    def delta_str(val, orig_val, lower_is_better=True):
        if not orig_val: return ""
        pct = (val - orig_val) / orig_val * 100
        better = pct < 0 if lower_is_better else pct > 0
        sign = "↓" if pct < 0 else "↑"
        col_str = "#4ade80" if better else "#f87171"
        return f'<span style="color:{col_str};font-size:0.7rem;margin-left:6px;">{sign}{abs(pct):.0f}%</span>'

    col.markdown(f"""
    <div style="background:rgba(0,240,200,0.02);border:1px solid {color}33;
        border-top:3px solid {color};border-radius:0 0 12px 12px;padding:1.2rem;
        {'opacity:0.6;' if not ok else ''}">
        <div style="font-family:'Orbitron',monospace;font-size:0.8rem;font-weight:700;
            color:{color};margin-bottom:12px;">{icon} {obj.upper()}</div>
        <div style="margin-bottom:8px;">
            <div style="font-family:'JetBrains Mono',monospace;font-size:0.62rem;
                color:rgba(160,185,205,0.4);margin-bottom:2px;">TIME</div>
            <div style="font-family:'Orbitron',monospace;font-size:1.1rem;color:#e8f4ff;">
                {t:.0f}min {delta_str(t,orig_time)}
            </div>
        </div>
        <div style="margin-bottom:8px;">
            <div style="font-family:'JetBrains Mono',monospace;font-size:0.62rem;
                color:rgba(160,185,205,0.4);margin-bottom:2px;">COST</div>
            <div style="font-family:'Orbitron',monospace;font-size:1.1rem;color:#e8f4ff;">
                ${c:.4f} {delta_str(c,orig_cost)}
            </div>
        </div>
        <div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:0.62rem;
                color:rgba(160,185,205,0.4);margin-bottom:2px;">PLASTIC</div>
            <div style="font-family:'Orbitron',monospace;font-size:1.1rem;color:#e8f4ff;">
                {p:.2f}g {delta_str(p,orig_plastic)}
            </div>
        </div>
        {f'<div style="font-size:0.72rem;color:#ffd33d;margin-top:8px;">⚠ Heuristic estimate</div>' if not ok else ''}
    </div>""", unsafe_allow_html=True)

divider()

# ── Radar chart ─────────────────────────────────────────────────────────────
section_label("Trade-off radar")
categories = ["Speed", "Cost efficiency", "Sustainability", "Confidence"]
fig = go.Figure()
for v in variants:
    obj   = v.get("objective","?")
    color = OBJ_COLORS.get(obj,"#888898")
    t     = v.get("estimated_time_min",60)
    c     = v.get("estimated_cost_usd",0.1)
    p     = v.get("estimated_plastic_g",0.5)
    conf  = v.get("protocol",{}).get("confidence_score",0.75) if v.get("success") else 0.5

    speed_score = max(0, min(1, (orig_time - t) / max(orig_time,1) + 0.7))
    cost_score  = max(0, min(1, (orig_cost  - c) / max(orig_cost,1) + 0.7))
    green_score = max(0, min(1, (orig_plastic - p) / max(orig_plastic,1) + 0.7))

    fig.add_trace(go.Scatterpolar(
        r=[speed_score, cost_score, green_score, conf],
        theta=categories,
        fill="toself",
        fillcolor=f"{color}22",
        line=dict(color=color, width=2),
        name=obj.upper(),
    ))

fig.update_layout(
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="JetBrains Mono, monospace", color="rgba(160,185,205,0.5)", size=10),
    polar=dict(
        bgcolor="rgba(0,240,200,0.02)",
        angularaxis=dict(tickfont=dict(color="rgba(160,185,205,0.6)", size=10),
                         linecolor="rgba(0,240,200,0.1)", gridcolor="rgba(0,240,200,0.06)"),
        radialaxis=dict(tickfont=dict(color="rgba(160,185,205,0.3)", size=9),
                        linecolor="rgba(0,240,200,0.06)", gridcolor="rgba(0,240,200,0.06)",
                        range=[0,1]),
    ),
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="rgba(160,185,205,0.6)")),
    margin=dict(l=40, r=40, t=40, b=40), height=360,
    hoverlabel=dict(bgcolor="#0a1018", font=dict(family="JetBrains Mono, monospace", color="#d0e4f0")),
)
st.plotly_chart(fig, use_container_width=True)

# ── Trade-off text ───────────────────────────────────────────────────────────
tradeoff = result.get("tradeoff_analysis","")
if tradeoff:
    divider()
    section_label("Analysis")
    for line in tradeoff.split("\n"):
        color = "#00f0c8" if "SPEED" in line else ("#4ade80" if "COST" in line else ("#00b8ff" if "GREEN" in line else "rgba(160,185,205,0.6)"))
        st.markdown(f"<div style='font-family:JetBrains Mono,monospace;font-size:0.78rem;color:{color};padding:2px 0;'>{line}</div>",
                    unsafe_allow_html=True)

# ── Save variant to history ──────────────────────────────────────────────────
divider()
section_label("Save variant to history")
v_opts = {f"{OBJ_ICONS.get(v['objective'],'')} {v['objective'].upper()} variant": v
          for v in variants if v.get("success") and v.get("protocol")}
if v_opts:
    sel_v = st.selectbox("Select variant", list(v_opts.keys()), label_visibility="collapsed")
    if st.button("Save to protocol history", use_container_width=False):
        chosen = v_opts[sel_v]
        if "protocol_history" not in st.session_state:
            st.session_state.protocol_history = []
        st.session_state.protocol_history.insert(0, chosen["protocol"])
        st.success(f"Saved: {chosen['protocol'].get('title','')}")
else:
    st.markdown("<span style='font-size:0.8rem;color:rgba(160,185,205,0.35);'>No successful variants to save (run backend for real LLM variants)</span>",
                unsafe_allow_html=True)