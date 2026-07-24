from fastapi import APIRouter

from app.api.gym.catalog import router as catalog_router
from app.api.gym.workouts import router as workouts_router
from app.api.gym.insights import router as insights_router

# Single aggregate router carrying the /api/v1/gym prefix; sub-routers define
# their paths relative to it.
router = APIRouter(prefix="/api/v1/gym")

router.include_router(catalog_router)
router.include_router(workouts_router)
router.include_router(insights_router)