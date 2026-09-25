"""
Tests for OWI WhatsApp Web Companion Bulk Ingestion & Diagnostics.
Covers:
- Date parsing (DD/MM, MM/DD, Arabic numerals, Arabic AM/PM, ISO)
- Impossible dates rejection (e.g., 31/02/2026, 2026-02-30)
- Time-only string rejection (cannot silently use current day)
- Chunked ingestion and idempotency/deduplication
- Empty messages rejection (400)
- Completeness status and partial reason reporting
- Historical timestamp provenance: explicit 'verified' vs 'unverified_fallback'
- Partial status on unverified timestamps (never pretend capture clock is verified)
- Retry idempotency for unverified timestamps without platform IDs
- Test isolation: zero writes to default data/ directory
- Diagnostic privacy: strict allowlisting of stages, codes, and static details;
  plain sensitive phrases (e.g. 'H private message') must never appear in logs
"""

import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime
import pytest
from fastapi.testclient import TestClient

from owi.main import app
from owi.db.database import engine
from owi.api.routes_companion import (
    parse_companion_timestamp,
    sanitize_diagnostic_entry,
    ALLOWED_STATIC_DETAILS,
    ALLOWED_STAGES,
    ALLOWED_CODES
)
from owi.core.security import pairing_manager
from owi.db.models import Conversation, Message
from owi.config import settings, DEFAULT_DATA_DIR

client = TestClient(app)

def test_companion_date_parsing_egypt_default_and_ambiguity():
    # Ambiguous date: 05/06/2026
    # Egypt default (day_first=True): June 5, 2026
    dt_egypt = parse_companion_timestamp("10:45 AM, 05/06/2026", default_day_first=True)
    assert dt_egypt is not None
    assert dt_egypt.year == 2026
    assert dt_egypt.month == 6
    assert dt_egypt.day == 5
    assert dt_egypt.hour == 10
    assert dt_egypt.minute == 45

    # US format (day_first=False): May 6, 2026
    dt_us = parse_companion_timestamp("10:45 AM, 05/06/2026", default_day_first=False)
    assert dt_us is not None
    assert dt_us.month == 5
    assert dt_us.day == 6

    # Unambiguous day > 12: 23/09/2026 (always Day 23, Month 9)
    dt_unambig = parse_companion_timestamp("10:45 AM, 23/09/2026", default_day_first=False)
    assert dt_unambig is not None
    assert dt_unambig.day == 23
    assert dt_unambig.month == 9

    # Unambiguous month > 12 in second position: 09/23/2026
    dt_unambig2 = parse_companion_timestamp("10:45 AM, 09/23/2026", default_day_first=True)
    assert dt_unambig2 is not None
    assert dt_unambig2.day == 23
    assert dt_unambig2.month == 9

def test_companion_date_parsing_arabic_numerals_and_am_pm():
    # Arabic digits and Arabic AM (ص)
    arabic_ts = "١٠:١٥ ص، ٢٥/٠٩/٢٠٢٦"
    dt_ar = parse_companion_timestamp(arabic_ts, default_day_first=True)
    assert dt_ar is not None
    assert dt_ar.year == 2026
    assert dt_ar.month == 9
    assert dt_ar.day == 25
    assert dt_ar.hour == 10
    assert dt_ar.minute == 15

    # Arabic digits and Arabic PM (م) -> 10:15 PM = 22:15
    arabic_ts_pm = "١٠:١٥ م، ٢٥/٠٩/٢٠٢٦"
    dt_ar_pm = parse_companion_timestamp(arabic_ts_pm, default_day_first=True)
    assert dt_ar_pm is not None
    assert dt_ar_pm.hour == 22
    assert dt_ar_pm.minute == 15

    # Arabic text صباحاً / مساءً
    dt_txt = parse_companion_timestamp("03:30 مساءً، 15/08/2026", default_day_first=True)
    assert dt_txt is not None
    assert dt_txt.hour == 15
    assert dt_txt.minute == 30

