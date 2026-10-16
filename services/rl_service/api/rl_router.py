"""
aurolab/services/rl_service/api/rl_router.py

GET  /api/v1/rl/telemetry/{protocol_id}  — Execution run history
GET  /api/v1/rl/stats/{protocol_id}      — Aggregate stats + Q-agent info
POST /api/v1/rl/optimise/{protocol_id}   — Generate parameter suggestions
GET  /api/v1/rl/suggestions/{protocol_id}— List pending suggestions
POST /api/v1/rl/suggestions/{id}/accept  — Accept a suggestion
POST /api/v1/rl/suggestions/{id}/reject  — Reject a suggestion
GET  /api/v1/rl/trend/{protocol_id}      — Reward trend over time
"""

from __future__ import annotations

import time
import structlog
from fastapi import APIRouter, HTTPException, Request

from services.rl_service.core.rl_engine import ProtocolOptimiser, RewardModel
from services.rl_service.core.telemetry_store import ExecutionRun, TelemetryStore

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/rl", tags=["RL Optimisation"])


def _get_optimiser(request: Request) -> ProtocolOptimiser:
    return request.app.state.rl_optimiser

def _get_store(request: Request) -> TelemetryStore:
    return request.app.state.telemetry_store


@router.get("/telemetry/{protocol_id}", summary="Get execution run history for a protocol")
async def get_telemetry(protocol_id: str, limit: int = 50, request: Request = None) -> dict:
    store = _get_store(request)
    runs = store.get_runs(protocol_id, limit=limit)
    return {"protocol_id": protocol_id, "runs": runs, "count": len(runs)}


@router.get("/stats/{protocol_id}", summary="Aggregate stats + Q-agent info")
async def get_stats(protocol_id: str, request: Request = None) -> dict:
    store = _get_store(request)
    optimiser = _get_optimiser(request)
    stats = store.aggregate_stats(protocol_id)
    agent_info = optimiser.agent_stats(protocol_id)
    return {
        "protocol_id": protocol_id,
        "execution_stats": stats,
        "rl_agent": agent_info,
    }


@router.post("/optimise/{protocol_id}", summary="Generate parameter improvement suggestions")
async def optimise(protocol_id: str, request: Request = None) -> dict:
    optimiser = _get_optimiser(request)
    plan_store: dict = request.app.state.execution_plan_store

    # Get commands from the latest plan for this protocol
    plan = next(
        (p for p in plan_store.values() if p.protocol_id == protocol_id),
        None,
    )
    commands = []
    if plan:
        commands = [c.to_wire() for c in plan.commands]

    suggestions = optimiser.generate_suggestions(protocol_id, commands)
    return {
        "protocol_id":  protocol_id,
        "suggestions":  [s.to_dict() for s in suggestions],
        "count":        len(suggestions),
    }


@router.get("/suggestions/{protocol_id}", summary="List pending suggestions")
async def get_suggestions(protocol_id: str, request: Request = None) -> dict:
    store = _get_store(request)
    suggestions = store.get_suggestions(protocol_id, status="pending")
    return {"protocol_id": protocol_id, "suggestions": suggestions}


@router.post("/suggestions/{suggestion_id}/accept")
async def accept_suggestion(suggestion_id: str, request: Request = None) -> dict:
    store = _get_store(request)
    store.update_suggestion_status(suggestion_id, "accepted")
    return {"suggestion_id": suggestion_id, "status": "accepted"}


@router.post("/suggestions/{suggestion_id}/reject")
async def reject_suggestion(suggestion_id: str, request: Request = None) -> dict:
    store = _get_store(request)
    store.update_suggestion_status(suggestion_id, "rejected")
    return {"suggestion_id": suggestion_id, "status": "rejected"}


@router.get("/trend/{protocol_id}", summary="Reward trend over time")
async def get_trend(protocol_id: str, last_n: int = 50, request: Request = None) -> dict:
    store = _get_store(request)
    trend = store.get_reward_trend(protocol_id, last_n=last_n)
    return {"protocol_id": protocol_id, "trend": trend}


@router.get("/overview", summary="RL overview across all protocols")
async def get_overview(request: Request = None) -> dict:
    store = _get_store(request)
    all_stats = store.aggregate_stats()
    return {"global_stats": all_stats}
