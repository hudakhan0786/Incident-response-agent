from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.postmortem_gen import generate_postmortem
from app import hindsight_memory

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


@router.get("", response_model=list[schemas.IncidentOut])
def list_incidents(
    status: Optional[str] = None,
    service: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(models.Incident)
    if status:
        q = q.filter(models.Incident.status == status)
    if service:
        q = q.filter(models.Incident.service == service)
    return q.order_by(models.Incident.started_at.desc()).all()


@router.post("", response_model=schemas.IncidentDetailOut, status_code=201)
def create_incident(payload: schemas.IncidentCreate, db: Session = Depends(get_db)):
    incident = models.Incident(
        title=payload.title,
        description=payload.description,
        service=payload.service,
        error_signature=payload.error_signature,
        severity=payload.severity,
        created_by=payload.created_by,
        started_at=datetime.utcnow(),
    )
    for rc in payload.root_causes:
        incident.root_causes.append(models.RootCause(category=rc.category, summary=rc.summary))
    db.add(incident)
    db.commit()
    db.refresh(incident)
    try:
        hindsight_memory.retain_incident(incident)
    except Exception:
        # Keep resolution available even when Hindsight is unreachable.
        pass
    return incident


@router.get("/{incident_id}", response_model=schemas.IncidentDetailOut)
def get_incident(incident_id: int, db: Session = Depends(get_db)):
    incident = db.get(models.Incident, incident_id)
    if not incident:
        raise HTTPException(404, "Incident not found")
    return incident


@router.post("/{incident_id}/steps", response_model=schemas.ResolutionStepOut, status_code=201)
def add_step(incident_id: int, payload: schemas.ResolutionStepCreate, db: Session = Depends(get_db)):
    incident = db.get(models.Incident, incident_id)
    if not incident:
        raise HTTPException(404, "Incident not found")
    step = models.ResolutionStep(incident_id=incident_id, **payload.model_dump())
    db.add(step)
    db.commit()
    db.refresh(step)
    return step


@router.post("/{incident_id}/resolve", response_model=schemas.IncidentDetailOut)
def resolve_incident(incident_id: int, db: Session = Depends(get_db)):
    incident = db.get(models.Incident, incident_id)
    if not incident:
        raise HTTPException(404, "Incident not found")
    incident.resolved_at = datetime.utcnow()
    incident.status = models.Status.RESOLVED
    delta = incident.resolved_at - incident.started_at
    incident.mttr_minutes = max(1, int(delta.total_seconds() // 60))
    db.commit()
    db.refresh(incident)
    return incident


@router.post("/{incident_id}/postmortem/generate", response_model=schemas.PostmortemOut)
def generate_incident_postmortem(incident_id: int, db: Session = Depends(get_db)):
    incident = db.get(models.Incident, incident_id)
    if not incident:
        raise HTTPException(404, "Incident not found")

    draft = generate_postmortem(incident)

    if incident.postmortem:
        pm = incident.postmortem
        pm.summary = draft["summary"]
        pm.contributing_factors = draft["contributing_factors"]
        pm.action_items = draft["action_items"]
        pm.lessons_learned = draft["lessons_learned"]
    else:
        pm = models.Postmortem(incident_id=incident_id, **draft)
        db.add(pm)

    db.commit()
    db.refresh(pm)
    return pm
