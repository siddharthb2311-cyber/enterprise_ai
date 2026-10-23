from fastapi import FastAPI

from app.database import Base, engine
from app.api import complaints, webhooks

app = FastAPI(
    title="CVAS MVP",
    description="Complaint Verification & Automated Settlement — Phase 1 pipeline",
    version="0.1.0",
)

# Dev convenience only — use Alembic migrations before this touches a real
# production database. Runs at import time (not just on ASGI startup) so it
# also fires correctly under TestClient in tests.
Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(complaints.router)
app.include_router(webhooks.router)
