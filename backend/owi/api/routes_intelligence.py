"""
Intelligence API routes:
- Ask Your WhatsApp (Conversational Search / RAG with local citations)
- Multi-mode search (Full-text & Semantic)
- Today Dashboard metrics
- Executive Briefings generator
"""

from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel
from sqlalchemy import text, or_
from sqlalchemy.orm import Session

from owi.db.database import get_db
from owi.db.models import (
    Conversation, Message, MediaAsset, Task, WaitingFor, Decision, Idea, Property
)
from owi.ai.rag import AskWhatsAppEngine
from owi.ai.embeddings import LocalEmbeddingEngine

router = APIRouter(prefix="/api/intelligence", tags=["Intelligence"])

class AskRequest(BaseModel):
    query: str
    conversation_id: Optional[int] = None

@router.post("/ask")
def ask_whatsapp(req: AskRequest, db: Session = Depends(get_db)):
    """Conversational question-answering with strict local database citations."""
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    return AskWhatsAppEngine.ask(req.query, db, conversation_id=req.conversation_id)

@router.get("/search")
def search(
    q: str = Query(..., description="Search keyword or phrase"),
    mode: str = Query("hybrid", description="fts, semantic, or hybrid"),
    conversation_id: Optional[int] = Query(None),
    message_type: Optional[str] = Query(None),
    limit: int = 30,
    db: Session = Depends(get_db)
):
    """Full-text and semantic search across messages, transcripts, and documents."""
    results = []
    seen_ids = set()

    # 1. Full-text search with FTS5
    if mode in ("fts", "hybrid"):
        try:
            tokens = [t for t in q.split() if len(t) > 1]
            if tokens:
                fts_query = " OR ".join(f'"{t}"' for t in tokens)
                sql = text("""
                    SELECT message_id FROM messages_fts
                    WHERE messages_fts MATCH :query
                    LIMIT :limit;
                """)
                rows = db.execute(sql, {"query": fts_query, "limit": limit}).fetchall()
                fts_ids = [r[0] for r in rows]
                if fts_ids:
                    query_obj = db.query(Message).filter(Message.id.in_(fts_ids))
                    if conversation_id:
                        query_obj = query_obj.filter(Message.conversation_id == conversation_id)
                    if message_type:
                        query_obj = query_obj.filter(Message.message_type == message_type)
                    for m in query_obj.all():
                        seen_ids.add(m.id)
                        results.append({
                            "message_id": m.id,
                            "conversation_id": m.conversation_id,
                            "sender_name": m.sender_name,
                            "timestamp": m.timestamp.isoformat(),
                            "content": m.content,
                            "message_type": m.message_type,
                            "match_mode": "full_text"
                        })
        except Exception:
            # Fallback to SQL LIKE if FTS table has syntax edge-case
            like_query = db.query(Message).filter(Message.content.ilike(f"%{q}%"))
            if conversation_id:
                like_query = like_query.filter(Message.conversation_id == conversation_id)
            for m in like_query.limit(limit).all():
                if m.id not in seen_ids:
                    seen_ids.add(m.id)
                    results.append({
                        "message_id": m.id,
                        "conversation_id": m.conversation_id,
                        "sender_name": m.sender_name,
                        "timestamp": m.timestamp.isoformat(),
                        "content": m.content,
                        "message_type": m.message_type,
                        "match_mode": "keyword"
                    })

    # 2. Semantic vector search
    if mode in ("semantic", "hybrid") and len(results) < limit:
        semantic_matches = LocalEmbeddingEngine.search_semantic(q, db, limit=limit, conversation_id=conversation_id)
        for sm in semantic_matches:
            if sm["message_id"] not in seen_ids:
                seen_ids.add(sm["message_id"])
                sm["match_mode"] = "semantic"
                results.append(sm)

    return {"query": q, "mode": mode, "total": len(results), "results": results[:limit]}

