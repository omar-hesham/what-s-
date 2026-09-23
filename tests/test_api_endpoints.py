"""
Unit tests for FastAPI endpoints using TestClient.
"""

from fastapi.testclient import TestClient
from owi.main import app

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["mode"] == "Local"
    assert data["cost"] == 0.0

def test_zero_surprise_cost_endpoint():
    response = client.get("/api/system/cost")
    assert response.status_code == 200
    data = response.json()
    assert data["core_mode"] == "Local"
    assert data["mandatory_subscription"] == "None"
    assert data["mandatory_api"] == "None"
    assert "$0.00" in data["recurring_software_fee"]
    assert data["cloud_ai_enabled"] is False
    assert data["cloud_storage_enabled"] is False

def test_system_storage_endpoint():
    response = client.get("/api/system/storage")
    assert response.status_code == 200
    data = response.json()
    assert "total_mb" in data
    assert "database_mb" in data

def test_system_resources_endpoint():
    response = client.get("/api/system/resources")
    assert response.status_code == 200
    data = response.json()
    assert "cpu_cores" in data
    assert "total_ram_gb" in data
    assert "suggested_profile" in data

def test_model_status_endpoint():
    response = client.get("/api/models/status")
    assert response.status_code == 200
    data = response.json()
    assert "performance_profile" in data
    assert "active_llm" in data
    assert "recommended_models" in data