def test_companion_date_parsing_iso_format():
    iso_ts = "2026-09-25T14:30:00"
    dt = parse_companion_timestamp(iso_ts)
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 9
    assert dt.day == 25
    assert dt.hour == 14
    assert dt.minute == 30

def test_companion_date_parsing_impossible_dates():
    # Calendar bounds validation: must return None rather than rolling over
    assert parse_companion_timestamp("10:00 AM, 31/02/2026") is None
    assert parse_companion_timestamp("2026-02-30T10:00:00") is None
    assert parse_companion_timestamp("10:00 AM, 31/04/2026") is None
    assert parse_companion_timestamp("10:00 AM, 29/02/2025") is None  # 2025 is not a leap year

    # 2024 is a leap year -> 29/02/2024 is valid
    leap_dt = parse_companion_timestamp("10:00 AM, 29/02/2024")
    assert leap_dt is not None
    assert leap_dt.day == 29
    assert leap_dt.month == 2
    assert leap_dt.year == 2024

def test_companion_date_parsing_time_only_rejected():
    # Time-only strings that lack a date component must be rejected (return None)
    # They must NEVER silently default to today's date
    assert parse_companion_timestamp("10:45 AM") is None
    assert parse_companion_timestamp("14:30:00") is None
    assert parse_companion_timestamp("١٠:١٥ ص") is None
    assert parse_companion_timestamp("03:30 مساءً") is None

def test_companion_chunked_ingest_and_idempotency(test_db):
    # Setup paired companion token
    code_obj = pairing_manager.create_pairing_code()
    token = pairing_manager.exchange_pairing_code(code_obj["code"], "Bulk Test Runner")
    assert token is not None

    chat_title = "Bulk Capture Unit Test Chat"
    messages_chunk_1 = [
        {
            "platform_msg_id": "test_msg_001",
            "sender": "Alice",
            "text": "First bulk message",
            "timestamp": "2026-09-25T10:00:00",
            "is_outgoing": False
        },
        {
            "platform_msg_id": "test_msg_002",
            "sender": "Bob",
            "text": "Second bulk message",
            "timestamp": "2026-09-25T10:01:00",
            "is_outgoing": True
        }
    ]

    # Ingest Chunk 1
    res1 = client.post(
        "/api/companion/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "chat_title": chat_title,
            "session_id": "sess_123",
            "chunk_index": 0,
            "total_chunks": 2,
            "is_last_chunk": False,
            "completeness_status": "in_progress",
            "messages": messages_chunk_1
        }
    )
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["status"] == "success"
    assert data1["messages_ingested"] == 2
    assert data1["duplicates_skipped"] == 0

    # Ingest Chunk 1 AGAIN (simulate network retry) -> Idempotency test
    res1_retry = client.post(
        "/api/companion/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "chat_title": chat_title,
            "session_id": "sess_123",
            "chunk_index": 0,
            "total_chunks": 2,
            "is_last_chunk": False,
            "completeness_status": "in_progress",
            "messages": messages_chunk_1
        }
    )
    assert res1_retry.status_code == 200
    data1_retry = res1_retry.json()
    assert data1_retry["messages_ingested"] == 0
    assert data1_retry["duplicates_skipped"] == 2

    # Ingest Chunk 2 (Final, with completeness status)
    messages_chunk_2 = [
        {
            "platform_msg_id": "test_msg_003",
            "sender": "Alice",
            "text": "Third bulk message",
            "timestamp": "2026-09-25T10:02:00",
            "is_outgoing": False
        }
    ]
    res2 = client.post(
        "/api/companion/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "chat_title": chat_title,
            "session_id": "sess_123",
            "chunk_index": 1,
            "total_chunks": 2,
            "is_last_chunk": True,
            "completeness_status": "complete",
            "messages": messages_chunk_2
        }
    )
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["messages_ingested"] == 1
    assert data2["completeness_status"] == "complete"
    assert data2["is_last_chunk"] is True

