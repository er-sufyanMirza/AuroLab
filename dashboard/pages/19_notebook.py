"""dashboard/pages/19_notebook.py — Lab Notebook (Protocol Annotations)"""
import sys
from pathlib import Path
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'dashboard'))
from shared import inject_css, render_nav, hero, kpi_row, divider, section_label, badge

st.set_page_config(page_title="Notebook — AuroLab", page_icon="⚗", layout="wide",
                   initial_sidebar_state="collapsed")
inject_css()
render_nav("notebook")

hero("LAB NOTEBOOK",
     "Annotate protocols with notes, tags, and execution outcomes — your electronic lab notebook",
     accent="#a89ef8", tag="Notes · Tags · Stars · Execution Log")

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from services.translation_service.core.protocol_notes import ProtocolNotesStore
notes_store = ProtocolNotesStore("./data/notes.db")

history = st.session_state.get("protocol_history", [])
if not history:
    st.markdown("""
    <div style="text-align:center;padding:4rem;color:rgba(160,185,205,0.4);">
        <div style="font-size:2rem;margin-bottom:1rem;">📓</div>
        <div style="font-family:'JetBrains Mono',monospace;">Generate protocols first</div>
    </div>""", unsafe_allow_html=True)
    st.stop()

# ── Stats ────────────────────────────────────────────────────────────────────
starred_ids = notes_store.get_starred()
all_tags    = notes_store.get_all_tags()
kpi_row([
    (len(history),     "Protocols",   "#00f0c8"),
    (len(starred_ids), "Starred",     "#ffd33d"),
    (len(all_tags),    "Unique tags", "#a89ef8"),
    (sum(len(notes_store.get_execution_logs(p.get("protocol_id",""))) for p in history[:10]),
     "Execution logs", "#4ade80"),
])
divider()

# ── Filter bar ───────────────────────────────────────────────────────────────
fc1, fc2, fc3 = st.columns([2, 2, 1])
with fc1:
    search_q = st.text_input("Search", placeholder="Title or tag...", label_visibility="collapsed")
with fc2:
    tag_filter = st.selectbox("Tag filter",
        ["All tags"] + [t["tag"] for t in all_tags],
        label_visibility="collapsed")
with fc3:
    starred_only = st.checkbox("⭐ Starred only")

# Filter protocols
filtered = history
if search_q:
    q = search_q.lower()
    filtered = [p for p in filtered if q in p.get("title","").lower()
                or q in " ".join(notes_store.get_tags(p.get("protocol_id","")))]
if tag_filter != "All tags":
    tagged_ids = set(notes_store.search_by_tag(tag_filter))
    filtered = [p for p in filtered if p.get("protocol_id","") in tagged_ids]
if starred_only:
    filtered = [p for p in filtered if p.get("protocol_id","") in starred_ids]

list_col, detail_col = st.columns([2, 3], gap="large")

with list_col:
    section_label(f"Protocols ({len(filtered)})")
    for p in filtered:
        pid     = p.get("protocol_id","")
        tags    = notes_store.get_tags(pid)
        starred = pid in starred_ids
        note    = notes_store.get_note(pid)
        has_note= note and note.content.strip()
        exe_ct  = len(notes_store.get_execution_logs(pid, limit=1))

        star_icon = "⭐" if starred else "☆"
        indicators = ""
        if has_note:   indicators += '<span style="color:#a89ef8;font-size:0.65rem;">📝</span>'
        if exe_ct:     indicators += '<span style="color:#4ade80;font-size:0.65rem;">✓</span>'
        if tags:       indicators += f'<span style="color:#00b8ff;font-size:0.65rem;">{len(tags)}🏷</span>'

        is_sel = st.session_state.get("nb_selected_id") == pid
        if st.button(f"{star_icon} {p.get('title','?')[:30]}", key=f"nb_{pid}",
                     use_container_width=True):
            st.session_state.nb_selected_id = pid
        if indicators:
            st.markdown(f"<div style='margin-top:-10px;margin-bottom:6px;padding-left:4px;'>{indicators}</div>",
                        unsafe_allow_html=True)

