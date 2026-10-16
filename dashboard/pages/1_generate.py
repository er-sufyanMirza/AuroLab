"""dashboard/pages/1_generate.py — Protocol Generator · Futuristic UI"""
import json, sys, time
from pathlib import Path
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'dashboard'))
from shared import inject_css, render_nav, hero, api_get, api_post, kpi_row, divider, section_label, badge, render_step_card, render_protocol_header, export_buttons, neon_card

st.set_page_config(page_title="Generate — AuroLab", page_icon="⚗", layout="wide",
                   initial_sidebar_state="collapsed")
inject_css()
render_nav("generate")

hero("PROTOCOL GENERATOR",
     "Describe any lab procedure in plain language — AuroLab retrieves context, generates cited steps, and simulates execution",
     accent="#6c4cdc", tag="RAG · LLM · Physics Simulation")

EXAMPLES = [
    "Perform a BCA protein assay on 8 samples using a 96-well plate at 562nm",
    "Run a standard 35-cycle PCR for a 500bp amplicon with Taq polymerase",
    "Prepare a serial dilution of BSA from 2000 µg/mL to 25 µg/mL for ELISA",
    "Execute a western blot transfer for proteins between 15–250 kDa",
    "Prepare competent E. coli cells using calcium chloride method",
    "Run a cell viability MTT assay on 96-well plate",
]

left, right = st.columns([3, 2], gap="large")

with left:
    section_label("Input instruction")

    # ── Template quick-fill ─────────────────────────────────────────────────
    if st.session_state.get("template_instruction"):
        tmpl_instr = st.session_state.pop("template_instruction")
        tmpl_name  = st.session_state.pop("template_name", "Template")
        st.markdown(f"""
        <div style="background:rgba(0,184,255,0.06);border:1px solid rgba(0,184,255,0.2);
            border-radius:8px;padding:8px 14px;margin-bottom:8px;font-size:0.8rem;color:#93c5fd;">
            📐 Pre-filled from template: <strong>{tmpl_name}</strong> — edit as needed
        </div>""", unsafe_allow_html=True)
    else:
        tmpl_instr = None

    ex = st.selectbox("Example", ["— enter custom instruction —"] + EXAMPLES, label_visibility="collapsed")
    default = tmpl_instr if tmpl_instr else ("" if ex.startswith("—") else ex)
    instruction = st.text_area("Instruction", value=default, height=110,
        placeholder="e.g. Perform a BCA protein assay on 8 samples at 562nm...",
        label_visibility="collapsed")

    with st.expander("⚙  CONFIG"):
        ca, cb, cc = st.columns(3)
        with ca:
            doc_f = st.selectbox("KB filter", ["All","protocol","SOP","paper"])
            doc_val = None if doc_f == "All" else doc_f
        with cb:
            top_k = st.slider("Chunks k", 1, 10, 5)
        with cc:
            sim_mode = st.selectbox("Sim mode", ["mock","pybullet","live"])
        src_on = st.checkbox("Include source citations", value=True)

    c1, c2 = st.columns(2)
    with c1:
        gen_btn = st.button("⚗  GENERATE", type="primary",
            disabled=len(instruction.strip()) < 10, use_container_width=True)
    with c2:
        sim_btn = st.button("▶  GENERATE + SIMULATE",
            disabled=len(instruction.strip()) < 10, use_container_width=True)

with right:
    section_label("5-stage pipeline")
    stages = [
        ("#6c4cdc", "01", "HyDE EXPANSION",     "Instruction → hypothetical protocol excerpt"),
        ("#00f0c8", "02", "HYBRID RETRIEVAL",    "Dense + BM25 · RRF · cross-encoder reranking"),
        ("#00b8ff", "03", "LLM GENERATION",      "Groq Llama 3.3-70B · [SOURCE_N] injection"),
        ("#ffd33d", "04", "SAFETY VALIDATION",   "Pre/post hazardous pattern detection"),
        ("#f87171", "05", "PHYSICS SIMULATION",  "PyBullet command-level collision check"),
    ]
    for color, num, title, desc in stages:
        st.markdown(f"""
        <div style="display:flex;gap:12px;margin:10px 0;align-items:flex-start;">
            <div style="
                width:26px;height:26px;border-radius:50%;
                background:rgba(255,255,255,0.02);
                border:1px solid {color};
                display:flex;align-items:center;justify-content:center;
                flex-shrink:0;margin-top:2px;
                box-shadow:0 0 8px {color}40;
            ">
                <span style="font-family:'Orbitron',monospace;font-size:0.55rem;color:{color};font-weight:700;">{num}</span>
            </div>
            <div>
                <div style="font-family:'JetBrains Mono',monospace;font-size:0.68rem;font-weight:500;color:#d0e4f0;margin-bottom:2px;letter-spacing:0.06em;">{title}</div>
                <div style="font-size:0.72rem;color:rgba(160,185,205,0.4);line-height:1.5;">{desc}</div>
            </div>
        </div>""", unsafe_allow_html=True)

