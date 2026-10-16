"""
aurolab/services/orchestration_service/api/fleet_router.py

POST /api/v1/fleet/schedule    — Schedule N plans across M robots
GET  /api/v1/fleet/status      — Live fleet status
POST /api/v1/fleet/dispatch    — Dispatch a scheduled task to its robot
POST /api/v1/fleet/complete    — Mark a task complete
GET  /api/v1/fleet/robots      — List all robots in the fleet
POST /api/v1/fleet/robots      — Add a robot to the fleet
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from services.orchestration_service.core.fleet_models import RobotAgent, RobotStatus
from services.orchestration_service.core.scheduler import RobotFleet

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/fleet", tags=["Fleet Orchestration"])


class ScheduleRequest(BaseModel):
    plan_ids: list[str] = Field(description="List of plan_ids from /api/v1/plans/")


class DispatchRequest(BaseModel):
    task_id: str


class CompleteRequest(BaseModel):
    task_id: str


class AddRobotRequest(BaseModel):
    robot_id: str
    name: str
    location: str = "lab_bench_1"


def _get_fleet(request: Request) -> RobotFleet:
    return request.app.state.robot_fleet


@router.post(
    "/schedule",
    summary="Schedule a set of execution plans across the robot fleet",
)
async def schedule_plans(body: ScheduleRequest, request: Request) -> dict:
    fleet = _get_fleet(request)
    plan_store: dict = request.app.state.execution_plan_store

    plans = []
    missing = []
    for pid in body.plan_ids:
        plan = plan_store.get(pid)
        if plan:
            plans.append(plan.model_dump(mode="json"))
        else:
            missing.append(pid)

    if missing:
        raise HTTPException(
            status_code=404,
            detail=f"Plans not found: {missing}",
        )

    if not plans:
        raise HTTPException(status_code=400, detail="No plans to schedule")

    schedule = fleet.schedule(plans)
    # Cache schedule in app state
    request.app.state.current_fleet_schedule = schedule
    return schedule.to_dict()


@router.get(
    "/status",
    summary="Get live fleet status",
)
async def get_fleet_status(request: Request) -> dict:
    fleet = _get_fleet(request)
    return fleet.status().to_dict()


@router.post(
    "/dispatch",
    summary="Dispatch a scheduled task to its assigned robot",
)
async def dispatch_task(body: DispatchRequest, request: Request) -> dict:
    fleet = _get_fleet(request)
    success = fleet.dispatch(body.task_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Task {body.task_id} not found or not schedulable")
    return {"task_id": body.task_id, "dispatched": True}


@router.post(
    "/complete",
    summary="Mark a task as completed and release robot + resource locks",
)
async def complete_task(body: CompleteRequest, request: Request) -> dict:
    fleet = _get_fleet(request)
    success = fleet.complete(body.task_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Task {body.task_id} not found")
    return {"task_id": body.task_id, "completed": True}


@router.get(
    "/robots",
    summary="List all robots in the fleet",
)
async def list_robots(request: Request) -> dict:
    fleet = _get_fleet(request)
    return fleet.status().to_dict()


@router.post(
    "/robots",
    status_code=status.HTTP_201_CREATED,
    summary="Add a robot to the fleet",
)
async def add_robot(body: AddRobotRequest, request: Request) -> dict:
    fleet = _get_fleet(request)
    robot = RobotAgent(
        robot_id=body.robot_id,
        name=body.name,
        location=body.location,
    )
    fleet.add_robot(robot)
    log.info("robot_added", robot_id=body.robot_id, name=body.name)
    return {"robot_id": body.robot_id, "added": True, "fleet_size": fleet.robot_count}


@router.get(
    "/schedule",
    summary="Get the current fleet schedule",
)
async def get_schedule(request: Request) -> dict:
    schedule = getattr(request.app.state, "current_fleet_schedule", None)
    if not schedule:
        return {"message": "No schedule computed yet", "tasks": []}
    return schedule.to_dict()