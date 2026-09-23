"""
Authoritative SQLite backup and atomic restoration pipeline for OWI.
- Uses native sqlite3.Connection.backup() to flush and snapshot WAL state atomically.
- Packages immutable sources and media assets with cryptographic SHA-256 integrity manifest.
- Validates staging integrity before replacing any active dataset.
"""

import os
import json
import sqlite3
import shutil
import tempfile
import zipfile
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

from owi.config import settings
from owi.core.hashing import compute_file_sha256
from owi.core.security import is_safe_path, safe_extract_zip
from owi.core.logging import logger

SCHEMA_VERSION = "1.0.0"

def create_backup(dest_zip_path: Optional[Path] = None) -> Path:
    """
    Create a consistent full backup archive.
    - Flushes WAL and snapshots SQLite via native backup API.
    - Collects immutable sources and media files.
    - Computes SHA-256 hashes and builds manifest.json.
    - Excludes regenerable caches, derived files, and downloaded model binaries.
    """
    if dest_zip_path is None:
        timestamp_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_dir = settings.DATA_DIR / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        dest_zip_path = backup_dir / f"owi_backup_{timestamp_str}.zip"

    dest_zip_path = dest_zip_path.resolve()
    dest_zip_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="owi_backup_staging_") as temp_stage_str:
        temp_stage = Path(temp_stage_str)
        db_snapshot_path = temp_stage / "owi.db"

        # 1. Native SQLite backup API (guarantees consistent snapshot flushing WAL)
        if settings.DATABASE_PATH.exists():
            src_conn = sqlite3.connect(str(settings.DATABASE_PATH.resolve()))
            dest_conn = sqlite3.connect(str(db_snapshot_path))
            try:
                with dest_conn:
                    src_conn.backup(dest_conn)
            finally:
                dest_conn.close()
                src_conn.close()
        else:
            # Empty database fallback
            conn = sqlite3.connect(str(db_snapshot_path))
            conn.close()

        db_sha256 = compute_file_sha256(db_snapshot_path)
        db_size = db_snapshot_path.stat().st_size

        # 2. Gather assets and compute checksums
        assets_manifest: List[Dict[str, Any]] = []
        assets_staging_dir = temp_stage / "assets"
        assets_staging_dir.mkdir(parents=True, exist_ok=True)

        include_folders = [
            settings.DATA_DIR / "sources",
            settings.DATA_DIR / "media" / "audio",
            settings.DATA_DIR / "media" / "images",
            settings.DATA_DIR / "media" / "video",
            settings.DATA_DIR / "media" / "documents",
        ]

        for folder in include_folders:
            if not folder.exists():
                continue
            for item in folder.rglob("*"):
                if item.is_file():
                    try:
                        rel_path = item.relative_to(settings.DATA_DIR)
                        sha = compute_file_sha256(item)
                        size = item.stat().st_size
                        
                        target_file = assets_staging_dir / rel_path
                        target_file.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, target_file)

                        assets_manifest.append({
                            "relative_path": str(rel_path).replace("\\", "/"),
                            "sha256": sha,
                            "size_bytes": size
                        })
                    except Exception as e:
                        logger.warning(f"Could not include asset {item} in backup: {e}")

        # 3. Create manifest.json
        manifest_data = {
            "application": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "schema_version": SCHEMA_VERSION,
            "created_at_utc": datetime.utcnow().isoformat(),
            "database": {
                "filename": "owi.db",
                "sha256": db_sha256,
                "size_bytes": db_size
            },
            "assets_count": len(assets_manifest),
            "assets": assets_manifest,
            "excluded_items": [
                "models/",
                "derived/",
                "logs/",
                "backups/"
            ]
        }

        manifest_path = temp_stage / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2, ensure_ascii=False)

        # 4. Create destination ZIP archive
        with zipfile.ZipFile(dest_zip_path, "w", zipfile.ZIP_DEFLATED) as zip_out:
            zip_out.write(manifest_path, arcname="manifest.json")
            zip_out.write(db_snapshot_path, arcname="owi.db")
            for root, _, files in os.walk(assets_staging_dir):
                for file in files:
                    file_path = Path(root) / file
                    arcname = "assets/" + str(file_path.relative_to(assets_staging_dir)).replace("\\", "/")
                    zip_out.write(file_path, arcname=arcname)

    logger.info(f"Created consistent backup archive at {dest_zip_path} with {len(assets_manifest)} assets.")
    return dest_zip_path

