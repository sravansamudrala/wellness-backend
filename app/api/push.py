from uuid import UUID

from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.core.config import settings
from app.database.session import SessionLocal
from app.schemas.push import PushSubscriptionRequest
from app.services.push_service import PushService

router = APIRouter(
    prefix="/api/v1/push",
    tags=["Push"],
)


@router.post("/subscribe")
def subscribe(
    request: PushSubscriptionRequest,
    user_id: UUID = Depends(get_current_user),
):

    db: Session = SessionLocal()

    try:
        # Attach this device to the logged-in user so the cron notifies them.
        PushService.save_subscription(db, user_id, request)
        return {"status": "ok"}
    finally:
        db.close()


@router.post("/dispatch")
def dispatch(token: str = Query(default="")):

    # Public endpoint hit by the cron caller — guard with a shared secret.
    if not settings.dispatch_token or token != settings.dispatch_token:
        raise HTTPException(status_code=401, detail="Invalid dispatch token")

    db: Session = SessionLocal()

    try:
        return PushService.dispatch_due(db)
    finally:
        db.close()