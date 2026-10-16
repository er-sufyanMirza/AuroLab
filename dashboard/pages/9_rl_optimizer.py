"""dashboard/pages/9_rl_optimiser.py — RL Optimiser"""
import sys
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'dashboard'))
from shared import (inject_css, render_nav, hero, api_get, api_post,
                    kpi_row, divider, section_label, badge, PLOTLY_DARK)

st.set_page_config(page_title="RL Optimiser — AuroLab", page_icon="⚗",
                   layout="wide", initial_sidebar_state="collapsed")
inject_css()
render_nav("rl")

hero("RL OPTIMISER",
     "Q-learning agent optimises protocol parameters across execution runs — reward trend, suggestions, Q-table",
     accent="#a89ef8", tag="Q-learning · Reward · Parameters · Convergence")

history = st.session_state.get("protocol_history", [])
if not history:
    st.info("Generate and simulate a protocol first, then return here.")
    st.stop()

opts = {f"{p.get('title','?')} — {p.get('protocol_id','')[:8]}": p
        for p in history}
sel = st.selectbox("Protocol", list(opts.keys()), label_visibility="collapsed")
proto   = opts[sel]
pid     = proto.get("protocol_id", "")

# ── Fetch RL data ─────────────────────────────────────────────────────────────
overview   = api_get("/api/v1/rl/overview",         silent=True) or {}
stats      = api_get(f"/api/v1/rl/stats/{pid}",     silent=True) or {}
trend      = api_get(f"/api/v1/rl/trend/{pid}",     silent=True) or {}
telemetry  = api_get(f"/api/v1/rl/telemetry/{pid}", silent=True) or {}
suggestions= api_get(f"/api/v1/rl/suggestions/{pid}",silent=True) or {}

runs = telemetry.get("runs", [])
rewards = [r.get("reward", r.get("computed_reward", 0)) for r in runs]
passed  = [r.get("passed", False) for r in runs]

kpi_row([
    (len(runs),                                      "Execution runs",   "#a89ef8"),
    (f"{sum(1 for p in passed if p)}/{max(len(passed),1)}", "Passed",   "#4ade80"),
    (f"{(sum(rewards)/max(len(rewards),1)):.3f}",    "Avg reward",       "#00f0c8"),
    (f"{max(rewards):.3f}" if rewards else "—",      "Best reward",      "#ffd33d"),
])
divider()

left, right = st.columns([3, 2], gap="large")

with left:
    section_label("Reward trend")
    if rewards:
        # Moving average
        window = min(5, len(rewards))
        ma = [sum(rewards[max(0,i-window+1):i+1]) / min(i+1, window)
              for i in range(len(rewards))]

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=list(range(1, len(rewards)+1)), y=rewards,
            mode="markers+lines",
            marker=dict(
                color=["#4ade80" if p else "#f87171" for p in passed],
                size=8, symbol=["circle" if p else "x" for p in passed]),
            line=dict(color="rgba(168,158,248,0.3)", width=1),
            name="Reward", hovertemplate="Run %{x}: %{y:.3f}<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=list(range(1, len(ma)+1)), y=ma,
            mode="lines",
            line=dict(color="#a89ef8", width=2),
            name=f"MA({window})",
            hovertemplate="MA: %{y:.3f}<extra></extra>",
        ))
        fig.add_hline(y=0.8, line=dict(color="rgba(0,240,200,0.25)", width=1, dash="dot"),
                      annotation_text="Target 0.80",
                      annotation_font_color="rgba(0,240,200,0.5)")
        fig.update_layout(
            **PLOTLY_DARK,
            xaxis=dict(title="Run #", gridcolor="rgba(0,240,200,0.04)"),
            yaxis=dict(title="Reward", range=[0,1.05], gridcolor="rgba(0,240,200,0.04)"),
            height=300, margin=dict(l=8,r=8,t=32,b=8),
            legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="rgba(160,185,205,0.5)")),
            title=dict(text="Reward per run (● pass  ✗ fail)",
                       font=dict(color="rgba(160,185,205,0.45)", size=11)),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.markdown("""
        <div style="text-align:center;padding:3rem;color:rgba(160,185,205,0.35);">
            <div style="font-size:1.8rem;margin-bottom:0.8rem;">📊</div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:0.75rem;">
                No runs yet — simulate a protocol to start collecting telemetry
            </div>
        </div>""", unsafe_allow_html=True)

    # Reward component breakdown (last run)
    if runs:
        divider()
        section_label("Reward breakdown — last run")
        last = runs[-1]
        components = [
            ("Speed",    last.get("speed_score",    last.get("reward_speed",    0)), "#00b8ff", 0.30),
            ("Accuracy", last.get("accuracy_score", last.get("reward_accuracy", 0)), "#4ade80", 0.35),
            ("Waste",    last.get("waste_score",    last.get("reward_waste",    0)), "#00f0c8", 0.20),
            ("Safety",   last.get("safety_score",   last.get("reward_safety",   0)), "#ffd33d", 0.15),
        ]
        for name, val, color, weight in components:
            pct = int(val * 100)
            st.markdown(f"""
            <div style="display:flex;align-items:center;gap:12px;padding:6px 0;
                border-bottom:1px solid rgba(0,240,200,0.04);">
                <span style="font-family:'JetBrains Mono',monospace;font-size:0.7rem;
                    color:{color};min-width:70px;">{name}</span>
                <div style="flex:1;background:rgba(255,255,255,0.04);border-radius:2px;
                    height:6px;overflow:hidden;">
                    <div style="background:{color};height:100%;width:{pct}%;
                        box-shadow:0 0 6px {color};transition:width 0.4s;"></div>
                </div>
                <span style="font-family:'Orbitron',monospace;font-size:0.7rem;
                    color:{color};min-width:40px;text-align:right;">{val:.3f}</span>
                <span style="font-family:'JetBrains Mono',monospace;font-size:0.6rem;
                    color:rgba(160,185,205,0.25);min-width:40px;">×{weight}</span>
            </div>""", unsafe_allow_html=True)

