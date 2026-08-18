from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.planning import TodayOverview
from app.services.planning_service import get_today_overview

router = APIRouter(prefix="/planning", tags=["planning"])


@router.get("/today", response_model=TodayOverview)
def today_overview(db: Session = Depends(get_db)):
    """Deterministic Today Overview — read-only, no AI involved."""
    return get_today_overview(db)
