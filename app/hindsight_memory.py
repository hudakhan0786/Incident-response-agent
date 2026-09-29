"""Optional Hindsight-backed memory for resolved incident outcomes.

The core application remains usable without a Hindsight server. Configure
HINDSIGHT_API_URL to enable persistent semantic recall and retention.
"""
import os
from typing import Any


def _client():
    base_url = os.getenv("HINDSIGHT_API_URL", "").strip()
    if not base_url:
        return None
    from hindsight_client import Hindsight

    kwargs: dict[str, Any] = {"base_url": base_url, "timeout": 10.0}
    api_key = os.getenv("HINDSIGHT_API_KEY", "").strip()
    if api_key:
        kwargs["api_key"] = api_key
    return Hindsight(**kwargs)


def enabled() -> bool:
    return bool(os.getenv("HINDSIGHT_API_URL", "").strip())


def bank_id() -> str:
    return os.getenv("HINDSIGHT_BANK_ID", "incident-response-agent")


def retain_incident(incident) -> bool:
    """Store a resolved incident and its observed response as one upsertable document."""
    client = _client()
    if client is None:
        return False
    causes = [f"{cause.category}: {cause.summary}" for cause in incident.root_causes]
    steps = [
        f"T+{step.minute_offset}m [{step.step_type}] {step.action_text}"
        for step in sorted(incident.steps, key=lambda item: item.minute_offset)
    ]
    content = "\n".join([
        f"Resolved incident #{incident.id}: {incident.title}",
        f"Service: {incident.service}; severity: {incident.severity}; error signature: {incident.error_signature or 'none'}.",
        f"Symptoms: {incident.description}",
        "Root causes: " + ("; ".join(causes) or "not recorded"),
        "Response timeline: " + ("; ".join(steps) or "no steps recorded"),
    ])
    timestamp = incident.resolved_at.isoformat() + "Z" if incident.resolved_at else None
    client.retain(
        bank_id=bank_id(),
        content=content,
        context="Production incident post-resolution record. Treat outcome and root cause as historical evidence.",
        document_id=f"incident-{incident.id}",
        timestamp=timestamp,
        metadata={"source": "incident-response-agent", "incident_id": str(incident.id), "service": incident.service},
    )
    return True


def recall_incidents(query: str, limit: int = 6) -> list[dict[str, str]]:
    client = _client()
    if client is None:
        return []
    response = client.recall(bank_id=bank_id(), query=query, budget="low", max_tokens=1800)
    results = []
    for memory in getattr(response, "results", [])[:limit]:
        value = getattr(memory, "text", "")
        if value:
            results.append({"text": str(value), "type": str(getattr(memory, "type", "memory"))})
    return results


def status() -> dict[str, Any]:
    return {"enabled": enabled(), "bank_id": bank_id() if enabled() else None}


def initialize_bank() -> None:
    """Create the application bank on first startup; tolerate an existing bank."""
    client = _client()
    if client is not None:
        try:
            client.create_bank(
                bank_id=bank_id(),
                name="Incident Response",
                mission="Remember verified incident symptoms, root causes, and response outcomes for on-call responders.",
                disposition={"skepticism": 4, "literalism": 4, "empathy": 2},
            )
        except Exception:
            # Existing banks and transient Hindsight outages must not stop app startup.
            pass
