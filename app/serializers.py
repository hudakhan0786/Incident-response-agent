"""Shared response-shaping helpers, used by more than one router.

Kept separate from schemas.py because these functions combine ORM data with
derived, time-dependent values (decayed Elo, freshness) that don't belong in
a pure data contract.
"""
from datetime import datetime

from app import elo, models, schemas


def runbook_to_out(rb: models.Runbook) -> schemas.RunbookOut:
    days_since = None
    if rb.last_used_at:
        days_since = (datetime.utcnow() - rb.last_used_at).total_seconds() / 86400
    effective_rating = elo.decayed_rating(rb.elo_rating, days_since)

    out = schemas.RunbookOut.model_validate(rb)
    out.trust_label = elo.trust_label(effective_rating)
    out.freshness = elo.freshness(days_since)
    return out