# ── Run ──────────────────────────────────────────────────────────────────────
if (gen_btn or sim_btn) and len(instruction.strip()) >= 10:
    # ── Streaming generate with live progress ────────────────────────────
    import httpx, json as _json
    API_BASE_LOCAL = "http://localhost:8080"

    stage_labels = {
        "hyde":     ("01", "HyDE expansion",    "#6c4cdc"),
        "retrieve": ("02", "Hybrid retrieval",   "#00f0c8"),
        "generate": ("03", "LLM generation",     "#00b8ff"),
        "validate": ("04", "Safety validation",  "#ffd33d"),
        "simulate": ("05", "Physics simulation", "#f87171"),
    }

    progress_placeholder = st.empty()
    result = None

    try:
        with httpx.Client(timeout=120.0) as client:
            with client.stream("POST", f"{API_BASE_LOCAL}/api/v1/generate/stream",
                json={
                    "instruction":    instruction.strip(),
                    "doc_type_filter":doc_val,
                    "top_k_chunks":   top_k,
                    "return_sources": src_on,
                    "run_sim":        sim_btn,
                }) as resp:
                if resp.status_code == 200:
                    for line in resp.iter_lines():
                        if not line.startswith("data:"):
                            continue
                        try:
                            evt = _json.loads(line[5:].strip())
                        except Exception:
                            continue

                        if evt.get("event") == "stage":
                            num, label, color = stage_labels.get(
                                evt["stage"], ("??", evt["stage"], "#888898"))
                            pct = evt.get("pct", 0)
                            progress_placeholder.markdown(f"""
                            <div style="background:rgba(0,240,200,0.02);border:1px solid rgba(0,240,200,0.1);
                                border-radius:10px;padding:1rem 1.25rem;margin:0.5rem 0;">
                                <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
                                    <div style="width:24px;height:24px;border-radius:50%;
                                        background:{color}22;border:1px solid {color};
                                        display:flex;align-items:center;justify-content:center;">
                                        <span style="font-family:Orbitron,monospace;font-size:0.55rem;color:{color};">{num}</span>
                                    </div>
                                    <span style="font-family:JetBrains Mono,monospace;font-size:0.75rem;
                                        color:{color};letter-spacing:0.06em;">{label.upper()}</span>
                                    <span style="font-size:0.7rem;color:rgba(160,185,205,0.4);margin-left:auto;">{pct}%</span>
                                </div>
                                <div style="background:rgba(255,255,255,0.05);border-radius:2px;height:4px;overflow:hidden;">
                                    <div style="background:{color};height:100%;width:{pct}%;
                                        box-shadow:0 0 8px {color};transition:width 0.3s;"></div>
                                </div>
                            </div>""", unsafe_allow_html=True)

                        elif evt.get("event") == "complete":
                            result = evt.get("protocol")
                            progress_placeholder.empty()

                        elif evt.get("event") == "error":
                            progress_placeholder.empty()
                            st.error(f"Generation error: {evt.get('message','unknown')}")
                else:
                    raise Exception(f"HTTP {resp.status_code}")

    except Exception as e:
        progress_placeholder.empty()
        # Fallback to standard (non-streaming) endpoint
        result = api_post("/api/v1/generate", json={
            "instruction":    instruction.strip(),
            "doc_type_filter":doc_val,
            "top_k_chunks":   top_k,
            "return_sources": src_on,
        })

    if result:
        if "protocol_history" not in st.session_state:
            st.session_state.protocol_history = []
        st.session_state.protocol_history.insert(0, result)
        st.session_state.last_protocol   = result
        st.session_state.last_sim_result = result.pop("sim_result", None)
        if sim_btn and not st.session_state.last_sim_result:
            pid = result.get("protocol_id","")
            with st.spinner(f"// SIMULATING [{sim_mode.upper()}]"):
                sr = api_post(f"/api/v1/execute/{pid}",
                              json={"sim_mode":sim_mode}, silent=True)
            st.session_state.last_sim_result = sr
        st.rerun()

