"""
Tasks, Waiting-For, Decisions, Commitments, Ideas, and Domain Template entities routes.
"""

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel
from sqlalchemy.orm import Session

from owi.db.database import get_db
from owi.db.models import Task, WaitingFor, Decision, Commitment, Idea, Property, ResearchItem

router = APIRouter(tags=["Knowledge Entities"])

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None  # inbox, open, waiting, completed, dismissed
    priority: Optional[str] = None
    due_date: Optional[str] = None
    assigned_contact_name: Optional[str] = None

class WaitingUpdate(BaseModel):
    status: Optional[str] = None  # open, resolved, overdue, dismissed
    deliverable: Optional[str] = None
    due_date: Optional[str] = None

@router.get("/api/tasks")
def list_tasks(
    status: Optional[str] = Query(None, description="Filter: inbox, open, waiting, completed, dismissed"),
    conversation_id: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    """List tasks with optional status and conversation filter."""
    q = db.query(Task)
    if status:
        q = q.filter(Task.status == status)
    if conversation_id:
        q = q.filter(Task.conversation_id == conversation_id)
        
    tasks = q.order_by(Task.created_at.desc()).all()
    res = []
    for t in tasks:
        res.append({
            "id": t.id,
            "conversation_id": t.conversation_id,
            "message_id": t.message_id,
            "title": t.title,
            "description": t.description,
            "status": t.status,
            "priority": t.priority,
            "confidence": t.confidence,
            "created_date": t.created_date.isoformat() if t.created_date else None,
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "assigned_contact_name": t.assigned_contact_name,
            "source_excerpt": t.source_excerpt
        })
    return res

@router.patch("/api/tasks/{task_id}")
def update_task(task_id: int, update: TaskUpdate, db: Session = Depends(get_db)):
    """Update task fields or change status (Accept, Dismiss, Complete)."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if update.title is not None:
        task.title = update.title
    if update.description is not None:
        task.description = update.description
    if update.status is not None:
        task.status = update.status
    if update.priority is not None:
        task.priority = update.priority
    if update.assigned_contact_name is not None:
        task.assigned_contact_name = update.assigned_contact_name

    db.commit()
    db.refresh(task)
    return {"status": "updated", "task_id": task.id, "new_status": task.status}

@router.get("/api/waiting")
def list_waiting_for(
    status: Optional[str] = Query(None, description="Filter: open, resolved, overdue, dismissed"),
    conversation_id: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    """List Waiting-For pending deliverables."""
    q = db.query(WaitingFor)
    if status:
        q = q.filter(WaitingFor.status == status)
    if conversation_id:
        q = q.filter(WaitingFor.conversation_id == conversation_id)
        
    items = q.order_by(WaitingFor.created_at.desc()).all()
    res = []
    for it in items:
        res.append({
            "id": it.id,
            "conversation_id": it.conversation_id,
            "message_id": it.message_id,
            "person_name": it.person_name,
            "deliverable": it.deliverable,
            "status": it.status,
            "due_date": it.due_date.isoformat() if it.due_date else None,
            "source_excerpt": it.source_excerpt
        })
    return res

@router.patch("/api/waiting/{waiting_id}")
def update_waiting_for(waiting_id: int, update: WaitingUpdate, db: Session = Depends(get_db)):
    """Update Waiting-For item status (Resolve, Dismiss)."""
    item = db.query(WaitingFor).filter(WaitingFor.id == waiting_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Waiting-For item not found")

    if update.status is not None:
        item.status = update.status
    if update.deliverable is not None:
        item.deliverable = update.deliverable

    db.commit()
    return {"status": "updated", "waiting_id": item.id, "new_status": item.status}

@router.get("/api/decisions")
def list_decisions(conversation_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    """List recorded decisions."""
    q = db.query(Decision)
    if conversation_id:
        q = q.filter(Decision.conversation_id == conversation_id)
    decisions = q.order_by(Decision.created_at.desc()).all()
    return [
        {
            "id": d.id,
            "conversation_id": d.conversation_id,
            "message_id": d.message_id,
            "decision_text": d.decision_text,
            "confidence": d.confidence,
            "participants": d.participants,
            "timestamp": d.timestamp.isoformat() if d.timestamp else None,
            "source_excerpt": d.source_excerpt
        }
        for d in decisions
    ]

@router.get("/api/commitments")
def list_commitments(conversation_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    """List participant commitments."""
    q = db.query(Commitment)
    if conversation_id:
        q = q.filter(Commitment.conversation_id == conversation_id)
    commitments = q.order_by(Commitment.created_at.desc()).all()
    return [
        {
            "id": c.id,
            "conversation_id": c.conversation_id,
            "message_id": c.message_id,
            "person_name": c.person_name,
            "commitment_text": c.commitment_text,
            "expected_date": c.expected_date.isoformat() if c.expected_date else None,
            "source_excerpt": c.source_excerpt
        }
        for c in commitments
    ]

@router.get("/api/ideas")
def list_ideas(conversation_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    """List extracted ideas and brainstorms."""
    q = db.query(Idea)
    if conversation_id:
        q = q.filter(Idea.conversation_id == conversation_id)
    ideas = q.order_by(Idea.created_at.desc()).all()
    return [
        {
            "id": i.id,
            "conversation_id": i.conversation_id,
            "message_id": i.message_id,
            "title": i.title,
            "description": i.description,
            "source_excerpt": i.source_excerpt
        }
        for i in ideas
    ]

@router.get("/api/properties")
def list_properties(conversation_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    """List Real Estate records extracted in Stone Mode."""
    q = db.query(Property)
    if conversation_id:
        q = q.filter(Property.conversation_id == conversation_id)
    props = q.order_by(Property.created_at.desc()).all()
    return [
        {
            "id": p.id,
            "conversation_id": p.conversation_id,
            "title": p.title,
            "property_type": p.property_type,
            "area_sqm": p.area_sqm,
            "location": p.location,
            "district": p.district,
            "price": p.price,
            "currency": p.currency,
            "deal_type": p.deal_type,
            "finishing": p.finishing,
            "has_admin_license": p.has_admin_license,
            "rooms": p.rooms,
            "bathrooms": p.bathrooms,
            "listing_draft": p.listing_draft,
            "source_evidence": p.source_evidence
        }
        for p in props
    ]

@router.get("/api/research")
def list_research(conversation_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    """List items extracted in Research Mode."""
    q = db.query(ResearchItem)
    if conversation_id:
        q = q.filter(ResearchItem.conversation_id == conversation_id)
    items = q.order_by(ResearchItem.created_at.desc()).all()
    return [
        {
            "id": r.id,
            "conversation_id": r.conversation_id,
            "topic": r.topic,
            "question": r.question,
            "author": r.author,
            "finding": r.finding,
            "citation": r.citation
        }
        for r in items
    ]

# --- CSV Export with Formula Injection Sanitization ---

@router.get("/api/tasks/export/csv")
def export_tasks_csv(db: Session = Depends(get_db)):
    """
    Export tasks to CSV with spreadsheet formula injection protection
    and UTF-8 BOM for Windows Excel Arabic/English compatibility.
    """
    import io
    import csv
    from fastapi.responses import Response
    from owi.core.security import sanitize_csv_cell

    tasks = db.query(Task).order_by(Task.created_at.desc()).all()
    output = io.StringIO()
    # Write UTF-8 BOM for Excel
    output.write("\ufeff")
    
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
    writer.writerow([
        "ID", "Title", "Status", "Due Date", "Assignee", 
        "Requester", "Confidence", "Source Excerpt", "Created At"
    ])
    
    for t in tasks:
        writer.writerow([
            t.id,
            sanitize_csv_cell(t.title),
            sanitize_csv_cell(t.status),
            sanitize_csv_cell(t.due_date.isoformat() if t.due_date else ""),
            sanitize_csv_cell(t.assigned_contact_name or ""),
            sanitize_csv_cell(t.related_project_name or ""),
            t.confidence,
            sanitize_csv_cell(t.source_excerpt or ""),
            t.created_at.isoformat() if t.created_at else ""
        ])
    
    return Response(
        content=output.getvalue().encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="owi_tasks_export.csv"'}
    )

@router.get("/api/properties/export/csv")
def export_properties_csv(db: Session = Depends(get_db)):
    """
    Export real estate listings to CSV with spreadsheet formula injection protection
    and UTF-8 BOM for Windows Excel compatibility.
    """
    import io
    import csv
    from fastapi.responses import Response
    from owi.core.security import sanitize_csv_cell

    props = db.query(Property).order_by(Property.created_at.desc()).all()
    output = io.StringIO()
    output.write("\ufeff")
    
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
    writer.writerow([
        "ID", "Title", "Property Type", "Area (sqm)", "District", 
        "Price", "Currency", "Deal Type", "Finishing", "Admin License", "Source Evidence"
    ])
    
    for p in props:
        writer.writerow([
            p.id,
            sanitize_csv_cell(p.title),
            sanitize_csv_cell(p.property_type),
            p.area_sqm or "",
            sanitize_csv_cell(p.district or ""),
            p.price or "",
            sanitize_csv_cell(p.currency or ""),
            sanitize_csv_cell(p.deal_type or ""),
            sanitize_csv_cell(p.finishing or ""),
            "Yes" if p.has_admin_license else "No",
            sanitize_csv_cell(p.source_evidence or "")
        ])
        
    return Response(
        content=output.getvalue().encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="owi_properties_export.csv"'}
    )

