"""
dashboard/pages/8_fleet.py — Fleet Orchestration
"""

import streamlit as st
import httpx
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'dashboard'))
from shared import inject_css, render_nav, hero, api_get, api_post, api_delete, kpi_row, divider, section_label, badge, stats_strip, neon_card, render_step_card, render_protocol_header, export_buttons, PLOTLY_DARK


st.set_page_config(page_title="Fleet — AuroLab", page_icon="⚗", layout="wide", initial_sidebar_state="collapsed")
inject_css()
render_nav("fleet")


API_BASE = "http://localhost:8080"

ROBOT_COLORS = {
    "robot_01": "#7c6af7",
    "robot_02": "#22c55e",
    "robot_03": "#f59e0b",
    "robot_04": "#60a5fa",
}

# ---------------------------------------------------------------------------
st.markdown("## Fleet Orchestration")
st.markdown("Schedule multiple protocols across the robot fleet with automatic conflict detection and resolution.")
st.markdown('<hr class="divider">', unsafe_allow_html=True)

left_col, right_col = st.columns([2, 3], gap="large")

# ---------------------------------------------------------------------------
# Left: Robot status + schedule controls
# ---------------------------------------------------------------------------
with left_col:
    st.markdown("#### Robot fleet")

    fleet_status = api_get("/api/v1/fleet/status")
    if not fleet_status:
        st.warning("API unavailable — start the backend first")
    else:
        robots = fleet_status.get("robots", [])
        m1, m2, m3 = st.columns(3)
        m1.markdown(f'<div class="kpi-card"><div class="kpi-value">{len(robots)}</div><div class="kpi-label">Robots</div></div>', unsafe_allow_html=True)
        m2.markdown(f'<div class="kpi-card"><div class="kpi-value" style="color:#22c55e">{fleet_status.get("idle_robots",0)}</div><div class="kpi-label">Idle</div></div>', unsafe_allow_html=True)
        m3.markdown(f'<div class="kpi-card"><div class="kpi-value" style="color:#60a5fa">{fleet_status.get("active_tasks",0)}</div><div class="kpi-label">Running</div></div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        for robot in robots:
            status_val = robot.get("status", "idle")
            status_cls = f"status-{status_val}"
            task = robot.get("current_task_id", "—") or "—"
            color = ROBOT_COLORS.get(robot.get("robot_id",""), "#888898")
            st.markdown(f"""
            <div class="robot-card" style="border-left: 3px solid {color};">
                <div class="robot-name">{robot.get('name','Unknown')}</div>
                <div class="robot-meta">
                    {robot.get('robot_id','')} · {robot.get('location','')}
                </div>
                <div class="{status_cls}" style="margin-top:4px;">{status_val.upper()}</div>
                {f'<div class="robot-meta" style="margin-top:2px;">Task: {task}</div>' if task != '—' else ''}
            </div>
            """, unsafe_allow_html=True)

    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown("#### Schedule protocols")

    # Get plans from execution plan store (via fleet/status not available — use history)
    history = st.session_state.get("protocol_history", [])
    if not history:
        st.info("No protocols generated yet. Generate some protocols first.")
    else:
        plan_options = {
            f"{p.get('title','Untitled')} — {p.get('protocol_id','')[:8]}": p.get("protocol_id","")
            for p in history
        }
        selected = st.multiselect(
            "Select protocols to schedule",
            list(plan_options.keys()),
            label_visibility="collapsed",
        )

        if st.button("Build schedule", disabled=not selected, use_container_width=True):
            # We need plan_ids from the execution plan store
            # Use protocol_ids as plan_ids for now (they match in the store)
            plan_ids = [plan_options[s] for s in selected]
            result = api_post("/api/v1/fleet/schedule", json={"plan_ids": plan_ids})
            if result:
                st.session_state.fleet_schedule = result
                st.success(f"Schedule built — {result.get('task_count',0)} tasks, {result.get('makespan_min',0):.1f} min makespan")
                st.rerun()

    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown("#### Add robot")
    with st.expander("Add a robot to the fleet"):
        new_id   = st.text_input("Robot ID", placeholder="robot_03")
        new_name = st.text_input("Name",     placeholder="AuroBot Gamma")
        new_loc  = st.text_input("Location", placeholder="lab_bench_3")
        if st.button("Add robot") and new_id and new_name:
            result = api_post("/api/v1/fleet/robots", json={
                "robot_id": new_id, "name": new_name, "location": new_loc or "lab_bench_1"
            })
            if result:
                st.success(f"Robot added — fleet size: {result.get('fleet_size',0)}")
                st.rerun()

# ---------------------------------------------------------------------------
# Right: Gantt chart + schedule details
# ---------------------------------------------------------------------------
with right_col:
    schedule = st.session_state.get("fleet_schedule")

    if not schedule or not schedule.get("tasks"):
        # Try loading from API
        schedule = api_get("/api/v1/fleet/schedule")
        if schedule and schedule.get("tasks"):
            st.session_state.fleet_schedule = schedule

    if not schedule or not schedule.get("tasks"):
        st.markdown("""
        <div style='text-align:center; padding:64px; color:#444458;'>
            <div style='font-size:2em; margin-bottom:12px;'>🤖</div>
            <div style='font-family:JetBrains Mono,monospace; font-size:0.85em;'>No schedule computed yet.</div>
            <div style='font-size:0.8em; margin-top:6px;'>Select protocols and click Build schedule.</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        tasks = schedule.get("tasks", [])
        conflicts = schedule.get("conflicts", [])
        makespan  = schedule.get("makespan_min", 0)
        utilisation = schedule.get("robot_utilisation", {})

        # Summary metrics
        s1, s2, s3 = st.columns(3)
        s1.markdown(f'<div class="kpi-card"><div class="kpi-value">{len(tasks)}</div><div class="kpi-label">Tasks</div></div>', unsafe_allow_html=True)
        s2.markdown(f'<div class="kpi-card"><div class="kpi-value">{makespan:.1f}m</div><div class="kpi-label">Makespan</div></div>', unsafe_allow_html=True)
        conflict_free = schedule.get("is_conflict_free", True)
        cf_color = "#22c55e" if conflict_free else "#f59e0b"
        s3.markdown(f'<div class="kpi-card"><div class="kpi-value" style="color:{cf_color}">{"✓" if conflict_free else len(conflicts)}</div><div class="kpi-label">{"Conflict free" if conflict_free else "Conflicts"}</div></div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("#### Gantt — task timeline")

        # Build Gantt
        fig = go.Figure()
        epoch = min(t["start_time_s"] for t in tasks) if tasks else 0

        for task in tasks:
            rid    = task.get("robot_id", "unknown")
            color  = ROBOT_COLORS.get(rid, "#888898")
            start  = (task["start_time_s"] - epoch) / 60
            end    = (task["end_time_s"]   - epoch) / 60
            title  = task.get("protocol_title", task.get("plan_id",""))[:30]

            fig.add_trace(go.Bar(
                name=rid,
                x=[end - start],
                y=[rid],
                base=[start],
                orientation="h",
                marker_color=color,
                marker_line_color="rgba(0,0,0,0)",
                text=title,
                textposition="inside",
                textfont=dict(size=9, color="#ffffff"),
                hovertemplate=(
                    f"<b>{title}</b><br>"
                    f"Robot: {rid}<br>"
                    f"Start: {start:.1f}m<br>"
                    f"End: {end:.1f}m<br>"
                    f"Duration: {end-start:.1f}m<extra></extra>"
                ),
                showlegend=False,
            ))

        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="#0a0a0e",
            font=dict(family="JetBrains Mono, monospace", color="#888898", size=10),
            xaxis=dict(title="Minutes from schedule start", gridcolor="#1a1a22",
                       linecolor="#2a2a38", tickfont=dict(color="#666680")),
            yaxis=dict(gridcolor="#1a1a22", linecolor="#2a2a38",
                       tickfont=dict(color="#c0c0cc")),
            barmode="overlay",
            height=max(200, len(set(t["robot_id"] for t in tasks)) * 80 + 60),
            margin=dict(l=0, r=0, t=8, b=0),
        )
        st.plotly_chart(fig, use_container_width=True)

        # Robot utilisation
        if utilisation:
            st.markdown("#### Robot utilisation")
            util_fig = go.Figure(go.Bar(
                x=list(utilisation.keys()),
                y=[v * 100 for v in utilisation.values()],
                marker_color=[ROBOT_COLORS.get(rid, "#888898") for rid in utilisation],
                marker_line_color="rgba(0,0,0,0)",
                text=[f"{v*100:.0f}%" for v in utilisation.values()],
                textposition="outside",
                textfont=dict(size=10, color="#888898"),
            ))
            util_fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="#0a0a0e",
                font=dict(family="JetBrains Mono, monospace", color="#888898", size=10),
                xaxis=dict(gridcolor="#1a1a22"),
                yaxis=dict(range=[0, 110], title="Utilisation %", gridcolor="#1a1a22"),
                height=200,
                margin=dict(l=0, r=0, t=8, b=0),
                showlegend=False,
            )
            st.plotly_chart(util_fig, use_container_width=True)

        # Conflicts
        if conflicts:
            st.markdown("#### Conflicts")
            for c in conflicts:
                is_resolved = c.get("resolution") != "unresolved"
                cls = "resolved-row" if is_resolved else "conflict-row"
                icon = "✓" if is_resolved else "⚠"
                st.markdown(
                    f"<div class='{cls}'>{icon} {c.get('task_a','')} × {c.get('task_b','')} "
                    f"— {c.get('resource','')} — {c.get('resolution_detail','')}</div>",
                    unsafe_allow_html=True,
                )

        # Task table
        st.markdown("#### Task assignments")
        rows = []
        for t in sorted(tasks, key=lambda x: x["start_time_s"]):
            start_min  = (t["start_time_s"] - epoch) / 60
            robot_id   = t["robot_id"]
            robot_color = ROBOT_COLORS.get(robot_id, "#888898")
            rows.append(
                f"<tr>"
                f"<td style='font-family:JetBrains Mono,monospace; color:#7c6af7; padding:6px 12px;'>{t['task_id']}</td>"
                f"<td style='color:#c0c0cc; padding:6px 12px;'>{t['protocol_title'][:28]}</td>"
                f"<td style='font-family:JetBrains Mono,monospace; color:{robot_color}; padding:6px 12px;'>{robot_id}</td>"
                f"<td style='font-family:JetBrains Mono,monospace; color:#888898; padding:6px 12px;'>{start_min:.1f}m</td>"
                f"<td style='font-family:JetBrains Mono,monospace; color:#888898; padding:6px 12px;'>{t['duration_min']:.1f}m</td>"
                f"</tr>"
            )
        st.markdown(f"""
        <table style='width:100%; border-collapse:collapse; font-size:0.82em;'>
            <thead><tr>
                <th style='background:#111118; color:#666680; padding:6px 12px; text-align:left; border-bottom:1px solid #1f1f28;'>Task</th>
                <th style='background:#111118; color:#666680; padding:6px 12px; text-align:left; border-bottom:1px solid #1f1f28;'>Protocol</th>
                <th style='background:#111118; color:#666680; padding:6px 12px; text-align:left; border-bottom:1px solid #1f1f28;'>Robot</th>
                <th style='background:#111118; color:#666680; padding:6px 12px; text-align:left; border-bottom:1px solid #1f1f28;'>Start</th>
                <th style='background:#111118; color:#666680; padding:6px 12px; text-align:left; border-bottom:1px solid #1f1f28;'>Duration</th>
            </tr></thead>
            <tbody>{''.join(rows)}</tbody>
        </table>
        """, unsafe_allow_html=True)