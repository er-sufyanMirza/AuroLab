"""dashboard/pages/15_templates.py — Protocol Templates Library"""
import sys
from pathlib import Path
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'dashboard'))
from shared import inject_css, render_nav, hero, kpi_row, divider, section_label, badge

st.set_page_config(page_title="Templates — AuroLab", page_icon="⚗", layout="wide",
                   initial_sidebar_state="collapsed")
inject_css()
render_nav("templates")

hero("PROTOCOL TEMPLATES",
     "8 pre-validated assay templates — configure parameters and generate a cited protocol instantly",
     accent="#00b8ff", tag="BCA · PCR · ELISA · Western Blot · MTT · Bradford · Gel · Miniprep")

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from services.translation_service.core.protocol_templates import (
    list_templates, get_template, build_instruction_from_template)

templates = list_templates()

CATEGORY_COLORS = {
    "assay":    "#00f0c8",
    "prep":     "#6c4cdc",
    "analysis": "#00b8ff",
    "qc":       "#ffd33d",
}
DIFF_COLORS = {"easy": "#4ade80", "medium": "#ffd33d", "hard": "#f87171"}

kpi_row([
    (len(templates),     "Templates",     "#00f0c8"),
    (sum(1 for t in templates if t["category"]=="assay"),    "Assays",    "#6c4cdc"),
    (sum(1 for t in templates if t["category"]=="analysis"), "Analysis",  "#00b8ff"),
    (sum(1 for t in templates if t["category"]=="prep"),     "Prep",      "#ffd33d"),
])
divider()

left, right = st.columns([2, 3], gap="large")

with left:
    section_label("Select template")
    cat_filter = st.selectbox("Category", ["All","assay","prep","analysis","qc"],
                               label_visibility="collapsed")
    filtered = [t for t in templates if cat_filter=="All" or t["category"]==cat_filter]

    selected_id = st.session_state.get("selected_template_id")
    for t in filtered:
        ac  = CATEGORY_COLORS.get(t["category"],"#888898")
        dc  = DIFF_COLORS.get(t["difficulty"],"#888898")
        is_sel = selected_id == t["template_id"]
        bg  = "rgba(0,240,200,0.06)" if is_sel else "rgba(0,240,200,0.015)"
        brd = "rgba(0,240,200,0.4)"  if is_sel else "rgba(0,240,200,0.08)"
        if st.button(t["name"], key=f"tmpl_{t['template_id']}", use_container_width=True):
            st.session_state.selected_template_id = t["template_id"]
            st.rerun()
        st.markdown(f"""
        <div style="margin:-10px 0 6px;padding:0 4px;display:flex;gap:8px;align-items:center;">
            <span style="font-family:JetBrains Mono,monospace;font-size:0.6rem;
                color:{ac};">{t['category'].upper()}</span>
            <span style="font-family:JetBrains Mono,monospace;font-size:0.6rem;
                color:{dc};">· {t['difficulty']}</span>
            <span style="font-family:JetBrains Mono,monospace;font-size:0.6rem;
                color:rgba(160,185,205,0.35);">· ~{t['estimated_time_min']}min</span>
        </div>""", unsafe_allow_html=True)

