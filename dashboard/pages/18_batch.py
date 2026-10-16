"""dashboard/pages/18_batch.py — Batch Protocol Generation"""
import json, sys, time
from pathlib import Path
import streamlit as st
import plotly.graph_objects as go

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'dashboard'))
from shared import inject_css, render_nav, hero, api_post, kpi_row, divider, section_label, badge, PLOTLY_DARK

st.set_page_config(page_title="Batch — AuroLab", page_icon="⚗", layout="wide",
                   initial_sidebar_state="collapsed")
inject_css()
render_nav("batch")

hero("BATCH GENERATION",
     "Generate N protocol variants from one instruction — auto-ranked by confidence, safety, and simulation",
     accent="#ffd33d", tag="Generate · Rank · Compare")

EXAMPLES = [
    "Perform a BCA protein assay on 8 samples using a 96-well plate at 562nm",
    "Run a standard PCR for a 500bp amplicon using Taq polymerase",
    "Prepare a Bradford assay standard curve from 0 to 1 mg/mL BSA",
]

left, right = st.columns([3, 2], gap="large")

with left:
    section_label("Instruction")
    ex = st.selectbox("Example", ["— type your own —"] + EXAMPLES, label_visibility="collapsed")
    default = "" if ex.startswith("—") else ex
    instruction = st.text_area("Instruction", value=default, height=100,
        placeholder="Describe the lab protocol...", label_visibility="collapsed")

    ca, cb = st.columns(2)
    with ca:
        n_variants = st.slider("Variants to generate", 2, 8, 4,
            help="Each variant uses a slightly different parameter set")
    with cb:
        sim_mode = st.selectbox("Simulation", ["mock", "pybullet"], label_visibility="collapsed")

    run_btn = st.button("⚡ Generate Batch", type="primary",
        disabled=len(instruction.strip()) < 10, use_container_width=True)

with right:
    section_label("How batch generation works")
    params = [
        ("#ffd33d", "Baseline",          "Standard parameters from instruction"),
        ("#00f0c8", "More samples",       "Increased sample count (+50%)"),
        ("#6c4cdc", "Higher temp",        "Elevated incubation temperature"),
        ("#f87171", "Extended time",      "Longer incubation (+50%)"),
        ("#00b8ff", "Reduced volumes",    "Cost optimisation — half volumes"),
        ("#4ade80", "Technical reps",     "3 technical replicates per sample"),
        ("#a89ef8", "Room temperature",   "22°C instead of 37°C"),
        ("#fb923c", "Minimal protocol",   "Minimum validated parameters"),
    ]
    for color, name, desc in params[:n_variants]:
        st.markdown(f"""
        <div style="display:flex;gap:10px;margin:7px 0;align-items:center;">
            <div style="width:8px;height:8px;border-radius:50%;background:{color};
                box-shadow:0 0 6px {color};flex-shrink:0;"></div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:0.68rem;
                color:#d0e4f0;min-width:130px;">{name}</div>
            <div style="font-size:0.72rem;color:rgba(160,185,205,0.4);">{desc}</div>
        </div>""", unsafe_allow_html=True)

    section_label("Ranking formula")
    st.markdown("""
    <div style="font-family:'JetBrains Mono',monospace;font-size:0.72rem;
        color:rgba(160,185,205,0.5);line-height:1.9;padding:8px 12px;
        background:rgba(0,240,200,0.02);border:1px solid rgba(0,240,200,0.08);border-radius:8px;">
        score = 0.40 × confidence<br>
              + 0.30 × safety_score<br>
              + 0.20 × sim_pass<br>
              + 0.10 × step_efficiency
    </div>""", unsafe_allow_html=True)

if run_btn and len(instruction.strip()) >= 10:
    result = api_post("/api/v1/batch/generate", json={
        "instruction": instruction.strip(),
        "n_variants":  n_variants,
        "sim_mode":    sim_mode,
        "run_sim":     True,
    })
    if result:
        st.session_state.batch_result = result
        # Add best variant to protocol history
        if result.get("variants"):
            best = result["variants"][0]
            if "protocol_history" not in st.session_state:
                st.session_state.protocol_history = []
            st.session_state.protocol_history.insert(0, best["protocol"])
        st.rerun()

divider()

result = st.session_state.get("batch_result")
if not result:
    st.markdown("""
    <div style="text-align:center;padding:4rem;color:rgba(160,185,205,0.35);">
        <div style="font-size:2.5rem;margin-bottom:1rem;">⚡</div>
        <div style="font-family:'JetBrains Mono',monospace;">Click Generate Batch to start</div>
        <div style="font-size:0.75rem;margin-top:6px;opacity:0.6;">Each call takes ~{n_variants * 3}s</div>
    </div>""", unsafe_allow_html=True)
    st.stop()

variants = result.get("variants", [])
n_ok = result.get("n_succeeded", len(variants))