with detail_col:
    sel_id = st.session_state.get("nb_selected_id")
    if not sel_id:
        st.markdown("""
        <div style="text-align:center;padding:4rem;color:rgba(160,185,205,0.35);">
            Select a protocol to annotate
        </div>""", unsafe_allow_html=True)
        st.stop()

    sel_proto = next((p for p in history if p.get("protocol_id","") == sel_id), None)
    if not sel_proto:
        st.warning("Protocol not found")
        st.stop()

    # Header
    starred = sel_id in starred_ids
    sc1, sc2 = st.columns([5, 1])
    with sc1:
        st.markdown(f"""
        <div style="font-family:'Orbitron',monospace;font-size:1.1rem;font-weight:700;
            color:#e8f4ff;margin-bottom:4px;">{sel_proto.get('title','')}</div>
        <div style="font-size:0.8rem;color:rgba(160,185,205,0.5);">
            {badge(sel_proto.get('safety_level','safe').upper(), sel_proto.get('safety_level','safe'))}
            &nbsp;{sel_proto.get('confidence_score',0):.0%} confidence &nbsp;
            {len(sel_proto.get('steps',[]))} steps
        </div>""", unsafe_allow_html=True)
    with sc2:
        if st.button("⭐" if not starred else "★ Unstar",
                     key="star_btn", use_container_width=True):
            if starred: notes_store.unstar(sel_id)
            else:        notes_store.star(sel_id)
            st.rerun()

    divider()
    tab_note, tab_tags, tab_exec, tab_links = st.tabs(["📝 Notes","🏷 Tags","✓ Execution","🔗 Links"])

    with tab_note:
        section_label("Lab notes (Markdown supported)")
        existing = notes_store.get_note(sel_id)
        default_content = existing.content if existing else ""
        note_content = st.text_area("Notes", value=default_content, height=200,
            label_visibility="collapsed",
            placeholder="Document your observations, deviations, modifications...\n\n**Markdown** is supported.")
        if st.button("💾 Save notes", type="primary", key="save_note"):
            notes_store.upsert_note(sel_id, note_content)
            st.success("Saved")
        if existing and existing.content.strip():
            st.markdown("<br>", unsafe_allow_html=True)
            section_label("Preview")
            st.markdown(existing.content)

    with tab_tags:
        section_label("Tags")
        cur_tags = notes_store.get_tags(sel_id)
        if cur_tags:
            tag_html = " ".join(
                f'<span style="background:rgba(168,142,248,0.12);color:#a89ef8;'
                f'border:1px solid rgba(168,142,248,0.25);padding:2px 10px;'
                f'border-radius:4px;font-family:JetBrains Mono,monospace;'
                f'font-size:0.7rem;margin:2px;">{t}</span>'
                for t in cur_tags)
            st.markdown(f"<div style='margin-bottom:12px;'>{tag_html}</div>",
                        unsafe_allow_html=True)
        ta, tb = st.columns([3, 1])
        with ta:
            new_tag = st.text_input("Add tag", placeholder="e.g. validated, bca, cell-line-hek",
                                    label_visibility="collapsed")
        with tb:
            if st.button("+ Add", key="add_tag", use_container_width=True) and new_tag.strip():
                notes_store.add_tag(sel_id, new_tag.strip())
                st.rerun()
        if cur_tags:
            rm = st.selectbox("Remove tag", ["— select —"] + cur_tags, label_visibility="collapsed")
            if rm != "— select —" and st.button("Remove", key="rm_tag"):
                notes_store.remove_tag(sel_id, rm)
                st.rerun()
        if all_tags:
            section_label("Popular tags")
            pop_html = " ".join(
                f'<span style="background:rgba(0,240,200,0.06);color:rgba(0,240,200,0.6);'
                f'border:1px solid rgba(0,240,200,0.12);padding:1px 8px;border-radius:4px;'
                f'font-family:JetBrains Mono,monospace;font-size:0.65rem;margin:2px;'
                f'cursor:pointer;">{t["tag"]} ({t["count"]})</span>'
                for t in all_tags[:12])
            st.markdown(f"<div>{pop_html}</div>", unsafe_allow_html=True)

    with tab_exec:
        section_label("Log execution")
        with st.form("exec_log_form", clear_on_submit=True):
            ec1, ec2 = st.columns(2)
            with ec1:
                outcome  = st.selectbox("Outcome", ["success","partial","failed","aborted"])
                operator = st.text_input("Operator", placeholder="Your name")
            with ec2:
                actual_time = st.number_input("Actual time (min)", 0.0, step=5.0)
                success     = st.checkbox("Successful result")
            observations = st.text_area("Observations", height=80,
                placeholder="What was actually observed...")
            deviations = st.text_area("Deviations from protocol", height=60,
                placeholder="Any steps that differed from the generated protocol...")
            if st.form_submit_button("Log execution", type="primary", use_container_width=True):
                notes_store.log_execution(
                    sel_id, outcome=outcome, operator=operator,
                    observations=observations, deviations=deviations,
                    actual_time_min=actual_time, success=success)
                st.success("Execution logged")

        exe_logs = notes_store.get_execution_logs(sel_id, limit=10)
        if exe_logs:
            st.markdown("<br>", unsafe_allow_html=True)
            section_label(f"Execution history ({len(exe_logs)} runs)")
            success_ct = sum(1 for l in exe_logs if l.success)
            st.markdown(f"""
            <div style="font-family:'JetBrains Mono',monospace;font-size:0.7rem;
                color:rgba(160,185,205,0.4);margin-bottom:8px;">
                Success rate: <span style="color:#4ade80;">{success_ct}/{len(exe_logs)}</span>
            </div>""", unsafe_allow_html=True)
            for log in exe_logs:
                from datetime import datetime
                dt  = datetime.fromtimestamp(log.executed_at).strftime("%Y-%m-%d %H:%M")
                col = "#4ade80" if log.success else "#f87171"
                st.markdown(f"""
                <div style="background:rgba(0,240,200,0.015);border:1px solid rgba(0,240,200,0.07);
                    border-left:2px solid {col};border-radius:0 8px 8px 0;
                    padding:8px 12px;margin:4px 0;">
                    <div style="display:flex;justify-content:space-between;margin-bottom:3px;">
                        <span style="font-family:'JetBrains Mono',monospace;font-size:0.62rem;color:{col};">{log.outcome.upper()}</span>
                        <span style="font-size:0.65rem;color:rgba(160,185,205,0.3);">{dt} · {log.operator or 'unknown'}</span>
                    </div>
                    {f'<div style="font-size:0.78rem;color:#c0d8e8;">{log.observations[:100]}</div>' if log.observations else ''}
                    {f'<div style="font-size:0.72rem;color:#ffd33d;margin-top:3px;">⚠ {log.deviations[:80]}</div>' if log.deviations else ''}
                </div>""", unsafe_allow_html=True)

    with tab_links:
        section_label("Linked protocols")
        if len(history) > 1:
            other_opts = {p.get("title","?"): p.get("protocol_id","")
                         for p in history if p.get("protocol_id","") != sel_id}
            lc1, lc2, lc3 = st.columns([2,2,1])
            with lc1:
                linked = st.selectbox("Protocol to link", list(other_opts.keys()),
                                      label_visibility="collapsed")
            with lc2:
                rel = st.selectbox("Relationship",
                    ["related","precedes","follows","alternative","derives-from"],
                    label_visibility="collapsed")
            with lc3:
                if st.button("Link", key="add_link", use_container_width=True):
                    notes_store.link_protocols(sel_id, other_opts[linked], rel)
                    st.rerun()

        links = notes_store.get_links(sel_id)
        if links:
            for lnk in links:
                other_id = lnk["linked_id"] if lnk["protocol_id"]==sel_id else lnk["protocol_id"]
                other    = next((p.get("title","?") for p in history if p.get("protocol_id","")==other_id), other_id[:8])
                st.markdown(f"""
                <div style="padding:6px 0;border-bottom:1px solid rgba(0,240,200,0.05);
                    font-size:0.82rem;color:#c0d8e8;">
                    <span style="font-family:'JetBrains Mono',monospace;font-size:0.62rem;
                        color:#a89ef8;">[{lnk['relationship']}]</span>
                    &nbsp;{other}
                </div>""", unsafe_allow_html=True)
        else:
            st.markdown("<span style='font-size:0.8rem;color:rgba(160,185,205,0.3);'>No links yet</span>",
                        unsafe_allow_html=True)