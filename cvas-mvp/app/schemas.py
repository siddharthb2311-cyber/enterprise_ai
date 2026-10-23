from datetime import datetime
from typing import Optional, List, Any

from pydantic import BaseModel

from app.models import ComplaintCategory, ComplaintStatus, DecisionBucket


class ComplaintCreate(BaseModel):
    tenant_id: str
    order_id: str
    user_id: str
    device_id: Optional[str] = None
    category: ComplaintCategory
    description: Optional[str] = None
    claimed_amount: Optional[float] = None


class ComplaintOut(BaseModel):
    id: str
    tenant_id: str
    order_id: str
    user_id: str
    category: ComplaintCategory
    status: ComplaintStatus
    created_at: datetime

    class Config:
        from_attributes = True


class EvidenceTelemetryIn(BaseModel):
    payload: dict


class OrderEventIn(BaseModel):
    tenant_id: str
    order_id: str
    delivered_at: Optional[datetime] = None
    delivery_lat: Optional[float] = None
    delivery_lng: Optional[float] = None
    weight_at_pickup_g: Optional[float] = None
    rider_id: Optional[str] = None
    order_value: Optional[float] = None


class VerificationResultOut(BaseModel):
    model_name: str
    model_version: str
    score: float
    verdict: Optional[str]
    reasoning: Optional[str]

    class Config:
        from_attributes = True


class DecisionOut(BaseModel):
    complaint_id: str
    composite_score: float
    bucket: DecisionBucket
    decided_by: str
    reasoning_summary: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class ComplaintStatusOut(BaseModel):
    complaint: ComplaintOut
    verification_results: List[VerificationResultOut]
    decision: Optional[DecisionOut]


class OverrideIn(BaseModel):
    agent_id: str
    new_bucket: DecisionBucket
    reason: str
