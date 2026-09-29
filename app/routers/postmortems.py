from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db

router = APIRouter(prefix="/api/postmortems", tags=["postmortems"])


@router.get("", response_model=list[schemas.PostmortemListItem])
def list_postmortems(db: Session = Depends(get_db)):
    rows = (
        db.query(models.Postmortem, models.Incident)
        .join(models.Incident, models.Postmortem.incident_id == models.Incident.id)
        .order_by(models.Postmortem.created_at.desc())
        .all()
    )
    out = []
    for pm, incident in rows:
        base = schemas.PostmortemOut.model_validate(pm).model_dump()
        out.append(schemas.PostmortemListItem(
            **base,
            incident_id=incident.id,
            incident_title=incident.title,
            incident_service=incident.service,
            incident_severity=getattr(incident.severity, "value", incident.severity),
        ))
    return out