def restore_backup(
    backup_zip_path: Path, 
    target_data_dir: Optional[Path] = None
) -> Dict[str, Any]:
    """
    Restore an authoritative OWI backup into target_data_dir.
    - Validates archive against Zip Slip attacks.
    - Verifies manifest.json integrity and SHA-256 for all components in a temporary staging directory.
    - Switches active files only after 100% cryptographic validation passes.
    """
    if target_data_dir is None:
        target_data_dir = settings.DATA_DIR

    target_data_dir = target_data_dir.resolve()
    backup_zip_path = backup_zip_path.resolve()

    if not backup_zip_path.exists():
        raise FileNotFoundError(f"Backup file not found at {backup_zip_path}")

    with tempfile.TemporaryDirectory(prefix="owi_restore_staging_") as temp_stage_str:
        temp_stage = Path(temp_stage_str)

        # 1. Safely extract archive to staging
        extracted_files, errors = safe_extract_zip(backup_zip_path, temp_stage)
        if errors:
            raise ValueError(f"Backup extraction failed security checks: {errors}")

        manifest_path = temp_stage / "manifest.json"
        if not manifest_path.exists():
            raise ValueError("Invalid backup: missing manifest.json")

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        # 2. Verify database checksum and SQLite integrity in staging
        restored_db_path = temp_stage / "owi.db"
        if not restored_db_path.exists():
            raise ValueError("Invalid backup: missing owi.db database snapshot")

        expected_db_sha = manifest.get("database", {}).get("sha256")
        actual_db_sha = compute_file_sha256(restored_db_path)
        if expected_db_sha and actual_db_sha != expected_db_sha:
            raise ValueError(f"Database SHA-256 mismatch! Expected {expected_db_sha}, got {actual_db_sha}")

        # Check SQLite integrity check on restored snapshot in staging
        import sqlite3
        staged_conn = sqlite3.connect(str(restored_db_path))
        try:
            check_res = staged_conn.execute("PRAGMA integrity_check").fetchone()
            if not check_res or check_res[0] != "ok":
                raise ValueError(f"Restored database snapshot failed SQLite integrity check: {check_res}")
        finally:
            staged_conn.close()

        # 3. Verify all assets in staging and enforce strict manifest whitelist
        staged_assets_dir = temp_stage / "assets"
        manifest_assets = manifest.get("assets", [])
        manifest_rel_map = {a["relative_path"]: a["sha256"] for a in manifest_assets}
        allowed_roots = ("media/audio/", "media/images/", "media/video/", "media/documents/", "sources/")

        # Verify that EVERY file in staging is accounted for and in an allowed destination
        if staged_assets_dir.exists():
            for item in staged_assets_dir.rglob("*"):
                if item.is_file():
                    rel_str = str(item.relative_to(staged_assets_dir)).replace("\\", "/")
                    if rel_str not in manifest_rel_map:
                        raise ValueError(f"Security error: unlisted unexpected file in backup archive: {rel_str}")
                    if not any(rel_str.startswith(r) for r in allowed_roots):
                        raise ValueError(f"Security error: unapproved destination path for asset: {rel_str}")
                    if rel_str.endswith("owi.db") or "owi.db" in rel_str:
                        raise ValueError(f"Security error: unauthorized database file in assets archive: {rel_str}")

        # Verify each manifest asset exists and matches expected SHA-256
        verified_assets_count = 0
        for rel_path, expected_sha in manifest_rel_map.items():
            staged_file = staged_assets_dir / rel_path
            if not staged_file.exists():
                raise ValueError(f"Missing asset in backup archive: {rel_path}")
            actual_sha = compute_file_sha256(staged_file)
            if actual_sha != expected_sha:
                raise ValueError(f"Asset integrity check failed for {rel_path}: checksum mismatch")
            verified_assets_count += 1

        # 4. Atomic, safe switch into target_data_dir over active WAL
        target_data_dir.mkdir(parents=True, exist_ok=True)
        target_db_path = target_data_dir / "owi.db"
        target_wal = target_data_dir / "owi.db-wal"
        target_shm = target_data_dir / "owi.db-shm"

        # Dispose active SQLAlchemy engine connections before replacing database files
        from owi.db.database import engine
        try:
            engine.dispose()
        except Exception as e:
            logger.warning(f"Engine dispose notice during restore: {e}")

        # If an active database exists, create a pre-restore safety copy and clear old WAL
        if target_db_path.exists():
            ts = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            pre_restore_backup = target_data_dir / f"owi.db.pre_restore_{ts}"
            try:
                shutil.copy2(target_db_path, pre_restore_backup)
                if target_wal.exists():
                    shutil.copy2(target_wal, target_data_dir / f"owi.db-wal.pre_restore_{ts}")
                    target_wal.unlink(missing_ok=True)
                if target_shm.exists():
                    target_shm.unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"Pre-restore safety copy notice: {e}")

        # Copy restored database
        shutil.copy2(restored_db_path, target_db_path)

        # Copy only validated assets from manifest whitelist
        for rel_path in manifest_rel_map.keys():
            src_file = staged_assets_dir / rel_path
            dest_file = target_data_dir / rel_path
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dest_file)

    logger.info(f"Successfully restored backup to {target_data_dir} ({verified_assets_count} assets verified).")
    return {
        "status": "restored",
        "app_version": manifest.get("version"),
        "schema_version": manifest.get("schema_version"),
        "verified_assets": verified_assets_count,
        "database_sha256": actual_db_sha
    }
