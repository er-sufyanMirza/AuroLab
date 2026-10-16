"""dashboard/pages/11_compare.py — Protocol Compare & Diff"""
import sys
from pathlib import Path
import streamlit as st
import plotly.graph_objects as go

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'dashboard'))
from shared import inject_css, render_nav, hero, api_get, kpi_row, divider, section_label, badge

st.set_page_config(page_title="Compare — AuroLab", page_icon="⚗", layout="wide",
                   initial_sidebar_state="collapsed")
inject_css()
render_nav("compare")

hero("PROTOCOL COMPARE",
     "Side-by-side comparison and diff of any two generated protocols",
     accent="#00b8ff", tag="Diff · Delta · Recommendation")

history = st.session_state.get("protocol_history", [])
if len(history) < 2:
    st.markdown("""
    <div style="text-align:center;padding:4rem;color:rgba(160,185,205,0.4);">
        <div style="font-size:2rem;margin-bottom:1rem;">⚖</div>
        <div style="font-family:'JetBrains Mono',monospace;font-size:0.85rem;">Need at least 2 protocols to compare</div>
        <div style="font-size:0.78rem;margin-top:6px;opacity:0.6;">Generate two protocols and return here</div>
    </div>""", unsafe_allow_html=True)
    st.stop()

opts = {f"{p.get('title','?')} — {p.get('protocol_id','')[:8]}": p for p in history}
labels = list(opts.keys())

ca, cb = st.columns(2, gap="large")
with ca:
    section_label("Protocol A")
    sel_a = st.selectbox("A", labels, index=0, label_visibility="collapsed")
with cb:
    section_label("Protocol B")
    sel_b = st.selectbox("B", labels, index=min(1, len(labels)-1), label_visibility="collapsed")

if sel_a == sel_b:
    st.warning("Select two different protocols to compare.")
    st.stop()

pa = opts[sel_a]
pb = opts[sel_b]

# Compute diff
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from services.translation_service.core.protocol_diff import diff_protocols

diff = diff_protocols(pa, pb)

divider()

# ── Recommendation banner ────────────────────────────────────────────────────
rec = diff.recommendation
rec_color = "#00f0c8" if "A preferred" in rec else ("#6c4cdc" if "B preferred" in rec else "#ffd33d")
st.markdown(f"""
<div style="background:rgba(0,184,255,0.06);border:1px solid rgba(0,184,255,0.2);
    border-radius:10px;padding:12px 16px;margin-bottom:1.5rem;">
    <span style="font-family:'JetBrains Mono',monospace;font-size:0.72rem;
        color:#00b8ff;letter-spacing:0.08em;">// RECOMMENDATION</span><br>
    <span style="font-size:0.88rem;color:#d0e4f0;">{rec}</span>
</div>""", unsafe_allow_html=True)

# ── Similarity score ──────────────────────────────────────────────────────────
sim_pct = int(diff.similarity_score * 100)
sim_color = "#4ade80" if sim_pct > 70 else ("#ffd33d" if sim_pct > 40 else "#f87171")
st.markdown(f"""
<div style="display:flex;align-items:center;gap:16px;margin-bottom:1.5rem;">
    <div style="font-family:'JetBrains Mono',monospace;font-size:0.65rem;
        color:rgba(160,185,205,0.4);letter-spacing:0.1em;text-transform:uppercase;">Similarity</div>
    <div style="flex:1;background:rgba(255,255,255,0.05);border-radius:2px;height:6px;overflow:hidden;">
        <div style="background:{sim_color};height:100%;width:{sim_pct}%;box-shadow:0 0 8px {sim_color};transition:width 0.6s;"></div>
    </div>
    <div style="font-family:'Orbitron',monospace;font-size:1rem;font-weight:700;
        color:{sim_color};text-shadow:0 0 10px {sim_color};">{sim_pct}%</div>
</div>""", unsafe_allow_html=True)

# ── KPI comparison grid ───────────────────────────────────────────────────────
section_label("Delta metrics")
col1, col2, col3 = st.columns(3, gap="large")

def delta_card(label, val_a, val_b, fmt=str, color_a="#00f0c8", color_b="#6c4cdc"):
    a_str = fmt(val_a) if callable(fmt) else f"{val_a:{fmt}}"
    b_str = fmt(val_b) if callable(fmt) else f"{val_b:{fmt}}"
    st.markdown(f"""
    <div style="background:rgba(0,240,200,0.02);border:1px solid rgba(0,240,200,0.08);
        border-radius:10px;padding:0.9rem 1.1rem;margin:4px 0;">
        <div style="font-family:'JetBrains Mono',monospace;font-size:0.58rem;
            color:rgba(160,185,205,0.35);text-transform:uppercase;letter-spacing:0.12em;margin-bottom:6px;">{label}</div>
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <div style="font-family:'Orbitron',monospace;font-size:1.2rem;font-weight:600;color:{color_a};">{a_str}</div>
            <div style="font-size:0.65rem;color:rgba(160,185,205,0.25);">vs</div>
            <div style="font-family:'Orbitron',monospace;font-size:1.2rem;font-weight:600;color:{color_b};">{b_str}</div>
        </div>
        <div style="display:flex;justify-content:space-between;font-size:0.6rem;color:rgba(160,185,205,0.3);margin-top:3px;">
            <span>Protocol A</span><span>Protocol B</span>
        </div>
    </div>""", unsafe_allow_html=True)

