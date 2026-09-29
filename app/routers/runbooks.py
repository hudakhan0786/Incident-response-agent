from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import elo, models, schemas
from app.database import get_db
from app.serializers import runbook_to_out as _to_out

router = APIRouter(prefix="/api/runbooks", tags=["runbooks"])


@router.get("", response_model=list[schemas.RunbookOut])
def list_runbooks(service: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(models.Runbook)
    if service:
        q = q.filter(models.Runbook.service == service)
    runbooks = q.order_by(models.Runbook.elo_rating.desc()).all()
    return [_to_out(rb) for rb in runbooks]


@router.post("", response_model=schemas.RunbookOut, status_code=201)
def create_runbook(payload: schemas.RunbookCreate, db: Session = Depends(get_db)):
    rb = models.Runbook(**payload.model_dump())
    db.add(rb)
    db.commit()
    db.refresh(rb)
    return _to_out(rb)


@router.get("/{runbook_id}", response_model=schemas.RunbookOut)
def get_runbook(runbook_id: int, db: Session = Depends(get_db)):
    rb = db.get(models.Runbook, runbook_id)
    if not rb:
        raise HTTPException(404, "Runbook not found")
    return _to_out(rb)


@router.post("/{runbook_id}/feedback", response_model=schemas.RunbookFeedbackResult)
def submit_feedback(runbook_id: int, payload: schemas.RunbookFeedback, db: Session = Depends(get_db)):
    rb = db.get(models.Runbook, runbook_id)
    if not rb:
        raise HTTPException(404, "Runbook not found")
    incident = db.get(models.Incident, payload.incident_id)
    if not incident:
        raise HTTPException(404, "Incident not found")
    if payload.outcome not in ("worked", "partial", "failed"):
        raise HTTPException(400, "outcome must be worked, partial, or failed")

    severity = getattr(incident.severity, "value", incident.severity)
    new_rating, delta = elo.update_elo(rb.elo_rating, severity, payload.outcome)

    usage = models.RunbookUsage(
        runbook_id=rb.id,
        incident_id=incident.id,
        outcome=payload.outcome,
        elo_before=rb.elo_rating,
        elo_after=new_rating,
    )
    db.add(usage)

    rb.elo_rating = new_rating
    rb.times_used += 1
    if payload.outcome == "worked":
        rb.times_worked += 1
    rb.last_used_at = datetime.utcnow()
    rb.last_validated_at = datetime.utcnow()

    db.commit()

    return schemas.RunbookFeedbackResult(
        runbook_id=rb.id,
        elo_before=usage.elo_before,
        elo_after=usage.elo_after,
        delta=delta,
        trust_label=elo.trust_label(new_rating),
    )
