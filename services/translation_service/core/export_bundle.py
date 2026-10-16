"""
core/export_bundle.py

Protocol export bundle for AuroLab.
Packages everything about a protocol into a single downloadable ZIP:

  protocol_{id}/
  ├── protocol.json           — full protocol data
  ├── report.html             — self-contained HTML report
  ├── report.md               — Markdown version
  ├── ot2_script.py           — Opentrons OT-2 Python script
  ├── steps.txt               — plain-text steps for printing
  └── manifest.json           — bundle metadata

Used by: dashboard export buttons and /api/v1/protocols/{id}/bundle
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime
from typing import Any


def create_export_bundle(
    protocol:    dict,
    analytics:   dict | None = None,
    sim_result:  dict | None = None,
) -> bytes:
    """
    Create a ZIP bundle containing all protocol formats.

    Args:
        protocol:   GeneratedProtocol dict.
        analytics:  Optional EfficiencyReport dict.
        sim_result: Optional SimulationResult dict.

    Returns:
        ZIP file as bytes — ready to stream as a download.
    """
    pid   = protocol.get("protocol_id", "unknown")[:8]
    title = protocol.get("title", "Protocol")
    now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_title = "".join(c if c.isalnum() or c in "-_ " else "_" for c in title)[:40]
    folder = f"aurolab_{pid}_{safe_title.replace(' ', '_')}"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:

        # ── protocol.json ─────────────────────────────────────────────────
        zf.writestr(f"{folder}/protocol.json",
                    json.dumps(protocol, indent=2, ensure_ascii=False))

        # ── report.html ───────────────────────────────────────────────────
        try:
            from core.report_generator import generate_html_report
            html = generate_html_report(protocol, analytics=analytics,
                                        sim_result=sim_result, include_provenance=True)
            zf.writestr(f"{folder}/report.html", html)
        except ImportError:
            zf.writestr(f"{folder}/report.html",
                        "<html><body><p>report_generator not available</p></body></html>")

        # ── report.md ─────────────────────────────────────────────────────
        try:
            from core.report_generator import generate_markdown_report
            md = generate_markdown_report(protocol)
            zf.writestr(f"{folder}/report.md", md)
        except ImportError:
            pass

        # ── ot2_script.py ─────────────────────────────────────────────────
        try:
            from services.translation_service.core.opentrons_exporter import export_opentrons_script
            script = export_opentrons_script(protocol)
            zf.writestr(f"{folder}/ot2_script.py", script)
        except ImportError:
            pass

        # ── steps.txt ─────────────────────────────────────────────────────
        lines = [
            f"AuroLab Protocol — {title}",
            f"ID: {pid}  |  Generated: {now}",
            f"Safety: {protocol.get('safety_level','safe').upper()}  |  "
            f"Confidence: {protocol.get('confidence_score',0):.0%}",
            "=" * 60,
            "",
        ]
        for note in protocol.get("safety_notes", []):
            lines.append(f"⚠ SAFETY: {note}")
        if protocol.get("safety_notes"):
            lines.append("")

        lines.append("STEPS")
        lines.append("-" * 40)
        for step in protocol.get("steps", []):
            sn   = step.get("step_number", "?")
            inst = step.get("instruction", "")
            cite = ", ".join(step.get("citations", [])) or "GENERAL"
            metas = []
            if step.get("duration_seconds"):
                m, s = divmod(int(step["duration_seconds"]), 60)
                metas.append(f"{m}m{s}s" if m else f"{s}s")
            if step.get("temperature_celsius") is not None:
                metas.append(f"{step['temperature_celsius']}°C")
            if step.get("volume_ul") is not None:
                metas.append(f"{step['volume_ul']}µL")
            meta = f" [{' · '.join(metas)}]" if metas else ""
            lines.append(f"[{sn}]{meta} {inst}  ({cite})")
            if step.get("safety_note"):
                lines.append(f"    ⚠ {step['safety_note']}")
        lines.append("")

        if protocol.get("reagents"):
            lines.append("REAGENTS")
            lines.append("-" * 40)
            for r in protocol["reagents"]:
                lines.append(f"  · {r}")
            lines.append("")

        if protocol.get("equipment"):
            lines.append("EQUIPMENT")
            lines.append("-" * 40)
            for e in protocol["equipment"]:
                lines.append(f"  · {e}")
            lines.append("")

        if analytics:
            lines.append("ANALYTICS")
            lines.append("-" * 40)
            lines.append(f"  Cost saved vs manual: ${analytics.get('cost_saved_usd',0):.2f}")
            lines.append(f"  Time saved:           {analytics.get('time_saved_min',0):.0f} min")
            lines.append(f"  Robot execution cost: ${analytics.get('robot_cost_usd',0):.4f}")
            lines.append(f"  Plastic waste:        {analytics.get('plastic_g',0):.1f} g")
            lines.append(f"  CO₂ equivalent:       {analytics.get('co2_g',0):.1f} g")
            lines.append("")

        if sim_result:
            passed = sim_result.get("passed", sim_result.get("simulation_passed", False))
            lines.append("SIMULATION")
            lines.append("-" * 40)
            lines.append(f"  Result:  {'PASSED' if passed else 'FAILED'}")
            lines.append(f"  Engine:  {sim_result.get('physics_engine', sim_result.get('sim_mode','?'))}")
            lines.append(f"  Commands:{sim_result.get('commands_executed', sim_result.get('command_count','?'))}")
            lines.append("")

        if protocol.get("sources_used"):
            lines.append("SOURCES")
            lines.append("-" * 40)
            for i, src in enumerate(protocol["sources_used"], 1):
                pct = int(src.get("score", 0) * 100)
                lines.append(f"  [{i}] {src.get('filename','')} — "
                              f"{src.get('section','') or '—'} p.{src.get('page_start','?')} "
                              f"({pct}% relevance)")
            lines.append("")

        lines += ["", f"Generated by AuroLab v2.0 — {now}"]
        zf.writestr(f"{folder}/steps.txt", "\n".join(lines))

        # ── manifest.json ─────────────────────────────────────────────────
        manifest = {
            "bundle_version":  "1.0",
            "created_at":      now,
            "protocol_id":     protocol.get("protocol_id", ""),
            "title":           title,
            "safety_level":    protocol.get("safety_level", "safe"),
            "confidence_score":protocol.get("confidence_score", 0),
            "steps_count":     len(protocol.get("steps", [])),
            "reagents_count":  len(protocol.get("reagents", [])),
            "model_used":      protocol.get("model_used", ""),
            "has_analytics":   analytics is not None,
            "has_sim_result":  sim_result is not None,
            "files": [
                "protocol.json",
                "report.html",
                "report.md",
                "ot2_script.py",
                "steps.txt",
                "manifest.json",
            ],
            "generated_by": "AuroLab v2.0",
        }
        zf.writestr(f"{folder}/manifest.json",
                    json.dumps(manifest, indent=2, ensure_ascii=False))

    buf.seek(0)
    return buf.read()


def bundle_filename(protocol: dict) -> str:
    """Generate a clean filename for the bundle ZIP."""
    pid   = protocol.get("protocol_id", "unknown")[:8]
    title = protocol.get("title", "protocol")
    safe  = "".join(c if c.isalnum() or c in "-_ " else "_" for c in title)[:30]
    return f"aurolab_{pid}_{safe.replace(' ','_')}.zip"