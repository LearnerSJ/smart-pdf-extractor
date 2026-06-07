"""Tests for the learn-lock (thundering-herd guard)."""

from __future__ import annotations

import asyncio

import pytest

from pipeline.models import AssembledDocument
from pipeline.schemas.learn_lock import LearnLock, compute_layout_signature


def _doc(headers: list[str], blocks: list[str]) -> AssembledDocument:
    return AssembledDocument(
        blocks=[{"text": t, "bbox": [0, 0, 1, 1], "provenance": {"page": 1}} for t in blocks],
        tables=[{"headers": headers, "rows": []}],
    )


class TestLayoutSignature:
    def test_identical_layout_collides(self) -> None:
        a = _doc(["Item", "Amount"], ["AVIVA LTD", "Currency SGD"])
        b = _doc(["Item", "Amount"], ["AVIVA LTD", "Currency SGD"])
        assert compute_layout_signature(a, "payments") == compute_layout_signature(b, "payments")

    def test_different_headers_differ(self) -> None:
        a = _doc(["Item", "Amount"], ["x"])
        b = _doc(["ISIN", "Market Value"], ["x"])
        assert compute_layout_signature(a, "payments") != compute_layout_signature(b, "payments")

    def test_different_theme_differs(self) -> None:
        a = _doc(["Item"], ["x"])
        assert compute_layout_signature(a, "payments") != compute_layout_signature(a, "custody")


class TestLearnLockConcurrency:
    @pytest.mark.asyncio
    async def test_same_key_serialises(self) -> None:
        """Concurrent callers on the same key never overlap (max concurrency 1)."""
        lock = LearnLock()
        active = 0
        peak = 0

        async def worker() -> None:
            nonlocal active, peak
            async with lock.guard("tenant", "sigA"):
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.02)
                active -= 1

        await asyncio.gather(*(worker() for _ in range(10)))
        assert peak == 1

    @pytest.mark.asyncio
    async def test_different_keys_run_in_parallel(self) -> None:
        """Distinct layouts must NOT serialise — they are genuinely different work."""
        lock = LearnLock()
        active = 0
        peak = 0

        async def worker(sig: str) -> None:
            nonlocal active, peak
            async with lock.guard("tenant", sig):
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.02)
                active -= 1

        await asyncio.gather(*(worker(f"sig{i}") for i in range(5)))
        assert peak > 1

    @pytest.mark.asyncio
    async def test_guard_reports_contention(self) -> None:
        """The first holder sees contended=False; a waiter sees True."""
        lock = LearnLock()
        seen: list[bool] = []
        gate = asyncio.Event()

        async def first() -> None:
            async with lock.guard("t", "s") as contended:
                seen.append(contended)
                gate.set()
                await asyncio.sleep(0.05)

        async def second() -> None:
            await gate.wait()
            async with lock.guard("t", "s") as contended:
                seen.append(contended)

        await asyncio.gather(first(), second())
        assert seen[0] is False
        assert seen[1] is True
