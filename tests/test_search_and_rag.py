"""
Unit tests for full-text search, semantic vector ranking, and grounded RAG citations.
"""

from datetime import datetime
from owi.db.models import Conversation, Message, Task, Property
from owi.ai.embeddings import LocalEmbeddingEngine
from owi.ai.rag import AskWhatsAppEngine

def test_local_embeddings():
    vec1 = LocalEmbeddingEngine.compute_embedding("مكتب إداري في التجمع الخامس")
    vec2 = LocalEmbeddingEngine.compute_embedding("مقر إداري بالتجمع")
    vec3 = LocalEmbeddingEngine.compute_embedding("عصير برتقال طازج")

    sim_related = LocalEmbeddingEngine.cosine_similarity(vec1, vec2)
    sim_unrelated = LocalEmbeddingEngine.cosine_similarity(vec1, vec3)

    assert len(vec1) == 384
    assert sim_related > sim_unrelated, f"Expected {sim_related} > {sim_unrelated}"

def test_ask_whatsapp_grounded_rag(test_db):
    conv = Conversation(title="Office Search", source_type="export_txt")
    test_db.add(conv)
    test_db.commit()

    msg = Message(
        conversation_id=conv.id,
        sender_name="Ahmed El-Sayed",
        timestamp=datetime(2026, 9, 14, 10, 0),
        content="سعر إيجار المقر 280,000 جنيه شهرياً."
    )
    test_db.add(msg)
    test_db.commit()

    prop = Property(
        conversation_id=conv.id,
        title="مكتب إداري 500 م²",
        price=280000.0,
        currency="EGP",
        location="التجمع الخامس",
        source_evidence="سعر إيجار المقر 280,000 جنيه شهرياً."
    )
    test_db.add(prop)
    test_db.commit()

    # Query RAG engine
    res = AskWhatsAppEngine.ask("ما هو سعر إيجار المكتب؟", test_db, conversation_id=conv.id)
    assert "answer" in res
    assert "citations" in res
    assert len(res["citations"]) > 0
    assert "280,000" in res["answer"]
    assert res["citations"][0]["conversation_id"] == conv.id
