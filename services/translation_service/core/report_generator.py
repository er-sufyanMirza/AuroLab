"""
core/report_generator.py

Protocol report generator for AuroLab.
Generates a self-contained HTML report for any protocol — suitable for
printing, archiving, or sharing with collaborators.

Report includes:
  - Protocol metadata and confidence score
  - Safety summary
  - Full step-by-step instructions with citations
  - Reagents and equipment list
  - Source bibliography
  - Analytics if available (cost, sustainability)
  - Generation provenance (model, RAG strategy, timestamp)
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any


def _safe(text: str) -> str:
    """Escape HTML special characters."""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def _safety_color(level: str) -> str:
    return {"safe": "#4ade80", "caution": "#ffd33d",
            "warning": "#fbbf24", "hazardous": "#f87171"}.get(level, "#888898")


def _conf_color(conf: float) -> str:
    if conf >= 0.8:  return "#4ade80"
    if conf >= 0.6:  return "#ffd33d"
    return "#f87171"


def generate_html_report(
    protocol: dict,
    analytics: dict | None = None,
    sim_result: dict | None = None,
    include_provenance: bool = True,
) -> str:
    """
    Generate a self-contained HTML report for a protocol.

    Args:
        protocol:    GeneratedProtocol dict.
        analytics:   Optional EfficiencyReport dict from analytics engine.
        sim_result:  Optional SimulationResult dict.
        include_provenance: Include generation metadata section.

    Returns:
        Full HTML string (self-contained, no external dependencies).
    """
    pid       = protocol.get("protocol_id", "unknown")[:8]
    title     = _safe(protocol.get("title", "Untitled Protocol"))
    desc      = _safe(protocol.get("description", ""))
    steps     = protocol.get("steps", [])
    reagents  = protocol.get("reagents", [])
    equipment = protocol.get("equipment", [])
    safety    = protocol.get("safety_level", "safe")
    notes     = protocol.get("safety_notes", [])
    sources   = protocol.get("sources_used", [])
    conf      = protocol.get("confidence_score", 0.0)
    model     = _safe(protocol.get("model_used", ""))
    gen_ms    = protocol.get("generation_ms", 0.0)
    now       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    safety_col = _safety_color(safety)
    conf_col   = _conf_color(conf)
    conf_pct   = int(conf * 100)

    # ── Steps HTML ────────────────────────────────────────────────────────────
    steps_html = ""
    for step in steps:
        sn      = step.get("step_number", "?")
        inst    = _safe(step.get("instruction", ""))
        cites   = ", ".join(_safe(c) for c in step.get("citations", [])) or "GENERAL"
        snote   = step.get("safety_note", "")
        metas   = []
        if step.get("duration_seconds"):
            m, s = divmod(int(step["duration_seconds"]), 60)
            metas.append(f"{m}m {s}s" if m else f"{s}s")
        if step.get("temperature_celsius") is not None:
            metas.append(f"{step['temperature_celsius']}°C")
        if step.get("volume_ul") is not None:
            metas.append(f"{step['volume_ul']} µL")
        meta_str = " · ".join(metas)
        sn_warn = f'<div class="step-warn">⚠ {_safe(snote)}</div>' if snote else ""
        steps_html += f"""
        <div class="step">
            <div class="step-header">
                <span class="step-num">Step {sn}</span>
                {f'<span class="step-meta">{meta_str}</span>' if meta_str else ''}
                <span class="step-cite">↗ {cites}</span>
            </div>
            <div class="step-inst">{inst}</div>
            {sn_warn}
        </div>"""

    # ── Safety notes HTML ─────────────────────────────────────────────────────
    safety_html = ""
    if notes:
        items = "".join(f"<li>{_safe(n)}</li>" for n in notes)
        safety_html = f'<div class="safety-box"><strong>⚠ Safety notes:</strong><ul>{items}</ul></div>'

    # ── Reagents + Equipment ──────────────────────────────────────────────────
    def _list_html(items: list[str]) -> str:
        return "".join(f"<li>{_safe(i)}</li>" for i in items) if items else "<li>—</li>"

    # ── Sources bibliography ──────────────────────────────────────────────────
    sources_html = ""
    if sources:
        rows = ""
        for i, src in enumerate(sources, 1):
            pct = int(src.get("score", 0) * 100)
            rows += f"""
            <tr>
                <td class="src-id">[SOURCE_{i}]</td>
                <td>{_safe(src.get('filename',''))}</td>
                <td>{_safe(src.get('section','') or '—')}</td>
                <td>p.{src.get('page_start','?')}</td>
                <td>{pct}%</td>
            </tr>"""
        sources_html = f"""
        <h2>Source bibliography</h2>
        <table class="src-table">
            <thead><tr><th>ID</th><th>Document</th><th>Section</th><th>Page</th><th>Relevance</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>"""

    # ── Analytics section ─────────────────────────────────────────────────────
    analytics_html = ""
    if analytics:
        cost_saved = analytics.get("cost_saved_usd", 0)
        time_saved = analytics.get("time_saved_min", 0)
        robot_cost = analytics.get("robot_cost_usd", 0)
        plastic_g  = analytics.get("plastic_g", 0)
        co2_g      = analytics.get("co2_g", 0)
        p_rating   = analytics.get("plastic_rating", "?")
        e_rating   = analytics.get("energy_rating", "?")
        analytics_html = f"""
        <h2>Analytics</h2>
        <div class="analytics-grid">
            <div class="ana-card"><div class="ana-val green">${cost_saved:.2f}</div><div class="ana-lbl">Cost saved vs manual</div></div>
            <div class="ana-card"><div class="ana-val green">{time_saved:.0f} min</div><div class="ana-lbl">Time saved</div></div>
            <div class="ana-card"><div class="ana-val">${robot_cost:.4f}</div><div class="ana-lbl">Robot cost</div></div>
            <div class="ana-card"><div class="ana-val amber">{plastic_g:.1f} g</div><div class="ana-lbl">Plastic waste</div></div>
            <div class="ana-card"><div class="ana-val amber">{co2_g:.1f} g</div><div class="ana-lbl">CO₂ equivalent</div></div>
            <div class="ana-card"><div class="ana-val">{p_rating} / {e_rating}</div><div class="ana-lbl">Plastic / Energy rating</div></div>
        </div>"""

    # ── Simulation section ────────────────────────────────────────────────────
    sim_html = ""
    if sim_result:
        passed  = sim_result.get("passed", sim_result.get("simulation_passed", False))
        sc      = "#4ade80" if passed else "#f87171"
        st_text = "PASSED" if passed else "FAILED"
        cmds    = sim_result.get("commands_executed", sim_result.get("command_count", "?"))
        engine  = sim_result.get("physics_engine", sim_result.get("sim_mode", "?"))
        sim_html = f"""
        <h2>Simulation result</h2>
        <div class="sim-box" style="border-color:{sc}22;background:{sc}11;">
            <span style="color:{sc};font-weight:700;">{st_text}</span>
            &nbsp;·&nbsp; {cmds} commands &nbsp;·&nbsp; engine: {_safe(str(engine))}
        </div>"""

    # ── Provenance ────────────────────────────────────────────────────────────
    prov_html = ""
    if include_provenance:
        prov_html = f"""
        <h2>Generation provenance</h2>
        <table class="prov-table">
            <tr><th>Protocol ID</th><td>{pid}</td></tr>
            <tr><th>Generated at</th><td>{now}</td></tr>
            <tr><th>LLM model</th><td>{model}</td></tr>
            <tr><th>Generation time</th><td>{gen_ms:.0f} ms</td></tr>
            <tr><th>RAG sources</th><td>{len(sources)} chunks retrieved</td></tr>
            <tr><th>Confidence</th><td>{conf_pct}%</td></tr>
            <tr><th>Safety classification</th><td style="color:{safety_col}">{safety.upper()}</td></tr>
            <tr><th>Generated by</th><td>AuroLab v2.0 — Autonomous Physical AI</td></tr>
        </table>"""

    # ── Full HTML document ────────────────────────────────────────────────────
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — AuroLab Report</title>
<style>
  :root {{
    --bg: #f8f9fa; --card: #ffffff; --border: #e2e8f0;
    --text: #1a202c; --muted: #64748b;
    --green: #16a34a; --amber: #d97706; --red: #dc2626;
    --accent: #6d28d9;
  }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
         background:var(--bg); color:var(--text); line-height:1.6; }}
  .page {{ max-width:900px; margin:0 auto; padding:2rem 1.5rem; }}
  .header {{ border-bottom:3px solid var(--accent); padding-bottom:1.5rem; margin-bottom:2rem; }}
  .header-top {{ display:flex; align-items:flex-start; justify-content:space-between; }}
  .logo {{ font-size:0.75rem; font-weight:700; letter-spacing:0.15em;
           color:var(--accent); text-transform:uppercase; margin-bottom:0.5rem; }}
  h1 {{ font-size:1.8rem; font-weight:700; color:var(--text); margin-bottom:0.4rem; }}
  .desc {{ color:var(--muted); font-size:0.95rem; max-width:600px; }}
  .badges {{ display:flex; gap:8px; margin-top:1rem; flex-wrap:wrap; }}
  .badge {{ padding:3px 12px; border-radius:100px; font-size:0.75rem; font-weight:600;
            border:1px solid; letter-spacing:0.04em; }}
  .conf-bar {{ margin-top:0.75rem; }}
  .conf-track {{ background:#e2e8f0; border-radius:4px; height:6px; width:200px; }}
  .conf-fill {{ height:100%; border-radius:4px; }}
  .conf-label {{ font-size:0.75rem; color:var(--muted); margin-top:3px; }}
  h2 {{ font-size:1.1rem; font-weight:600; color:var(--text);
        border-bottom:1px solid var(--border); padding-bottom:0.4rem;
        margin:2rem 0 1rem; }}
  .step {{ background:var(--card); border:1px solid var(--border);
           border-left:3px solid var(--accent); border-radius:0 8px 8px 0;
           padding:0.9rem 1.1rem; margin:0.5rem 0; }}
  .step-header {{ display:flex; align-items:center; gap:10px; margin-bottom:5px; flex-wrap:wrap; }}
  .step-num {{ font-size:0.7rem; font-weight:700; color:var(--accent);
               text-transform:uppercase; letter-spacing:0.08em; }}
  .step-meta {{ font-size:0.72rem; color:var(--muted);
                background:#f1f5f9; padding:1px 8px; border-radius:100px; }}
  .step-cite {{ font-size:0.68rem; color:#059669; margin-left:auto; }}
  .step-inst {{ font-size:0.92rem; color:var(--text); }}
  .step-warn {{ background:#fef9c3; border:1px solid #fde047; border-radius:4px;
                padding:5px 10px; margin-top:6px; font-size:0.8rem; color:#92400e; }}
  .safety-box {{ background:#fef2f2; border:1px solid #fecaca; border-radius:8px;
                 padding:12px 16px; margin:1rem 0; font-size:0.88rem; color:#991b1b; }}
  .safety-box ul {{ margin:6px 0 0 1.2rem; }}
  .two-col {{ display:grid; grid-template-columns:1fr 1fr; gap:1.5rem; }}
  .list-card {{ background:var(--card); border:1px solid var(--border);
                border-radius:8px; padding:1rem; }}
  .list-card h3 {{ font-size:0.8rem; font-weight:600; color:var(--muted);
                   text-transform:uppercase; letter-spacing:0.08em; margin-bottom:8px; }}
  .list-card ul {{ list-style:none; padding:0; }}
  .list-card li {{ font-size:0.88rem; padding:4px 0;
                   border-bottom:1px solid var(--border); }}
  .list-card li:last-child {{ border-bottom:none; }}
  .list-card li::before {{ content:'·'; color:var(--accent); margin-right:8px; }}
  .src-table, .prov-table {{ width:100%; border-collapse:collapse; font-size:0.85rem; }}
  .src-table th, .prov-table th {{
    background:#f1f5f9; text-align:left; padding:8px 12px;
    font-size:0.75rem; font-weight:600; color:var(--muted);
    text-transform:uppercase; letter-spacing:0.06em; }}
  .src-table td, .prov-table td {{ padding:8px 12px; border-bottom:1px solid var(--border); }}
  .src-id {{ font-family:monospace; color:var(--accent); font-weight:600; }}
  .prov-table th {{ width:200px; }}
  .analytics-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }}
  .ana-card {{ background:var(--card); border:1px solid var(--border);
               border-radius:8px; padding:0.9rem; text-align:center; }}
  .ana-val {{ font-size:1.3rem; font-weight:700; color:var(--text); }}
  .ana-val.green {{ color:var(--green); }}
  .ana-val.amber {{ color:var(--amber); }}
  .ana-lbl {{ font-size:0.72rem; color:var(--muted); margin-top:3px; }}
  .sim-box {{ border:1px solid; border-radius:8px; padding:10px 16px;
              font-size:0.9rem; margin:0.5rem 0; }}
  .footer {{ border-top:1px solid var(--border); margin-top:3rem; padding-top:1rem;
             font-size:0.75rem; color:var(--muted); text-align:center; }}
  .green {{ color:var(--green); }}
  .amber {{ color:var(--amber); }}
  @media print {{
    body {{ background:white; }}
    .page {{ padding:1rem; }}
    .step {{ break-inside:avoid; }}
  }}
</style>
</head>
<body>
<div class="page">

  <div class="header">
    <div class="logo">⚗ AuroLab — Protocol Report</div>
    <div class="header-top">
      <div>
        <h1>{title}</h1>
        <p class="desc">{desc}</p>
        <div class="badges">
          <span class="badge" style="color:{safety_col};border-color:{safety_col}44;background:{safety_col}11;">{safety.upper()}</span>
          <span class="badge" style="color:{conf_col};border-color:{conf_col}44;background:{conf_col}11;">CONFIDENCE {conf_pct}%</span>
          <span class="badge" style="color:var(--muted);border-color:var(--border);">{len(steps)} STEPS</span>
          <span class="badge" style="color:var(--muted);border-color:var(--border);">{len(reagents)} REAGENTS</span>
        </div>
      </div>
      <div style="text-align:right;font-size:0.75rem;color:var(--muted);white-space:nowrap;margin-left:1rem;">
        <div>ID: {pid}</div>
        <div>{now}</div>
      </div>
    </div>
  </div>

  {safety_html}

  <h2>Protocol steps</h2>
  {steps_html}

  <div class="two-col" style="margin-top:2rem;">
    <div class="list-card">
      <h3>Reagents</h3>
      <ul>{_list_html(reagents)}</ul>
    </div>
    <div class="list-card">
      <h3>Equipment</h3>
      <ul>{_list_html(equipment)}</ul>
    </div>
  </div>

  {sim_html}
  {analytics_html}
  {sources_html}
  {prov_html}

  <div class="footer">
    Generated by AuroLab v2.0 — Autonomous Physical AI Lab Automation System<br>
    Protocol ID: {pid} · {now}
  </div>

</div>
</body>
</html>"""


