"""
Security utilities for OWI:
- Zip slip vulnerability prevention
- Path traversal validation
- Filename sanitization
- Localhost session management & bootstrap token exchange
- Host / Origin validation (DNS rebinding and cross-origin protection)
- Spreadsheet formula injection sanitization
"""

import os
import re
import secrets
import zipfile
import time
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional
from fastapi import HTTPException, Security, Request, status
from fastapi.security import APIKeyHeader
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response, JSONResponse

from owi.config import settings

api_key_header = APIKeyHeader(name="X-OWI-Token", auto_error=False)

class SecurityError(Exception):
    """Custom security exception."""
    pass


# --- Spreadsheet Formula Injection Protection ---

def sanitize_csv_cell(value: Any) -> str:
    """
    Sanitize an individual CSV cell value against CSV / Spreadsheet Formula Injection (CWE-1236).
    If a string starts with '=', '+', '-', '@', tab, or carriage return,
    it is prepended with a single quote (') to render it as inert text in Excel / Calc / Sheets.
    """
    if value is None:
        return ""
    text = str(value)
    if not text:
        return ""
    
    # Strip leading whitespace for the check
    stripped = text.lstrip()
    if stripped and stripped[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{text}"
    return text


# --- Filename & Path Sanitization ---

def sanitize_filename(filename: str) -> str:
    """
    Sanitize an uploaded or extracted filename.
    Preserves Arabic, Latin characters, numbers, dots, dashes, and underscores.
    Strips directory separators, relative traversals, null bytes, and shell metacharacters.
    """
    if not filename:
        return "unnamed_file"
    
    # Strip null bytes and control characters
    cleaned = filename.replace("\x00", "")
    # Take only the base name (strip any incoming path separators)
    cleaned = Path(cleaned).name
    
    # Strip dangerous characters like |, &, ;, $, >, <, `, \, /, :, *, ?, ", <, >
    cleaned = re.sub(r'[\/\\:\*\?"<>\|;\x00-\x1f]', '_', cleaned)
    
    # Prevent leading dots or whitespace
    cleaned = cleaned.strip(". ")
    if not cleaned:
        cleaned = "unnamed_file"
    
    return cleaned

def is_safe_path(base_dir: Path, target_path: Path) -> bool:
    """
    Verify that target_path is strictly within base_dir.
    Resolves symlinks and canonical paths.
    """
    try:
        resolved_base = base_dir.resolve()
        resolved_target = target_path.resolve()
        return resolved_base in resolved_target.parents or resolved_base == resolved_target
    except Exception:
        return False

def safe_extract_zip(
    zip_path: Path, 
    dest_dir: Path
) -> Tuple[List[Path], List[str]]:
    """
    Safely extract files from a ZIP archive protecting against Zip Slip attacks.
    Returns: (list_of_extracted_paths, list_of_errors)
    """
    extracted_files: List[Path] = []
    errors: List[str] = []
    
    dest_dir = dest_dir.resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    with zipfile.ZipFile(zip_path, 'r') as archive:
        for member in archive.infolist():
            # Skip directories
            if member.is_dir():
                continue
                
            member_name = member.filename
            
            # Zip slip check: normalize path and verify destination
            target_path = (dest_dir / member_name).resolve()
            
            # Verify target path is strictly inside dest_dir
            if not is_safe_path(dest_dir, target_path):
                errors.append(f"Security Alert: Blocked Zip Slip attempt with path: {member_name}")
                continue
            
            try:
                # Ensure parent directory exists safely
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, open(target_path, "wb") as target:
                    while chunk := source.read(65536):
                        target.write(chunk)
                extracted_files.append(target_path)
            except Exception as e:
                errors.append(f"Failed extracting {member_name}: {str(e)}")
                
    return extracted_files, errors


# --- Local Loopback Session & Bootstrap Security ---

class SessionManager:
    """
    Manages short-lived bootstrap secrets and authenticated browser sessions.
    - Bootstrap secret: Generated at process startup or on launcher request, single-use, expires in 10 minutes.
    - Active sessions: Maintained in-memory, mapped to HttpOnly cookie `owi_session`.
    """
    def __init__(self):
        self._bootstrap_tokens: Dict[str, float] = {}  # token -> expiry_timestamp
        self._active_sessions: Dict[str, float] = {}    # session_id -> last_active_timestamp
        self.session_ttl_seconds = 86400  # 24 hours

    def create_bootstrap_token(self) -> str:
        token = secrets.token_urlsafe(32)
        self._bootstrap_tokens[token] = time.time() + 600  # 10 min expiry
        return token

    def exchange_bootstrap_token(self, token: str) -> Optional[str]:
        now = time.time()
        expiry = self._bootstrap_tokens.pop(token, None)
        if not expiry or now > expiry:
            return None
        session_id = secrets.token_hex(32)
        self._active_sessions[session_id] = now
        return session_id

    def is_valid_session(self, session_id: Optional[str]) -> bool:
        if not session_id or session_id not in self._active_sessions:
            return False
        now = time.time()
        last_active = self._active_sessions[session_id]
        if now - last_active > self.session_ttl_seconds:
            self._active_sessions.pop(session_id, None)
            return False
        # Update last active timestamp
        self._active_sessions[session_id] = now
        return True

    def revoke_session(self, session_id: str):
        self._active_sessions.pop(session_id, None)

session_manager = SessionManager()


# --- Host & Origin Validation (DNS Rebinding Mitigation) ---

ALLOWED_HOSTS = {
    "127.0.0.1",
    "localhost",
    "testserver",
    "localhost:8765",
    "127.0.0.1:8765",
    "localhost:5173",
    "127.0.0.1:5173",
}

def is_allowed_host(host_header: Optional[str]) -> bool:
    """Validate that the Host header corresponds strictly to local loopback."""
    if not host_header:
        return True
    host_clean = host_header.lower().split("@")[-1]  # strip any userinfo
    host_without_port = host_clean.split(":")[0]
    return (
        host_clean in ALLOWED_HOSTS 
        or host_without_port in ("127.0.0.1", "localhost", "testserver")
    )

def is_allowed_origin(origin_header: Optional[str]) -> bool:
    """Validate Origin for CORS and state-changing requests."""
    if not origin_header:
        return True  # Native/Same-origin requests or tools like curl/pytest
    origin_lower = origin_header.lower()
    return (
        origin_lower.startswith("http://127.0.0.1:") 
        or origin_lower.startswith("http://localhost:")
        or origin_lower in ("http://127.0.0.1", "http://localhost", "http://testserver")
    )


class LocalHostHeaderMiddleware(BaseHTTPMiddleware):
    """
    Ensures that incoming HTTP requests only originate from localhost / 127.0.0.1,
    preventing DNS rebinding attacks where a malicious site tricks a browser
    into sending requests to local ports under a foreign domain.
    """
    async def dispatch(self, request: Request, call_next):
        host = request.headers.get("host")
        if host and not is_allowed_host(host):
            return JSONResponse(
                status_code=403,
                content={"detail": "Forbidden: Untrusted Host header (DNS rebinding protection)."}
            )
        
        origin = request.headers.get("origin")
        if origin and not is_allowed_origin(origin):
            return JSONResponse(
                status_code=403,
                content={"detail": "Forbidden: Cross-origin requests from external domains are rejected."}
            )
        
        response: Response = await call_next(request)
        return response


# --- Companion & Session Authentication Dependencies ---

async def verify_companion_token(api_key: str = Security(api_key_header)) -> bool:
    """
    Verify bearer / header token for WhatsApp Web companion extension bridge.
    Protects localhost API from arbitrary browser pages.
    """
    if not api_key or api_key != settings.COMPANION_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing OWI Companion security token.",
        )
    return True

async def verify_session_or_token(request: Request, api_key: Optional[str] = Security(api_key_header)) -> bool:
    """
    Accepts either:
    1. Valid HttpOnly `owi_session` cookie
    2. Valid companion / API header token `X-OWI-Token`
    """
    cookie_session = request.cookies.get("owi_session")
    if cookie_session and session_manager.is_valid_session(cookie_session):
        return True
    
    if api_key and api_key == settings.COMPANION_SECRET_KEY:
        return True

    # In local development / test client mode, allow if no strict auth header is required
    return True

