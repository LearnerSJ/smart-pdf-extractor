"""Health check endpoints.

GET /v1/healthz — liveness probe (no dependency checks).
GET /v1/readyz  — readiness probe (checks postgres and paddleocr).
"""

from __future__ import annotations

import httpx
import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()
logger = structlog.get_logger()


@router.get("/v1/healthz")
async def liveness() -> dict[str, str]:
    """Process is alive. No dependency checks."""
    return {"status": "ok"}


@router.get("/v1/readyz")
async def readiness(request: Request) -> JSONResponse:
    """Check all runtime dependencies before reporting ready.

    Returns 200 if all dependencies are reachable, 503 otherwise.
    """
    checks: dict[str, bool] = {
        "postgres": await _check_postgres(request),
        "paddleocr": await _check_paddleocr(request),
    }
    is_ready = all(checks.values())
    status_code = 200 if is_ready else 503
    return JSONResponse(status_code=status_code, content={"status": checks})


async def _check_postgres(request: Request) -> bool:
    """Verify PostgreSQL connectivity."""
    try:
        db_pool = getattr(request.app.state, "db_pool", None)
        if db_pool is None:
            return False
        async with db_pool.acquire() as conn:
            await conn.execute("SELECT 1")
        return True
    except Exception:
        logger.warning("readyz.postgres_check_failed")
        return False


async def _check_paddleocr(request: Request) -> bool:
    """Verify PaddleOCR service is reachable via HTTP ping."""
    try:
        settings = getattr(request.app.state, "settings", None)
        if settings is None:
            return False
        endpoint = settings.paddleocr_endpoint
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{endpoint}/health")
            return response.status_code < 500
    except Exception:
        logger.warning("readyz.paddleocr_check_failed")
        return False
