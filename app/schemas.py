from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------- Root causes / steps / postmortems ----------

class RootCauseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    category: str
    summary: str


class RootCauseCreate(BaseModel):
    category: str = "unknown"
    summary: str = ""


class ResolutionStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    minute_offset: int
    actor: str
    step_type: str
    action_text: str
    runbook_id: Optional[int] = None


class ResolutionStepCreate(BaseModel):
    minute_offset: int = 0
    actor: str = "on-call"
    step_type: str = "diagnosis"
    action_text: str
    runbook_id: Optional[int] = None


class PostmortemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    summary: str
    contributing_factors: str
    action_items: list
    lessons_learned: str
    auto_generated: bool
    created_at: datetime


class PostmortemListItem(PostmortemOut):
    incident_id: int
    incident_title: str
    incident_service: str
    incident_severity: str


# ---------- Incidents ----------

class IncidentCreate(BaseModel):
    title: str
    description: str = ""
    service: str = "unknown"
    error_signature: str = ""
    severity: str = "SEV3"
    created_by: str = "on-call"
    root_causes: list[RootCauseCreate] = Field(default_factory=list)


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    description: str
    service: str
    error_signature: str
    severity: str
    status: str
    started_at: datetime
    resolved_at: Optional[datetime] = None
    mttr_minutes: Optional[int] = None
    created_by: str


class IncidentDetailOut(IncidentOut):
    root_causes: list[RootCauseOut] = Field(default_factory=list)
    steps: list[ResolutionStepOut] = Field(default_factory=list)
    postmortem: Optional[PostmortemOut] = None


# ---------- Runbooks ----------

class RunbookCreate(BaseModel):
    title: str
    service: str = "unknown"
    tags: str = ""
    content: str = ""


class RunbookOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    service: str
    tags: str
    content: str
    elo_rating: float
    times_used: int
    times_worked: int
    last_used_at: Optional[datetime] = None
    last_validated_at: datetime
    created_at: datetime
    trust_label: str = ""
    freshness: float = 1.0


class RunbookFeedback(BaseModel):
    incident_id: int
    outcome: str  # worked | partial | failed


class RunbookFeedbackResult(BaseModel):
    runbook_id: int
    elo_before: float
    elo_after: float
    delta: float
    trust_label: str


# ---------- Search / suggest ----------

class SuggestRequest(BaseModel):
    description: str
    service: str = ""
    severity: str = "SEV3"
    error_signature: str = ""
    top_k: int = 5


class SuggestedRunbook(BaseModel):
    runbook: RunbookOut
    why: str


class SuggestedIncident(BaseModel):
    incident: IncidentOut
    score: float
    fingerprint: dict
    recommended_runbooks: list[SuggestedRunbook]


class SuggestResponse(BaseModel):
    matches: list[SuggestedIncident]
    hindsight_memories: list[dict[str, str]] = Field(default_factory=list)


# ---------- Dashboard ----------

class ServiceBreakdown(BaseModel):
    service: str
    count: int


class DashboardStats(BaseModel):
    open_incidents: int
    resolved_incidents: int
    avg_mttr_minutes: Optional[float] = None
    incidents_by_service: list[ServiceBreakdown]
    top_runbooks: list[RunbookOut]
    decaying_runbooks: list[RunbookOut]
    mttr_trend: list[dict]
