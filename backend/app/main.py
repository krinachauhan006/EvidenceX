"""FastAPI application factory for EvidenceX."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import Settings, get_settings
from app.core.database import engine
from app.core.deploy_checks import check_deployment_config
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger
from app.core.schema import schema_state
from app.modules.analysis.router import router as analysis_router
from app.modules.analysis.router_phase2 import ai_router
from app.modules.analysis.router_phase2 import router as phase2_router
from app.modules.auth.deps import authorize
from app.modules.auth.router import members_router
from app.modules.auth.router import router as auth_router
from app.modules.cases.router import router as cases_router
from app.modules.cases.router import workspace_router
from app.modules.evidence.router import router as evidence_router
from app.modules.processing.router import audio_router, ocr_router
from app.modules.processing.router import router as processing_router

logger = get_logger(__name__)

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# FastAPI's interactive docs load their own scripts; they get no restrictive CSP.
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


class SchemaNotReadyError(RuntimeError):
    """Production start-up refused: the database is not at the revision this code needs."""


def check_schema_for_production(settings: Settings, db_engine=None) -> None:  # noqa: ANN001
    """In production, refuse to serve on a database that is missing migrations (or has
    no Alembic revision at all). Migrations are run explicitly with
    ``alembic upgrade head``; development keeps starting so the 503/health reporting
    can guide the developer."""
    if settings.app_env != "production":
        return
    state = schema_state(db_engine or engine)
    if state["expected"] is None:
        raise SchemaNotReadyError(
            "the migration scripts (alembic.ini and alembic/) were not found next to the "
            "application or in the working directory, so the required database revision "
            "is unknown; deploy the whole backend folder"
        )
    if state["up_to_date"] is not True:
        raise SchemaNotReadyError(
            f"database revision {state['revision']!r} does not match the code's "
            f"{state['expected']!r}; back up the database, then run 'alembic upgrade head'"
        )


def _cross_site(request: Request, allowed: set[str]) -> bool:
    """True when a browser says the request comes from an origin we do not trust."""
    origin = request.headers.get("origin")
    if origin:
        own = f"{request.url.scheme}://{request.url.netloc}"
        return origin.rstrip("/") not in allowed and origin != own
    # Older browsers may omit Origin; Fetch Metadata still reveals a cross-site call.
    return request.headers.get("sec-fetch-site") == "cross-site"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):  # noqa: ANN202
        check_deployment_config(settings)
        check_schema_for_production(settings)
        yield

    app = FastAPI(title="EvidenceX API", version="0.2.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    allowed_origins = {o.rstrip("/") for o in settings.cors_origins}

    @app.middleware("http")
    async def _security_headers(request: Request, call_next):  # noqa: ANN001, ANN202
        if request.method not in _SAFE_METHODS and _cross_site(request, allowed_origins):
            # CSRF defence in depth (the session cookie is also SameSite=Lax): a
            # state-changing request from a page on another origin is refused before
            # any route runs. Non-browser clients send no Origin and are unaffected.
            response = JSONResponse(
                status_code=403, content={"detail": "cross-origin request refused"}
            )
        else:
            response = await call_next(request)
        for k, v in _SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        path = request.url.path
        if not path.startswith(_DOCS_PATHS):
            # The API serves data and files, never pages: nothing may run or be framed.
            response.headers.setdefault(
                "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
            )
        if path.startswith("/api/"):
            # Case data, evidence and session responses must not be stored by caches.
            response.headers.setdefault("Cache-Control", "no-store")
        return response

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
        schema = schema_state(engine) if db_ok else {"up_to_date": None}
        # Reachable but older than the code: sign-in and most routes cannot work yet.
        behind = schema["up_to_date"] is False
        return {
            "status": "ok" if db_ok and not behind else "degraded",
            "service": "evidencex-api",
            "database": "unavailable" if not db_ok else "migration_required" if behind else "ok",
            "schema": schema,
        }

    protected = [Depends(authorize)]
    app.include_router(auth_router)  # public: register / login; session: me / logout
    app.include_router(cases_router)  # declares its own authorize dependency
    app.include_router(workspace_router)
    app.include_router(members_router)
    app.include_router(evidence_router, dependencies=protected)
    app.include_router(processing_router, dependencies=protected)
    app.include_router(audio_router, dependencies=protected)
    app.include_router(ocr_router, dependencies=protected)
    app.include_router(analysis_router, dependencies=protected)
    app.include_router(phase2_router, dependencies=protected)
    app.include_router(ai_router, dependencies=protected)
    logger.info("EvidenceX API initialized (env=%s)", settings.app_env)
    return app


app = create_app()