with col1:
    delta_card("Steps", diff.step_count_a, diff.step_count_b)
    delta_card("Safety", diff.safety_a.upper(), diff.safety_b.upper())
with col2:
    delta_card("Confidence", f"{diff.confidence_a:.0%}", f"{diff.confidence_b:.0%}")
    delta_card("Sources cited", diff.sources_a, diff.sources_b)
with col3:
    delta_card("Gen time", f"{diff.gen_ms_a:.0f}ms", f"{diff.gen_ms_b:.0f}ms")
    delta_card("Reagents", len(diff.reagents_only_a)+len(diff.reagents_shared),
               len(diff.reagents_only_b)+len(diff.reagents_shared))

divider()

# ── Step diff ─────────────────────────────────────────────────────────────────
section_label("Step-by-step diff")
diff_counts_html = f"""
<div style="display:flex;gap:16px;margin-bottom:1rem;">
    <span style="font-family:'JetBrains Mono',monospace;font-size:0.7rem;color:#4ade80;">
        ● {diff.steps_added} added</span>
    <span style="font-family:'JetBrains Mono',monospace;font-size:0.7rem;color:#f87171;">
        ● {diff.steps_removed} removed</span>
    <span style="font-family:'JetBrains Mono',monospace;font-size:0.7rem;color:#ffd33d;">
        ● {diff.steps_changed} changed</span>
    <span style="font-family:'JetBrains Mono',monospace;font-size:0.7rem;color:rgba(160,185,205,0.4);">
        ● {diff.steps_same} unchanged</span>
</div>"""
st.markdown(diff_counts_html, unsafe_allow_html=True)

KIND_COLORS = {
    "same":    ("rgba(160,185,205,0.04)", "rgba(160,185,205,0.06)", "rgba(160,185,205,0.3)"),
    "changed": ("rgba(255,211,61,0.05)",  "rgba(255,211,61,0.08)",  "#ffd33d"),
    "added":   ("rgba(74,222,128,0.05)",  "rgba(74,222,128,0.08)",  "#4ade80"),
    "removed": ("rgba(248,113,113,0.05)", "rgba(248,113,113,0.08)", "#f87171"),
}

for sd in diff.step_diffs:
    bg, border, accent = KIND_COLORS.get(sd.kind, KIND_COLORS["same"])
    ia = sd.instruction_a or "—"
    ib = sd.instruction_b or "—"
    changes_html = ""
    if sd.changes:
        changes_html = "<div style='margin-top:5px;'>" + "".join(
            f"<span style='font-family:JetBrains Mono,monospace;font-size:0.62rem;"
            f"background:rgba(255,211,61,0.1);color:#ffd33d;padding:1px 6px;"
            f"border-radius:3px;margin-right:4px;'>{c}</span>"
            for c in sd.changes
        ) + "</div>"

    st.markdown(f"""
    <div style="background:{bg};border:1px solid {border};border-left:2px solid {accent};
        border-radius:0 8px 8px 0;padding:0.75rem 1rem;margin:4px 0;">
        <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
            <span style="font-family:'JetBrains Mono',monospace;font-size:0.6rem;
                color:{accent};text-transform:uppercase;letter-spacing:0.1em;">
                Step {sd.step_number} · {sd.kind}</span>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div style="font-size:0.82rem;color:rgba(208,228,240,{'0.8' if sd.kind!='removed' else '0.35'});">{ia}</div>
            <div style="font-size:0.82rem;color:rgba(208,228,240,{'0.8' if sd.kind!='added' else '0.35'});">{ib}</div>
        </div>
        {changes_html}
    </div>""", unsafe_allow_html=True)

divider()

# ── Reagents comparison ───────────────────────────────────────────────────────
if diff.reagents_only_a or diff.reagents_only_b or diff.reagents_shared:
    section_label("Reagents")
    rc1, rc2, rc3 = st.columns(3, gap="large")
    with rc1:
        st.markdown("<div style='font-family:JetBrains Mono,monospace;font-size:0.62rem;color:#00f0c8;margin-bottom:6px;'>A ONLY</div>", unsafe_allow_html=True)
        for r in diff.reagents_only_a:
            st.markdown(f"<div style='font-size:0.8rem;color:rgba(208,228,240,0.7);padding:3px 0;border-bottom:1px solid rgba(0,240,200,0.06);'>+ {r}</div>", unsafe_allow_html=True)
    with rc2:
        st.markdown("<div style='font-family:JetBrains Mono,monospace;font-size:0.62rem;color:rgba(160,185,205,0.4);margin-bottom:6px;'>SHARED</div>", unsafe_allow_html=True)
        for r in diff.reagents_shared:
            st.markdown(f"<div style='font-size:0.8rem;color:rgba(208,228,240,0.4);padding:3px 0;border-bottom:1px solid rgba(255,255,255,0.04);'>= {r}</div>", unsafe_allow_html=True)
    with rc3:
        st.markdown("<div style='font-family:JetBrains Mono,monospace;font-size:0.62rem;color:#6c4cdc;margin-bottom:6px;'>B ONLY</div>", unsafe_allow_html=True)
        for r in diff.reagents_only_b:
            st.markdown(f"<div style='font-size:0.8rem;color:rgba(208,228,240,0.7);padding:3px 0;border-bottom:1px solid rgba(108,76,220,0.06);'>+ {r}</div>", unsafe_allow_html=True)