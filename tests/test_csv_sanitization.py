"""
Tests for Spreadsheet Formula Injection (CSV Injection / CWE-1236) prevention.
Verifies that text beginning with '=', '+', '-', '@', tab, or carriage return
is escaped with a single quote (') so spreadsheet applications execute no formulas.
"""

import pytest
from fastapi.testclient import TestClient
from owi.main import app
from owi.core.security import sanitize_csv_cell
from owi.db.database import SessionLocal
from owi.db.models import Task, Conversation
from datetime import datetime

client = TestClient(app)

def test_sanitize_csv_cell():
    # Dangerous formula triggers
    assert sanitize_csv_cell("=SUM(A1:A10)") == "'=SUM(A1:A10)"
    assert sanitize_csv_cell("=cmd|'/C calc'!A0") == "'=cmd|'/C calc'!A0"
    assert sanitize_csv_cell("+123456") == "'+123456"
    assert sanitize_csv_cell("-100 USD") == "'-100 USD"
    assert sanitize_csv_cell("@username") == "'@username"
    assert sanitize_csv_cell("   =DANGEROUS()") == "'   =DANGEROUS()"
    assert sanitize_csv_cell("\t=TAB_FORMULA") == "'\t=TAB_FORMULA"
    
    # Safe text
    assert sanitize_csv_cell("Normal text") == "Normal text"
    assert sanitize_csv_cell("إرسال العقد غداً") == "إرسال العقد غداً"
    assert sanitize_csv_cell("") == ""
    assert sanitize_csv_cell(None) == ""
    assert sanitize_csv_cell(123) == "123"

def test_csv_export_endpoint():
    db = SessionLocal()
    try:
        conv = Conversation(title="Security Test Conv")
        db.add(conv)
        db.commit()
        db.refresh(conv)

        # Add task with potentially malicious title
        malicious_task = Task(
            conversation_id=conv.id,
            title="=2+5",
            status="Inbox",
            confidence=0.9,
            source_excerpt="@Omar send payment -500",
            created_at=datetime.utcnow()
        )
        db.add(malicious_task)
        db.commit()
    finally:
        db.close()

    res = client.get("/api/tasks/export/csv")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    content = res.content.decode("utf-8")
    
    # UTF-8 BOM must be present for Excel
    assert content.startswith("\ufeff")
    # Formula must be sanitized
    assert "'=2+5" in content
    assert "'@Omar send payment -500" in content
