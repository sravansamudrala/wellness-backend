from datetime import date

from sqlalchemy.orm import Session

from app.models.skincare import SkincareEntry
from app.schemas.skincare import SkincareUpdateRequest


class SkincareService:

    @staticmethod
    def get_today(db: Session) -> SkincareEntry:
        today = date.today()

        skincare = (
            db.query(SkincareEntry)
            .filter(SkincareEntry.date == today)
            .first()
        )

        if skincare:
            return skincare

        skincare = SkincareEntry(date=today)

        db.add(skincare)
        db.commit()
        db.refresh(skincare)

        return skincare

    @staticmethod
    def update_today(db: Session, request: SkincareUpdateRequest) -> SkincareEntry:

        skincare = SkincareService.get_today(db)

        skincare.face_wash = request.face_wash
        skincare.vitamin_c = request.vitamin_c
        skincare.moisturizer = request.moisturizer
        skincare.sunscreen = request.sunscreen
        skincare.cleanser = request.cleanser
        skincare.evening_moisturizer = request.evening_moisturizer

        db.commit()
        db.refresh(skincare)

        return skincare
