from uuid import UUID

from sqlalchemy.orm import Session

from app.models.gym.plan import PlanDay, PlanExercise, WorkoutPlan
from app.models.gym.state import GymState
from app.schemas.gym.plan import PlanCreateRequest, PlanUpdateRequest
from app.services.gym.builders import build_plan_detail
from app.services.gym.workout_service import WorkoutService


class PlanService:

    @staticmethod
    def list_plans(db: Session):
        return db.query(WorkoutPlan).order_by(WorkoutPlan.name.asc()).all()

    @staticmethod
    def get_plan(db: Session, plan_id: UUID):
        plan = db.query(WorkoutPlan).filter(WorkoutPlan.id == plan_id).first()
        if plan is None:
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
    def create_plan(db: Session, request: PlanCreateRequest):
        plan = WorkoutPlan(
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
    def update_plan(db: Session, plan_id: UUID, request: PlanUpdateRequest):
        plan = db.query(WorkoutPlan).filter(WorkoutPlan.id == plan_id).first()
        if plan is None:
            return None

        plan.name = request.name
        plan.description = request.description
        plan.goal = request.goal

        # Full replace of the plan's days/exercises.
        PlanService._delete_days(db, plan_id)
        db.flush()
        PlanService._add_days(db, plan_id, request.days)

        db.commit()
        db.refresh(plan)
        return build_plan_detail(db, plan)

    @staticmethod
    def delete_plan(db: Session, plan_id: UUID) -> bool:
        plan = db.query(WorkoutPlan).filter(WorkoutPlan.id == plan_id).first()
        if plan is None:
            return False

        PlanService._delete_days(db, plan_id)

        # If this was the active plan, clear the cursor so nothing dangles.
        state = db.query(GymState).first()
        if state is not None and state.active_plan_id == plan_id:
            state.active_plan_id = None
            state.last_completed_day_id = None

        db.delete(plan)
        db.commit()
        return True

    @staticmethod
    def activate_plan(db: Session, plan_id: UUID):
        plan = db.query(WorkoutPlan).filter(WorkoutPlan.id == plan_id).first()
        if plan is None:
            return None

        state = WorkoutService.get_state(db)
        state.active_plan_id = plan_id
        # Reset the rotation to the start of the newly activated plan.
        state.last_completed_day_id = None

        db.commit()
        db.refresh(state)
        return state
