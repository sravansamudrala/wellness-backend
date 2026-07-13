from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.gym.plan import PlanDay, PlanExercise, WorkoutPlan
from app.models.gym.state import GymState
from app.schemas.gym.plan import PlanCreateRequest, PlanUpdateRequest
from app.services.gym.builders import build_plan_detail
from app.services.gym.workout_service import WorkoutService


class PlanService:

    @staticmethod
    def list_plans(db: Session, user_id: UUID):
        # Shared templates (user_id IS NULL) plus this user's own custom plans.
        return (
            db.query(WorkoutPlan)
            .filter(
                or_(
                    WorkoutPlan.user_id.is_(None),
                    WorkoutPlan.user_id == user_id,
                )
            )
            .order_by(WorkoutPlan.name.asc())
            .all()
        )

    @staticmethod
    def get_plan(db: Session, user_id: UUID, plan_id: UUID):
        plan = db.query(WorkoutPlan).filter(WorkoutPlan.id == plan_id).first()
        if plan is None:
            return None
        # Visible only if it's a template or belongs to this user.
        if plan.user_id is not None and plan.user_id != user_id:
            return None
        return build_plan_detail(db, plan)

    @staticmethod
    def _add_days(db: Session, plan_id: UUID, days):
        for day in days:
            plan_day = PlanDay(
                plan_id=plan_id,
                name=day.name,
                order_index=day.order_index,
            )
            db.add(plan_day)
            db.flush()

            for pe in day.exercises:
                db.add(
                    PlanExercise(
                        plan_day_id=plan_day.id,
                        exercise_id=pe.exercise_id,
                        order_index=pe.order_index,
                        target_sets=pe.target_sets,
                        target_reps=pe.target_reps,
                        target_rest_seconds=pe.target_rest_seconds,
                    )
                )

    @staticmethod
    def create_plan(db: Session, user_id: UUID, request: PlanCreateRequest):
        plan = WorkoutPlan(
            user_id=user_id,
            name=request.name,
            description=request.description,
            goal=request.goal,
            is_custom=True,
        )
        db.add(plan)
        db.flush()

        PlanService._add_days(db, plan.id, request.days)

        db.commit()
        db.refresh(plan)
        return build_plan_detail(db, plan)

    @staticmethod
    def _delete_days(db: Session, plan_id: UUID):
        days = db.query(PlanDay).filter(PlanDay.plan_id == plan_id).all()
        for day in days:
            db.query(PlanExercise).filter(
                PlanExercise.plan_day_id == day.id
            ).delete()
        db.query(PlanDay).filter(PlanDay.plan_id == plan_id).delete()

    @staticmethod
    def update_plan(
        db: Session, user_id: UUID, plan_id: UUID, request: PlanUpdateRequest
    ):
        # Only your OWN plan can be edited (not shared templates).
        plan = (
            db.query(WorkoutPlan)
            .filter(WorkoutPlan.id == plan_id, WorkoutPlan.user_id == user_id)
            .first()
        )
        if plan is None:
            return None

        plan.name = request.name
        plan.description = request.description
        plan.goal = request.goal

        PlanService._delete_days(db, plan_id)
        db.flush()
        PlanService._add_days(db, plan_id, request.days)

        db.commit()
        db.refresh(plan)
        return build_plan_detail(db, plan)

    @staticmethod
    def delete_plan(db: Session, user_id: UUID, plan_id: UUID) -> bool:
        # Only your own plan (templates can't be deleted by a user).
        plan = (
            db.query(WorkoutPlan)
            .filter(WorkoutPlan.id == plan_id, WorkoutPlan.user_id == user_id)
            .first()
        )
        if plan is None:
            return False

        PlanService._delete_days(db, plan_id)

        # If this was the user's active plan, clear their cursor.
        state = (
            db.query(GymState)
            .filter(GymState.user_id == user_id)
            .first()
        )
        if state is not None and state.active_plan_id == plan_id:
            state.active_plan_id = None
            state.last_completed_day_id = None

        db.delete(plan)
        db.commit()
        return True

    @staticmethod
    def activate_plan(db: Session, user_id: UUID, plan_id: UUID):
        # Can activate a template or your own plan.
        plan = (
            db.query(WorkoutPlan)
            .filter(
                WorkoutPlan.id == plan_id,
                or_(
                    WorkoutPlan.user_id.is_(None),
                    WorkoutPlan.user_id == user_id,
                ),
            )
            .first()
        )
        if plan is None:
            return None

        state = WorkoutService.get_state(db, user_id)
        state.active_plan_id = plan_id
        state.last_completed_day_id = None  # restart rotation at day 1

        db.commit()
        db.refresh(state)
        return state