from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database.session import SessionLocal
from app.models.feature_flag import FeatureFlag

# Deliberately ungated (no require_feature dependency) — this is how the
# frontend discovers which flags it should even be checking for.
router = APIRouter(prefix="/api/v1/feature-flags", tags=["Feature Flags"])


@router.get("", response_model=List[str])
def get_enabled_features(user_id: UUID = Depends(get_current_user)):
    db: Session = SessionLocal()
    try:
        rows = (
            db.query(FeatureFlag.feature_key)
            .filter(FeatureFlag.user_id == user_id, FeatureFlag.enabled.is_(True))
            .all()
        )
        return [key for (key,) in rows]
    finally:
        db.close()