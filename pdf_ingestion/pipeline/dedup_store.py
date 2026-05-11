"""Persistent SHA-256 dedup store.

Stores hash→job_id mappings in a JSON file for cross-restart dedup.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock

import structlog

logger = structlog.get_logger()

DEDUP_FILE = Path(".dedup_cache.json")


class DedupStore:
    """File-backed dedup store for document hashes."""

    def __init__(self, path: Path = DEDUP_FILE) -> None:
        self._path = path
        self._lock = Lock()
        self._cache: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        """Load existing dedup cache from disk."""
        if self._path.exists():
            try:
                with open(self._path) as f:
                    self._cache = json.load(f)
                logger.info("dedup_store.loaded", entries=len(self._cache))
            except (json.JSONDecodeError, OSError):
                self._cache = {}

    def _save(self) -> None:
        """Persist cache to disk."""
        try:
            with open(self._path, "w") as f:
                json.dump(self._cache, f)
        except OSError as e:
            logger.warning("dedup_store.save_failed", error=str(e))

    def lookup(self, doc_hash: str) -> str | None:
        """Check if a hash exists. Returns job_id if found."""
        with self._lock:
            return self._cache.get(doc_hash)

    def store(self, doc_hash: str, job_id: str) -> None:
        """Store a hash→job_id mapping."""
        with self._lock:
            self._cache[doc_hash] = job_id
            self._save()

    def remove(self, doc_hash: str) -> None:
        """Remove a hash from the store."""
        with self._lock:
            self._cache.pop(doc_hash, None)
            self._save()
