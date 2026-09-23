"""
Rule-based NLP and semantic extraction engine.
Extracts Tasks, Waiting-For, Decisions, Commitments, Ideas, Properties, and Research items
from message content with confidence scores and source citations.
"""

import re
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from owi.core.logging import logger
from owi.db.models import (
    Message, Conversation, Task, WaitingFor, Decision, Idea, Commitment, Property, ResearchItem
)
from owi.ai.date_resolver import resolve_relative_date

# Regular expressions and keywords for Arabic and English extraction
TASK_PATTERNS = [
    re.compile(r'(?i)(?:please|plz|pls)\s+(?:send|check|call|review|prepare|submit|follow\s*up|arrange|share|update)\s+([^\.\n\?!]+)'),
    re.compile(r'(?i)(?:need\s+to|have\s+to|must|action\s*item|todo:?)\s+([^\.\n\?!]+)'),
    re.compile(r'(?:برجاء|أرجو|ارجو|مطلوب|لازم|محتاجين|ضروري)\s+(?:إرسال|ارسال|مراجعة|الاتصال|تجهيز|تحضير|متابعة|تحديث)\s+([^\.\n\?!]+)'),
    re.compile(r'(?:ابعت|ابعتلي|كلم|راجع|خلّص|خلص|جهّز|جهز|شوف)\s+([^\.\n\?!]+)'),
]

WAITING_PATTERNS = [
    re.compile(r'(?i)waiting\s+(?:for|on)\s+([a-zA-Z\s]+?)\s+(?:to\s+send|to\s+reply|for\s+the|to\s+confirm)\s*([^\.\n\?!]+)'),
    re.compile(r'(?:مستني|في انتظار|بانتظار|منتظر|مستنيين)\s+([\u0600-\u06FF\s]+?)\s+(?:يبعت|يرد|يأكد|يرسل|عشان)\s*([^\.\n\?!]+)'),
    re.compile(r'(?:مستني|بانتظار|في انتظار)\s+([^\.\n\?!]+)'),
]

DECISION_PATTERNS = [
    re.compile(r'(?i)(?:we\s+decided|agreed\s+(?:to|on)|we\'ll\s+offer|offer\s+approved|deal\s+closed|approved|deal:)\s+([^\.\n\?!]+)'),
    re.compile(r'(?:قررنا|اتفقنا|تم الاتفاق|اعتمدنا|خلاص هانعمل|خلاص هنعمل|تمام هنشتري|هنقدم عرض|وافقت على)\s+([^\.\n\?!]+)'),
]

COMMITMENT_PATTERNS = [
    re.compile(r'(?i)(?:i\s+will|i\'ll|we\s+will|we\'ll)\s+(?:send|prepare|call|finish|check|share)\s+([^\.\n\?!]+)'),
    re.compile(r'(?:هبعتلك|هبعت|سأقوم بإرسال|سأرسل|هكلمه|هخلص|هخلّص|هجهّز|هشوفلك)\s+([^\.\n\?!]+)'),
]

IDEA_PATTERNS = [
    re.compile(r'(?i)(?:idea:?|what\s+if\s+we|how\s+about|we\s+could|suggestion:?)\s+([^\.\n\?!]+)'),
    re.compile(r'(?:فكرة:?|إيه رأيك لو|ايه رايك لو|بفكر نعمل|اقتراح:?|ممكن نعمل)\s+([^\.\n\?!]+)'),
]

