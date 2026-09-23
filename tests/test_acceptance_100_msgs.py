"""
End-to-End Acceptance Test for Omar WhatsApp Intelligence (OWI).
Imports a 105-message synthetic WhatsApp export ZIP archive with media,
validates parsing, task extraction, Stone Mode real estate intelligence,
and grounded conversational Q&A search with local citations.
"""

from pathlib import Path
from owi.config import WORKSPACE_DIR
from owi.ingest.zip_importer import ZipImporter
from owi.ai.local_nlp import LocalNLPEngine
from owi.templates.property_stone import PropertyStoneEngine
from owi.ai.rag import AskWhatsAppEngine
from owi.db.models import Conversation, Message, Task, WaitingFor, Decision, Commitment, Property, MediaAsset

def test_acceptance_100_messages_pipeline(test_db):
    zip_path = WORKSPACE_DIR / "synthetic_chats" / "WhatsApp Chat - Omar Team Office.zip"
    assert zip_path.exists(), "Synthetic dataset ZIP archive must exist."

    # 1. Ingest WhatsApp Export ZIP archive
    import_result = ZipImporter.import_zip(zip_path, test_db)
    assert import_result["status"] == "success"
    assert import_result["messages_imported"] >= 100, f"Expected 100+ messages, got {import_result['messages_imported']}"
    assert import_result["media_files_linked"] >= 3, f"Expected >= 3 media attachments linked, got {import_result['media_files_linked']}"
    
    conv_id = import_result["conversation_id"]

    # 2. Verify Conversation & Message integrity
    conv = test_db.query(Conversation).filter(Conversation.id == conv_id).first()
    assert conv is not None
    assert conv.message_count >= 100

    messages = test_db.query(Message).filter(Message.conversation_id == conv_id).all()
    assert len(messages) >= 100
    
    # Check participants
    senders = {m.sender_name for m in messages if m.sender_name not in ("System", "Unknown")}
    assert "Omar" in senders
    assert "Ahmed El-Sayed" in senders
    assert "Sarah Hassan" in senders
    assert "Tarek Mansour" in senders

    # 3. Trigger & Verify Knowledge Extraction
    nlp_res = LocalNLPEngine.analyze_conversation(conv_id, test_db)
    assert nlp_res["tasks"] > 0
    assert nlp_res["waiting_for"] > 0
    assert nlp_res["decisions"] > 0
    assert nlp_res["commitments"] > 0

    # 4. Verify Task Inbox
    tasks = test_db.query(Task).filter(Task.conversation_id == conv_id).all()
    assert len(tasks) > 0
    for t in tasks:
        assert t.status == "inbox"
        assert t.confidence >= 0.7
        assert t.source_excerpt is not None

    # 5. Verify Waiting For
    waiting_items = test_db.query(WaitingFor).filter(WaitingFor.conversation_id == conv_id).all()
    assert len(waiting_items) > 0

    # 6. Verify Property Stone Mode
    prop = PropertyStoneEngine.extract_from_conversation(conv_id, test_db)
    assert prop is not None
    assert prop.area_sqm == 500.0 or prop.area_sqm == 450.0
    assert prop.price == 280000.0 or prop.price == 300000.0
    assert "التجمع" in (prop.location or "") or "التجمع" in (prop.district or "")
    assert prop.listing_draft is not None

    # 7. Conversational Search / RAG with local citations
    rag_query = "ما هو سعر إيجار المقر؟"
    rag_res = AskWhatsAppEngine.ask(rag_query, test_db, conversation_id=conv_id)
    assert "answer" in rag_res
    assert len(rag_res["citations"]) > 0
    assert any("280,000" in str(c) or "300,000" in str(c) for c in rag_res["citations"])

    # 8. Verify Idempotent re-import does not duplicate
    reimport_res = ZipImporter.import_zip(zip_path, test_db)
    assert reimport_res["status"] == "already_imported"
    assert reimport_res["duplicate"] is True
    assert reimport_res["conversation_id"] == conv_id
