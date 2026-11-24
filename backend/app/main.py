"""FastAPI application factory for EvidenceX."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import Settings, get_settings
from app.core.database import engine
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger
from app.modules.analysis.router import router as analysis_router
from app.modules.cases.router import router as cases_router
from app.modules.evidence.router import router as evidence_router
from app.modules.processing.router import audio_router
from app.modules.processing.router import router as processing_router

logger = get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="EvidenceX API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    @app.get("/health", tags=["health"])
    def health() -> dict:
        """Report service status and database connectivity."""
        db_ok = True
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001 - we only report connectivity, not details
            db_ok = False
        return {
            "status": "ok" if db_ok else "degraded",
            "service": "evidencex-api",
            "database": "ok" if db_ok else "unavailable",
        }

    app.include_router(cases_router)
    app.include_router(evidence_router)
    app.include_router(processing_router)
    app.include_router(audio_router)
    app.include_router(analysis_router)
    logger.info("EvidenceX API initialized (env=%s)", settings.app_env)
    return app


app = create_app()
