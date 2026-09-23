"""
Tests for durable background job queue:
- Worker crash recovery on system restart (reclaiming orphaned jobs in 'processing' state).
- Job cancellation support.
"""

import pytest
from datetime import datetime, timedelta
from owi.core.queue import JobQueue
from owi.db.database import SessionLocal
from owi.db.models import Job

def test_reclaim_orphaned_jobs():
    queue = JobQueue(max_workers=1)
    db = SessionLocal()
    try:
        # Simulate a job that was in 'processing' when the server unexpectedly crashed
        orphaned_job = Job(
            job_type="transcription",
            status="processing",
            progress=45,
            attempts=1,
            lease_expires_at=datetime.utcnow() - timedelta(minutes=5),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(orphaned_job)
        db.commit()
        db.refresh(orphaned_job)
        orphan_id = orphaned_job.id
    finally:
        db.close()

    # Reclaim jobs as happens during app startup
    reclaimed_count = queue.reclaim_orphaned_jobs()
    assert reclaimed_count >= 1

    db = SessionLocal()
    try:
        recovered = db.query(Job).filter(Job.id == orphan_id).first()
        assert recovered.status == "failed"
        assert "interrupted unexpectedly" in recovered.error_message
        assert recovered.lease_expires_at is None
    finally:
        db.close()

def test_job_cancellation():
    queue = JobQueue(max_workers=1)
    job_id = queue.enqueue("dummy_test", {"param": 123})
    
    # Cancel the job
    cancelled = queue.cancel(job_id)
    assert cancelled is True

    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        assert job.status == "cancelled"
        assert "Cancelled by user" in job.error_message
    finally:
        db.close()
