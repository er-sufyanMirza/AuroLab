"""dashboard/pages/3_eval.py — RAG Evaluation Dashboard"""

import json, sys
from pathlib import Path
import streamlit as st
import plotly.graph_objects as go
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'dashboard'))
from shared import inject_css, render_nav, hero, api_get, api_post, api_delete, kpi_row, divider, section_label, badge, stats_strip, neon_card, render_step_card, render_protocol_header, export_buttons, PLOTLY_DARK

st.set_page_config(page_title="Eval — AuroLab", page_icon="⚗", layout="wide", initial_sidebar_state="collapsed")
inject_css()
render_nav("eval")

VARIANT_COLORS = {
    "A_dense_only": "#555568",
    "B_hybrid":     "#7c6af7",
    "C_full":       "#22c55e",
}

RESULTS_PATH = Path("data/eval/results.json")

def load_results():
    if "eval_results" in st.session_state:
        return st.session_state.eval_results
    if RESULTS_PATH.exists():
        data = json.loads(RESULTS_PATH.read_text())
        st.session_state.eval_results = data
        return data
    return None

def results_to_df(results):
    rows = []
    for v in results.get("variants", []):
        rows.append({
            "Variant":      v["variant"],
            "MRR@k":        round(v["MRR@k"], 4),
            "NDCG@k":       round(v["NDCG@k"], 4),
            "Recall@k":     round(v["Recall@k"], 4),
            "Precision@k":  round(v["Precision@k"], 4),
            "Hit Rate@k":   round(v["HitRate@k"], 4),
            "Latency (ms)": round(v["mean_latency_ms"], 1),
            "Queries":      v["n_queries"],
        })
    return pd.DataFrame(rows)

# ── Mock fallback data for demo ───────────────────────────────────────────────
MOCK_RESULTS = {
    "k": 5,
    "variants": [
        {"variant": "A_dense_only", "MRR@k": 0.512, "NDCG@k": 0.488, "Recall@k": 0.621,
         "Precision@k": 0.312, "HitRate@k": 0.724, "mean_latency_ms": 145.2, "n_queries": 50},
        {"variant": "B_hybrid",     "MRR@k": 0.681, "NDCG@k": 0.654, "Recall@k": 0.782,
         "Precision@k": 0.441, "HitRate@k": 0.856, "mean_latency_ms": 198.7, "n_queries": 50},
        {"variant": "C_full",       "MRR@k": 0.748, "NDCG@k": 0.721, "Recall@k": 0.834,
         "Precision@k": 0.502, "HitRate@k": 0.902, "mean_latency_ms": 312.4, "n_queries": 50},
    ]
}

st.markdown("## RAG Evaluation")
st.markdown("Compare retrieval quality across pipeline variants: dense-only, hybrid (dense+BM25), and full (hybrid+HyDE+reranker).")
st.markdown('<hr class="divider">', unsafe_allow_html=True)

# Run eval button
rc1, rc2, rc3 = st.columns([2, 1, 3])
with rc1:
    run_btn = st.button("Run evaluation now", type="primary", use_container_width=True,
        help="Runs the full RAG eval harness against the knowledge base. Requires documents to be indexed.")
with rc2:
    use_mock = st.checkbox("Demo data", value=True, help="Use built-in demo results when no eval has been run")

if run_btn:
    with st.spinner("Running RAG eval harness (this may take 60–120 seconds)..."):
        result = api_post("/api/v1/eval/run", silent=True)
    if result:
        st.session_state.eval_results = result
        st.success(f"Eval complete — {result.get('total_queries', '?')} queries across {len(result.get('variants',[]))} variants")
        st.rerun()
    else:
        st.warning("Eval endpoint not available — showing demo data")
        st.session_state.eval_results = MOCK_RESULTS

results = load_results()
if results is None:
    if use_mock:
        results = MOCK_RESULTS
    else:
        st.info("No results yet. Click **Run evaluation now** or enable **Demo data**.")
        st.stop()

df = results_to_df(results)
k = results.get("k", 5)
best_variant = df.loc[df["NDCG@k"].idxmax(), "Variant"]

# ── Summary metrics ───────────────────────────────────────────────────────────
best = df[df["Variant"] == best_variant].iloc[0]
m1, m2, m3, m4, m5 = st.columns(5)
for col, label, val in [
    (m1, f"MRR@{k} (best)",      f"{best['MRR@k']:.3f}"),
    (m2, f"NDCG@{k} (best)",     f"{best['NDCG@k']:.3f}"),
    (m3, f"Recall@{k} (best)",   f"{best['Recall@k']:.3f}"),
    (m4, f"Hit Rate@{k} (best)", f"{best['Hit Rate@k']:.3f}"),
    (m5, "Best variant",         best_variant.replace("_"," ")),
]:
    col.markdown(f'<div class="kpi-card"><div class="kpi-value" style="font-size:1.5em;">{val}</div><div class="kpi-label">{label}</div></div>', unsafe_allow_html=True)