with right:
    section_label("Q-agent info")
    q_info = stats.get("q_agent", stats.get("agent", {}))
    agent_items = [
        ("Protocol ID",    pid[:8]),
        ("Epsilon",        f"{q_info.get('epsilon', 0.15):.3f}"),
        ("Q-states",       q_info.get("q_states", "—")),
        ("Total runs",     len(runs)),
        ("Success rate",   f"{sum(1 for p in passed if p)/max(len(passed),1):.0%}"),
        ("Best reward",    f"{max(rewards):.3f}" if rewards else "—"),
        ("Reward formula", "0.30×speed + 0.35×accuracy"),
        ("",               "0.20×waste + 0.15×safety"),
    ]
    for k, v in agent_items:
        if not k:
            st.markdown(f"<div style='font-family:JetBrains Mono,monospace;"
                        f"font-size:0.7rem;color:rgba(160,185,205,0.25);"
                        f"padding-left:80px;'>{v}</div>", unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div style="display:flex;justify-content:space-between;padding:5px 0;
                border-bottom:1px solid rgba(0,240,200,0.05);">
                <span style="font-size:0.75rem;color:rgba(160,185,205,0.35);">{k}</span>
                <span style="font-family:'JetBrains Mono',monospace;font-size:0.72rem;
                    color:#a89ef8;">{v}</span>
            </div>""", unsafe_allow_html=True)

    # Suggestions
    divider()
    section_label("Parameter suggestions")
    sugg_list = suggestions.get("suggestions", [])
    if sugg_list:
        for s in sugg_list[:5]:
            param  = s.get("parameter", "?")
            curr   = s.get("current_value", "?")
            sugg   = s.get("suggested_value", "?")
            imp    = s.get("expected_improvement", 0)
            conf   = s.get("confidence", 0)
            col_c  = "#4ade80" if imp > 0 else "#f87171"
            with st.expander(f"📈 {param}: {curr} → {sugg}"):
                st.markdown(f"""
                <div style="font-family:'JetBrains Mono',monospace;font-size:0.7rem;
                    color:rgba(160,185,205,0.5);line-height:1.8;">
                    Expected improvement: <span style="color:{col_c}">+{imp:.1%}</span><br>
                    Confidence: <span style="color:#a89ef8">{conf:.0%}</span>
                </div>""", unsafe_allow_html=True)
                ac, rc = st.columns(2)
                with ac:
                    if st.button("✓ Accept", key=f"acc_{s.get('suggestion_id','x')[:6]}",
                                 type="primary", use_container_width=True):
                        api_post(f"/api/v1/rl/suggestions/{s.get('suggestion_id','')}/accept",
                                 silent=True)
                        st.success("Accepted"); st.rerun()
                with rc:
                    if st.button("✗ Reject", key=f"rej_{s.get('suggestion_id','x')[:6]}",
                                 use_container_width=True):
                        api_post(f"/api/v1/rl/suggestions/{s.get('suggestion_id','')}/reject",
                                 silent=True)
                        st.rerun()
    else:
        st.markdown("<div style='font-size:0.78rem;color:rgba(160,185,205,0.3);"
                    "font-family:JetBrains Mono,monospace;'>"
                    f"No suggestions yet — need {max(0, 10-len(runs))} more runs to generate</div>",
                    unsafe_allow_html=True)

    # Trigger optimise
    divider()
    if st.button("⚡ Generate suggestions now", use_container_width=True):
        r = api_post(f"/api/v1/rl/optimise/{pid}", silent=True)
        if r:
            st.success(f"Generated {r.get('count',0)} suggestions")
            st.rerun()
        else:
            st.info("Backend offline — start uvicorn first")