# ── Display ───────────────────────────────────────────────────────────────────
if "last_protocol" in st.session_state:
    p = st.session_state.last_protocol
    divider()
    render_protocol_header(p)

    for note in p.get("safety_notes",[]):
        st.markdown(f'<div style="background:rgba(255,211,61,0.06);border:1px solid rgba(255,211,61,0.18);border-radius:8px;padding:10px 14px;margin:8px 0;font-size:0.8rem;color:#ffd33d;letter-spacing:0.02em;">⚠ {note}</div>', unsafe_allow_html=True)

    sr = st.session_state.get("last_sim_result")
    if sr:
        passed = sr.get("passed", sr.get("simulation_passed", False))
        bg     = "rgba(0,240,200,0.06)"  if passed else "rgba(248,113,113,0.06)"
        border = "rgba(0,240,200,0.2)"   if passed else "rgba(248,113,113,0.2)"
        glow   = "rgba(0,240,200,0.1)"   if passed else "rgba(248,113,113,0.1)"
        color  = "#00f0c8"               if passed else "#f87171"
        icon   = "✓" if passed else "✗"
        cmds   = sr.get("command_count", sr.get("commands_executed","?"))
        eng    = sr.get("physics_engine", sim_mode)
        st.markdown(f"""
        <div style="background:{bg};border:1px solid {border};border-radius:8px;padding:10px 16px;margin:8px 0;box-shadow:0 0 20px {glow};">
            <span style="font-family:'Orbitron',monospace;font-size:0.72rem;font-weight:700;color:{color};text-shadow:0 0 10px {color};">{icon} SIM {'PASS' if passed else 'FAIL'}</span>
            <span style="font-family:'JetBrains Mono',monospace;font-size:0.65rem;color:rgba(160,185,205,0.4);margin-left:14px;">{cmds} CMDS · ENGINE:{eng.upper()}</span>
        </div>""", unsafe_allow_html=True)

    divider()
    kpi_row([
        (len(p.get("steps",[])),        "Steps",          "#00f0c8"),
        (len(p.get("reagents",[])),     "Reagents",       "#6c4cdc"),
        (len(p.get("equipment",[])),    "Equipment",      "#00b8ff"),
        (len(p.get("sources_used",[])), "Sources cited",  "#ffd33d"),
    ])
    divider()

    main_col, side_col = st.columns([3, 1], gap="large")
    with main_col:
        section_label("Protocol steps")
        for step in p.get("steps",[]): render_step_card(step)

    with side_col:
        if p.get("reagents"):
            section_label("Reagents")
            for r in p["reagents"]:
                st.markdown(f"<div style='font-size:0.78rem;color:rgba(208,228,240,0.7);padding:5px 0;border-bottom:1px solid rgba(0,240,200,0.06);font-family:JetBrains Mono,monospace;'>· {r}</div>", unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)
        if p.get("equipment"):
            section_label("Equipment")
            for eq in p["equipment"]:
                st.markdown(f"<div style='font-size:0.78rem;color:rgba(208,228,240,0.7);padding:5px 0;border-bottom:1px solid rgba(0,240,200,0.06);font-family:JetBrains Mono,monospace;'>· {eq}</div>", unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)
        if p.get("sources_used"):
            section_label("Sources")
            for src in p["sources_used"]:
                pct = int(src.get("score",0)*100)
                st.markdown(f"""
                <div style="background:rgba(0,240,200,0.02);border:1px solid rgba(0,240,200,0.07);border-radius:8px;padding:9px 12px;margin:4px 0;">
                    <div style="font-family:'JetBrains Mono',monospace;color:#6c4cdc;font-size:0.65rem;margin-bottom:3px;">{src.get('source_id','')}</div>
                    <div style="color:rgba(208,228,240,0.7);font-size:0.75rem;">{src.get('filename','')}</div>
                    <div style="font-family:'JetBrains Mono',monospace;color:rgba(160,185,205,0.3);font-size:0.62rem;margin-top:3px;">{src.get('section','') or '—'} p.{src.get('page_start','?')} · {pct}%</div>
                </div>""", unsafe_allow_html=True)

    divider()
    export_buttons(p, key_prefix="gen")

    # ── Opentrons OT-2 export ─────────────────────────────────────────────────
    try:
        from services.translation_service.core.opentrons_exporter import export_opentrons_script
        ot2_script = export_opentrons_script(p)
        ot2_col, _ = st.columns([1, 3])
        with ot2_col:
            st.download_button(
                "⬇ OT-2 Python Script",
                data=ot2_script,
                file_name=f"aurolab_{p.get('protocol_id','x')[:8]}.py",
                mime="text/x-python",
                key="gen_ot2",
                help="Load in Opentrons App → calibrate → run on OT-2",
            )
        st.markdown(
            '<div style="font-family:JetBrains Mono,monospace;font-size:0.62rem;'
            'color:rgba(160,185,205,0.3);margin-top:2px;">'
            '// Runnable on physical OT-2 — load in Opentrons App</div>',
            unsafe_allow_html=True)
    except ImportError:
        pass