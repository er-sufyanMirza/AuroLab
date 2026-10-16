"""dashboard/pages/21_scheduler.py — Experiment Scheduler"""
import sys
from pathlib import Path
import streamlit as st
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'dashboard'))
from shared import inject_css, render_nav, hero, kpi_row, divider, section_label, badge

st.set_page_config(page_title="Scheduler — AuroLab", page_icon="⚗", layout="wide", initial_sidebar_state="collapsed")
inject_css(); render_nav("scheduler")
hero("EXPERIMENT SCHEDULER", "Schedule recurring protocol runs — daily, weekly, or custom cron expressions", accent="#4ade80", tag="Schedule · Automate · Recurring")

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
try:
    from services.translation_service.core.scheduler_jobs import JobScheduler
    scheduler = JobScheduler("./data/scheduler.db")
except Exception as e:
    st.error(f"Scheduler unavailable: {e}")
    st.stop()

history = st.session_state.get("protocol_history", [])
jobs = scheduler.list_jobs()
kpi_row([(len(jobs),"Scheduled jobs","#4ade80"),(sum(1 for j in jobs if j.get("enabled")),"Active","#00f0c8"),
         (sum(j.get("run_count",0) for j in jobs),"Total runs","#ffd33d")])
divider()

left, right = st.columns([2,3], gap="large")
with left:
    section_label("Add job")
    with st.form("add_job"):
        name = st.text_input("Job name", placeholder="Daily BCA assay")
        if history:
            opts = {p.get("title","?"): p.get("protocol_id","") for p in history}
            proto_sel = st.selectbox("Protocol", list(opts.keys()))
        else:
            st.info("Generate a protocol first"); proto_sel = None
        sched = st.selectbox("Schedule", ["once","hourly","daily","weekly","monthly","custom"])
        cron  = ""
        if sched == "custom":
            cron = st.text_input("Cron expression", placeholder="0 9 * * 1  (Mon 9am)")
        sim_mode = st.selectbox("Sim mode", ["mock","pybullet"])
        if st.form_submit_button("➕ Add job", type="primary", use_container_width=True) and name and proto_sel:
            pid = opts[proto_sel]
            scheduler.add_job(name, pid, sched, cron, sim_mode)
            st.success(f"Scheduled: {name}")
            st.rerun()

with right:
    section_label(f"Scheduled jobs ({len(jobs)})")
    if not jobs:
        st.markdown("<div style='text-align:center;padding:3rem;color:rgba(160,185,205,0.35);font-family:JetBrains Mono,monospace;'>No jobs scheduled yet</div>", unsafe_allow_html=True)
    else:
        for j in jobs:
            enabled = bool(j.get("enabled", 1))
            col = "#4ade80" if enabled else "#555568"
            from datetime import datetime
            last = datetime.fromtimestamp(j["last_run"]).strftime("%Y-%m-%d %H:%M") if j.get("last_run") else "Never"
            with st.expander(f"{'✓' if enabled else '○'} {j['name']} · {j['schedule']}"):
                st.markdown(f"""
                <div style="font-family:'JetBrains Mono',monospace;font-size:0.7rem;color:rgba(160,185,205,0.5);line-height:2;">
                    Protocol ID: {j.get('protocol_id','')[:12]}<br>
                    Schedule: {j.get('schedule','')} {j.get('cron_expr','')}<br>
                    Sim mode: {j.get('sim_mode','mock')}<br>
                    Runs: {j.get('run_count',0)} · Last: {last}
                </div>""", unsafe_allow_html=True)
                bc1, bc2 = st.columns(2)
                with bc1:
                    if st.button("▶ Run now", key=f"run_{j['job_id'][:8]}", use_container_width=True):
                        scheduler._execute_job(j["job_id"]); st.success("Executed"); st.rerun()
                with bc2:
                    if st.button("Delete", key=f"del_{j['job_id'][:8]}", use_container_width=True):
                        scheduler.delete_job(j["job_id"]); st.rerun()
                runs = scheduler.get_job_runs(j["job_id"], limit=5)
                if runs:
                    for r in runs:
                        rc = "#4ade80" if r.get("status")=="completed" else "#f87171"
                        dt = datetime.fromtimestamp(r["started"]).strftime("%m-%d %H:%M")
                        st.markdown(f"<div style='font-family:JetBrains Mono,monospace;font-size:0.65rem;color:{rc};padding:2px 0;'>{dt} · {r.get('status','?')}</div>", unsafe_allow_html=True)