"""
Tests for local loopback security controls:
- Host header enforcement (DNS rebinding protection).
- Origin header validation (Cross-origin protection).
- Bootstrap token creation, single-use exchange, and HttpOnly session cookies.
"""

import pytest
from fastapi.testclient import TestClient
from owi.main import app
from owi.core.security import session_manager

client = TestClient(app)

def test_dns_rebinding_protection():
    # Valid localhost / 127.0.0.1 Host headers should be allowed
    res_valid = client.get("/api/health", headers={"Host": "127.0.0.1:8765"})
    assert res_valid.status_code == 200

    res_valid_lh = client.get("/api/health", headers={"Host": "localhost:8765"})
    assert res_valid_lh.status_code == 200

    # Malicious host headers simulating DNS rebinding must be blocked with 403 Forbidden
    res_blocked = client.get("/api/health", headers={"Host": "attacker.com"})
    assert res_blocked.status_code == 403
    assert "DNS rebinding" in res_blocked.json()["detail"]

def test_cross_origin_protection():
    # Disallow state-changing requests from foreign origins
    res_blocked = client.post(
        "/api/system/cleanup", 
        headers={"Origin": "https://malicious-website.com"}
    )
    assert res_blocked.status_code == 403
    assert "Cross-origin" in res_blocked.json()["detail"]

    # Allow local origins
    res_allowed = client.post(
        "/api/system/cleanup", 
        headers={"Origin": "http://127.0.0.1:8765"}
    )
    assert res_allowed.status_code == 200

def test_bootstrap_token_exchange():
    # 1. Generate bootstrap token
    bootstrap_res = client.get("/api/auth/bootstrap")
    assert bootstrap_res.status_code == 200
    token = bootstrap_res.json()["bootstrap_token"]
    assert len(token) > 20

    # 2. Exchange token for session cookie
    exchange_res = client.post("/api/auth/exchange", json={"bootstrap_token": token})
    assert exchange_res.status_code == 200
    assert "owi_session" in exchange_res.cookies

    # 3. Verify token is single-use (replay attempt must fail)
    replay_res = client.post("/api/auth/exchange", json={"bootstrap_token": token})
    assert replay_res.status_code == 401
    assert "Invalid or expired" in replay_res.json()["detail"]
