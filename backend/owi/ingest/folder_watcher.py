"""
Folder Watcher & Folder Import module.
User-initiated folder scanner and watcher.
Monitors an explicitly chosen folder for newly saved WhatsApp exports or media.
Never scans arbitrary directories without explicit opt-in.
"""

import threading
import time
from pathlib import Path
from typing import Optional, Set
from owi.core.logging import logger
from owi.core.hashing import compute_sha256
from owi.db.database import SessionLocal
from owi.ingest.zip_importer import ZipImporter
from owi.ingest.drag_drop import DragDropIngester

class FolderWatcher:
    """Manages explicit folder watching for WhatsApp materials."""

    def __init__(self):
        self.watch_path: Optional[Path] = None
        self.is_active: bool = False
        self._thread: Optional[threading.Thread] = None
        self.processed_hashes: Set[str] = set()

    def start(self, folder_path: str):
        """Start watching an explicitly specified folder."""
        p = Path(folder_path)
        if not p.exists() or not p.is_dir():
            raise ValueError(f"Target folder '{folder_path}' does not exist or is not a directory.")

        self.watch_path = p
        self.is_active = True
        logger.info(f"Explicit folder watcher activated on: {self.watch_path}")
        
        self._thread = threading.Thread(target=self._watch_loop, daemon=True, name="owi-folder-watcher")
        self._thread.start()

    def stop(self):
        """Stop watching the folder."""
        self.is_active = False
        logger.info("Folder watcher stopped.")

    def scan_once(self) -> int:
        """Perform a single immediate scan of the watched folder."""
        if not self.watch_path or not self.watch_path.exists():
            return 0
        
        new_items = 0
        db = SessionLocal()
        try:
            for item in self.watch_path.iterdir():
                if item.is_file():
                    h = compute_sha256(item)
                    if h not in self.processed_hashes:
                        self.processed_hashes.add(h)
                        try:
                            if item.suffix.lower() == ".zip":
                                ZipImporter.import_zip(item, db)
                            else:
                                DragDropIngester.ingest_file(item, db)
                            new_items += 1
                        except Exception as e:
                            logger.error(f"Error processing item from watched folder {item.name}: {e}")
        finally:
            db.close()
        return new_items

    def _watch_loop(self):
        """Periodic background poll of the folder."""
        while self.is_active:
            try:
                self.scan_once()
            except Exception as e:
                logger.error(f"Error in folder watch loop: {e}")
            time.sleep(10)

folder_watcher = FolderWatcher()
