"""
Decision engine v1: weighted composite score → three buckets.

Weights are a starting point tuned by intuition, not data — the roadmap's
Phase 1 exit criteria is to validate/re-tune these against a labeled sample
before trusting auto_approve/auto_reject in production. Keep weights out of
code and in the WEIGHTS dict below so re-tuning doesn't require touching
logic elsewhere.
"""

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Complaint, Decision, DecisionBucket
from app.services import audit_service
from app.services.verification_engine import VerificationOutcome

WEIGHTS = {
    "complaint_classifier_stub": 0.15,
    "vision_consistency_stub": 0.20,
    "duplicate_hash_check": 0.30,
    "geo_time_plausibility": 0.20,
    "fraud_velocity": 0.15,
}


def composite_score(outcome: VerificationOutcome) -> float:
    total_weight = 0.0
    weighted_sum = 0.0
    for signal in outcome.signals:
        w = WEIGHTS.get(signal.model_name, 0.0)
        weighted_sum += w * signal.score
        total_weight += w
    if total_weight == 0:
        return 0.5
    return weighted_sum / total_weight


def bucket_for_score(score: float) -> DecisionBucket:
    if score >= settings.auto_approve_threshold:
        return DecisionBucket.AUTO_APPROVE
    if score <= settings.auto_reject_threshold:
        return DecisionBucket.AUTO_REJECT
    return DecisionBucket.REVIEW


def decide(db: Session, complaint: Complaint, outcome: VerificationOutcome) -> Decision:
    score = composite_score(outcome)
    bucket = bucket_for_score(score)

    reasoning_lines = [f"{s.model_name}: {s.verdict} (score={s.score:.2f}) — {s.reasoning}" for s in outcome.signals]
    reasoning_summary = "\n".join(reasoning_lines)

    decision = Decision(
        complaint_id=complaint.id,
        composite_score=score,
        bucket=bucket,
        decided_by="system",
        reasoning_summary=reasoning_summary,
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)

    audit_service.record(
        db, complaint.id, "system", "decision_made",
        {"composite_score": score, "bucket": bucket.value},
    )

    return decision


def override(db: Session, decision: Decision, agent_id: str, new_bucket: DecisionBucket, reason: str) -> Decision:
    """Human override — always logged with a mandatory reason. Overrides are
    themselves a fraud/quality signal (Phase 2/6): pattern-check agents who
    override auto_reject far more than peers."""
    old_bucket = decision.bucket
    decision.bucket = new_bucket
    decision.decided_by = f"agent:{agent_id}"
    db.add(decision)
    db.commit()
    db.refresh(decision)

    audit_service.record(
        db, decision.complaint_id, f"agent:{agent_id}", "decision_overridden",
        {"old_bucket": old_bucket.value, "new_bucket": new_bucket.value, "reason": reason},
    )

    return decision
