"""dashboard/pages/14_workflows.py — Multi-Protocol Workflow Chains"""
import sys
from pathlib import Path
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'dashboard'))
from shared import inject_css, render_nav, hero, api_get, api_post, kpi_row, divider, section_label, badge

st.set_page_config(page_title="Workflows — AuroLab", page_icon="⚗", layout="wide",
                   initial_sidebar_state="collapsed")
inject_css()
render_nav("workflows")

hero("WORKFLOW CHAINS",
     "Connect multiple protocols into automated sequences — output of one step feeds into the next",
     accent="#a89ef8", tag="Chain · Sequence · Automate")

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from services.translation_service.core.workflow_engine import WorkflowEngine, WorkflowStep
engine = WorkflowEngine("./data/workflows.db")

history = st.session_state.get("protocol_history", [])
workflows = engine.list_workflows()

kpi_row([
    (len(workflows),    "Workflows defined", "#a89ef8"),
    (len(history),      "Available protocols","#00f0c8"),
    (len(engine.list_runs()), "Total runs",  "#ffd33d"),
])
divider()

left, right = st.columns([2, 3], gap="large")

with left:
    section_label("Create workflow")
    wf_name = st.text_input("Workflow name", placeholder="e.g. Protein Quantification → Western Blot")
    wf_desc = st.text_area("Description", height=70, placeholder="What this workflow accomplishes...")

    if history:
        opts = {f"{p.get('title','?')} ({p.get('protocol_id','')[:6]})": p for p in history}
        st.markdown("<div style='font-size:0.7rem;color:rgba(160,185,205,0.4);margin:8px 0 4px;'>Add steps:</div>", unsafe_allow_html=True)

        if "wf_steps" not in st.session_state:
            st.session_state.wf_steps = []

        step_sel  = st.selectbox("Protocol", list(opts.keys()), label_visibility="collapsed")
        cond      = st.selectbox("Condition", ["always","on_pass","on_fail"], label_visibility="collapsed")
        step_name = st.text_input("Step name", placeholder="e.g. Measure concentration")

        add_col, clear_col = st.columns(2)
        with add_col:
            if st.button("+ Add step", use_container_width=True):
                p = opts[step_sel]
                st.session_state.wf_steps.append({
                    "name":       step_name or step_sel.split("(")[0].strip(),
                    "protocol_id": p.get("protocol_id",""),
                    "condition":  cond,
                    "step_index": len(st.session_state.wf_steps),
                })
        with clear_col:
            if st.button("Clear", use_container_width=True):
                st.session_state.wf_steps = []

        # Show current steps
        if st.session_state.wf_steps:
            st.markdown("<br>", unsafe_allow_html=True)
            section_label("Workflow steps")
            for i, s in enumerate(st.session_state.wf_steps):
                cond_color = {"always":"#00f0c8","on_pass":"#4ade80","on_fail":"#f87171"}.get(s["condition"],"#888898")
                st.markdown(f"""
                <div style="background:rgba(168,142,248,0.04);border:1px solid rgba(168,142,248,0.1);
                    border-left:2px solid {cond_color};border-radius:0 8px 8px 0;
                    padding:7px 10px;margin:4px 0;font-size:0.78rem;color:#c0c8e8;">
                    <span style="font-family:'JetBrains Mono',monospace;color:{cond_color};font-size:0.6rem;">{i+1:02d} [{s['condition']}]</span>
                    &nbsp; {s['name']}
                </div>""", unsafe_allow_html=True)

            if wf_name and st.button("💾 Save workflow", type="primary", use_container_width=True):
                steps = [WorkflowStep(
                    step_index=s["step_index"], name=s["name"],
                    protocol_id=s["protocol_id"], condition=s["condition"]
                ) for s in st.session_state.wf_steps]
                wid = engine.create_workflow(wf_name, steps, wf_desc)
                st.success(f"Workflow saved: {wid[:8]}")
                st.session_state.wf_steps = []
                st.rerun()
    else:
        st.info("Generate some protocols first to add as workflow steps.")

