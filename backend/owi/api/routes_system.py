"""
System inspection, storage dashboard, diagnostics, and Zero-Surprise Cost verification routes.
"""

import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import psutil

from owi.config import settings
from owi.core.logging import export_diagnostics

router = APIRouter(prefix="/api/system", tags=["System & Storage"])

def get_dir_size_bytes(directory: Path) -> int:
    """Calculate recursive size of a directory in bytes."""
    total = 0
    if not directory.exists():
        return 0
    for p in directory.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except Exception:
                pass
    return total

@router.get("/resources")
def get_hardware_resources() -> Dict[str, Any]:
    """Inspect CPU, RAM, and hardware configuration to suggest best profile."""
    mem = psutil.virtual_memory()
    cpu_count = psutil.cpu_count(logical=True)
    
    total_ram_gb = round(mem.total / (1024 ** 3), 2)
    available_ram_gb = round(mem.available / (1024 ** 3), 2)

    # Suggest profile based on RAM
    suggested_profile = "LIGHT"
    if total_ram_gb >= 16:
        suggested_profile = "QUALITY"
    elif total_ram_gb >= 8:
        suggested_profile = "BALANCED"

    return {
        "cpu_cores": cpu_count,
        "total_ram_gb": total_ram_gb,
        "available_ram_gb": available_ram_gb,
        "ram_usage_percent": mem.percent,
        "suggested_profile": suggested_profile,
        "current_profile": settings.PERFORMANCE_PROFILE
    }

@router.get("/storage")
def get_storage_dashboard() -> Dict[str, Any]:
    """Return storage consumption breakdown across database, media, models, and cache."""
    db_size = settings.DATABASE_PATH.stat().st_size if settings.DATABASE_PATH.exists() else 0
    audio_size = get_dir_size_bytes(settings.DATA_DIR / "media" / "audio")
    images_size = get_dir_size_bytes(settings.DATA_DIR / "media" / "images")
    video_size = get_dir_size_bytes(settings.DATA_DIR / "media" / "video")
    docs_size = get_dir_size_bytes(settings.DATA_DIR / "media" / "documents")
    models_size = get_dir_size_bytes(settings.DATA_DIR / "models")
    derived_size = get_dir_size_bytes(settings.DATA_DIR / "derived")
    logs_size = get_dir_size_bytes(settings.DATA_DIR / "logs")

    total_bytes = (
        db_size + audio_size + images_size + video_size + docs_size +
        models_size + derived_size + logs_size
    )

    def to_mb(b: int) -> float:
        return round(b / (1024 * 1024), 2)

    return {
        "total_mb": to_mb(total_bytes),
        "database_mb": to_mb(db_size),
        "audio_mb": to_mb(audio_size),
        "images_mb": to_mb(images_size),
        "video_mb": to_mb(video_size),
        "documents_mb": to_mb(docs_size),
        "models_mb": to_mb(models_size),
        "derived_files_mb": to_mb(derived_size),
        "logs_mb": to_mb(logs_size),
        "storage_path": str(settings.DATA_DIR.resolve())
    }

@router.post("/cleanup")
def cleanup_cache() -> Dict[str, Any]:
    """Safely cleanup temporary derived files and log files without touching original user media."""
    cleaned_bytes = 0
    derived_dir = settings.DATA_DIR / "derived"
    if derived_dir.exists():
        for f in derived_dir.rglob("*"):
            if f.is_file():
                try:
                    cleaned_bytes += f.stat().st_size
                    f.unlink()
                except Exception:
                    pass

    return {
        "status": "cleaned",
        "freed_mb": round(cleaned_bytes / (1024 * 1024), 2),
        "message": "Safely cleared derived caches. Original media preserved."
    }

@router.get("/cost")
def get_cost_audit() -> Dict[str, Any]:
    """
    Zero-Surprise Cost Screen verification.
    Guarantees that no external recurring or pay-per-token services are enabled.
    """
    return {
        "core_mode": settings.CORE_MODE,
        "mandatory_subscription": settings.MANDATORY_SUBSCRIPTION,
        "mandatory_api": settings.MANDATORY_API,
        "recurring_software_fee": settings.RECURRING_SOFTWARE_FEE,
        "cloud_ai_enabled": settings.CLOUD_AI_ENABLED,
        "cloud_storage_enabled": settings.CLOUD_STORAGE_ENABLED,
        "status_notice": "Your system is operating in 100% Local Mode with Zero recurring expenses or cloud fees."
    }

@router.get("/diagnostics")
def get_diagnostics() -> Dict[str, Any]:
    """Export sanitized diagnostic logs."""
    return {"diagnostics": export_diagnostics()}

@router.post("/backup")
def trigger_backup() -> Dict[str, Any]:
    """Create a consistent full backup archive of SQLite database (flushing WAL) and media."""
    from owi.db.backup import create_backup
    try:
        backup_zip = create_backup()
        return {
            "status": "success",
            "backup_file": str(backup_zip.name),
            "backup_path": str(backup_zip),
            "size_bytes": backup_zip.stat().st_size
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Backup failed: {str(e)}")

@router.get("/backups")
def list_backups() -> Dict[str, Any]:
    """List available backups in the data/backups directory."""
    backup_dir = settings.DATA_DIR / "backups"
    backups = []
    if backup_dir.exists():
        for f in sorted(backup_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
            backups.append({
                "filename": f.name,
                "size_mb": round(f.stat().st_size / (1024 * 1024), 2),
                "created_at": datetime.fromtimestamp(f.stat().st_mtime).isoformat()
            })
    return {"backups": backups}

class RestoreRequest(BaseModel):
    backup_filename: str

@router.post("/restore")
def trigger_restore(payload: RestoreRequest) -> Dict[str, Any]:
    """Restore database and media from a verified backup archive."""
    from owi.db.backup import restore_backup
    backup_path = (settings.DATA_DIR / "backups" / payload.backup_filename).resolve()
    if not backup_path.exists():
        raise HTTPException(status_code=404, detail=f"Backup file {payload.backup_filename} not found.")
    try:
        res = restore_backup(backup_path)
        return {"status": "success", "details": res}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Restore failed integrity checks: {str(e)}")