def test_companion_ingest_empty_messages_rejected(test_db):
    code_obj = pairing_manager.create_pairing_code()
    token = pairing_manager.exchange_pairing_code(code_obj["code"], "Empty Msg Runner")

    # Ingest with empty messages array must return 400 Bad Request
    res = client.post(
        "/api/companion/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "chat_title": "Empty Messages Chat",
            "session_id": "sess_empty",
            "chunk_index": 0,
            "total_chunks": 1,
            "is_last_chunk": True,
            "completeness_status": "complete",
            "messages": []
        }
    )
    assert res.status_code == 400
    assert "No messages provided" in res.json()["detail"]

def test_companion_partial_completeness_reporting(test_db):
    code_obj = pairing_manager.create_pairing_code()
    token = pairing_manager.exchange_pairing_code(code_obj["code"], "Partial Test Runner")

    res = client.post(
        "/api/companion/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "chat_title": "Partial Capture Test Chat",
            "session_id": "sess_partial",
            "chunk_index": 0,
            "total_chunks": 1,
            "is_last_chunk": True,
            "completeness_status": "partial",
            "partial_reason": "history_exhausted_before_from_bound",
            "messages": [
                {
                    "platform_msg_id": "part_001",
                    "sender": "Charlie",
                    "text": "Only history available",
                    "timestamp": "2026-09-25T08:00:00"
                }
            ]
        }
    )
    assert res.status_code == 200
    data = res.json()
    assert data["completeness_status"] == "partial"
    assert data["partial_reason"] == "history_exhausted_before_from_bound"
    assert data["messages_ingested"] == 1

def test_companion_unverified_timestamp_provenance_and_partial_status(test_db):
    code_obj = pairing_manager.create_pairing_code()
    token = pairing_manager.exchange_pairing_code(code_obj["code"], "Unverified Runner")

    # Ingest a message with missing/invalid timestamp
    res = client.post(
        "/api/companion/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "chat_title": "Unverified Timestamp Chat",
            "session_id": "sess_unverified",
            "chunk_index": 0,
            "total_chunks": 1,
            "is_last_chunk": True,
            "completeness_status": "complete",  # Caller attempted complete, but has unverified time
            "messages": [
                {
                    "platform_msg_id": "unver_001",
                    "sender": "Dave",
                    "text": "Message with unparseable timestamp",
                    "timestamp": "unparseable_corrupt_time"
                }
            ]
        }
    )
    assert res.status_code == 200
    data = res.json()
    # Must report partial status due to unverified timestamp!
    assert data["completeness_status"] == "partial"
    assert data["partial_reason"] == "unverified_timestamps_present"
    assert data["unverified_timestamps"] == 1
    assert data["messages_ingested"] == 1

    # Verify database provenance field is explicitly set to 'unverified_fallback'
    msg = test_db.query(Message).filter(Message.raw_text == "unver_001").first()
    assert msg is not None
    assert msg.timestamp_provenance == "unverified_fallback"

def test_companion_verified_timestamp_provenance(test_db):
    code_obj = pairing_manager.create_pairing_code()
    token = pairing_manager.exchange_pairing_code(code_obj["code"], "Verified Runner")

    res = client.post(
        "/api/companion/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "chat_title": "Verified Timestamp Chat",
            "session_id": "sess_verified",
            "chunk_index": 0,
            "total_chunks": 1,
            "is_last_chunk": True,
            "completeness_status": "complete",
            "messages": [
                {
                    "platform_msg_id": "ver_001",
                    "sender": "Eve",
                    "text": "Message with valid time",
                    "timestamp": "2026-09-25T11:00:00"
                }
            ]
        }
    )
    assert res.status_code == 200
    data = res.json()
    assert data["completeness_status"] == "complete"
    assert data["unverified_timestamps"] == 0

    msg = test_db.query(Message).filter(Message.raw_text == "ver_001").first()
    assert msg is not None
    assert msg.timestamp_provenance == "verified"

