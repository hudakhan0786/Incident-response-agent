import enum
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Float, ForeignKey, Integer, JSON,
    String, Text,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Severity(str, enum.Enum):
    SEV1 = "SEV1"  # full outage
    SEV2 = "SEV2"  # major degradation
    SEV3 = "SEV3"  # partial / limited-blast-radius
    SEV4 = "SEV4"  # minor / cosmetic


class Status(str, enum.Enum):
    OPEN = "open"
    MITIGATED = "mitigated"
    RESOLVED = "resolved"


class Outcome(str, enum.Enum):
    WORKED = "worked"
    PARTIAL = "partial"
    FAILED = "failed"


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False, default="")
    service = Column(String(120), index=True, default="unknown")
    error_signature = Column(String(255), index=True, default="")
    severity = Column(Enum(Severity), default=Severity.SEV3, nullable=False)
    status = Column(Enum(Status), default=Status.OPEN, nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    mttr_minutes = Column(Integer, nullable=True)
    created_by = Column(String(120), default="on-call")

    root_causes = relationship(
        "RootCause", back_populates="incident",
        cascade="all, delete-orphan",
    )
    steps = relationship(
        "ResolutionStep", back_populates="incident",
        cascade="all, delete-orphan",
        order_by="ResolutionStep.minute_offset",
    )
    postmortem = relationship(
        "Postmortem", back_populates="incident", uselist=False,
        cascade="all, delete-orphan",
    )
    runbook_usages = relationship(
        "RunbookUsage", back_populates="incident",
        cascade="all, delete-orphan",
    )


class RootCause(Base):
    __tablename__ = "root_causes"

    id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False)
    category = Column(String(80), default="unknown")
    summary = Column(Text, default="")

    incident = relationship("Incident", back_populates="root_causes")


class ResolutionStep(Base):
    """One entry in an incident's black-box timeline replay."""
    __tablename__ = "resolution_steps"

    id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False)
    minute_offset = Column(Integer, default=0)  # minutes since incident start
    actor = Column(String(120), default="on-call")
    step_type = Column(String(40), default="diagnosis")
    # detection | diagnosis | mitigation | fix | communication | resolution
    action_text = Column(Text, default="")
    runbook_id = Column(Integer, ForeignKey("runbooks.id"), nullable=True)

    incident = relationship("Incident", back_populates="steps")
    runbook = relationship("Runbook")


class Runbook(Base):
    __tablename__ = "runbooks"

    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    service = Column(String(120), index=True, default="unknown")
    tags = Column(String(255), default="")  # comma-separated
    content = Column(Text, default="")  # markdown steps
    elo_rating = Column(Float, default=1200.0)
    times_used = Column(Integer, default=0)
    times_worked = Column(Integer, default=0)
    last_used_at = Column(DateTime, nullable=True)
    last_validated_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    usages = relationship("RunbookUsage", back_populates="runbook")


class RunbookUsage(Base):
    """One Elo 'match': a runbook applied to an incident, with the result."""
    __tablename__ = "runbook_usages"

    id = Column(Integer, primary_key=True)
    runbook_id = Column(Integer, ForeignKey("runbooks.id"), nullable=False)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False)
    outcome = Column(Enum(Outcome), nullable=False)
    elo_before = Column(Float)
    elo_after = Column(Float)
    used_at = Column(DateTime, default=datetime.utcnow)

    runbook = relationship("Runbook", back_populates="usages")
    incident = relationship("Incident", back_populates="runbook_usages")


class Postmortem(Base):
    __tablename__ = "postmortems"

    id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False)
    summary = Column(Text, default="")
    contributing_factors = Column(Text, default="")
    action_items = Column(JSON, default=list)
    lessons_learned = Column(Text, default="")
    auto_generated = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    incident = relationship("Incident", back_populates="postmortem")
