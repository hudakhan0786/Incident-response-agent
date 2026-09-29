from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models, schemas, similarity
from app.database import get_db
from app.serializers import runbook_to_out
from app import hindsight_memory

router = APIRouter(prefix="/api/search", tags=["search"])


@router.post("/suggest", response_model=schemas.SuggestResponse)
def suggest(payload: schemas.SuggestRequest, db: Session = Depends(get_db)):
    query = " ".join(filter(None, [payload.service, payload.severity, payload.error_signature, payload.description]))
    try:
        hindsight_memories = hindsight_memory.recall_incidents(query)
    except Exception:
        # A memory service outage must not block active incident triage.
        hindsight_memories = []
    candidates = db.query(models.Incident).filter(
        models.Incident.status == models.Status.RESOLVED
    ).all()

    matches = similarity.find_similar_incidents(
        query_text=f"{payload.description}",
        query_service=payload.service,
        query_severity=payload.severity,
        query_error_sig=payload.error_signature,
        candidates=candidates,
        top_k=payload.top_k,
    )

    results = []
    for incident, score, fingerprint in matches:
        runbook_ids = {s.runbook_id for s in incident.steps if s.runbook_id}
        recommended = []
        for rb_id in runbook_ids:
            rb = db.get(models.Runbook, rb_id)
            if not rb:
                continue
            why_bits = []
            if fingerprint["service_match"] == 1.0:
                why_bits.append(f"same service ({incident.service})")
            if fingerprint["error_signature_match"] == 1.0:
                why_bits.append("identical error signature")
            elif fingerprint["error_signature_match"] == 0.5:
                why_bits.append("closely related error text")
            if fingerprint["severity_match"] == 1.0:
                why_bits.append("same severity class")
            why_bits.append(f"used on incident #{incident.id} \u2014 \u201c{incident.title}\u201d")
            recommended.append(schemas.SuggestedRunbook(
                runbook=runbook_to_out(rb),
                why="Matched on " + ", ".join(why_bits) + ".",
            ))
        # highest-trust runbooks first
        recommended.sort(key=lambda r: r.runbook.elo_rating, reverse=True)

        results.append(schemas.SuggestedIncident(
            incident=schemas.IncidentOut.model_validate(incident),
            score=score,
            fingerprint=fingerprint,
            recommended_runbooks=recommended,
        ))

    return schemas.SuggestResponse(matches=results, hindsight_memories=hindsight_memories)