with right:
    section_label("Defined workflows")
    if not workflows:
        st.markdown("""
        <div style="text-align:center;padding:3rem;color:rgba(160,185,205,0.35);">
            <div style="font-size:2rem;margin-bottom:0.8rem;">🔗</div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:0.82rem;">No workflows yet</div>
            <div style="font-size:0.72rem;margin-top:4px;">Create one on the left</div>
        </div>""", unsafe_allow_html=True)
    else:
        for wf in workflows:
            wid = wf["workflow_id"]
            wf_detail = engine.get_workflow(wid)
            n_steps = len(wf_detail.get("steps",[])) if wf_detail else 0
            runs = engine.list_runs(wid)
            n_runs = len(runs)
            last_status = runs[0]["status"] if runs else "never run"
            status_color = {"completed":"#4ade80","running":"#00b8ff","failed":"#f87171"}.get(last_status,"#555568")

            with st.expander(f"{wf['name']} · {n_steps} steps"):
                if wf.get("description"):
                    st.markdown(f"<div style='font-size:0.8rem;color:rgba(160,185,205,0.5);margin-bottom:8px;'>{wf['description']}</div>", unsafe_allow_html=True)

                if wf_detail:
                    for s in wf_detail.get("steps",[]):
                        cond_c = {"always":"#00f0c8","on_pass":"#4ade80","on_fail":"#f87171"}.get(s.get("condition","always"),"#888898")
                        st.markdown(f"""
                        <div style="display:flex;gap:8px;padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.04);font-size:0.78rem;">
                            <span style="font-family:'JetBrains Mono',monospace;color:{cond_c};font-size:0.6rem;min-width:60px;">[{s.get('condition','always')}]</span>
                            <span style="color:#c0c8e8;">{s.get('name','?')}</span>
                        </div>""", unsafe_allow_html=True)

                bc1, bc2, bc3 = st.columns(3)
                with bc1:
                    if st.button("▶ Run", key=f"run_{wid[:8]}", use_container_width=True):
                        try:
                            run = engine.start_run(wid)
                            protocol_registry = {p.get("protocol_id",""): p for p in history}
                            if hasattr(p, 'model_dump'): pass
                            for i in range(n_steps):
                                result = engine.execute_step(run, i, protocol_registry, "mock")
                                run.results[i] = result
                                if result.status == "failed" and wf_detail["steps"][i].get("condition") == "on_pass":
                                    break
                            run.status = "completed" if all(r.status in ("passed","skipped") for r in run.results) else "failed"
                            st.session_state[f"wf_run_{wid}"] = run.to_dict()
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))
                with bc2:
                    st.markdown(f"<div style='font-size:0.7rem;font-family:JetBrains Mono,monospace;color:rgba(160,185,205,0.3);padding-top:6px;'>{n_runs} runs · {last_status}</div>", unsafe_allow_html=True)
                with bc3:
                    if st.button("Delete", key=f"del_{wid[:8]}", use_container_width=True):
                        engine.delete_workflow(wid)
                        st.rerun()

                # Show last run result
                run_data = st.session_state.get(f"wf_run_{wid}")
                if run_data:
                    st.markdown("<br>", unsafe_allow_html=True)
                    for sr in run_data.get("results",[]):
                        sc = {"passed":"#4ade80","failed":"#f87171","skipped":"#ffd33d","pending":"#555568"}.get(sr["status"],"#888898")
                        st.markdown(f"""
                        <div style="display:flex;align-items:center;gap:8px;padding:4px 0;">
                            <div style="width:6px;height:6px;border-radius:50%;background:{sc};"></div>
                            <span style="font-size:0.78rem;color:#c0c8e8;flex:1;">{sr['name']}</span>
                            <span style="font-family:'JetBrains Mono',monospace;font-size:0.65rem;color:{sc};">{sr['status'].upper()}</span>
                        </div>""", unsafe_allow_html=True)