class LocalNLPEngine:
    """Extracts structured knowledge items from messages."""

    @classmethod
    def analyze_message(cls, message: Message, db: Session) -> Dict[str, Any]:
        text = message.content or ""
        msg_date = message.timestamp or datetime.utcnow()
        sender = message.sender_name or "Unknown"

        tasks_found = []
        waiting_found = []
        decisions_found = []
        commitments_found = []
        ideas_found = []

        # 1. Tasks
        for pat in TASK_PATTERNS:
            m = pat.search(text)
            if m:
                task_content = m.group(1).strip()
                due_date = resolve_relative_date(text, msg_date)
                task = Task(
                    conversation_id=message.conversation_id,
                    message_id=message.id,
                    title=f"{task_content[:80]}",
                    description=text,
                    status="inbox",
                    priority="medium",
                    confidence=0.88,
                    created_date=msg_date,
                    due_date=due_date,
                    assigned_contact_name=sender if "هبعت" in text or "i will" in text.lower() else None,
                    source_excerpt=text[:250]
                )
                db.add(task)
                tasks_found.append(task)
                break

        # 2. Waiting For
        for pat in WAITING_PATTERNS:
            m = pat.search(text)
            if m:
                groups = m.groups()
                person = groups[0].strip() if len(groups) > 1 else sender
                deliverable = groups[1].strip() if len(groups) > 1 else groups[0].strip()
                due_date = resolve_relative_date(text, msg_date)
                
                wf = WaitingFor(
                    conversation_id=message.conversation_id,
                    message_id=message.id,
                    person_name=person,
                    deliverable=deliverable[:200],
                    status="open",
                    due_date=due_date,
                    source_excerpt=text[:250]
                )
                db.add(wf)
                waiting_found.append(wf)
                break

        # 3. Decisions
        for pat in DECISION_PATTERNS:
            m = pat.search(text)
            if m:
                decision_text = m.group(1).strip()
                dec = Decision(
                    conversation_id=message.conversation_id,
                    message_id=message.id,
                    decision_text=decision_text,
                    confidence=0.90,
                    participants=sender,
                    timestamp=msg_date,
                    source_excerpt=text[:250]
                )
                db.add(dec)
                decisions_found.append(dec)
                break

        # 4. Commitments
        for pat in COMMITMENT_PATTERNS:
            m = pat.search(text)
            if m:
                comm_text = m.group(1).strip()
                due_date = resolve_relative_date(text, msg_date)
                comm = Commitment(
                    conversation_id=message.conversation_id,
                    message_id=message.id,
                    person_name=sender,
                    commitment_text=comm_text[:200],
                    expected_date=due_date,
                    source_excerpt=text[:250]
                )
                db.add(comm)
                commitments_found.append(comm)
                break

        # 5. Ideas
        for pat in IDEA_PATTERNS:
            m = pat.search(text)
            if m:
                idea_text = m.group(1).strip()
                idea = Idea(
                    conversation_id=message.conversation_id,
                    message_id=message.id,
                    title=idea_text[:80],
                    description=text,
                    source_excerpt=text[:250]
                )
                db.add(idea)
                ideas_found.append(idea)
                break

        db.commit()

        return {
            "message_id": message.id,
            "tasks": len(tasks_found),
            "waiting_for": len(waiting_found),
            "decisions": len(decisions_found),
            "commitments": len(commitments_found),
            "ideas": len(ideas_found)
        }

    @classmethod
    def analyze_conversation(cls, conversation_id: int, db: Session) -> Dict[str, Any]:
        """Analyze all messages in a conversation and compile summary and entities."""
        messages = db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.timestamp).all()
        if not messages:
            return {"status": "no_messages"}

        total_tasks = 0
        total_waiting = 0
        total_decisions = 0
        total_commitments = 0
        total_ideas = 0

        for msg in messages:
            res = cls.analyze_message(msg, db)
            total_tasks += res["tasks"]
            total_waiting += res["waiting_for"]
            total_decisions += res["decisions"]
            total_commitments += res["commitments"]
            total_ideas += res["ideas"]

        # Generate summary
        conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if conv:
            msg_count = len(messages)
            senders = list({m.sender_name for m in messages if m.sender_name not in ("System", "Unknown")})
            senders_str = ", ".join(senders)
            
            summary = (
                f"محادثة تحتوي على {msg_count} رسالة بين ({senders_str}). "
                f"تم استخراج {total_tasks} مهمة، و {total_decisions} قرارات، "
                f"و {total_commitments} التزامات، و {total_waiting} عناصر قيد الانتظار."
            )
            conv.summary = summary
            conv.detailed_summary = summary
            db.commit()

        return {
            "conversation_id": conversation_id,
            "tasks": total_tasks,
            "waiting_for": total_waiting,
            "decisions": total_decisions,
            "commitments": total_commitments,
            "ideas": total_ideas
        }
