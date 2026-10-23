"""
End-to-end pipeline test using an isolated in-memory SQLite DB, so this runs
without Postgres/Docker for fast local iteration.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ["DATABASE_URL"] = "sqlite:///./test_cvas.db"

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200


def test_full_pipeline_review_bucket_by_default():
    # 1. Create complaint
    resp = client.post("/v1/complaints", json={
        "tenant_id": "zepto_demo",
        "order_id": "order_123",
        "user_id": "user_abc",
        "device_id": "device_xyz",
        "category": "item_missing",
        "description": "The mango pack I ordered was missing from the bag.",
        "claimed_amount": 120.0,
    })
    assert resp.status_code == 200
    complaint_id = resp.json()["id"]

    # 2. Push order-event ground truth (delivered before the complaint was filed)
    resp = client.post("/v1/webhooks/order-events", json={
        "tenant_id": "zepto_demo",
        "order_id": "order_123",
        "delivered_at": "2020-01-01T10:00:00",
        "weight_at_pickup_g": 500,
        "rider_id": "rider_1",
        "order_value": 120.0,
    })
    assert resp.status_code == 200

    # 3. Upload telemetry evidence
    resp = client.post(f"/v1/complaints/{complaint_id}/evidence/telemetry", json={
        "payload": {"app_session_id": "sess_1"}
    })
    assert resp.status_code == 200

    # 4. Run verification + decision
    resp = client.post(f"/v1/complaints/{complaint_id}/verify")
    assert resp.status_code == 200
    body = resp.json()

    assert body["decision"] is not None
    assert body["decision"]["bucket"] in ("auto_approve", "auto_reject", "review")
    assert len(body["verification_results"]) == 5

    # 5. Status endpoint returns the same decision
    resp = client.get(f"/v1/complaints/{complaint_id}/status")
    assert resp.status_code == 200
    assert resp.json()["decision"]["complaint_id"] == complaint_id


def test_duplicate_image_hash_pushes_toward_reject():
    # First complaint with an image
    resp = client.post("/v1/complaints", json={
        "tenant_id": "zepto_demo",
        "order_id": "order_A",
        "user_id": "user_1",
        "category": "item_damaged",
        "description": "Bottle arrived cracked.",
    })
    complaint_a = resp.json()["id"]
    client.post(
        f"/v1/complaints/{complaint_a}/evidence/image",
        files={"file": ("crack.jpg", b"fixed-bytes-for-test", "image/jpeg")},
    )
    client.post(f"/v1/complaints/{complaint_a}/verify")

    # Second complaint, different order, SAME image bytes -> duplicate hash
    resp = client.post("/v1/complaints", json={
        "tenant_id": "zepto_demo",
        "order_id": "order_B",
        "user_id": "user_2",
        "category": "item_damaged",
        "description": "Bottle arrived cracked.",
    })
    complaint_b = resp.json()["id"]
    client.post(
        f"/v1/complaints/{complaint_b}/evidence/image",
        files={"file": ("crack.jpg", b"fixed-bytes-for-test", "image/jpeg")},
    )
    resp = client.post(f"/v1/complaints/{complaint_b}/verify")

    results = {r["model_name"]: r for r in resp.json()["verification_results"]}
    assert results["duplicate_hash_check"]["verdict"] == "duplicate_image_detected"
    assert results["duplicate_hash_check"]["score"] < 0.1