@router.get("/today")
def get_today_dashboard(db: Session = Depends(get_db)):
    """Executive metrics for Today dashboard."""
    convs_count = db.query(Conversation).count()
    msgs_count = db.query(Message).count()
    voice_count = db.query(MediaAsset).filter(MediaAsset.file_type == "audio").count()
    images_count = db.query(MediaAsset).filter(MediaAsset.file_type == "image").count()
    docs_count = db.query(MediaAsset).filter(MediaAsset.file_type == "document").count()

    inbox_tasks = db.query(Task).filter(Task.status == "inbox").count()
    open_tasks = db.query(Task).filter(Task.status == "open").count()
    waiting_count = db.query(WaitingFor).filter(WaitingFor.status == "open").count()
    decisions_count = db.query(Decision).count()
    ideas_count = db.query(Idea).count()
    properties_count = db.query(Property).count()

    recent_tasks = db.query(Task).order_by(Task.created_at.desc()).limit(5).all()
    recent_waiting = db.query(WaitingFor).order_by(WaitingFor.created_at.desc()).limit(5).all()

    return {
        "metrics": {
            "conversations": convs_count,
            "messages": msgs_count,
            "voice_notes": voice_count,
            "images": images_count,
            "documents": docs_count,
            "inbox_tasks": inbox_tasks,
            "open_tasks": open_tasks,
            "waiting_items": waiting_count,
            "decisions": decisions_count,
            "ideas": ideas_count,
            "properties": properties_count
        },
        "recent_tasks": [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "priority": t.priority,
                "due_date": t.due_date.isoformat() if t.due_date else None
            }
            for t in recent_tasks
        ],
        "recent_waiting": [
            {
                "id": w.id,
                "person": w.person_name,
                "deliverable": w.deliverable,
                "status": w.status
            }
            for w in recent_waiting
        ]
    }

@router.get("/briefing")
def generate_briefing(
    briefing_type: str = Query("daily", description="daily, weekly, project"),
    db: Session = Depends(get_db)
):
    """Generate structured executive briefings."""
    tasks = db.query(Task).filter(Task.status.in_(["inbox", "open"])).all()
    waiting = db.query(WaitingFor).filter(WaitingFor.status == "open").all()
    decisions = db.query(Decision).order_by(Decision.created_at.desc()).limit(5).all()
    properties = db.query(Property).order_by(Property.created_at.desc()).limit(3).all()

    title = f"الموجز التنفيذي ({'اليومي' if briefing_type == 'daily' else 'الأسبوعي'})"
    
    lines = [
        f"# {title}",
        f"**تاريخ الإصدار:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 📌 المهام النشطة والمطلوبة",
    ]
    if tasks:
        for t in tasks:
            due = f" (الموعد: {t.due_date.strftime('%Y-%m-%d')})" if t.due_date else ""
            lines.append(f"- [ ] **{t.title}**{due} - *{t.status}*")
    else:
        lines.append("- لا توجد مهام معلقة حالياً.")

    lines.extend(["", "## ⏳ قيد الانتظار (Waiting For)"])
    if waiting:
        for w in waiting:
            lines.append(f"- بانتظار **{w.person_name}**: {w.deliverable}")
    else:
        lines.append("- لا توجد عناصر معلقة قيد الانتظار.")

    lines.extend(["", "## 🤝 أحدث القرارات والاتفاقات"])
    if decisions:
        for d in decisions:
            lines.append(f"- {d.decision_text} ({d.participants or 'غير محدد'})")
    else:
        lines.append("- لا توجد قرارات جديدة مسجلة.")

    if properties:
        lines.extend(["", "## 🏢 مستجدات العقارات (Stone Mode)"])
        for p in properties:
            lines.append(f"- **{p.title}**: {f'{p.price:,.0f} {p.currency}' if p.price else 'سعر غير محدد'}")

    return {
        "briefing_type": briefing_type,
        "title": title,
        "content_markdown": "\n".join(lines)
    }