def test_companion_unverified_timestamp_idempotent_retry(test_db):
    code_obj = pairing_manager.create_pairing_code()
    token = pairing_manager.exchange_pairing_code(code_obj["code"], "Idemp Unver Runner")

    # Message lacking platform_msg_id AND lacking valid timestamp
    messages = [
        {
            "sender": "Frank",
            "text": "Message without platform ID and invalid time",
            "timestamp": "invalid_time_str"
        }
    ]

    res1 = client.post(
        "/api/companion/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "chat_title": "Idemp Unverified Chat",
            "session_id": "sess_idemp_unver",
            "messages": messages
        }
    )
    assert res1.status_code == 200
    assert res1.json()["messages_ingested"] == 1
    assert res1.json()["duplicates_skipped"] == 0

    # Retry the exact same payload: must be strictly deduplicated
    res2 = client.post(
        "/api/companion/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "chat_title": "Idemp Unverified Chat",
            "session_id": "sess_idemp_unver",
            "messages": messages
        }
    )
    assert res2.status_code == 200
    assert res2.json()["messages_ingested"] == 0
    assert res2.json()["duplicates_skipped"] == 1

def test_test_isolation_guarantee(test_db):
    """
    Verify test_db fixture guarantees strict isolation:
    settings.DATA_DIR and engine URL must never target DEFAULT_DATA_DIR,
    regardless of whether DEFAULT_DATA_DIR/owi.db exists.
    """
    assert settings.DATA_DIR.resolve() != DEFAULT_DATA_DIR.resolve()
    engine_db_path = Path(engine.url.database).resolve() if engine.url.database else None
    assert engine_db_path is not None
    assert engine_db_path != (DEFAULT_DATA_DIR / "owi.db").resolve(), "engine must never point to default data/owi.db!"
    assert str(DEFAULT_DATA_DIR.resolve()) not in str(engine.url), "engine URL must never target DEFAULT_DATA_DIR!"
    assert settings.DATABASE_PATH.resolve() != (DEFAULT_DATA_DIR / "owi.db").resolve()

def test_fresh_no_env_pytest_invocation_isolation(tmp_path):
    """
    Regression test:
    Running pytest in a clean subprocess with OWI_DATA_DIR explicitly unset
    and PYTHON_DOTENV_DISABLED=1 must guarantee engine and DATA_DIR never target DEFAULT_DATA_DIR.
    Uses a read-only metadata check on DEFAULT_DATA_DIR/owi.db (without opening or reading content)
    so the test passes when DEFAULT_DATA_DIR/owi.db legitimately exists and confirms it remains untouched.
    """
    clean_env = os.environ.copy()
    clean_env.pop("OWI_DATA_DIR", None)
    clean_env["PYTHON_DOTENV_DISABLED"] = "1"
    clean_env["GEMINI_API_KEY"] = ""

    basetemp = str(tmp_path / "basetemp")
    repo_root = str(DEFAULT_DATA_DIR.parent)
    default_db_file = DEFAULT_DATA_DIR / "owi.db"

    # Read-only filesystem metadata check: capture mtime and size if pre-existing,
    # strictly without opening or reading file content
    stat_before = None
    if default_db_file.exists():
        stat_before = default_db_file.stat()

    res = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "tests/test_companion_bulk.py",
            "-k", "test_test_isolation_guarantee",
            f"--basetemp={basetemp}",
            "-q"
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        env=clean_env
    )
    assert res.returncode == 0, f"No-env pytest failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"

    if stat_before is not None:
        # Pre-existing database must remain completely unchanged
        stat_after = default_db_file.stat()
        assert stat_after.st_mtime_ns == stat_before.st_mtime_ns, "Pre-existing database mtime was modified!"
        assert stat_after.st_size == stat_before.st_size, "Pre-existing database size was modified!"
    else:
        # If no database existed prior to test, none should have been created in default data/
        assert not default_db_file.exists(), "Running pytest with no env must not create default data/owi.db!"

