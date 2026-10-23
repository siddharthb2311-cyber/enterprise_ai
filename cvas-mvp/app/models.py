import uuid
import enum
from datetime import datetime

from sqlalchemy import (
    Column, String, Float, Integer, DateTime, ForeignKey, Text, Enum as SAEnum, JSON
)
from sqlalchemy.orm import relationship

from app.database import Base


def gen_id() -> str:
    return str(uuid.uuid4())


def Enum(enum_cls):
    """Wrapper so every Enum column stores the lowercase .value (e.g.
    'item_missing') instead of SQLAlchemy's default of the member NAME
    (e.g. 'ITEM_MISSING') — keeps DB contents matching the API's JSON."""
    return SAEnum(enum_cls, values_callable=lambda x: [e.value for e in x])


class ComplaintCategory(str, enum.Enum):
    ITEM_MISSING = "item_missing"
    ITEM_DAMAGED = "item_damaged"
    WRONG_ITEM = "wrong_item"
    QUALITY_SPOILAGE = "quality_spoilage"
    LATE_DELIVERY = "late_delivery"
    OTHER = "other"


class ComplaintStatus(str, enum.Enum):
    RECEIVED = "received"
    EVIDENCE_PENDING = "evidence_pending"
    VERIFYING = "verifying"
    DECIDED = "decided"
    SETTLED = "settled"  # unused until Phase 3, kept for schema stability


class DecisionBucket(str, enum.Enum):
    AUTO_APPROVE = "auto_approve"
    AUTO_REJECT = "auto_reject"
    REVIEW = "review"


class Complaint(Base):
    __tablename__ = "complaints"

    id = Column(String, primary_key=True, default=gen_id)
    tenant_id = Column(String, index=True, nullable=False)
    order_id = Column(String, index=True, nullable=False)
    user_id = Column(String, index=True, nullable=False)
    device_id = Column(String, index=True, nullable=True)

    category = Column(Enum(ComplaintCategory), nullable=False)
    description = Column(Text, nullable=True)
    claimed_amount = Column(Float, nullable=True)

    status = Column(Enum(ComplaintStatus), default=ComplaintStatus.RECEIVED, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    evidence = relationship("Evidence", back_populates="complaint", cascade="all, delete-orphan")
    verification_results = relationship("VerificationResult", back_populates="complaint", cascade="all, delete-orphan")
    decision = relationship("Decision", back_populates="complaint", uselist=False, cascade="all, delete-orphan")
    audit_events = relationship("AuditEvent", back_populates="complaint", cascade="all, delete-orphan")


class OrderEvent(Base):
    """Ground truth pushed by the host platform via webhook — used to verify claims against."""
    __tablename__ = "order_events"

    id = Column(String, primary_key=True, default=gen_id)
    tenant_id = Column(String, index=True, nullable=False)
    order_id = Column(String, index=True, nullable=False)

    delivered_at = Column(DateTime, nullable=True)
    delivery_lat = Column(Float, nullable=True)
    delivery_lng = Column(Float, nullable=True)
    weight_at_pickup_g = Column(Float, nullable=True)
    rider_id = Column(String, nullable=True)
    order_value = Column(Float, nullable=True)

    received_at = Column(DateTime, default=datetime.utcnow)


class Evidence(Base):
    __tablename__ = "evidence"

    id = Column(String, primary_key=True, default=gen_id)
    complaint_id = Column(String, ForeignKey("complaints.id"), nullable=False)

    evidence_type = Column(String, nullable=False)  # "image" | "text" | "telemetry"
    file_path = Column(String, nullable=True)        # set for images
    content_hash = Column(String, index=True, nullable=True)  # perceptual/sha hash for dup detection
    payload = Column(JSON, nullable=True)             # arbitrary structured telemetry

    captured_at = Column(DateTime, default=datetime.utcnow)

    complaint = relationship("Complaint", back_populates="evidence")


class VerificationResult(Base):
    __tablename__ = "verification_results"

    id = Column(String, primary_key=True, default=gen_id)
    complaint_id = Column(String, ForeignKey("complaints.id"), nullable=False)

    model_name = Column(String, nullable=False)
    model_version = Column(String, default="v1")
    score = Column(Float, nullable=False)     # 0..1, higher = more consistent with a genuine claim
    verdict = Column(String, nullable=True)
    reasoning = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    complaint = relationship("Complaint", back_populates="verification_results")


class RiskProfile(Base):
    __tablename__ = "risk_profiles"

    id = Column(String, primary_key=True, default=gen_id)
    tenant_id = Column(String, index=True, nullable=False)
    user_id = Column(String, index=True, nullable=False)

    total_orders = Column(Integer, default=0)
    total_claims = Column(Integer, default=0)
    total_refunded_amount = Column(Float, default=0.0)
    account_age_days = Column(Integer, default=0)
    fraud_flags = Column(JSON, default=list)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Decision(Base):
    __tablename__ = "decisions"

    id = Column(String, primary_key=True, default=gen_id)
    complaint_id = Column(String, ForeignKey("complaints.id"), unique=True, nullable=False)

    composite_score = Column(Float, nullable=False)
    bucket = Column(Enum(DecisionBucket), nullable=False)
    decided_by = Column(String, default="system")  # "system" or an agent_id on override
    reasoning_summary = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    complaint = relationship("Complaint", back_populates="decision")


class Settlement(Base):
    """Schema reserved for Phase 3 — not populated by this MVP's pipeline."""
    __tablename__ = "settlements"

    id = Column(String, primary_key=True, default=gen_id)
    complaint_id = Column(String, ForeignKey("complaints.id"), nullable=False)
    amount = Column(Float, nullable=True)
    method = Column(String, nullable=True)
    status = Column(String, default="not_started")
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(String, primary_key=True, default=gen_id)
    complaint_id = Column(String, ForeignKey("complaints.id"), nullable=False)

    actor = Column(String, nullable=False)   # "system" | "agent:<id>" | "user:<id>"
    action = Column(String, nullable=False)
    details = Column(JSON, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

    complaint = relationship("Complaint", back_populates="audit_events")
