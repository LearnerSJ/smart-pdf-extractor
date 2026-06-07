"""Learn-lock — prevents a thundering herd of VLM discovery on identical layouts.

When N never-before-seen documents of the SAME layout arrive at once (e.g. a
batch of 50 GIRO reports), each one misses the template store and would
independently fire VLM discovery + synthesis — N× the cost, N× the latency, and
N racing writes of the same template.

The fix: serialise on a cheap, deterministic layout signature computed BEFORE any
VLM call. The first document through the lock learns and saves the template; every
other document, on acquiring the lock, re-checks the store (double-checked
locking) and finds the freshly-learned template — so it extracts deterministically
with zero VLM. Different layouts hash to different keys and still run in parallel.

Two implementations:
- AsyncioLearnLock — per-key asyncio.Lock. Correct for a single process (the
  current uvicorn model: many background tasks, one event loop). Default.
- PostgresLearnLock — session-level advisory lock, correct across worker
  processes/hosts. Wire this in when scaling out to multiple workers.
"""

from __future__ import annotations

import asyncio
import hashlib
from contextlib import asynccontextmanager

import structlog

from pipeline.models import AssembledDocument

logger = structlog.get_logger()

# How many text blocks to fold into the layout signature. Enough to capture the
# distinctive header/label shape without being sensitive to row-level data.
_SIGNATURE_BLOCK_SAMPLE = 40


def compute_layout_signature(doc: AssembledDocument, theme: str | None) -> str:
    """Cheap, deterministic key for a document's layout (no VLM, no OCR).

    Folds the theme, table header signatures, and a sample of leading block text
    into a stable hash. Two documents of the same layout (same headers, same
    label scaffolding) collide; documents that differ structurally do not.
    """
    parts: list[str] = [theme or "_"]

    for tbl in doc.tables or []:
        headers = tbl.get("headers") if isinstance(tbl, dict) else None
        if headers:
            parts.append("|".join(str(h).strip().lower() for h in headers))

    sampled = 0
    for block in doc.blocks or []:
        text = str(block.get("text", "")).strip().lower() if isinstance(block, dict) else ""
        if not text:
            continue
        parts.append(text)
        sampled += 1
        if sampled >= _SIGNATURE_BLOCK_SAMPLE:
            break

    digest = hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()
    return digest[:32]


class LearnLock:
    """In-process learn-lock: one asyncio.Lock per (tenant, layout) key.

    Correct when all extraction runs share an event loop (single uvicorn worker).
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    async def _lock_for(self, key: str) -> asyncio.Lock:
        async with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
            return lock

    @asynccontextmanager
    async def guard(self, tenant_id: str, signature: str):
        """Serialise learning for one (tenant, layout) key."""
        key = f"{tenant_id}:{signature}"
        lock = await self._lock_for(key)
        contended = lock.locked()
        if contended:
            logger.info("learn_lock.wait", key=key)
        async with lock:
            yield contended


class PostgresLearnLock(LearnLock):
    """Cross-process learn-lock via Postgres session-level advisory locks.

    Use when running multiple worker processes/hosts: an asyncio.Lock only
    serialises within one process, advisory locks serialise across the cluster.
    The lock is held for the duration of the (rare) cold-layout learn, so it ties
    up one pooled connection per concurrent distinct layout — acceptable because
    cold layouts are infrequent by design.
    """

    @asynccontextmanager
    async def guard(self, tenant_id: str, signature: str):
        from sqlalchemy import text

        from db.session import async_session_factory

        key = f"{tenant_id}:{signature}"
        # Map the string key to a stable signed 64-bit int for pg_advisory_lock.
        lock_id = int.from_bytes(
            hashlib.sha256(key.encode("utf-8")).digest()[:8], "big", signed=True
        )
        async with async_session_factory() as session:
            await session.execute(
                text("SELECT pg_advisory_lock(:k)"), {"k": lock_id}
            )
            logger.info("learn_lock.acquired", key=key, backend="postgres")
            try:
                # `contended` is unknown across processes; report False (callers
                # must double-check the store regardless, which is always correct).
                yield False
            finally:
                await session.execute(
                    text("SELECT pg_advisory_unlock(:k)"), {"k": lock_id}
                )
                await session.commit()


_default_lock = LearnLock()


def get_default_learn_lock() -> LearnLock:
    """Process-wide default in-process learn-lock."""
    return _default_lock
