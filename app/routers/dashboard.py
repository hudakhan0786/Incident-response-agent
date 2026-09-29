from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import elo, models, schemas
from app.database import get_db
from app.serializers import runbook_to_out

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=schemas.DashboardStats)
def stats(db: Session = Depends(get_db)):
    open_count = db.query(models.Incident).filter(
        models.Incident.status != models.Status.RESOLVED
    ).count()
    resolved = db.query(models.Incident).filter(
        models.Incident.status == models.Status.RESOLVED
    ).all()
    resolved_count = len(resolved)

    avg_mttr = None
    mttrs = [i.mttr_minutes for i in resolved if i.mttr_minutes]
    if mttrs:
        avg_mttr = round(sum(mttrs) / len(mttrs), 1)

    service_rows = (
        db.query(models.Incident.service, func.count(models.Incident.id))
        .group_by(models.Incident.service)
        .all()
    )
    incidents_by_service = [
        schemas.ServiceBreakdown(service=s or "unknown", count=c) for s, c in service_rows
    ]

    all_runbooks = db.query(models.Runbook).all()
    ranked = []
    for rb in all_runbooks:
        days_since = None
        if rb.last_used_at:
            days_since = (datetime.utcnow() - rb.last_used_at).total_seconds() / 86400
        effective = elo.decayed_rating(rb.elo_rating, days_since)
        ranked.append((rb, effective, days_since))

    top_runbooks = [
        runbook_to_out(rb) for rb, _, _ in
        sorted(ranked, key=lambda r: r[1], reverse=True)[:5]
    ]

    decaying_runbooks = [
        runbook_to_out(rb) for rb, _, days in ranked
        if days is not None and days > elo.DECAY_HALF_LIFE_DAYS and rb.times_used > 0
    ]
    decaying_runbooks.sort(key=lambda r: r.freshness)
    decaying_runbooks = decaying_runbooks[:5]

    trend_source = sorted(
        [i for i in resolved if i.mttr_minutes],
        key=lambda i: i.resolved_at,
    )[-12:]
    mttr_trend = [
        {
            "incident_id": i.id,
            "title": i.title,
            "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
            "mttr_minutes": i.mttr_minutes,
            "severity": getattr(i.severity, "value", i.severity),
        }
        for i in trend_source
    ]

    return schemas.DashboardStats(
        open_incidents=open_count,
        resolved_incidents=resolved_count,
        avg_mttr_minutes=avg_mttr,
        incidents_by_service=incidents_by_service,
        top_runbooks=top_runbooks,
        decaying_runbooks=decaying_runbooks,
        mttr_trend=mttr_trend,
    )
