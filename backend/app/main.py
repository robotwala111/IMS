"""
FastAPI Application Entry Point

This module initializes the FastAPI application with all routers, middleware,
exception handlers, and lifecycle events.

Architecture:
    - Lifespan context manager handles startup/shutdown
    - Middleware stack: CORS → CorrelationID → RequestLogging → RateLimit
    - Exception handlers provide consistent JSON error responses
    - Static frontend served only when a bundled frontend directory is available
"""

import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.exceptions import AppException
from app.core.logging import get_logger, setup_logging
from app.core.middleware import (
    CorrelationIdMiddleware,
    RateLimitMiddleware,
    RequestLoggingMiddleware,
)
from app.api.v1.router import api_router
from app.db.session import async_session_factory, init_db
from app.services.scheduler import scheduler_service

logger = get_logger(__name__)

# Application metadata
APP_VERSION = "2.0.0"
APP_START_TIME: datetime | None = None

# Path to optional bundled static frontend
FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend"


def validate_startup_config() -> None:
    """Validate critical configuration before starting the application."""
    errors: list[str] = []

    if settings.is_production:
        default_secret = "your-super-secret-jwt-key-change-in-production-min-32-chars"
        if settings.JWT_SECRET_KEY == default_secret:
            errors.append("JWT_SECRET_KEY must be changed from default in production")
        if len(settings.JWT_SECRET_KEY) < 32:
            errors.append("JWT_SECRET_KEY must be at least 32 characters")
        if settings.DEBUG:
            errors.append("DEBUG must be False in production")

    if errors:
        for error in errors:
            logger.error(f"Configuration error: {error}")
        if settings.is_production:
            sys.exit(1)


def ensure_directories() -> None:
    """Ensure required data directories exist."""
    directories = [
        Path(settings.STORAGE_LOCAL_PATH),
        Path("./data"),
    ]
    if settings.LOG_FILE_PATH:
        directories.append(Path(settings.LOG_FILE_PATH).parent)
    for directory in directories:
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning(
                "Directory is not writable; continuing without local persistence",
                path=str(directory),
                error=str(exc),
            )


def safe_exception_details(exc: Exception) -> str:
    """Format exception details without allowing __str__ failures to mask errors."""
    try:
        return str(exc)
    except Exception:
        return f"{exc.__class__.__name__} raised, but its details could not be formatted"

from sqlalchemy import select
from app.models.user import User, UserRole
from app.core.security import hash_password
import uuid

