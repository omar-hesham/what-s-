"""
Unit tests for NLP extraction: tasks, waiting-for, decisions, commitments, and real estate Stone Mode.
"""

from datetime import datetime
from owi.db.models import Conversation, Message, Task, WaitingFor, Decision, Commitment, Property
from owi.ai.local_nlp import LocalNLPEngine
from owi.templates.property_stone import PropertyStoneEngine

def test_task_extraction(test_db):
    conv = Conversation(title="Project Chat", source_type="export_txt")
    test_db.add(conv)
    test_db.commit()

    msg = Message(
        conversation_id=conv.id,
        sender_name="Omar",
        timestamp=datetime(2026, 9, 14, 10, 0),
        content="برجاء إرسال السجل التجاري والبطاقة الضريبية بكرة الصبح."
    )
    test_db.add(msg)
    test_db.commit()

    res = LocalNLPEngine.analyze_message(msg, test_db)
    assert res["tasks"] == 1

    task = test_db.query(Task).filter(Task.message_id == msg.id).first()
    assert task is not None
    assert "السجل التجاري" in task.title or "السجل" in task.description
    assert task.status == "inbox"
    assert task.confidence > 0.8
    assert task.due_date == datetime(2026, 9, 15, 10, 0)  # "بكرة" from 14 Sept = 15 Sept

def test_waiting_for_extraction(test_db):
    conv = Conversation(title="Project Chat", source_type="export_txt")
    test_db.add(conv)
    test_db.commit()

    msg = Message(
        conversation_id=conv.id,
        sender_name="Tarek",
        timestamp=datetime(2026, 9, 14, 11, 0),
        content="مستني أحمد يبعت رخصة الإداري وموافقة المالك."
    )
    test_db.add(msg)
    test_db.commit()

    res = LocalNLPEngine.analyze_message(msg, test_db)
    assert res["waiting_for"] == 1

    wf = test_db.query(WaitingFor).filter(WaitingFor.message_id == msg.id).first()
    assert wf is not None
    assert "أحمد" in wf.person_name
    assert wf.status == "open"

def test_decision_and_commitment(test_db):
    conv = Conversation(title="Project Chat", source_type="export_txt")
    test_db.add(conv)
    test_db.commit()

    msg1 = Message(
        conversation_id=conv.id,
        sender_name="Omar",
        timestamp=datetime(2026, 9, 14, 12, 0),
        content="اتفقنا على تقديم عرض مبدئي بـ 280,000 جنيه."
    )
    msg2 = Message(
        conversation_id=conv.id,
        sender_name="Ahmed",
        timestamp=datetime(2026, 9, 14, 12, 5),
        content="هبعتلك العقد المعدل بكرة إن شاء الله."
    )
    test_db.add_all([msg1, msg2])
    test_db.commit()

    LocalNLPEngine.analyze_message(msg1, test_db)
    LocalNLPEngine.analyze_message(msg2, test_db)

    decision = test_db.query(Decision).filter(Decision.message_id == msg1.id).first()
    assert decision is not None
    assert "280,000" in decision.decision_text

    commitment = test_db.query(Commitment).filter(Commitment.message_id == msg2.id).first()
    assert commitment is not None
    assert commitment.person_name == "Ahmed"
    assert commitment.expected_date == datetime(2026, 9, 15, 12, 5)

def test_property_stone_mode(test_db):
    conv = Conversation(title="Real Estate Search", source_type="export_txt")
    test_db.add(conv)
    test_db.commit()

    messages = [
        Message(conversation_id=conv.id, sender_name="Omar", timestamp=datetime(2026, 9, 14, 9, 0), content="محتاجين مكتب في التجمع الخامس مساحة 500 متر."),
        Message(conversation_id=conv.id, sender_name="Tarek", timestamp=datetime(2026, 9, 14, 9, 5), content="المكتب تشطيب الترا سوبر لوكس وفيه رخصة إداري رسمي."),
        Message(conversation_id=conv.id, sender_name="Ahmed", timestamp=datetime(2026, 9, 14, 9, 10), content="سعر الإيجار 280,000 جنيه شهرياً.")
    ]
    test_db.add_all(messages)
    test_db.commit()

    prop = PropertyStoneEngine.extract_from_conversation(conv.id, test_db)
    assert prop is not None
    assert prop.area_sqm == 500.0
    assert prop.price == 280000.0
    assert prop.deal_type == "rent"
    assert prop.district == "التجمع الخامس" or "التجمع" in prop.location
    assert prop.has_admin_license is True
    assert prop.finishing == "Ultra Lux"
    assert prop.listing_draft is not None
