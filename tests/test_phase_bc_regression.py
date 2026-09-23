"""
Regression and verification tests for:
- 6-digit companion pairing flow and persistent token authentication
- Property administrative license negation checks ("بدون رخصة إداري")
- Local NLP task idempotence (no duplicates on re-analysis)
- Gemini multimodal service configuration
"""

import pytest
from datetime import datetime
from fastapi.testclient import TestClient
from owi.main import app
from owi.templates.property_stone import PropertyStoneEngine
from owi.ai.local_nlp import LocalNLPEngine
from owi.ai.gemini_service import GeminiService
from owi.db.models import Conversation, Message, Task

client = TestClient(app)

def test_companion_pairing_full_lifecycle():
    # 0. Authenticate test client session via bootstrap flow
    boot = client.get("/api/auth/bootstrap").json()["bootstrap_token"]
    exchange = client.post("/api/auth/exchange", json={"bootstrap_token": boot})
    assert exchange.status_code == 200

    # 1. Generate 6-digit code from authenticated UI session
    code_res = client.get("/api/companion/pairing/code")
    assert code_res.status_code == 200
    code_data = code_res.json()
    assert "code" in code_data
    assert len(code_data["code"]) == 6
    code = code_data["code"]

    # 2. Pair with code
    pair_res = client.post("/api/companion/pairing/pair", json={
        "code": code,
        "device_name": "Test Extension Runner"
    })
    assert pair_res.status_code == 200
    pair_data = pair_res.json()
    assert pair_data["status"] == "paired"
    token = pair_data["token"]
    assert token.startswith("owi_pair_")

    # 3. Using token on ingest
    ingest_res = client.post(
        "/api/companion/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "chat_title": "Test Pair Chat",
            "messages": [
                {
                    "sender": "Companion Tester",
                    "text": "Hello through authenticated companion!",
                    "timestamp": "10:30 AM, 9/23/2026",
                    "is_outgoing": False
                }
            ]
        }
    )
    assert ingest_res.status_code == 200
    ingest_data = ingest_res.json()
    assert ingest_data["messages_ingested"] == 1

    # 4. Ingest with invalid token should fail
    bad_res = client.post(
        "/api/companion/ingest",
        headers={"Authorization": "Bearer bad_invalid_token"},
        json={"chat_title": "Bad", "messages": []}
    )
    assert bad_res.status_code == 401

    # 5. Revoke token
    revoke_res = client.post(f"/api/companion/pairing/revoke?token={token}")
    assert revoke_res.status_code == 200

    # 6. Once revoked, ingest with it fails
    revoked_ingest = client.post(
        "/api/companion/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={"chat_title": "Test", "messages": []}
    )
    assert revoked_ingest.status_code == 401

def test_property_admin_license_negation(test_db):
    conv = Conversation(title="Property Negation Test", source_type="test")
    test_db.add(conv)
    test_db.commit()

    # Message with negation "بدون رخصة إداري"
    msg = Message(
        conversation_id=conv.id,
        sender_name="Broker",
        content="مكتب للبيع في التجمع الخامس بمساحة 150 متر بسعر 5 مليون بدون رخصة إداري تماماً.",
        timestamp=datetime.utcnow()
    )
    test_db.add(msg)
    test_db.commit()

    prop = PropertyStoneEngine.extract_from_conversation(conv.id, test_db)
    assert prop is not None
    assert prop.area_sqm == 150.0
    assert prop.price == 5000000.0
    # Crucial check: has_admin_license MUST be False because of "بدون رخصة إداري"
    assert prop.has_admin_license is False

def test_property_admin_license_positive(test_db):
    conv = Conversation(title="Property Positive Test", source_type="test")
    test_db.add(conv)
    test_db.commit()

    # Message with positive "رخصة إداري"
    msg = Message(
        conversation_id=conv.id,
        sender_name="Broker",
        content="مكتب للبيع في التجمع الخامس بمساحة 200 متر بسعر 8 مليون ومعه رخصة إداري معتمدة.",
        timestamp=datetime.utcnow()
    )
    test_db.add(msg)
    test_db.commit()

    prop = PropertyStoneEngine.extract_from_conversation(conv.id, test_db)
    assert prop is not None
    assert prop.has_admin_license is True

def test_nlp_task_idempotency(test_db):
    conv = Conversation(title="Idempotency Test", source_type="test")
    test_db.add(conv)
    test_db.commit()

    msg = Message(
        conversation_id=conv.id,
        sender_name="Omar",
        content="لازم مراجعة الفصل الخامس من الكتاب غداً ضروري.",
        timestamp=datetime.utcnow()
    )
    test_db.add(msg)
    test_db.commit()

    # Run analysis first time
    res1 = LocalNLPEngine.analyze_message(msg, test_db)
    assert res1["tasks"] == 1
    tasks1 = test_db.query(Task).filter(Task.message_id == msg.id).all()
    assert len(tasks1) == 1

    # Mark task as completed
    tasks1[0].status = "completed"
    test_db.commit()

    # Run analysis second time on same message
    res2 = LocalNLPEngine.analyze_message(msg, test_db)
    tasks2 = test_db.query(Task).filter(Task.message_id == msg.id).all()
    # Must NOT create a duplicate task or overwrite completed status
    assert len(tasks2) == 1
    assert tasks2[0].status == "completed"

def test_gemini_service_configured():
    # Verify Gemini service detects local configuration
    assert GeminiService.is_configured() is True