def test_no_env_sentinel_database_isolation_and_immutability(tmp_path):
    """
    Deterministic Sentinel Fixture:
    Proves that a fresh no-env invocation selects an isolated settings.DATA_DIR and engine URL
    before any imports, and that an existing database remains 100% byte-for-byte unchanged.
    Operates strictly within a disposable cloned-layout fixture in tmp_path with zero access
    to real production data.
    """
    import sqlite3
    import hashlib

    # 1. Create a disposable cloned workspace layout with a pre-existing sentinel database
    sentinel_workspace = tmp_path / "sentinel_workspace"
    sentinel_data = sentinel_workspace / "data"
    sentinel_data.mkdir(parents=True)
    sentinel_db = sentinel_data / "owi.db"

    # Populate sentinel DB with deterministic synthetic schema and records
    with sqlite3.connect(str(sentinel_db)) as conn:
        conn.execute("CREATE TABLE sentinel_preexisting (id INTEGER PRIMARY KEY, canary TEXT);")
        conn.execute("INSERT INTO sentinel_preexisting (canary) VALUES ('CANARY_PREEXISTING_RECORD_XYZ');")
        conn.commit()

    sentinel_bytes_before = sentinel_db.read_bytes()
    sentinel_hash_before = hashlib.sha256(sentinel_bytes_before).hexdigest()
    sentinel_mtime_before = sentinel_db.stat().st_mtime_ns

    # 2. Run fresh subprocess where OWI_DATA_DIR is explicitly unset, but OWI_DEFAULT_DATA_DIR points to sentinel_data
    clean_env = os.environ.copy()
    clean_env.pop("OWI_DATA_DIR", None)
    clean_env["PYTHON_DOTENV_DISABLED"] = "1"
    clean_env["OWI_DEFAULT_DATA_DIR"] = str(sentinel_data)
    clean_env["GEMINI_API_KEY"] = ""

    repo_root = str(DEFAULT_DATA_DIR.parent)

    backend_path_str = str(Path(repo_root) / "backend")
    verify_code = (
        f"import os, sys\n"
        f"from pathlib import Path\n"
        f"b_dir = r'{backend_path_str}'\n"
        f"if b_dir not in sys.path: sys.path.insert(0, b_dir)\n"
        f"# Import conftest first, exactly as pytest does\n"
        f"import tests.conftest\n"
        f"from owi.config import settings, DEFAULT_DATA_DIR\n"
        f"from owi.db.database import engine\n"
        f"from owi.db.migrations import init_db\n"
        f"\n"
        f"# Verify pre-import isolation\n"
        f"assert settings.DATA_DIR.resolve() != DEFAULT_DATA_DIR.resolve(), 'settings.DATA_DIR must be isolated'\n"
        f"assert str(DEFAULT_DATA_DIR.resolve()) not in str(engine.url), 'engine URL must not target DEFAULT_DATA_DIR'\n"
        f"\n"
        f"# Simulate full initialization in no-env test session\n"
        f"settings.init_directories()\n"
        f"init_db()\n"
        f"\n"
        f"# Verify tables went to isolated directory\n"
        f"isolated_db = settings.DATA_DIR / 'owi.db'\n"
        f"assert isolated_db.exists(), 'Isolated db must be created in disposable location'\n"
    )

    res = subprocess.run(
        [sys.executable, "-c", verify_code],
        cwd=repo_root,
        capture_output=True,
        text=True,
        env=clean_env
    )
    assert res.returncode == 0, f"Sentinel isolation verification failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"

    # 3. Assert pre-existing sentinel DB was completely untouched (exact byte hash, mtime, and content)
    sentinel_bytes_after = sentinel_db.read_bytes()
    sentinel_hash_after = hashlib.sha256(sentinel_bytes_after).hexdigest()
    assert sentinel_hash_after == sentinel_hash_before, "Pre-existing sentinel database was modified!"
    assert sentinel_db.stat().st_mtime_ns == sentinel_mtime_before, "Sentinel DB mtime changed!"

    with sqlite3.connect(str(sentinel_db)) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
        assert tables == ["sentinel_preexisting"], f"Sentinel DB must only contain sentinel table, found: {tables}"
        row = conn.execute("SELECT canary FROM sentinel_preexisting WHERE id=1;").fetchone()
        assert row[0] == "CANARY_PREEXISTING_RECORD_XYZ"


