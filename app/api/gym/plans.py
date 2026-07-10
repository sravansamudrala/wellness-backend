from typing import List
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.schemas.gym.plan import (
    PlanCreateRequest,
    PlanUpdateRequest,
    WorkoutPlanDetailResponse,
    WorkoutPlanResponse,
)
from app.schemas.gym.state import GymStateResponse
from app.services.gym.plan_service import PlanService

router = APIRouter(tags=["Gym — Plans"])


@router.get("/plans", response_model=List[WorkoutPlanResponse])
def list_plans():
    db: Session = SessionLocal()

    try:
        return PlanService.list_plans(db)
    finally:
        db.close()


@router.get("/plans/{plan_id}", response_model=WorkoutPlanDetailResponse)
def get_plan(plan_id: UUID):
    db: Session = SessionLocal()

    try:
        plan = PlanService.get_plan(db, plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="Plan not found")
        return plan
    finally:
        db.close()


@router.post("/plans", response_model=WorkoutPlanDetailResponse)
def create_plan(request: PlanCreateRequest):
    db: Session = SessionLocal()

    try:
        return PlanService.create_plan(db, request)
    finally:
        db.close()


@router.put("/plans/{plan_id}", response_model=WorkoutPlanDetailResponse)
def update_plan(plan_id: UUID, request: PlanUpdateRequest):
    db: Session = SessionLocal()

    try:
        plan = PlanService.update_plan(db, plan_id, request)
        if plan is None:
            raise HTTPException(status_code=404, detail="Plan not found")
        return plan
    finally:
        db.close()


@router.delete("/plans/{plan_id}")
def delete_plan(plan_id: UUID):
    db: Session = SessionLocal()

    try:
        deleted = PlanService.delete_plan(db, plan_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Plan not found")
        return {"status": "ok"}
    finally:
        db.close()


@router.post("/plans/{plan_id}/activate", response_model=GymStateResponse)
def activate_plan(plan_id: UUID):
    db: Session = SessionLocal()

    try:
        state = PlanService.activate_plan(db, plan_id)
        if state is None:
            raise HTTPException(status_code=404, detail="Plan not found")
        return state
    finally:
        db.close()