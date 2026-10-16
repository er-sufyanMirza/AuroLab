"""
aurolab/services/analytics_service/api/analytics_router.py

GET  /api/v1/analytics/{protocol_id}   — Compute analytics for one protocol
GET  /api/v1/analytics/aggregate       — Aggregate across all session protocols
POST /api/v1/analytics/compare         — Side-by-side comparison of two protocols
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..core.analytics_engine import AnalyticsEngine
from ..core.analytics_models import AggregateAnalytics, EfficiencyReport

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/analytics", tags=["Analytics"])


class CompareRequest(BaseModel):
    protocol_id_a: str
    protocol_id_b: str


def _get_plan_and_protocol(request: Request, protocol_id: str) -> tuple[dict, dict]:
    """Retrieve plan and protocol from app state by protocol_id."""
    proto_registry: dict = request.app.state.protocol_registry
    plan_store: dict = request.app.state.execution_plan_store

    protocol = proto_registry.get(protocol_id)
    if not protocol:
        raise HTTPException(status_code=404, detail=f"Protocol {protocol_id} not found")

    # Find the matching execution plan
    plan_obj = next(
        (p for p in plan_store.values() if p.protocol_id == protocol_id),
        None,
    )
    plan = plan_obj.model_dump(mode="json") if plan_obj else {
        "protocol_id": protocol_id,
        "estimated_mins": 0,
        "commands": [],
    }

    # Extract telemetry if available
    telemetry = {}
    if plan_obj and plan_obj.simulation_result:
        telemetry = plan_obj.simulation_result.telemetry

    return plan, protocol.model_dump() if hasattr(protocol, "model_dump") else dict(protocol), telemetry


@router.get(
    "/{protocol_id}",
    summary="Compute analytics for a specific protocol",
)
async def get_analytics(protocol_id: str, request: Request) -> dict:
    engine: AnalyticsEngine = request.app.state.analytics_engine

    if engine is None:
        raise HTTPException(status_code=503, detail="Analytics engine not initialised")

    # Look up protocol from protocol_manager (SQLite) first, then registry dict
    protocol = None
    pm = getattr(request.app.state, "protocol_manager", None)
    if pm:
        protocol = pm.get(protocol_id)
    if not protocol:
        proto_registry = getattr(request.app.state, "protocol_registry", {})
        protocol = proto_registry.get(protocol_id)
    if not protocol:
        raise HTTPException(status_code=404, detail=f"Protocol {protocol_id} not found")

    # Get execution plan if available
    plan_store = getattr(request.app.state, "execution_plan_store", {})
    plan_obj   = next((p for p in plan_store.values()
                       if getattr(p, "protocol_id", None) == protocol_id), None)
    plan      = plan_obj.model_dump(mode="json") if plan_obj else {"estimated_mins": 0, "commands": []}
    telemetry = (plan_obj.simulation_result.telemetry
                 if (plan_obj and plan_obj.simulation_result) else {})

    proto_dict = protocol.model_dump() if hasattr(protocol, "model_dump") else dict(protocol)

    report = engine.compute_report(plan, proto_dict, telemetry)

    # Cache in analytics store
    store: dict = getattr(request.app.state, "analytics_store", {})
    store[protocol_id] = report

    return report.to_dict()


@router.get(
    "/",
    summary="Aggregate analytics across all protocols in this session",
)
async def get_aggregate(request: Request) -> dict:
    engine: AnalyticsEngine = request.app.state.analytics_engine
    store: dict = request.app.state.analytics_store

    if not store:
        return AggregateAnalytics().to_dict()

    reports = list(store.values())
    agg = engine.compute_aggregate(reports)
    return agg.to_dict()


@router.post(
    "/compare",
    summary="Side-by-side comparison of two protocols",
)
async def compare_protocols(body: CompareRequest, request: Request) -> dict:
    engine: AnalyticsEngine = request.app.state.analytics_engine
    store: dict = request.app.state.analytics_store
    proto_registry = request.app.state.protocol_registry
    plan_store = request.app.state.execution_plan_store

    results = {}
    for pid in [body.protocol_id_a, body.protocol_id_b]:
        if pid in store:
            results[pid] = store[pid]
        else:
            protocol = proto_registry.get(pid)
            if not protocol:
                raise HTTPException(status_code=404, detail=f"Protocol {pid} not found")
            plan_obj = next((p for p in plan_store.values() if p.protocol_id == pid), None)
            plan = plan_obj.model_dump(mode="json") if plan_obj else {"estimated_mins": 0, "commands": []}
            telemetry = plan_obj.simulation_result.telemetry if (plan_obj and plan_obj.simulation_result) else {}
            proto_dict = protocol.model_dump() if hasattr(protocol, "model_dump") else dict(protocol)
            results[pid] = engine.compute_report(plan, proto_dict, telemetry)

    a = results[body.protocol_id_a]
    b = results[body.protocol_id_b]

    return {
        "protocol_a": a.to_dict(),
        "protocol_b": b.to_dict(),
        "delta": {
            "cost_usd":        round(a.robot_cost.total_usd - b.robot_cost.total_usd, 4),
            "duration_min":    round(a.robot_duration_min - b.robot_duration_min, 1),
            "plastic_g":       round(a.robot_sustainability.total_plastic_g - b.robot_sustainability.total_plastic_g, 3),
            "co2_g":           round(a.robot_sustainability.co2_g - b.robot_sustainability.co2_g, 3),
            "time_saved_min":  round(a.time_saved_min - b.time_saved_min, 1),
        },
    }