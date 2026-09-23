"""
FastAPI application entry point for Omar WhatsApp Intelligence (OWI).
Configures middleware, lifecycle hooks, and mounts API routers.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from owi.config import settings
from owi.core.logging import logger
from owi.db.migrations import init_db

# Import routers
from owi.api.routes_conversations import router as conversations_router
from owi.api.routes_messages import router as messages_router
from owi.api.routes_tasks import router as tasks_router
from owi.api.routes_intelligence import router as intelligence_router
from owi.api.routes_models import router as models_router
from owi.api.routes_system import router as system_router
from owi.api.routes_companion import router as companion_router
from owi.api.routes_auth import router as auth_router

from owi.core.security import LocalHostHeaderMiddleware
from owi.core.queue import job_queue

app = FastAPI(
    title=settings.APP_NAME,
    description="Local-First, Privacy-Conscious Intelligence System for WhatsApp",
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc"
)

# DNS rebinding & Host/Origin validation middleware
app.add_middleware(LocalHostHeaderMiddleware)

# Strict loopback CORS (no wildcard)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8765",
        "http://localhost:8765",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Startup lifecycle hook
@app.on_event("startup")
def on_startup():
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION} on {settings.HOST}:{settings.PORT}")
    settings.init_directories()
    init_db()
    reclaimed = job_queue.reclaim_orphaned_jobs()
    if reclaimed > 0:
        logger.info(f"Recovered {reclaimed} background jobs from previous session.")

# Mount API routers
app.include_router(auth_router)
app.include_router(conversations_router)
app.include_router(messages_router)
app.include_router(tasks_router)
app.include_router(intelligence_router)
app.include_router(models_router)
app.include_router(system_router)
app.include_router(companion_router)

@app.get("/api/health")
def health_check():
    """Health status and core local mode verification."""
    return {
        "status": "healthy",
        "app_name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "mode": settings.CORE_MODE,
        "cost": 0.0
    }

# Mount static frontend production build if available
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists() and (frontend_dist / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")

    @app.get("/{full_path:path}")
    def serve_frontend_spa(full_path: str):
        target = frontend_dist / full_path
        if full_path and target.is_file():
            return FileResponse(target)
        return FileResponse(frontend_dist / "index.html")
