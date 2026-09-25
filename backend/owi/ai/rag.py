"""
Conversational Search & Local RAG Engine ("Ask Your WhatsApp").
Grounds all responses in local SQLite records (messages, transcripts, documents, tasks, properties)
with mandatory local source citations. Never fabricates answers without evidence.
"""

import re
from typing import Dict, Any, List, Optional
from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from owi.core.logging import logger
from owi.config import settings
from owi.ai.gemini_service import GeminiService
from owi.db.models import (
    Message, Conversation, Task, WaitingFor, Decision, Property, MediaAsset, Transcript
)
from owi.ai.embeddings import LocalEmbeddingEngine
from owi.ai.provider import ai_registry

class AskWhatsAppEngine:
    """Answers conversational questions strictly using local retrieved evidence."""

    @classmethod
    def ask(
        cls, 
        query: str, 
        db: Session, 
        conversation_id: Optional[int] = None
    ) -> Dict[str, Any]:
        q_lower = query.lower().strip()
        citations: List[Dict[str, Any]] = []
        answer = ""

        # 1. Specialized Intent: Waiting For
        if any(w in q_lower for w in ["waiting", "مستني", "بانتظار", "في انتظار", "قيد الانتظار"]):
            wf_query = db.query(WaitingFor)
            if conversation_id:
                wf_query = wf_query.filter(WaitingFor.conversation_id == conversation_id)
            items = wf_query.all()
            if items:
                lines = ["إليك العناصر التي تنتظرها من جهات الاتصال:"]
                for it in items:
                    lines.append(f"• من: **{it.person_name}** | المطلوب: {it.deliverable} | الحالة: {it.status}")
                    citations.append({
                        "source_type": "waiting_for",
                        "sender": it.person_name,
                        "deliverable": it.deliverable,
                        "status": it.status,
                        "due_date": it.due_date.isoformat() if it.due_date else None,
                        "source_excerpt": it.source_excerpt,
                        "message_id": it.message_id,
                        "conversation_id": it.conversation_id
                    })
                answer = "\n".join(lines)
                return {"answer": answer, "citations": citations}

        # 2. Specialized Intent: Tasks / To-Do
        if any(w in q_lower for w in ["task", "todo", "مهام", "مهمة", "مطلوب", "action items"]):
            t_query = db.query(Task)
            if conversation_id:
                t_query = t_query.filter(Task.conversation_id == conversation_id)
            tasks = t_query.all()
            if tasks:
                lines = ["إليك المهام المسجلة:"]
                for t in tasks:
                    lines.append(f"• **{t.title}** (الحالة: {t.status} | الأولوية: {t.priority})")
                    citations.append({
                        "source_type": "task",
                        "title": t.title,
                        "status": t.status,
                        "priority": t.priority,
                        "due_date": t.due_date.isoformat() if t.due_date else None,
                        "source_excerpt": t.source_excerpt,
                        "message_id": t.message_id,
                        "conversation_id": t.conversation_id
                    })
                answer = "\n".join(lines)
                return {"answer": answer, "citations": citations}

        # 3. Specialized Intent: Decisions
        if any(w in q_lower for w in ["decision", "agreed", "قرارات", "اتفاق", "اتفقنا", "قررنا"]):
            d_query = db.query(Decision)
            if conversation_id:
                d_query = d_query.filter(Decision.conversation_id == conversation_id)
            decisions = d_query.all()
            if decisions:
                lines = ["إليك القرارات والاتفاقات المسجلة:"]
                for d in decisions:
                    lines.append(f"• {d.decision_text} (المشاركون: {d.participants or 'غير محدد'})")
                    citations.append({
                        "source_type": "decision",
                        "decision_text": d.decision_text,
                        "participants": d.participants,
                        "timestamp": d.timestamp.isoformat() if d.timestamp else None,
                        "source_excerpt": d.source_excerpt,
                        "message_id": d.message_id,
                        "conversation_id": d.conversation_id
                    })
                answer = "\n".join(lines)
                return {"answer": answer, "citations": citations}

        # 4. Specialized Intent: Properties / Real Estate
        if any(w in q_lower for w in ["property", "office", "sqm", "مكتب", "شقة", "فيلا", "عقار", "متر", "سعر", "price"]):
            p_query = db.query(Property)
            if conversation_id:
                p_query = p_query.filter(Property.conversation_id == conversation_id)
            props = p_query.all()
            if props:
                lines = ["إليك العقارات والوحدات المستخرجة:"]
                for p in props:
                    lines.append(f"• **{p.title}** | السعر: {f'{p.price:,.0f} {p.currency}' if p.price else 'غير محدد'} | الموقع: {p.location or 'غير محدد'}")
                    citations.append({
                        "source_type": "property",
                        "title": p.title,
                        "area_sqm": p.area_sqm,
                        "price": p.price,
                        "currency": p.currency,
                        "location": p.location,
                        "evidence": p.source_evidence,
                        "conversation_id": p.conversation_id
                    })
                answer = "\n".join(lines)
                return {"answer": answer, "citations": citations}

        # 5. Hybrid Retrieval: FTS5 + Semantic Search over Messages
        search_terms = [t for t in re.findall(r"\w+", query) if len(t) > 1]
        fts_messages = []
        if search_terms:
            try:
                fts_query_str = " OR ".join(f'"{t}"' for t in search_terms)
                sql = text("""
                    SELECT message_id FROM messages_fts
                    WHERE messages_fts MATCH :query
                    LIMIT 10;
                """)
                res = db.execute(sql, {"query": fts_query_str}).fetchall()
                msg_ids = [r[0] for r in res]
                if msg_ids:
                    msg_q = db.query(Message).filter(Message.id.in_(msg_ids))
                    if conversation_id:
                        msg_q = msg_q.filter(Message.conversation_id == conversation_id)
                    fts_messages = msg_q.all()
            except Exception as e:
                logger.warning(f"FTS search notice: {e}")

        # Search verified derived attachment text (transcripts, OCR, documents)
        derived_citations = []
        der_res = []
        if search_terms:
            try:
                fts_query_str = " OR ".join(f'"{t}"' for t in search_terms)
                sql_der = text("""
                    SELECT media_asset_id, message_id, conversation_id, file_name, source_type, content
                    FROM derived_fts
                    WHERE derived_fts MATCH :query
                    LIMIT 6;
                """)
                der_res = db.execute(sql_der, {"query": fts_query_str}).fetchall()
            except Exception as e:
                logger.warning(f"Derived FTS retrieval notice: {e}")

        if not der_res:
            try:
                # Substring/LIKE fallback for derived content
                for st in search_terms:
                    sql_der_like = text("""
                        SELECT media_asset_id, message_id, conversation_id, file_name, source_type, content
                        FROM derived_fts
                        WHERE content LIKE :like_q
                        LIMIT 6;
                    """)
                    der_res = db.execute(sql_der_like, {"like_q": f"%{st}%"}).fetchall()
                    if der_res:
                        break
            except Exception as e:
                logger.warning(f"Derived LIKE retrieval notice: {e}")

        for aid, mid, cid, fname, stype, d_text in der_res:
            if conversation_id and cid != conversation_id:
                continue
            m_linked = db.query(Message).filter(Message.id == mid).first() if mid else None
            derived_citations.append({
                "source_origin": "derived",
                "source_type": stype,
                "media_asset_id": aid,
                "message_id": mid,
                "conversation_id": cid,
                "file_name": fname,
                "sender": m_linked.sender_name if m_linked else "Attachment",
                "timestamp": m_linked.timestamp.isoformat() if m_linked else None,
                "content": d_text[:300]
            })

        # Semantic vector matches
        semantic_matches = LocalEmbeddingEngine.search_semantic(query, db, limit=5, conversation_id=conversation_id)
        semantic_ids = [m["message_id"] for m in semantic_matches]
        semantic_messages = db.query(Message).filter(Message.id.in_(semantic_ids)).all() if semantic_ids else []

        # Combine and deduplicate retrieved messages
        candidate_map = {m.id: m for m in (fts_messages + semantic_messages)}
        retrieved_messages = list(candidate_map.values())[:8]

        if not retrieved_messages and not derived_citations:
            return {
                "answer": "لم يتم العثور على معلومات مطابقة في قاعدة البيانات المحلية لهذه المحادثة.",
                "citations": []
            }

        # Construct Grounded Response with Citations
        lines = ["بناءً على سجلات المحادثة المحلية:"]
        for m in retrieved_messages:
            lines.append(f"• **{m.sender_name}** ({m.timestamp.strftime('%Y-%m-%d %H:%M')}): {m.content}")
            citations.append({
                "source_origin": "source_message",
                "source_type": "message",
                "message_id": m.id,
                "conversation_id": m.conversation_id,
                "sender": m.sender_name,
                "timestamp": m.timestamp.isoformat(),
                "content": m.content,
                "message_type": m.message_type
            })

        for dc in derived_citations:
            lines.append(f"• **[مرفق: {dc['file_name']} ({dc['source_type']})]** ({dc['sender']}): {dc['content']}")
            citations.append(dc)

        if GeminiService.is_configured():
            try:
                evidence_items = [
                    f"[{m.sender_name} في {m.timestamp.strftime('%Y-%m-%d %H:%M')}]: {m.content}"
                    for m in retrieved_messages
                ]
                for dc in derived_citations:
                    evidence_items.append(f"[مرفق {dc['file_name']} ({dc['source_type']}) من {dc['sender']}]: {dc['content']}")
                evidence_context = "\n".join(evidence_items)
                prompt = (
                    f"أنت مساعد ذكي لتطبيق Omar WhatsApp Intelligence (OWI).\n"
                    f"أجب عن سؤال المستخدم بدقة وبناءً فقط على الأدلة المقتبسة التالية من محادثات الواتساب:\n\n"
                    f"{evidence_context}\n\n"
                    f"سؤال المستخدم: {query}\n\n"
                    f"القواعد:\n"
                    f"1. لا تخترع أي معلومة غير موجودة في الأدلة المقتبسة أعلاه.\n"
                    f"2. أجب باللغة العربية الواضحة والمباشرة وبلهجة ودية ومهنية.\n"
                    f"3. اذكر اسم الشخص أو التوقيت عند ذكر أي معلومة أو قرار أو مهمة."
                )
                client = GeminiService.get_client()
                response = client.models.generate_content(
                    model=settings.GEMINI_MODEL,
                    contents=prompt
                )
                if response.text and response.text.strip():
                    return {
                        "answer": response.text.strip(),
                        "citations": citations,
                        "powered_by": "Gemini 2.5 Flash (Grounded on local records)"
                    }
            except Exception as e:
                logger.warning(f"Gemini RAG synthesis fallback to direct citations: {e}")

        answer = "\n".join(lines)
        return {
            "answer": answer,
            "citations": citations
        }
