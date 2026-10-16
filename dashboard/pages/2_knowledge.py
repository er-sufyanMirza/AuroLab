"""dashboard/pages/2_knowledge.py — Knowledge Base"""

import time, sys
from pathlib import Path
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'dashboard'))
from shared import inject_css, render_nav, hero, api_get, api_post, api_delete, kpi_row, kpi_card, page_header, divider, section_label, badge, stats_strip, neon_card, render_step_card, render_protocol_header, export_buttons, PLOTLY_DARK

st.set_page_config(page_title="Knowledge Base — AuroLab", page_icon="⚗", layout="wide", initial_sidebar_state="collapsed")
inject_css()
render_nav("knowledge")

page_header("Knowledge Base", "Upload lab PDFs, SOPs, and research papers to expand the retrieval index.")
divider()

upload_col, list_col = st.columns([2, 3], gap="large")

with upload_col:
    section_label("Upload documents")
    uploaded_files = st.file_uploader("Drop PDFs here", type=["pdf"],
        accept_multiple_files=True, label_visibility="collapsed")

    if uploaded_files:
        for uf in uploaded_files:
            queued = st.session_state.get("queued_uploads", set())
            if uf.name in queued: continue
            with st.spinner(f"Ingesting {uf.name}..."):
                result = api_post("/api/v1/documents/upload",
                    files={"file": (uf.name, uf.getvalue(), "application/pdf")})
            if result:
                status = result.get("status","queued")
                if status == "duplicate":
                    st.info(f"Already indexed: {uf.name}")
                else:
                    st.success(f"Queued: {uf.name} · {result.get('size_kb',0)} KB")
                    queued.add(uf.name)
                    st.session_state.queued_uploads = queued

    divider()
    st.markdown("""
    <div style="font-size:0.8rem;line-height:2;">
    <div class="section-label">Supported types</div>
    <div style="color:#888898;">· Lab protocols (BCA, PCR, ELISA, Western blot)</div>
    <div style="color:#888898;">· Standard Operating Procedures</div>
    <div style="color:#888898;">· Research papers with methods sections</div>
    <div style="color:#888898;">· Equipment datasheets</div>
    <br>
    <div class="section-label">Parse pipeline</div>
    <div style="color:#888898;"><span style="color:#7c6af7;">PyMuPDF</span> → layout-aware text extraction</div>
    <div style="color:#888898;"><span style="color:#4ade80;">Unstructured</span> → scanned PDF fallback</div>
    <div style="color:#888898;"><span style="color:#60a5fa;">SHA-256</span> → deduplication guard</div>
    <div style="color:#888898;"><span style="color:#fbbf24;">Section chunking</span> → heading-anchored splits</div>
    </div>""", unsafe_allow_html=True)

with list_col:
    section_label("Indexed documents")
    c1, c2 = st.columns([1, 1])
    with c1:
        search_q = st.text_input("Search docs", placeholder="filename or type...", label_visibility="collapsed")
    with c2:
        if st.button("⟳ Refresh", use_container_width=True):
            st.rerun()

    docs_data = api_get("/api/v1/documents/")
    if docs_data is None:
        st.warning("Backend offline — start uvicorn first")
    else:
        # API may return {"documents": [...]} or {"documents": ["file.pdf",...]} or {"files": [...]}
        raw = docs_data.get("documents") or docs_data.get("files") or []
        # Normalise: if items are strings, convert to dicts
        docs = []
        for item in raw:
            if isinstance(item, str):
                docs.append({"filename": item, "doc_type": "unknown",
                             "status": "ready", "chunk_count": 0, "sha256": ""})
            elif isinstance(item, dict):
                docs.append(item)
        if not docs:
            st.markdown("""
        <div style="text-align:center;padding:4rem;color:#444458;">
            <div style="font-size:2.5rem;margin-bottom:1rem;">📭</div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:0.85rem;">No documents indexed yet</div>
            <div style="font-size:0.78rem;margin-top:6px;">Upload a PDF to get started</div>
        </div>""", unsafe_allow_html=True)
        if search_q:
            q = search_q.lower()
            docs = [d for d in docs if q in d.get("filename","").lower() or q in d.get("doc_type","").lower()]

        ready = sum(1 for d in docs if d.get("status") == "ready")
        processing = sum(1 for d in docs if d.get("status") in ("processing","queued"))
        total_chunks = sum(d.get("chunk_count",0) for d in docs)

        kpi_row([
            (len(docs),              "Total",      "#00f0c8"),
            (ready,                  "Ready",      "#4ade80"),
            (processing,             "Processing", "#ffd33d"),
            (f"{total_chunks:,}",    "Chunks",     "#6c4cdc"),
        ])

        for doc in docs:
            status = doc.get("status","unknown")
            sha = doc.get("sha256","")[:10]
            cols = st.columns([5, 1])
            with cols[0]:
                st.markdown(f"""
                <div class="doc-row">
                    <div style="flex:1">
                        <div class="doc-name">{doc.get('filename','?')}</div>
                        <div class="doc-meta">{doc.get('doc_type','?')} · {doc.get('page_count',0)}pp · {doc.get('chunk_count',0)} chunks · {doc.get('parse_strategy','')}</div>
                    </div>
                    <span class="status-{status}">{status.upper()}</span>
                </div>""", unsafe_allow_html=True)
            with cols[1]:
                if st.button("Delete", key=f"del_{sha}", use_container_width=True):
                    if api_delete(f"/api/v1/documents/{doc.get('sha256','')}"):
                        st.success("Deleted")
                        time.sleep(0.4)
                        st.rerun()

        if processing > 0:
            time.sleep(3); st.rerun()