st.markdown('<hr class="divider">', unsafe_allow_html=True)

chart_col, table_col = st.columns([3, 2], gap="large")

with chart_col:
    st.markdown("#### Retrieval metrics by variant")
    metrics = [f"MRR@{k}", f"NDCG@{k}", f"Recall@{k}", f"Hit Rate@{k}"]
    fig = go.Figure()
    for _, row in df.iterrows():
        color = VARIANT_COLORS.get(row["Variant"], "#888898")
        fig.add_trace(go.Bar(
            name=row["Variant"].replace("_", " "),
            x=metrics,
            y=[row["MRR@k"], row["NDCG@k"], row["Recall@k"], row["Hit Rate@k"]],
            marker_color=color,
        ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="JetBrains Mono, monospace", color="rgba(160,185,205,0.5)", size=10),
        xaxis=dict(gridcolor="rgba(0,240,200,0.06)", linecolor="rgba(0,240,200,0.08)", tickfont=dict(color="rgba(160,185,205,0.4)")),
        yaxis=dict(gridcolor="rgba(0,240,200,0.06)", linecolor="rgba(0,240,200,0.08)", tickfont=dict(color="rgba(160,185,205,0.4)"), range=[0, 1]),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="rgba(160,185,205,0.6)", size=10)),
        margin=dict(l=8, r=8, t=36, b=8),
        hoverlabel=dict(bgcolor="#0a1018", bordercolor="rgba(0,240,200,0.3)", font=dict(family="JetBrains Mono, monospace", color="#d0e4f0")),
        height=300, barmode="group",
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### Latency vs quality trade-off")
    fig2 = go.Figure()
    for _, row in df.iterrows():
        color = VARIANT_COLORS.get(row["Variant"], "#888898")
        fig2.add_trace(go.Scatter(
            x=[row["Latency (ms)"]], y=[row["NDCG@k"]],
            mode="markers+text",
            text=[row["Variant"].replace("_", " ")],
            textposition="top center",
            marker=dict(size=14, color=color),
            name=row["Variant"],
        ))
    fig2.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="JetBrains Mono, monospace", color="rgba(160,185,205,0.5)", size=10),
        xaxis=dict(gridcolor="rgba(0,240,200,0.06)", linecolor="rgba(0,240,200,0.08)", tickfont=dict(color="rgba(160,185,205,0.4)"), title="Latency (ms)"),
        yaxis=dict(gridcolor="rgba(0,240,200,0.06)", linecolor="rgba(0,240,200,0.08)", tickfont=dict(color="rgba(160,185,205,0.4)"), title=f"NDCG@{k}", range=[0, 1]),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="rgba(160,185,205,0.6)", size=10)),
        margin=dict(l=8, r=8, t=36, b=8),
        hoverlabel=dict(bgcolor="#0a1018", bordercolor="rgba(0,240,200,0.3)", font=dict(family="JetBrains Mono, monospace", color="#d0e4f0")),
        height=260,
    )
    st.plotly_chart(fig2, use_container_width=True)

with table_col:
    st.markdown("#### Full results table")
    rows_html = ""
    for _, row in df.iterrows():
        is_best = row["Variant"] == best_variant
        cls = "best" if is_best else ""
        star = " ★" if is_best else ""
        rows_html += f"""<tr class="{cls}">
            <td>{row['Variant'].replace('_',' ')}{star}</td>
            <td>{row['MRR@k']}</td><td>{row['NDCG@k']}</td>
            <td>{row['Recall@k']}</td><td>{row['Hit Rate@k']}</td>
            <td>{row['Latency (ms)']} ms</td>
        </tr>"""
    st.markdown(f"""
    <table class="eval-table">
        <thead><tr>
            <th>Variant</th><th>MRR@{k}</th><th>NDCG@{k}</th>
            <th>Recall@{k}</th><th>Hit@{k}</th><th>Latency</th>
        </tr></thead>
        <tbody>{rows_html}</tbody>
    </table>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("#### What each variant uses")
    st.markdown("""
    <div style='font-size:0.84em; color:#888898; line-height:2;'>
    <b style='color:#555568;'>A — Dense only:</b> ChromaDB vector search<br>
    <b style='color:#7c6af7;'>B — Hybrid:</b> Dense + BM25 + RRF fusion<br>
    <b style='color:#22c55e;'>C — Full:</b> Hybrid + HyDE expansion + cross-encoder reranking<br><br>
    <span style='color:#444458;'>k={k} · MRR = Mean Reciprocal Rank · NDCG = Normalised Discounted Cumulative Gain</span>
    </div>""".format(k=k), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.download_button("Export results JSON",
        data=json.dumps(results, indent=2),
        file_name="rag_eval_results.json",
        mime="application/json", use_container_width=True)