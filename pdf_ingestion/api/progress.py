"""In-memory job progress tracking.

Provides a lightweight progress store that the pipeline updates during
processing and the frontend polls for real-time progress feedback.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class JobProgress:
    """Tracks processing progress for a single job."""

    job_id: str
    total_pages: int = 0
    pages_classified: int = 0
    pages_ocr_complete: int = 0
    current_stage: str = "uploading"  # uploading, classifying, extracting, vlm, packaging, complete
    stage_detail: str = ""
    started_at: float = field(default_factory=time.time)
    avg_page_time_ms: float = 0.0  # rolling average ms per page

    # VLM progress
    vlm_total_windows: int = 0
    vlm_windows_complete: int = 0

    # Partial results (streaming fields as they're extracted)
    partial_fields: dict[str, object] = field(default_factory=dict)
    partial_tables_count: int = 0

    # Internal timing
    _page_times: list[float] = field(default_factory=list, repr=False)

    @property
    def progress_percent(self) -> int:
        """Overall progress as a percentage (0-100).

        Stages weighted: OCR = 50%, VLM = 40%, packaging = 10%
        """
        if self.total_pages == 0:
            return 0

        if self.current_stage == "complete":
            return 100
        if self.current_stage == "packaging":
            return 95

        # OCR phase: 0-50%
        ocr_progress = (self.pages_ocr_complete / self.total_pages) * 50

        if self.current_stage in ("uploading", "classifying", "extracting"):
            return min(int(ocr_progress), 50)

        # VLM phase: 50-90%
        if self.current_stage == "vlm":
            vlm_progress = 0
            if self.vlm_total_windows > 0:
                vlm_progress = (self.vlm_windows_complete / self.vlm_total_windows) * 40
            return min(int(50 + vlm_progress), 90)

        return min(int(ocr_progress), 100)

    @property
    def estimated_remaining_seconds(self) -> float | None:
        """Estimated seconds remaining based on current stage."""
        if self.current_stage == "complete":
            return 0.0
        if self.current_stage == "packaging":
            return 2.0

        if self.current_stage in ("uploading", "classifying", "extracting"):
            if not self._page_times or self.total_pages == 0:
                return None
            avg_ms = sum(self._page_times[-20:]) / len(self._page_times[-20:])
            remaining_pages = self.total_pages - self.pages_ocr_complete
            ocr_remaining = (remaining_pages * avg_ms) / 1000.0
            # Estimate VLM time: ~3s per window, total_pages/9 windows (step=9),
            # divided by concurrency (10)
            total_windows = max(1, self.total_pages // 9)
            vlm_estimate = (total_windows / 10) * 4.0  # 10 concurrent, ~4s per call
            return ocr_remaining + vlm_estimate

        if self.current_stage == "vlm":
            if self.vlm_total_windows == 0:
                return None
            remaining_windows = self.vlm_total_windows - self.vlm_windows_complete
            # ~3s per window on average
            return remaining_windows * 3.0

        return None

    def record_page_complete(self, elapsed_ms: float) -> None:
        """Record that a page has been processed."""
        self._page_times.append(elapsed_ms)
        self.pages_ocr_complete += 1
        # Keep rolling window of last 50 timings
        if len(self._page_times) > 50:
            self._page_times = self._page_times[-50:]

    def update_partial_fields(self, fields: dict[str, object]) -> None:
        """Update partial fields as they are extracted during the pipeline run."""
        self.partial_fields.update(fields)

    def update_partial_tables(self, count: int) -> None:
        """Update the count of tables extracted so far."""
        self.partial_tables_count = count

    def to_dict(self) -> dict:
        """Serialize for API response."""
        elapsed = time.time() - self.started_at
        remaining = self.estimated_remaining_seconds

        # Determine latest field name
        field_names = list(self.partial_fields.keys())
        latest_field = field_names[-1] if field_names else None

        return {
            "job_id": self.job_id,
            "total_pages": self.total_pages,
            "pages_processed": self.pages_ocr_complete,
            "current_stage": self.current_stage,
            "stage_detail": self.stage_detail,
            "progress_percent": self.progress_percent,
            "elapsed_seconds": round(elapsed, 1),
            "estimated_remaining_seconds": round(remaining, 1) if remaining is not None else None,
            "vlm_windows_complete": self.vlm_windows_complete,
            "vlm_total_windows": self.vlm_total_windows,
            "fields_extracted_so_far": len(self.partial_fields),
            "tables_extracted_so_far": self.partial_tables_count,
            "latest_field": latest_field,
        }


class ProgressStore:
    """Thread-safe in-memory store for job progress."""

    def __init__(self) -> None:
        self._jobs: dict[str, JobProgress] = {}
        self._lock = Lock()

    def create(self, job_id: str) -> JobProgress:
        """Create a new progress tracker for a job."""
        progress = JobProgress(job_id=job_id)
        with self._lock:
            self._jobs[job_id] = progress
        return progress

    def get(self, job_id: str) -> JobProgress | None:
        """Get progress for a job."""
        with self._lock:
            return self._jobs.get(job_id)

    def remove(self, job_id: str) -> None:
        """Remove a completed job's progress (cleanup)."""
        with self._lock:
            self._jobs.pop(job_id, None)


# Singleton instance
progress_store = ProgressStore()
