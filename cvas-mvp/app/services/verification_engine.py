"""
Verification engine v1.

Three hooks are meant to be replaced with real model calls as they become
available (see README "Swapping in real models"). Everything downstream
(DecisionEngine) only depends on the VerificationSignal contract below, so
swapping an implementation here never requires touching the decision logic.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import Complaint, Evidence, OrderEvent, RiskProfile, VerificationResult
from app.services import audit_service, evidence_service


@dataclass
class VerificationSignal:
    model_name: str
    score: float          # 0..1, higher = more consistent with a genuine claim
    verdict: str
    reasoning: str


@dataclass
class VerificationOutcome:
    signals: list[VerificationSignal] = field(default_factory=list)


def classify_complaint(description: str | None) -> VerificationSignal:
    """STUB — replace with an LLM call that returns category confidence and
    flags contradictions between stated category and free text. Keyword
    matching here is only enough to keep the pipeline runnable end-to-end."""
    if not description:
        return VerificationSignal(
            model_name="complaint_classifier_stub",
            score=0.5,
            verdict="neutral",
            reasoning="No description provided to classify against.",
        )

    text = description.lower()
    red_flags = ["never received anything", "always broken", "every time"]
    if any(flag in text for flag in red_flags):
        return VerificationSignal(
            model_name="complaint_classifier_stub",
            score=0.35,
            verdict="suspicious_language",
            reasoning="Description contains absolute/repeat-pattern language often seen in serial claims.",
        )

    return VerificationSignal(
        model_name="complaint_classifier_stub",
        score=0.7,
        verdict="plausible",
        reasoning="Description is specific and consistent with the claimed category.",
    )


def check_image_consistency(evidence_items: list[Evidence]) -> VerificationSignal:
    """STUB — replace with a vision model call: damage/count detection against
    the catalog image, EXIF/capture-time consistency, and duplicate/perceptual
    hash lookup. Currently returns a neutral score and only checks whether
    image evidence exists at all, since "no photo" is itself a weak signal
    for damage/missing-item categories."""
    images = [e for e in evidence_items if e.evidence_type == "image"]
    if not images:
        return VerificationSignal(
            model_name="vision_consistency_stub",
            score=0.5,
            verdict="no_image_evidence",
            reasoning="No image evidence attached — neutral score pending manual review.",
        )
    return VerificationSignal(
        model_name="vision_consistency_stub",
        score=0.65,
        verdict="image_present",
        reasoning=f"{len(images)} image(s) attached; content-level damage/count check not yet wired to a real model.",
    )


def duplicate_evidence_check(db: Session, complaint: Complaint, evidence_items: list[Evidence]) -> VerificationSignal:
    for item in evidence_items:
        if item.evidence_type == "image" and item.content_hash:
            if evidence_service.find_duplicate_hash(db, complaint.tenant_id, item.content_hash, complaint.id):
                return VerificationSignal(
                    model_name="duplicate_hash_check",
                    score=0.05,
                    verdict="duplicate_image_detected",
                    reasoning="This exact image hash was used on a different complaint by this tenant.",
                )
    return VerificationSignal(
        model_name="duplicate_hash_check",
        score=0.9,
        verdict="no_duplicate_found",
        reasoning="No exact-hash matches against other complaints for this tenant.",
    )


def geo_time_plausibility(complaint: Complaint, order_event: OrderEvent | None) -> VerificationSignal:
    if order_event is None or order_event.delivered_at is None:
        return VerificationSignal(
            model_name="geo_time_plausibility",
            score=0.5,
            verdict="no_order_event",
            reasoning="No order-event ground truth received yet from host platform webhook.",
        )

    # A claim filed before delivery is a hard implausibility signal.
    if complaint.created_at < order_event.delivered_at:
        return VerificationSignal(
            model_name="geo_time_plausibility",
            score=0.02,
            verdict="claim_before_delivery",
            reasoning="Complaint timestamp precedes the recorded delivery timestamp.",
        )

    return VerificationSignal(
        model_name="geo_time_plausibility",
        score=0.8,
        verdict="plausible_timing",
        reasoning="Complaint filed after recorded delivery time.",
    )


def fraud_velocity_signal(db: Session, tenant_id: str, user_id: str) -> VerificationSignal:
    profile = (
        db.query(RiskProfile)
        .filter(RiskProfile.tenant_id == tenant_id, RiskProfile.user_id == user_id)
        .first()
    )
    if profile is None or profile.total_orders == 0:
        return VerificationSignal(
            model_name="fraud_velocity",
            score=0.6,
            verdict="no_history",
            reasoning="No risk profile / order history yet for this user — treated as neutral-new.",
        )

    claim_ratio = profile.total_claims / max(profile.total_orders, 1)

    if claim_ratio > 0.5 and profile.total_orders >= 4:
        return VerificationSignal(
            model_name="fraud_velocity",
            score=0.15,
            verdict="high_claim_ratio",
            reasoning=f"Claim ratio {claim_ratio:.2f} across {profile.total_orders} orders exceeds tenant baseline.",
        )

    return VerificationSignal(
        model_name="fraud_velocity",
        score=0.75,
        verdict="within_baseline",
        reasoning=f"Claim ratio {claim_ratio:.2f} is within normal range.",
    )


def run(db: Session, complaint: Complaint) -> VerificationOutcome:
    """Runs every signal, persists each as a VerificationResult row, and
    returns them for the decision engine to score. Order of signals doesn't
    matter — DecisionEngine treats them as a flat weighted set."""
    evidence_items = db.query(Evidence).filter(Evidence.complaint_id == complaint.id).all()
    order_event = (
        db.query(OrderEvent)
        .filter(OrderEvent.tenant_id == complaint.tenant_id, OrderEvent.order_id == complaint.order_id)
        .first()
    )

    signals = [
        classify_complaint(complaint.description),
        check_image_consistency(evidence_items),
        duplicate_evidence_check(db, complaint, evidence_items),
        geo_time_plausibility(complaint, order_event),
        fraud_velocity_signal(db, complaint.tenant_id, complaint.user_id),
    ]

    for s in signals:
        result = VerificationResult(
            complaint_id=complaint.id,
            model_name=s.model_name,
            model_version="v1",
            score=s.score,
            verdict=s.verdict,
            reasoning=s.reasoning,
        )
        db.add(result)

    db.commit()
    audit_service.record(db, complaint.id, "system", "verification_completed",
                          {"signal_count": len(signals)})

    return VerificationOutcome(signals=signals)
