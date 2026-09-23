"""
In-process local background job queue with durable lease management and crash recovery.
Executes long-running tasks (transcription, OCR, document indexing, video analysis)
without freezing FastAPI or requiring Redis/Celery.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, Any, Optional
from datetime import datetime, timedelta
from owi.db.database import SessionLocal
from owi.db.models import Job
from owi.core.logging import logger

class JobQueue:
    def __init__(self, max_workers: int = 2):
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="owi-worker")
        self.handlers: Dict[str, Callable[[int, Dict[str, Any]], Any]] = {}
        self.is_running = True
        self._cancelled_jobs = set()

    def register_handler(self, job_type: str, handler: Callable[[int, Dict[str, Any]], Any]):
        """Register a handler callback for a specific job_type."""
        self.handlers[job_type] = handler
        logger.info(f"Registered job handler for '{job_type}'")

    def enqueue(self, job_type: str, payload: Optional[Dict[str, Any]] = None) -> int:
        """Enqueue a new job and schedule it for execution."""
        db = SessionLocal()
        try:
            job = Job(
                job_type=job_type,
                status="queued",
                progress=0,
                attempts=0,
                payload=payload or {},
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.add(job)
            db.commit()
            db.refresh(job)
            job_id = job.id
        finally:
            db.close()

        # Submit to thread pool
        self.executor.submit(self._run_job, job_id, job_type, payload or {})
        return job_id

    def _run_job(self, job_id: int, job_type: str, payload: Dict[str, Any]):
        """Worker thread execution wrapper with lease heartbeat and cancellation support."""
        if job_id in self._cancelled_jobs:
            self.update_status(job_id, status="cancelled", error_message="Job was cancelled before execution started.")
            return

        logger.info(f"Starting execution of job #{job_id} ({job_type})")
        handler = self.handlers.get(job_type)
        
        # Claim lease atomically: 15-minute lease duration
        lease_expiry = datetime.utcnow() + timedelta(minutes=15)
        db = SessionLocal()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                if job.status == "cancelled":
                    return
                job.status = "processing"
                job.progress = 10
                job.attempts = (job.attempts or 0) + 1
                job.lease_expires_at = lease_expiry
                job.updated_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()
        
        if not handler:
            self.update_status(job_id, status="failed", error_message=f"No registered handler for job type '{job_type}'")
            return

        try:
            result = handler(job_id, payload)
            if job_id in self._cancelled_jobs:
                self.update_status(job_id, status="cancelled", error_message="Job was cancelled during execution.")
                return
            self.update_status(job_id, status="completed", progress=100, result=result if isinstance(result, dict) else {"result": str(result)})
            logger.info(f"Job #{job_id} ({job_type}) completed successfully.")
        except Exception as e:
            logger.error(f"Job #{job_id} ({job_type}) failed: {str(e)}", exc_info=True)
            self.update_status(job_id, status="failed", error_message=str(e))

    def update_status(
        self, 
        job_id: int, 
        status: str, 
        progress: Optional[int] = None, 
        error_message: Optional[str] = None, 
        result: Optional[Dict[str, Any]] = None
    ):
        """Update job status, lease, and progress in the database."""
        db = SessionLocal()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job.status = status
                if progress is not None:
                    job.progress = progress
                if error_message is not None:
                    job.error_message = error_message
                if result is not None:
                    job.result = result
                # Extend lease if still processing
                if status == "processing":
                    job.lease_expires_at = datetime.utcnow() + timedelta(minutes=15)
                elif status in ("completed", "failed", "cancelled"):
                    job.lease_expires_at = None
                job.updated_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()

    def cancel(self, job_id: int) -> bool:
        """Cancel a queued or processing job."""
        self._cancelled_jobs.add(job_id)
        db = SessionLocal()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if not job or job.status in ("completed", "failed", "cancelled"):
                return False
            job.status = "cancelled"
            job.error_message = "Cancelled by user request."
            job.lease_expires_at = None
            job.updated_at = datetime.utcnow()
            db.commit()
            return True
        finally:
            db.close()

    def retry(self, job_id: int) -> bool:
        """Retry a failed or cancelled job."""
        if job_id in self._cancelled_jobs:
            self._cancelled_jobs.remove(job_id)
        db = SessionLocal()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if not job or job.status not in ("failed", "queued", "cancelled"):
                return False
            job.status = "queued"
            job.progress = 0
            job.error_message = None
            job.lease_expires_at = None
            job.updated_at = datetime.utcnow()
            db.commit()
            self.executor.submit(self._run_job, job.id, job.job_type, job.payload or {})
            return True
        finally:
            db.close()

    def reclaim_orphaned_jobs(self) -> int:
        """
        Recover orphaned jobs after application or worker crash.
        Invoked during application startup.
        Any job remaining in 'processing' state from a terminated process is safely resolved.
        """
        db = SessionLocal()
        reclaimed_count = 0
        try:
            orphans = db.query(Job).filter(Job.status == "processing").all()
            for job in orphans:
                job.status = "failed"
                job.error_message = "Worker process interrupted unexpectedly (recovered on process restart)."
                job.lease_expires_at = None
                job.updated_at = datetime.utcnow()
                reclaimed_count += 1
            if reclaimed_count > 0:
                db.commit()
                logger.warning(f"Reclaimed {reclaimed_count} orphaned background jobs from prior process run.")
        finally:
            db.close()
        return reclaimed_count

# Global job queue singleton
job_queue = JobQueue(max_workers=2)

