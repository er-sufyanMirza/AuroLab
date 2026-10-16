"""dashboard/pages/22_eln.py — ELN Export (CSV / Excel / JSON-LD)"""
import sys
from pathlib import Path
import streamlit as st
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'dashboard'))
from shared import inject_css, render_nav, hero, kpi_row, divider, section_label, badge

st.set_page_config(page_title="ELN Export — AuroLab", page_icon="⚗", layout="wide", initial_sidebar_state="collapsed")
inject_css(); render_nav("eln")
hero("ELN EXPORT", "Export protocols to CSV, Excel, or JSON-LD for Electronic Lab Notebooks", accent="#ffd33d", tag="CSV · Excel · JSON-LD · LIMS")

history = st.session_state.get("protocol_history", [])
if not history:
    st.info("Generate protocols first, then return here to export.")
    st.stop()

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from services.translation_service.core.eln_exporter import export_csv, export_excel, export_jsonld

opts = {f"{p.get('title','?')} — {p.get('protocol_id','')[:8]}": p for p in history}
ca, cb = st.columns([4,1])
with ca: sel = st.selectbox("Protocol", list(opts.keys()), label_visibility="collapsed")
p = opts[sel]
kpi_row([(len(p.get("steps",[])), "Steps","#00f0c8"), (len(p.get("reagents",[])),"Reagents","#6c4cdc"),
         (p.get("confidence_score",0),"Confidence","#ffd33d")])
divider()
section_label("Export formats")
cols = st.columns(3, gap="large")
with cols[0]:
    st.markdown("""<div style="background:rgba(0,240,200,0.02);border:1px solid rgba(0,240,200,0.1);border-top:2px solid #00f0c8;border-radius:0 0 10px 10px;padding:1.1rem;text-align:center;">
    <div style="font-family:'Orbitron',monospace;font-size:0.8rem;color:#00f0c8;margin-bottom:6px;">CSV</div>
    <div style="font-size:0.72rem;color:rgba(160,185,205,0.4);">Steps table · Import to any ELN or LIMS</div></div>""", unsafe_allow_html=True)
    csv_data = export_csv(p)
    st.download_button("⬇ Download CSV", data=csv_data,
        file_name=f"protocol_{p.get('protocol_id','x')[:8]}.csv",
        mime="text/csv", use_container_width=True)

with cols[1]:
    st.markdown("""<div style="background:rgba(255,211,61,0.02);border:1px solid rgba(255,211,61,0.1);border-top:2px solid #ffd33d;border-radius:0 0 10px 10px;padding:1.1rem;text-align:center;">
    <div style="font-family:'Orbitron',monospace;font-size:0.8rem;color:#ffd33d;margin-bottom:6px;">EXCEL</div>
    <div style="font-size:0.72rem;color:rgba(160,185,205,0.4);">4 sheets: Summary · Steps · Reagents · Sources</div></div>""", unsafe_allow_html=True)
    try:
        xl_data = export_excel(p)
        st.download_button("⬇ Download Excel", data=xl_data,
            file_name=f"protocol_{p.get('protocol_id','x')[:8]}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True)
    except ImportError:
        st.warning("pip install openpyxl")

with cols[2]:
    st.markdown("""<div style="background:rgba(108,76,220,0.02);border:1px solid rgba(108,76,220,0.1);border-top:2px solid #6c4cdc;border-radius:0 0 10px 10px;padding:1.1rem;text-align:center;">
    <div style="font-family:'Orbitron',monospace;font-size:0.8rem;color:#a89ef8;margin-bottom:6px;">JSON-LD</div>
    <div style="font-size:0.72rem;color:rgba(160,185,205,0.4);">Bioschemas · Semantic web · FAIR data</div></div>""", unsafe_allow_html=True)
    jld = export_jsonld(p)
    st.download_button("⬇ Download JSON-LD", data=jld,
        file_name=f"protocol_{p.get('protocol_id','x')[:8]}.jsonld",
        mime="application/ld+json", use_container_width=True)

divider()
section_label("CSV preview")
st.code(export_csv(p)[:800] + ("..." if len(export_csv(p))>800 else ""), language="text")