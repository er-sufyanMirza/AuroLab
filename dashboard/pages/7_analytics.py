"""dashboard/pages/7_analytics.py — Analytics & Sustainability"""

import sys
from pathlib import Path
import streamlit as st
import plotly.graph_objects as go

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'dashboard'))
from shared import inject_css, render_nav, hero, api_get, api_post, api_delete, kpi_row, kpi_card, page_header, divider, section_label, badge, stats_strip, neon_card, render_step_card, render_protocol_header, export_buttons, PLOTLY_DARK

st.set_page_config(page_title="Analytics — AuroLab", page_icon="⚗", layout="wide", initial_sidebar_state="collapsed")
inject_css()
render_nav("analytics")

def rating_badge(r):
    return f"<span class='rating-{r}'>{r}</span>"

page_header("Analytics & Sustainability",
    "Cost breakdown · environmental impact · ROI vs manual execution")
divider()

history = st.session_state.get("protocol_history",[])
if not history:
    st.info("Generate some protocols first, then return here to compute analytics.")
    st.stop()

ca, cb = st.columns([3, 1])
with ca:
    opts = {f"{p.get('title','?')} — {p.get('protocol_id','')[:8]}": p for p in history}
    sel  = st.selectbox("Protocol", list(opts.keys()), label_visibility="collapsed")
    prot = opts[sel]
    pid  = prot.get("protocol_id","")
with cb:
    if st.button("⟳ Compute", type="primary", use_container_width=True):
        with st.spinner("Computing..."):
            d = api_get(f"/api/v1/analytics/{pid}")
        if d: st.session_state[f"ana_{pid}"] = d

data = st.session_state.get(f"ana_{pid}")
if not data:
    st.markdown("""
    <div style="text-align:center;padding:4rem;color:#444458;">
        <div style="font-size:2rem;margin-bottom:1rem;">💰</div>
        <div style="font-family:'JetBrains Mono',monospace;">Select a protocol and click Compute</div>
    </div>""", unsafe_allow_html=True)
    st.stop()

divider()

cost_saved = data.get("cost_saved_usd",0)
time_saved = data.get("time_saved_min",0)
robot_cost = data.get("robot_cost_usd",0)
plastic_g  = data.get("plastic_g",0)
co2_g      = data.get("co2_g",0)
p_rating   = data.get("plastic_rating","?")
e_rating   = data.get("energy_rating","?")
annual     = data.get("annual_savings_usd_250runs",0)

kpi_row([
    (f"${cost_saved:.2f}",  "Cost saved vs manual", "#4ade80"),
    (f"{time_saved:.0f}m",  "Time saved",           "#4ade80"),
    (f"${robot_cost:.4f}",  "Robot execution cost", "#00f0c8"),
    (f"{plastic_g:.1f}g",   "Plastic waste",        "#ffd33d"),
    (f"{co2_g:.1f}g",       "CO₂ equivalent",       "#f87171"),
    (f"${annual:,.0f}",     "Annual saving (250×)", "#4ade80"),
])

left, right = st.columns([3, 2], gap="large")

with left:
    section_label("Cost breakdown")
    line_items = data.get("line_items",[])
    total_cost = sum(i.get("cost_usd",0) for i in line_items)
    for item in line_items:
        pct = (item.get("cost_usd",0)/total_cost*100) if total_cost else 0
        bar_w = max(1, int(pct*2.2))
        st.markdown(f"""
        <div class="line-row">
            <div class="line-category">{item.get('category','?')}</div>
            <div style="flex:1;margin:0 12px;">
                <div style="background:rgba(124,106,247,0.08);border-radius:2px;height:4px;width:100%;overflow:hidden;">
                    <div style="background:#7c6af7;height:100%;width:{pct:.0f}%;border-radius:2px;"></div>
                </div>
            </div>
            <div class="line-qty">{item.get('quantity','')} {item.get('unit','')}</div>
            <div class="line-cost">${item.get('cost_usd',0):.4f}</div>
        </div>""", unsafe_allow_html=True)
    if line_items:
        st.markdown(f"""
        <div style="display:flex;justify-content:flex-end;padding:10px 0;border-top:1px solid rgba(255,255,255,0.08);margin-top:4px;">
            <span style="font-family:'JetBrains Mono',monospace;font-size:0.85rem;font-weight:600;color:#e2e2ea;">Total: ${total_cost:.4f}</span>
        </div>""", unsafe_allow_html=True)

    # Donut chart
    if line_items:
        st.markdown("<br>", unsafe_allow_html=True)
        section_label("Cost composition")
        labels = [i.get("category","?") for i in line_items]
        values = [i.get("cost_usd",0) for i in line_items]
        colors = ["#7c6af7","#4ade80","#60a5fa","#fbbf24","#f87171","#a78bfa"]
        fig = go.Figure(go.Pie(labels=labels, values=values, hole=0.6,
            marker=dict(colors=colors[:len(labels)], line=dict(color="#070709", width=2)),
            textfont=dict(size=9, color="#888898"), showlegend=True))
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="JetBrains Mono, monospace", color="rgba(160,185,205,0.5)", size=10),
            legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="rgba(160,185,205,0.6)", size=9), orientation="h", y=-0.15),
            margin=dict(l=8, r=8, t=36, b=8),
            hoverlabel=dict(bgcolor="#0a1018", bordercolor="rgba(0,240,200,0.3)", font=dict(family="JetBrains Mono, monospace", color="#d0e4f0")),
            height=240,
        )
        st.plotly_chart(fig, use_container_width=True)

