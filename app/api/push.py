import hashlib
from uuid import UUID

from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Query

from app.ai.water_message import guardrails, inference
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


@router.get("/_debug/water-message")
def debug_water_message(
    goal: str = Query(...),
    streak: str = Query(...),
    time: str = Query(...),
    token: str = Query(default=""),
):
    # Kept deliberately (not temporary) as a way to test Aiwt's bucketed
    # generation directly on Render - e.g. comparing against local dev to
    # rule out cross-platform ONNX divergence - without any push send or
    # ReminderDispatchLog write. Scoped to water-message only for now;
    # other modules adopting this bucketed-generation pattern (gym, etc.)
    # will need their own equivalent route, not a reuse of this one.
    if not settings.dispatch_token or token != settings.dispatch_token:
        raise HTTPException(status_code=401, detail="Invalid dispatch token")

    input_text = f"water reminder | goal: {goal}% | streak: {streak} | time: {time}"
    raw = inference.generate_water_message(input_text)
    return {
        "input_text": input_text,
        "raw": raw,
        "passed_guardrails": guardrails.check(raw) is not None,
    }


@router.get("/_debug/artifact-info")
def debug_artifact_info(token: str = Query(default="")):
    # Reports sha256 + byte size of the Aiwt encoder/decoder .onnx files as
    # actually loaded on disk here, so it can be diffed against a local
    # dev checkout's hashes - the direct way to confirm whether a deployed
    # environment is running the same weights as expected (e.g. a git-lfs
    # pull that silently didn't fetch real content).
    if not settings.dispatch_token or token != settings.dispatch_token:
        raise HTTPException(status_code=401, detail="Invalid dispatch token")

    result = {}
    for name in ("encoder_model.onnx", "decoder_model.onnx", "spiece.model"):
        path = inference.ARTIFACT_DIR / name
        if not path.exists():
            result[name] = {"exists": False}
            continue
        data = path.read_bytes()
        result[name] = {
            "exists": True,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    return result


@router.post("/dispatch")
def dispatch(token: str = Query(default="")):

    # Public endpoint hit by the cron caller — guard with a shared secret.
    if not settings.dispatch_token or token != settings.dispatch_token:
        raise HTTPException(status_code=401, detail="Invalid dispatch token")

    db: Session = SessionLocal()

    try:
        skincare_result = PushService.dispatch_due(db)
        water_result = PushService.dispatch_water_due(db)
        return {
            "processed_users": skincare_result["processed_users"] + water_result["processed_users"],
            "sent": skincare_result["sent"] + water_result["sent"],
            "errors": skincare_result["errors"] + water_result["errors"],
        }
    finally:
        db.close()