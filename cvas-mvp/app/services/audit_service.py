from sqlalchemy.orm import Session

from app.models import AuditEvent


def record(db: Session, complaint_id: str, actor: str, action: str, details: dict | None = None) -> AuditEvent:
    """Every meaningful state change goes through here. Never update or delete
    an AuditEvent row once written — this table is append-only by convention.
    In production this should be backed by a hash-chained or WORM store."""
    event = AuditEvent(
        complaint_id=complaint_id,
        actor=actor,
        action=action,
        details=details or {},
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
