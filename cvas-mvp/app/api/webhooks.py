from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import OrderEvent
from app.schemas import OrderEventIn

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


@router.post("/order-events")
def receive_order_event(payload: OrderEventIn, db: Session = Depends(get_db)):
    """Host platform (Zepto/Swiggy/Amazon-style) pushes delivery ground truth
    here — this is what geo_time_plausibility and future liability-attribution
    signals verify claims against. Upserts on (tenant_id, order_id)."""
    existing = (
        db.query(OrderEvent)
        .filter(OrderEvent.tenant_id == payload.tenant_id, OrderEvent.order_id == payload.order_id)
        .first()
    )
    if existing:
        for field, value in payload.model_dump().items():
            setattr(existing, field, value)
        db.add(existing)
        db.commit()
        return {"status": "updated", "order_event_id": existing.id}

    event = OrderEvent(**payload.model_dump())
    db.add(event)
    db.commit()
    db.refresh(event)
    return {"status": "created", "order_event_id": event.id}
