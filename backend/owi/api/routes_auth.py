"""
Authentication and local loopback session endpoints for OWI.
Provides bootstrap token exchange for HttpOnly SameSite=Strict cookies.
"""

from fastapi import APIRouter, Response, Request, HTTPException, status
from pydantic import BaseModel
from typing import Dict, Any

from owi.core.security import session_manager

router = APIRouter(prefix="/api/auth", tags=["Authentication & Session"])

class ExchangeRequest(BaseModel):
    bootstrap_token: str

@router.get("/bootstrap")
def get_bootstrap_token() -> Dict[str, Any]:
    """
    Generate an ephemeral single-use bootstrap token.
    Used by the Windows launcher to pass credentials via URL fragment to the frontend.
    """
    token = session_manager.create_bootstrap_token()
    return {"bootstrap_token": token, "expires_in_seconds": 600}

@router.post("/exchange")
def exchange_token(payload: ExchangeRequest, response: Response) -> Dict[str, Any]:
    """
    Exchange single-use bootstrap token for an HttpOnly SameSite=Strict session cookie.
    """
    session_id = session_manager.exchange_bootstrap_token(payload.bootstrap_token)
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired bootstrap token."
        )
    
    # Set HttpOnly SameSite=Strict cookie
    response.set_cookie(
        key="owi_session",
        value=session_id,
        httponly=True,
        samesite="strict",
        max_age=86400,
        secure=False  # Localhost HTTP does not use SSL
    )
    return {"status": "authenticated", "message": "Session established successfully."}

@router.get("/session")
def check_session(request: Request) -> Dict[str, Any]:
    """Check whether the active session cookie is valid."""
    cookie = request.cookies.get("owi_session")
    is_valid = session_manager.is_valid_session(cookie)
    return {"authenticated": is_valid}

@router.post("/logout")
def logout(request: Request, response: Response) -> Dict[str, Any]:
    """Revoke session and clear session cookie."""
    cookie = request.cookies.get("owi_session")
    if cookie:
        session_manager.revoke_session(cookie)
    response.delete_cookie(key="owi_session")
    return {"status": "logged_out"}