with right:
    section_label("Sustainability")
    st.markdown(f"""
    <div style="display:flex;gap:24px;margin-bottom:1.2rem;">
        <div>
            <div style="font-size:0.68rem;color:#555568;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px;">Plastic</div>
            {rating_badge(p_rating)}
        </div>
        <div>
            <div style="font-size:0.68rem;color:#555568;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px;">Energy</div>
            {rating_badge(e_rating)}
        </div>
    </div>""", unsafe_allow_html=True)

    for label, val, color in [
        ("Tip plastic",  f"{data.get('tip_plastic_g',plastic_g):.2f} g", "#fbbf24"),
        ("Total plastic",f"{plastic_g:.2f} g",                           "#fb923c"),
        ("Energy",       f"{data.get('energy_kwh',0)*1000:.2f} Wh",      "#60a5fa"),
        ("CO₂",          f"{co2_g:.2f} g",                               "#f87171"),
    ]:
        st.markdown(f"""
        <div class="health-row">
            <div class="health-label">{label}</div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:0.82rem;color:{color};">{val}</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    section_label("ROI vs manual")
    robot_d  = data.get("robot_duration_min",0)
    manual_d = data.get("manual_duration_min",0)
    manual_c = data.get("manual_cost_usd",0)
    speedup  = manual_d/max(robot_d,0.001)

    for label, val, color in [
        ("Robot time",   f"{robot_d:.1f} min",  "#7c6af7"),
        ("Manual time",  f"{manual_d:.1f} min",  "#555568"),
        ("Robot cost",   f"${robot_cost:.4f}",   "#7c6af7"),
        ("Manual cost",  f"${manual_c:.4f}",     "#555568"),
        ("Speedup",      f"{speedup:.1f}×",      "#4ade80"),
        ("Annual saving",f"${annual:,.0f}",      "#4ade80"),
    ]:
        st.markdown(f"""
        <div class="health-row">
            <div class="health-label">{label}</div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:0.82rem;color:{color};">{val}</div>
        </div>""", unsafe_allow_html=True)

    # Bar comparison
    st.markdown("<br>", unsafe_allow_html=True)
    section_label("Time comparison")
    fig2 = go.Figure()
    fig2.add_trace(go.Bar(name="Robot", x=["Duration (min)"], y=[robot_d], marker_color="#7c6af7"))
    fig2.add_trace(go.Bar(name="Manual", x=["Duration (min)"], y=[manual_d], marker_color="#333345"))
    fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(family="JetBrains Mono, monospace", color="rgba(160,185,205,0.5)", size=10), legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="rgba(160,185,205,0.6)", size=10)), margin=dict(l=8, r=8, t=36, b=8), hoverlabel=dict(bgcolor="#0a1018", bordercolor="rgba(0,240,200,0.3)", font=dict(family="JetBrains Mono, monospace", color="#d0e4f0")), height=200, barmode="group",
        title=dict(text="Robot vs manual execution time", font=dict(color="#555568",size=11)))
    st.plotly_chart(fig2, use_container_width=True)

divider()
section_label("Session aggregate")
agg = api_get("/api/v1/analytics/", silent=True)
if agg and agg.get("total_protocols",0) > 0:
    kpi_row([
        (agg["total_protocols"],                              "Protocols analysed", "#00f0c8"),
        (f"${agg.get('total_cost_saved_usd',0):.2f}",         "Total cost saved",  "#4ade80"),
        (f"{agg.get('total_plastic_g',0):.1f}g",              "Total plastic",     "#ffd33d"),
        (f"${agg.get('annual_savings_usd',0):,.0f}",          "Annual saving",     "#4ade80"),
    ])
    st.markdown("<span style='font-size:0.82rem;color:#555568;'>Run analytics on multiple protocols to see session aggregate.</span>", unsafe_allow_html=True)