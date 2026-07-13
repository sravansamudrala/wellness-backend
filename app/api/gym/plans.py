from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
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

# Plans are MIXED: templates (user_id IS NULL) are shared with everyone; custom
# plans belong to one user. So user_id here filters visibility and scopes writes.


@router.get("/plans", response_model=List[WorkoutPlanResponse])
def list_plans(user_id: UUID = Depends(get_current_user)):
    db: Session = SessionLocal()

    try:
        return PlanService.list_plans(db, user_id)
    finally:
        db.close()


@router.get("/plans/{plan_id}", response_model=WorkoutPlanDetailResponse)
def get_plan(plan_id: UUID, user_id: UUID = Depends(get_current_user)):
    db: Session = SessionLocal()

    try:
        plan = PlanService.get_plan(db, user_id, plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="Plan not found")
        return plan
    finally:
        db.close()


@router.post("/plans", response_model=WorkoutPlanDetailResponse)
def create_plan(
    request: PlanCreateRequest,
    user_id: UUID = Depends(get_current_user),
):
    db: Session = SessionLocal()

    try:
        return PlanService.create_plan(db, user_id, request)
    finally:
        db.close()


@router.put("/plans/{plan_id}", response_model=WorkoutPlanDetailResponse)
def update_plan(
    plan_id: UUID,
    request: PlanUpdateRequest,
    user_id: UUID = Depends(get_current_user),
):
    db: Session = SessionLocal()

    try:
        plan = PlanService.update_plan(db, user_id, plan_id, request)
        if plan is None:
            raise HTTPException(status_code=404, detail="Plan not found")
        return plan
    finally:
        db.close()


@router.delete("/plans/{plan_id}")
def delete_plan(plan_id: UUID, user_id: UUID = Depends(get_current_user)):
    db: Session = SessionLocal()

    try:
        deleted = PlanService.delete_plan(db, user_id, plan_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Plan not found")
        return {"status": "ok"}
    finally:
        db.close()


@router.post("/plans/{plan_id}/activate", response_model=GymStateResponse)
def activate_plan(plan_id: UUID, user_id: UUID = Depends(get_current_user)):
    db: Session = SessionLocal()

    try:
        state = PlanService.activate_plan(db, user_id, plan_id)
        if state is None:
            raise HTTPException(status_code=404, detail="Plan not found")
        return state
    finally:
        db.close()
