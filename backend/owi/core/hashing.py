"""
Cryptographic hashing and deduplication utilities.
Uses SHA-256 for data integrity and deduplication of media and exports.
"""

import hashlib
from pathlib import Path
from typing import Union

def compute_sha256(source: Union[Path, str, bytes]) -> str:
    """Compute SHA-256 hex digest for a file path, string, or bytes."""
    hasher = hashlib.sha256()
    
    if isinstance(source, Path) or (isinstance(source, str) and Path(source).is_file()):
        file_path = Path(source)
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
    elif isinstance(source, str):
        hasher.update(source.encode("utf-8"))
    elif isinstance(source, bytes):
        hasher.update(source)
    else:
        raise ValueError(f"Unsupported source type for hashing: {type(source)}")
        
    return hasher.hexdigest()

def compute_text_fingerprint(text: str) -> str:
    """Normalize text (strip whitespace) and return its SHA-256 fingerprint."""
    normalized = " ".join(text.strip().split())
    return compute_sha256(normalized.encode("utf-8"))

compute_file_sha256 = compute_sha256