with right:
    tid = st.session_state.get("selected_template_id")
    if not tid:
        st.markdown("""
        <div style="text-align:center;padding:5rem;color:rgba(160,185,205,0.35);">
            <div style="font-size:2.5rem;margin-bottom:1rem;">🧪</div>
            <div style="font-family:'JetBrains Mono',monospace;">Select a template</div>
        </div>""", unsafe_allow_html=True)
    else:
        tmpl = get_template(tid)
        if not tmpl:
            st.error("Template not found")
            st.stop()

        ac = CATEGORY_COLORS.get(tmpl.category,"#888898")
        sc = DIFF_COLORS.get(tmpl.difficulty,"#888898")

        st.markdown(f"""
        <div style="margin-bottom:1rem;">
            <div style="font-family:'Orbitron',monospace;font-size:1.2rem;font-weight:700;
                color:#e8f4ff;margin-bottom:4px;">{tmpl.name}</div>
            <div style="font-size:0.85rem;color:rgba(160,185,205,0.55);margin-bottom:8px;">{tmpl.description}</div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
                {badge(tmpl.category.upper(), "default")}
                {badge(tmpl.difficulty.upper(), "safe" if tmpl.difficulty=="easy" else ("warning" if tmpl.difficulty=="medium" else "blocked"))}
                {badge(tmpl.safety_level.upper(), tmpl.safety_level)}
                {badge(f"~{tmpl.estimated_time_min}min", "idle")}
            </div>
        </div>""", unsafe_allow_html=True)

        divider()
        section_label("Configure parameters")

        param_vals = {}
        cols_per_row = 2
        params = tmpl.parameters
        for i in range(0, len(params), cols_per_row):
            row_params = params[i:i+cols_per_row]
            cols = st.columns(len(row_params), gap="medium")
            for col, p in zip(cols, row_params):
                with col:
                    if p.param_type == "choice" and p.choices:
                        val = col.selectbox(
                            f"{p.label}{' ('+p.unit+')' if p.unit else ''}",
                            p.choices,
                            index=p.choices.index(p.default) if p.default in p.choices else 0,
                            key=f"p_{tid}_{p.name}",
                            help=p.description,
                        )
                    elif p.param_type == "bool":
                        val = col.checkbox(p.label, value=bool(p.default),
                                           key=f"p_{tid}_{p.name}", help=p.description)
                    elif p.param_type == "text":
                        val = col.text_input(p.label, value=str(p.default),
                                             key=f"p_{tid}_{p.name}", help=p.description)
                    else:
                        label = f"{p.label}{' ('+p.unit+')' if p.unit else ''}"
                        if p.min_val is not None and p.max_val is not None:
                            val = col.slider(label, float(p.min_val), float(p.max_val),
                                             float(p.default), key=f"p_{tid}_{p.name}",
                                             help=p.description)
                        else:
                            val = col.number_input(label, value=float(p.default),
                                                   key=f"p_{tid}_{p.name}", help=p.description)
                    param_vals[p.name] = val

        # Build instruction preview
        instruction = tmpl.build_instruction(param_vals)
        st.markdown("<br>", unsafe_allow_html=True)
        section_label("Generated instruction")
        st.markdown(f"""
        <div style="background:rgba(0,240,200,0.03);border:1px solid rgba(0,240,200,0.15);
            border-radius:8px;padding:12px 16px;font-size:0.88rem;color:#d0e4f0;
            line-height:1.7;font-style:italic;">
            "{instruction}"
        </div>""", unsafe_allow_html=True)

        c1, c2 = st.columns(2, gap="medium")
        with c1:
            if st.button("⚗ Generate protocol from template", type="primary",
                         use_container_width=True):
                st.session_state.template_instruction = instruction
                st.session_state.template_name = tmpl.name
                st.success(f"Instruction ready — go to Generate page to run it")

        with c2:
            if st.button("Copy instruction", use_container_width=True):
                st.session_state.template_instruction = instruction
                st.info("Instruction saved — paste it on the Generate page")

        # Hint steps preview
        if tmpl.hint_steps:
            divider()
            section_label("Protocol hints")
            for i, hint in enumerate(tmpl.hint_steps, 1):
                filled_hint = hint
                for p in tmpl.parameters:
                    val = param_vals.get(p.name, p.default)
                    filled_hint = filled_hint.replace(f"{{{p.name}}}", str(val))
                st.markdown(f"""
                <div style="display:flex;gap:10px;padding:6px 0;
                    border-bottom:1px solid rgba(0,240,200,0.05);">
                    <span style="font-family:'Orbitron',monospace;font-size:0.6rem;
                        color:{ac};min-width:22px;">{i:02d}</span>
                    <span style="font-size:0.82rem;color:rgba(208,228,240,0.7);">{filled_hint}</span>
                </div>""", unsafe_allow_html=True)

        # References
        if tmpl.references:
            divider()
            section_label("References")
            for ref in tmpl.references:
                st.markdown(f"<div style='font-size:0.78rem;color:rgba(160,185,205,0.4);padding:2px 0;'>· {ref}</div>",
                            unsafe_allow_html=True)