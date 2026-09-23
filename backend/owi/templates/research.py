"""
Research Mode Domain Template.
Extracts research questions, methodologies, citations, authors, findings, and follow-ups.
"""

import re
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from owi.db.models import Message, ResearchItem

RESEARCH_PATTERNS = [
    re.compile(r'(?i)(?:research\s*question|rq:?)\s*([^\.\n\?!]+)'),
    re.compile(r'(?i)(?:paper:?|citation:?|doi:?)\s*([^\.\n\?!]+)'),
    re.compile(r'(?i)(?:finding:?|result:?|discovered)\s*([^\.\n\?!]+)'),
    re.compile(r'(?:سؤال البحث|فرضية|دراسة|ورقة بحثية|نتائج البحث)\s*([^\.\n\?!]+)'),
]

class ResearchEngine:
    """Extracts academic and investigatory research items."""

    @classmethod
    def extract_from_conversation(cls, conversation_id: int, db: Session) -> List[ResearchItem]:
        messages = db.query(Message).filter(Message.conversation_id == conversation_id).all()
        created_items = []

        for m in messages:
            for pat in RESEARCH_PATTERNS:
                match = pat.search(m.content)
                if match:
                    item_text = match.group(1).strip()
                    r_item = ResearchItem(
                        conversation_id=conversation_id,
                        topic="بحث علمي / دراسة",
                        question=item_text,
                        author=m.sender_name,
                        finding=m.content,
                    )
                    db.add(r_item)
                    created_items.append(r_item)
                    break

        if created_items:
            db.commit()

        return created_items