async def create_default_user():
    if not settings.CREATE_DEFAULT_ADMIN:
        logger.info("Default admin creation skipped")
        return

    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(User.email == settings.DEFAULT_ADMIN_EMAIL)
        )
        user = result.scalar_one_or_none()

        if not user:
            new_user = User(
                id=str(uuid.uuid4()),
                email=settings.DEFAULT_ADMIN_EMAIL,
                name="Admin",
                password_hash=hash_password(settings.DEFAULT_ADMIN_PASSWORD),
                role=UserRole.ADMIN,
                is_active=True
            )
            session.add(new_user)
            await session.commit()
            logger.info("Default admin user created")
        else:
            logger.info("Default admin user already exists")

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifecycle manager."""
    global APP_START_TIME

    # Startup
    logger.info(
        "Starting ScienceTech-IMS application",
        version=APP_VERSION,
        environment=settings.APP_ENV,
    )
    validate_startup_config()
    ensure_directories()

    # Initialize database tables only when explicitly enabled.
    if settings.AUTO_CREATE_TABLES:
        await init_db()
        logger.info("Database initialized")
    else:
        logger.info("Database table auto-creation skipped")

    await create_default_user()

    # Start scheduler if enabled
    if settings.SCHEDULER_ENABLED and not os.getenv("VERCEL"):
        scheduler_service.start()
        logger.info("Scheduler started")
    elif settings.SCHEDULER_ENABLED:
        logger.info("Scheduler disabled in Vercel/serverless runtime; use cron endpoints")

    APP_START_TIME = datetime.now(timezone.utc)
    logger.info("Application startup complete")

    yield

    # Shutdown
    logger.info("Shutting down ScienceTech-IMS application...")

    if settings.SCHEDULER_ENABLED:
        scheduler_service.shutdown()
        logger.info("Scheduler stopped")

    logger.info("Application shutdown complete")


def create_application() -> FastAPI:
    """Create and configure the FastAPI application."""
    setup_logging()

    app = FastAPI(
        title=settings.APP_NAME,
        description=(
            "Enterprise-grade Non-Destructive Testing Inventory Management System.\n\n"
            "## Features\n"
            "- Multi-location inventory tracking\n"
            "- Serialized asset management with calibration tracking\n"
            "- Transfer workflow with approval chains\n"
            "- Role-based access control (RBAC)\n"
            "- Real-time low-stock alerts\n"
            "- Comprehensive audit trail\n"
        ),
        version=APP_VERSION,
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
        docs_url=f"{settings.API_V1_PREFIX}/docs" if not settings.is_production else None,
        redoc_url=f"{settings.API_V1_PREFIX}/redoc" if not settings.is_production else None,
        lifespan=lifespan,
        license_info={"name": "MIT", "url": "https://opensource.org/licenses/MIT"},
        contact={"name": "ScienceTech-IMS Support", "email": "support@sciencetech-ims.com"},
        openapi_tags=[
            {"name": "Authentication", "description": "Login, logout, token refresh"},
            {"name": "Users", "description": "User management (Admin)"},
            {"name": "Locations", "description": "Warehouse / branch location management"},
            {"name": "Categories", "description": "Item category management"},
            {"name": "Items", "description": "Inventory item master data"},
            {"name": "Stock", "description": "Stock levels, adjustments, and alerts"},
            {"name": "Transactions", "description": "Receipt, issue, and return operations"},
            {"name": "Transfers", "description": "Inter-location transfer workflow"},
            {"name": "Assets", "description": "Serialized asset tracking"},
            {"name": "Calibration", "description": "Calibration records and scheduling"},
            {"name": "Maintenance", "description": "Maintenance records"},
            {"name": "Attachments", "description": "File attachments"},
            {"name": "Dashboard", "description": "Dashboard analytics and KPIs"},
            {"name": "Reports", "description": "Report generation"},
            {"name": "Notifications", "description": "System notifications"},
            {"name": "Audit", "description": "Audit trail logs"},
            {"name": "Employee Records", "description": "Employee digital records"},
            {"name": "Jobs", "description": "NDT job management"},
        ],
    )

    # Configure CORS
    if settings.is_production:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],
            expose_headers=["X-Correlation-ID", "X-Response-Time-Ms"],
            max_age=600,
        )
    else:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Correlation-ID", "X-Response-Time-Ms"],
        )

    # Add custom middleware (order matters — outermost first)
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(RequestLoggingMiddleware)

    if settings.RATE_LIMIT_ENABLED:
        app.add_middleware(RateLimitMiddleware)

    @app.middleware("http")
    async def cache_control_headers(request: Request, call_next):
        """Prevent stale application/API data while caching versioned static assets."""
        response = await call_next(request)
        path = request.url.path
        if path.startswith(settings.API_V1_PREFIX) or path in {"/", "/ready", "/health"}:
            response.headers["Cache-Control"] = "no-store"
        elif path.startswith(("/js/", "/css/")):
            response.headers["Cache-Control"] = "public, max-age=3600"
        return response

    # ---- Exception Handlers ----
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", None)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.error_code,
                    "message": exc.message,
                    "details": exc.details,
                    "correlation_id": correlation_id,
                }
            },
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", None)
        logger.exception("Unhandled exception", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An unexpected error occurred",
                    "details": safe_exception_details(exc) if settings.DEBUG else None,
                    "correlation_id": correlation_id,
                }
            },
        )

    # ---- API Routers ----
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    # ---- Health & Readiness Endpoints ----
    @app.get("/health", tags=["System"])
    async def health_check() -> dict:
        """Liveness probe — confirms the process is running."""
        return {
            "status": "healthy",
            "app": settings.APP_NAME,
            "version": APP_VERSION,
            "environment": settings.APP_ENV,
            "uptime_seconds": (
                (datetime.now(timezone.utc) - APP_START_TIME).total_seconds()
                if APP_START_TIME
                else 0
            ),
        }

    @app.get("/ready", tags=["System"])
    async def readiness_check() -> dict:
        """Readiness probe — confirms the app can serve requests (DB is reachable)."""
        from sqlalchemy import text
        from app.db.session import async_session_factory

        checks: dict = {"database": "unknown"}
        try:
            async with async_session_factory() as session:
                await session.execute(text("SELECT 1"))
            checks["database"] = "connected"
        except Exception as e:
            checks["database"] = f"error: {e}"
            return JSONResponse(
                status_code=503,
                content={"status": "not ready", "checks": checks},
            )
        return {"status": "ready", "checks": checks}
    # ---- Serve Static Frontend ----
    if FRONTEND_DIR.exists():
        app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="css")
        app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="js")
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")

        @app.get("/")
        async def serve_frontend():
            return FileResponse(FRONTEND_DIR / "index.html")

        logger.info(f"Serving static frontend from {FRONTEND_DIR}")
    else:
        logger.warning(f"Frontend directory not found: {FRONTEND_DIR}")

    return app


app = create_application()


def run() -> None:
    """Run the application using uvicorn."""
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower(),
        access_log=not settings.is_production,
    )


if __name__ == "__main__":
    run()