def generate_markdown_report(protocol: dict) -> str:
    """Generate a clean Markdown report for documentation or GitHub."""
    pid      = protocol.get("protocol_id","unknown")[:8]
    title    = protocol.get("title","Untitled Protocol")
    desc     = protocol.get("description","")
    steps    = protocol.get("steps", [])
    reagents = protocol.get("reagents", [])
    equipment= protocol.get("equipment", [])
    safety   = protocol.get("safety_level","safe").upper()
    conf     = protocol.get("confidence_score", 0.0)
    notes    = protocol.get("safety_notes", [])
    sources  = protocol.get("sources_used", [])
    model    = protocol.get("model_used","")
    now      = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        f"# {title}",
        f"",
        f"> **Protocol ID:** `{pid}` · **Safety:** {safety} · **Confidence:** {conf:.0%} · **Generated:** {now}",
        f"",
        f"{desc}",
        f"",
    ]

    if notes:
        lines += ["## ⚠ Safety Notes", ""]
        for n in notes:
            lines.append(f"- {n}")
        lines.append("")

    lines += ["## Protocol Steps", ""]
    for step in steps:
        sn   = step.get("step_number","?")
        inst = step.get("instruction","")
        cite = ", ".join(step.get("citations",[])) or "GENERAL"
        metas = []
        if step.get("duration_seconds"):
            m,s = divmod(int(step["duration_seconds"]),60)
            metas.append(f"{m}m{s}s" if m else f"{s}s")
        if step.get("temperature_celsius") is not None:
            metas.append(f"{step['temperature_celsius']}°C")
        if step.get("volume_ul") is not None:
            metas.append(f"{step['volume_ul']}µL")
        meta_str = f" `{'·'.join(metas)}`" if metas else ""
        lines.append(f"**Step {sn}**{meta_str} _{cite}_")
        lines.append(f"{inst}")
        if step.get("safety_note"):
            lines.append(f"> ⚠ {step['safety_note']}")
        lines.append("")

    if reagents:
        lines += ["## Reagents", ""]
        for r in reagents:
            lines.append(f"- {r}")
        lines.append("")

    if equipment:
        lines += ["## Equipment", ""]
        for e in equipment:
            lines.append(f"- {e}")
        lines.append("")

    if sources:
        lines += ["## Sources", ""]
        for i, src in enumerate(sources, 1):
            pct = int(src.get("score",0)*100)
            lines.append(f"{i}. **{src.get('filename','')}** — {src.get('section','') or '—'} p.{src.get('page_start','?')} ({pct}% relevance)")
        lines.append("")

    lines += [
        "---",
        f"*Generated by AuroLab v2.0 using {model}*",
    ]
    return "\n".join(lines)