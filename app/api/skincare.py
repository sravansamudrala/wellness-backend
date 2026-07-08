from sqlalchemy.orm import Session
from fastapi import APIRouter

from app.database.session import SessionLocal
from app.schemas.skincare import SkincareResponse
from app.services.skincare_service import SkincareService
from app.schemas.skincare import ( SkincareResponse,SkincareUpdateRequest,)

router = APIRouter(
    prefix="/api/v1/skincare",
    tags=["Skincare"]
)


@router.get("/today", response_model=SkincareResponse)
def get_today():

    db: Session = SessionLocal()

    try:
        return SkincareService.get_today(db)

    finally:
        db.close()


@router.put( "/today", response_model=SkincareResponse)
def update_today(
    request: SkincareUpdateRequest,
):

    db: Session = SessionLocal()

    try:
        return SkincareService.update_today(
            db,
            request
        )

    finally:
        db.close()