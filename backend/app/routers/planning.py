from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.planning import TodayOverview
from app.schemas.day_plan import DayPlan
from app.services.planning_service import get_today_overview
from app.services.day_planner import build_day_plan

router = APIRouter(prefix="/planning", tags=["planning"])


@router.get("/today", response_model=TodayOverview)
def today_overview(db: Session = Depends(get_db)):
    """Deterministic Today Overview — read-only, no AI involved."""
    return get_today_overview(db)


@router.get("/day", response_model=DayPlan)
def day_plan(db: Session = Depends(get_db)):
    """Deterministic recommended Day Plan — read-only.

    Builds the Today Overview, then passes it to the day planner. The planner
    performs no further database or calendar queries; nothing is scheduled in
    Google Calendar and no task is modified.
    """
    return build_day_plan(get_today_overview(db))