def test_diagnostic_sanitization_and_redaction():
    # 1. Plain sensitive phrase must be rejected and set to None
    sensitive_entry = {
        "timestamp": "2026-09-25T10:00:00Z",
        "stage": "scroll_up",
        "code": "STEP",
        "count": 5,
        "details": "H private message"
    }
    clean = sanitize_diagnostic_entry(sensitive_entry)
    assert clean["stage"] == "scroll_up"
    assert clean["code"] == "STEP"
    assert clean["count"] == 5
    assert clean["details"] is None
    assert "H private message" not in str(clean)

    # 2. Arbitrary text, tokens, urls in details must be rejected
    arbitrary_entry = {
        "stage": "ingest_chunk",
        "code": "CHUNK_INGESTED",
        "count": 10,
        "details": "token=owi_pair_secret123 chat_title=SecretChat"
    }
    clean_arb = sanitize_diagnostic_entry(arbitrary_entry)
    assert clean_arb["details"] is None

    # 3. Allowlisted static reason codes are preserved
    for static_reason in [
        "history_exhausted_before_from_bound",
        "scroll_attempts_exhausted",
        "traversal_stalled",
        "first_visible_anchor_not_found",
        "zero_messages_captured",
        "unparseable_timestamp_present",
        "unverified_timestamps_present",
        "payload_too_large"
    ]:
        entry = {
            "stage": "scroll_up",
            "code": "PARTIAL",
            "count": 1,
            "details": static_reason
        }
        sanitized = sanitize_diagnostic_entry(entry)
        assert sanitized["details"] == static_reason

    # 4. Unknown stage and code fall back to general/INFO
    bad_entry = {
        "stage": "malicious_stage_injection",
        "code": "DROP TABLE",
        "count": -10,
        "details": "some free text"
    }
    cleaned_bad = sanitize_diagnostic_entry(bad_entry)
    assert cleaned_bad["stage"] == "general"
    assert cleaned_bad["code"] == "INFO"
    assert cleaned_bad["count"] == 0
    assert cleaned_bad["details"] is None

def test_companion_diagnostic_endpoints(test_db):
    code_obj = pairing_manager.create_pairing_code()
    token = pairing_manager.exchange_pairing_code(code_obj["code"], "Diag Test Runner")

    # Post diagnostic batch with plain sensitive phrase and static reason
    res_post = client.post(
        "/api/companion/diagnostics",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "entries": [
                {
                    "stage": "scroll_up",
                    "code": "STEP",
                    "count": 15,
                    "details": "H private message in secret chat"
                },
                {
                    "stage": "scroll_up",
                    "code": "PARTIAL",
                    "count": 1,
                    "details": "history_exhausted_before_from_bound"
                }
            ]
        }
    )
    assert res_post.status_code == 200
    assert res_post.json()["status"] == "recorded"

    # Fetch diagnostic logs
    boot = client.get("/api/auth/bootstrap").json()["bootstrap_token"]
    exchange = client.post("/api/auth/exchange", json={"bootstrap_token": boot})
    assert exchange.status_code == 200

    res_get = client.get("/api/companion/diagnostics?limit=50")
    assert res_get.status_code == 200
    diag_data = res_get.json()
    assert "entries" in diag_data
    assert len(diag_data["entries"]) >= 2

    # Verify that 'H private message' is NEVER present anywhere in entries
    raw_json_str = str(diag_data)
    assert "H private message" not in raw_json_str
    assert "secret chat" not in raw_json_str

    # Verify that the static reason is preserved
    found_static = any(
        e.get("details") == "history_exhausted_before_from_bound"
        for e in diag_data["entries"]
    )
    assert found_static is True