kpi_row([
    (n_ok,                          "Generated",     "#00f0c8"),
    (f"{result.get('total_ms',0)/1000:.1f}s", "Total time", "#6c4cdc"),
    (f"{variants[0]['composite_score']:.3f}" if variants else "—",
     "Best score",  "#ffd33d"),
    (variants[0]['protocol'].get('title','')[:20] if variants else "—",
     "Top variant", "#4ade80"),
])
divider()

# ── Comparison chart ─────────────────────────────────────────────────────────
section_label("Score comparison")
COLORS = ["#ffd33d","#00f0c8","#6c4cdc","#f87171","#00b8ff","#4ade80","#a89ef8","#fb923c"]

fig = go.Figure()
labels = [f"#{v['rank']} {v['variation_desc'][:25]}" for v in variants]
scores = [v["composite_score"] for v in variants]
colors = [COLORS[i % len(COLORS)] for i in range(len(variants))]

fig.add_trace(go.Bar(
    x=labels, y=scores,
    marker_color=colors, marker_line_width=0,
    text=[f"{s:.3f}" for s in scores],
    textposition="outside",
    textfont=dict(color="rgba(160,185,205,0.7)", size=9, family="JetBrains Mono"),
))
fig.add_hline(y=0.8, line=dict(color="rgba(0,240,200,0.3)", width=1, dash="dot"),
    annotation_text="0.80 target", annotation_font_color="rgba(0,240,200,0.5)")
fig.update_layout(
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="JetBrains Mono, monospace", color="rgba(160,185,205,0.5)", size=10),
    xaxis=dict(gridcolor="rgba(0,240,200,0.04)", tickfont=dict(size=8)),
    yaxis=dict(gridcolor="rgba(0,240,200,0.04)", range=[0, 1.1]),
    margin=dict(l=8,r=8,t=36,b=8), height=280, showlegend=False,
    hoverlabel=dict(bgcolor="#0a1018", font=dict(family="JetBrains Mono, monospace", color="#d0e4f0")),
    title=dict(text="Composite score by variant (higher = better)",
               font=dict(color="rgba(160,185,205,0.5)", size=11)),
)
st.plotly_chart(fig, use_container_width=True)

divider()

# ── Variant cards ─────────────────────────────────────────────────────────────
section_label("Ranked variants")
for v in variants:
    rank     = v["rank"]
    score    = v["composite_score"]
    proto    = v["protocol"]
    sim      = v.get("sim_result")
    color    = COLORS[(rank-1) % len(COLORS)]
    is_best  = rank == 1
    bg       = "rgba(255,211,61,0.04)" if is_best else "rgba(0,240,200,0.015)"
    border   = "rgba(255,211,61,0.3)"  if is_best else "rgba(0,240,200,0.08)"

    passed   = sim.get("passed", False) if sim else None
    sim_icon = "✓" if passed else ("✗" if passed is False else "—")
    sim_col  = "#4ade80" if passed else ("#f87171" if passed is False else "#555568")

    with st.expander(
        f"#{rank}  {proto.get('title','?')}  ·  score:{score:.3f}  ·  sim:{sim_icon}",
        expanded=(rank == 1)
    ):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Confidence", f"{proto.get('confidence_score',0):.0%}")
        c2.metric("Steps",      len(proto.get("steps",[])))
        c3.metric("Safety",     proto.get("safety_level","safe").upper())
        c4.metric("Sim",        "PASS" if passed else ("FAIL" if passed is False else "N/A"))

        st.markdown(f"""
        <div style="font-family:'JetBrains Mono',monospace;font-size:0.68rem;
            color:rgba(160,185,205,0.4);padding:4px 0;">
            // {v.get('variation_desc','')}
        </div>""", unsafe_allow_html=True)

        # Show steps
        for step in proto.get("steps", [])[:3]:
            st.markdown(f"""
            <div style="padding:5px 0;border-bottom:1px solid rgba(0,240,200,0.05);
                font-size:0.8rem;color:#c0d8e8;">
                <span style="font-family:JetBrains Mono,monospace;color:#00f0c8;
                    font-size:0.62rem;">[{step['step_number']}]</span>
                {step.get('instruction','')}
            </div>""", unsafe_allow_html=True)
        if len(proto.get("steps",[])) > 3:
            st.markdown(f"<div style='font-size:0.7rem;color:rgba(160,185,205,0.3);padding-top:4px;'>... and {len(proto['steps'])-3} more steps</div>",
                        unsafe_allow_html=True)

        bc1, bc2, _ = st.columns([1, 1, 4])
        with bc1:
            if st.button("Use this variant", key=f"use_{v['variant_id'][:8]}", type="primary"):
                if "protocol_history" not in st.session_state:
                    st.session_state.protocol_history = []
                st.session_state.protocol_history.insert(0, proto)
                st.session_state.last_protocol = proto
                st.success("Saved to history — view on Generate page")
        with bc2:
            st.download_button("⬇ JSON", data=json.dumps(proto, indent=2),
                file_name=f"variant_{v['variant_id'][:8]}.json",
                mime="application/json", key=f"dl_{v['variant_id'][:8]}")