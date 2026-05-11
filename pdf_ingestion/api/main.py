"""FastAPI application entry point.

Configures structlog for JSON output, registers routers with /v1 prefix,
and provides a lifespan context manager for startup/shutdown lifecycle.
Handles SIGTERM gracefully by draining in-flight requests before closing
DB connections.
"""

from __future__ import annotations

import asyncio
import signal
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI

from api.config import Settings, get_settings
from api.routes.batches import router as batches_router
from api.routes.extract import router as extract_router
from api.routes.feedback import router as feedback_router
from api.routes.health import router as health_router
from api.routes.jobs import router as jobs_router
from api.routes.results import router as results_router
from api.routes.tenants import router as tenants_router

# Admin dashboard routes
from api.routes.admin_auth import router as admin_auth_router
from api.routes.admin_users import router as admin_users_router
from api.routes.admin_usage import router as admin_usage_router
from api.routes.admin_logs import router as admin_logs_router
from api.routes.admin_alerts import router as admin_alerts_router
from api.routes.schema_cache import router as schema_cache_router

# Alert engine and notification dispatcher
from pipeline.alerts.engine import AlertEngine
from pipeline.alerts.notifier import NotificationDispatcher
from pipeline.discovery.schema_cache import SchemaCache
from pipeline.dedup_store import DedupStore

# Self-healing feedback loops
from pipeline.self_healing.schema_learner import SchemaLearner
from pipeline.self_healing.pattern_miner import PatternMiner


def _configure_structlog() -> None:
    """Configure structlog with JSON rendering for production use."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )


# Track in-flight requests for graceful shutdown
_in_flight_count: int = 0
_shutting_down: bool = False


def _handle_sigterm(signum: int, frame: object) -> None:
    """Handle SIGTERM signal for graceful shutdown.

    Sets the shutting_down flag so the application can drain in-flight
    requests before exiting. Uvicorn's --timeout-graceful-shutdown handles
    the actual drain; this handler ensures we log the event.
    """
    global _shutting_down
    _shutting_down = True
    logger = structlog.get_logger()
    logger.info("app.sigterm_received", signal=signum)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan — startup and shutdown hooks.

    Startup:
        - Configure structlog
        - Register SIGTERM handler
        - Load settings into app state
        - Wire dependency injection (placeholder for DB pool, repos, etc.)

    Shutdown:
        - Drain in-flight requests (handled by uvicorn --timeout-graceful-shutdown)
        - Close DB connections
    """
    # ── Startup ──────────────────────────────────────────────────────────────
    _configure_structlog()

    # Register SIGTERM handler for graceful shutdown
    signal.signal(signal.SIGTERM, _handle_sigterm)

    settings = get_settings()
    app.state.settings = settings

    # Placeholder: wire database pool
    app.state.db_pool = None

    # Placeholder: wire tenant repository
    app.state.tenant_repo = None

    # Placeholder: wire port implementations (VLM, OCR, Redactor, Delivery)
    app.state.vlm_client = None
    app.state.ocr_client = None
    app.state.redactor = None
    app.state.delivery_client = None

    # ── Schema Cache (auto-discovery) ────────────────────────────────────────
    app.state.schema_cache = SchemaCache()

    # ── Dedup Store (persistent SHA-256 dedup) ───────────────────────────────
    app.state.dedup_store = DedupStore()

    # ── PDF Store (in-memory for viewer) ─────────────────────────────────────
    app.state.pdf_store = {}

    # ── Self-Healing: Schema Learner + Pattern Miner ─────────────────────────
    app.state.schema_learner = SchemaLearner(app.state.schema_cache, None)  # VLM client wired per-request
    app.state.pattern_miner = PatternMiner()
    await app.state.pattern_miner.start(interval_seconds=3600)

    # ── Alert Engine ─────────────────────────────────────────────────────────
    alert_engine = AlertEngine()
    notifier = NotificationDispatcher(
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        smtp_from=settings.smtp_from,
    )
    alert_engine.set_notifier(notifier)
    await alert_engine.start(interval_seconds=settings.alert_evaluation_interval_seconds)
    app.state.alert_engine = alert_engine

    logger = structlog.get_logger()
    logger.info("app.startup", settings_loaded=True)

    yield

    # ── Shutdown ─────────────────────────────────────────────────────────────
    logger = structlog.get_logger()
    logger.info("app.shutdown", draining=True)

    # Stop pattern miner before draining requests
    if hasattr(app.state, "pattern_miner") and app.state.pattern_miner is not None:
        await app.state.pattern_miner.stop()

    # Stop alert engine before draining requests
    if hasattr(app.state, "alert_engine") and app.state.alert_engine is not None:
        await app.state.alert_engine.stop()

    # Wait briefly for in-flight requests to complete (uvicorn handles the
    # actual drain via --timeout-graceful-shutdown=30, but we add a small
    # buffer here for any cleanup that needs to happen after drain)
    await asyncio.sleep(0.5)

    # Close DB pool after requests have drained
    if app.state.db_pool is not None:
        logger.info("app.shutdown.db_closing")
        # await app.state.db_pool.close()

    logger.info("app.shutdown.complete")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory.

    Args:
        settings: Optional settings override (useful for testing).

    Returns:
        Configured FastAPI application instance.
    """
    app = FastAPI(
        title="PDF Ingestion Layer",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Register routers — all routes are prefixed /v1/
    app.include_router(health_router)
    app.include_router(extract_router)
    app.include_router(jobs_router)
    app.include_router(results_router)
    app.include_router(batches_router)
    app.include_router(tenants_router)
    app.include_router(feedback_router)

    # Admin dashboard routers (prefixed /v1/admin/ in their modules)
    app.include_router(admin_auth_router)
    app.include_router(admin_users_router)
    app.include_router(admin_usage_router)
    app.include_router(admin_logs_router)
    app.include_router(admin_alerts_router)
    app.include_router(schema_cache_router)

    return app


# Default application instance for uvicorn
app = create_app()
