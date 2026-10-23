from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Complaint, ComplaintStatus, DecisionBucket
from app.schemas import ComplaintCreate, ComplaintOut, ComplaintStatusOut, OverrideIn
from app.services import audit_service, evidence_service, verification_engine, decision_engine

router = APIRouter(prefix="/v1/complaints", tags=["complaints"])


@router.post("", response_model=ComplaintOut)
def create_complaint(payload: ComplaintCreate, db: Session = Depends(get_db)):
    complaint = Complaint(**payload.model_dump())
    db.add(complaint)
    db.commit()
    db.refresh(complaint)

    audit_service.record(db, complaint.id, f"user:{complaint.user_id}", "complaint_created",
                          {"category": complaint.category.value})

    return complaint


@router.post("/{complaint_id}/evidence/image")
async def upload_image_evidence(complaint_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    content = await file.read()
    evidence = evidence_service.save_image_evidence(db, complaint_id, file.filename, content)

    complaint.status = ComplaintStatus.EVIDENCE_PENDING
    db.add(complaint)
    db.commit()

    return {"evidence_id": evidence.id, "content_hash": evidence.content_hash}


@router.post("/{complaint_id}/evidence/telemetry")
def upload_telemetry_evidence(complaint_id: str, payload: dict, db: Session = Depends(get_db)):
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    evidence = evidence_service.save_telemetry_evidence(db, complaint_id, payload)
    return {"evidence_id": evidence.id}


@router.post("/{complaint_id}/verify", response_model=ComplaintStatusOut)
def run_verification(complaint_id: str, db: Session = Depends(get_db)):
    """Triggers the verification + decision pipeline. In production this
    would be kicked off async via a queue on evidence-submission-complete,
    not called synchronously by the client — kept synchronous here for
    MVP simplicity and easy debugging."""
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    complaint.status = ComplaintStatus.VERIFYING
    db.add(complaint)
    db.commit()

    outcome = verification_engine.run(db, complaint)
    decision_engine.decide(db, complaint, outcome)

    complaint.status = ComplaintStatus.DECIDED
    db.add(complaint)
    db.commit()
    db.refresh(complaint)

    return get_status(complaint_id, db)


@router.get("/{complaint_id}/status", response_model=ComplaintStatusOut)
def get_status(complaint_id: str, db: Session = Depends(get_db)):
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    return ComplaintStatusOut(
        complaint=complaint,
        verification_results=complaint.verification_results,
        decision=complaint.decision,
    )


@router.get("/queue/review")
def review_queue(tenant_id: str, db: Session = Depends(get_db)):
    """Merchant-facing queue: everything the system couldn't confidently
    auto-approve or auto-reject. This is the Phase 1 deliverable — the
    system recommends, a human/merchant system still executes."""
    from app.models import Decision

    rows = (
        db.query(Complaint, Decision)
        .join(Decision, Decision.complaint_id == Complaint.id)
        .filter(Complaint.tenant_id == tenant_id, Decision.bucket == DecisionBucket.REVIEW)
        .all()
    )
    return [
        {
            "complaint_id": c.id,
            "order_id": c.order_id,
            "category": c.category.value,
            "composite_score": d.composite_score,
            "reasoning_summary": d.reasoning_summary,
        }
        for c, d in rows
    ]


@router.post("/{complaint_id}/decision/override")
def override_decision(complaint_id: str, payload: OverrideIn, db: Session = Depends(get_db)):
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint or not complaint.decision:
        raise HTTPException(status_code=404, detail="Complaint or decision not found")

    decision = decision_engine.override(
        db, complaint.decision, payload.agent_id, payload.new_bucket, payload.reason
    )
    return {"complaint_id": complaint_id, "new_bucket": decision.bucket.value}
