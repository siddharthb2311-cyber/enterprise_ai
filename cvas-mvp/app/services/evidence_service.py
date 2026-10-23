import hashlib
import os
from datetime import datetime

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Evidence
from app.services import audit_service


def _sha256_bytes(data: bytes) -> str:
    """Placeholder for perceptual hashing. A real implementation should use
    a perceptual hash (pHash/dHash) so visually-similar-but-not-identical
    reused images still collide, since fraud rings resize/recompress photos
    to dodge exact-hash matching. Swap this function's internals only —
    callers don't need to change."""
    return hashlib.sha256(data).hexdigest()


def save_image_evidence(db: Session, complaint_id: str, filename: str, content: bytes) -> Evidence:
    os.makedirs(settings.media_root, exist_ok=True)
    content_hash = _sha256_bytes(content)

    safe_name = f"{complaint_id}_{datetime.utcnow().timestamp()}_{filename}"
    file_path = os.path.join(settings.media_root, safe_name)
    with open(file_path, "wb") as f:
        f.write(content)

    evidence = Evidence(
        complaint_id=complaint_id,
        evidence_type="image",
        file_path=file_path,
        content_hash=content_hash,
    )
    db.add(evidence)
    db.commit()
    db.refresh(evidence)

    audit_service.record(db, complaint_id, "system", "evidence_captured",
                          {"type": "image", "hash": content_hash})

    return evidence


def save_telemetry_evidence(db: Session, complaint_id: str, payload: dict) -> Evidence:
    evidence = Evidence(
        complaint_id=complaint_id,
        evidence_type="telemetry",
        payload=payload,
    )
    db.add(evidence)
    db.commit()
    db.refresh(evidence)

    audit_service.record(db, complaint_id, "system", "evidence_captured",
                          {"type": "telemetry"})

    return evidence


def find_duplicate_hash(db: Session, tenant_id: str, content_hash: str, exclude_complaint_id: str) -> bool:
    """Checks whether this exact evidence hash has been used on a different
    complaint by this tenant before — the simplest fraud signal: reused photos
    across claims. Join through Complaint to scope by tenant."""
    from app.models import Complaint  # local import to avoid circulars

    hit = (
        db.query(Evidence)
        .join(Complaint, Evidence.complaint_id == Complaint.id)
        .filter(
            Complaint.tenant_id == tenant_id,
            Evidence.content_hash == content_hash,
            Evidence.complaint_id != exclude_complaint_id,
        )
        .first()
    )
    return hit is not None
