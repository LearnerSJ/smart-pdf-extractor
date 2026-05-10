"""Unit tests for the log sink processor."""

import pytest

from api.middleware.log_sink import (
    _LOG_STORE,
    clear_logs,
    db_log_sink,
    get_logs,
)


@pytest.fixture(autouse=True)
def _clean_log_store():
    """Ensure a clean log store for each test."""
    clear_logs()
    yield
    clear_logs()


class TestDbLogSink:
    """Tests for the db_log_sink structlog processor."""

    def test_returns_event_dict_unchanged(self):
        """The processor must return the event_dict unchanged."""
        event_dict = {"event": "test_event", "level": "info", "extra": "data"}
        result = db_log_sink(None, "info", event_dict)
        assert result is event_dict

    def test_stores_log_entry(self):
        """The processor should store a log entry in _LOG_STORE."""
        db_log_sink(None, "info", {"event": "something_happened"})
        assert len(_LOG_STORE) == 1
        entry = _LOG_STORE[0]
        assert entry["event_name"] == "something_happened"
        assert entry["severity"] == "info"
        assert entry["id"] == 1

    def test_extracts_tenant_id(self):
        """tenant_id should be extracted into a dedicated column."""
        db_log_sink(None, "info", {"event": "test", "tenant_id": "t-123"})
        assert _LOG_STORE[0]["tenant_id"] == "t-123"

    def test_extracts_job_id(self):
        """job_id should be extracted into a dedicated column."""
        db_log_sink(None, "warning", {"event": "test", "job_id": "j-456"})
        assert _LOG_STORE[0]["job_id"] == "j-456"

    def test_extracts_trace_id(self):
        """trace_id should be extracted into a dedicated column."""
        db_log_sink(None, "error", {"event": "test", "trace_id": "tr-789"})
        assert _LOG_STORE[0]["trace_id"] == "tr-789"

    def test_remaining_fields_stored_in_fields_column(self):
        """Fields not in the extracted set should go into the 'fields' dict."""
        db_log_sink(
            None,
            "info",
            {"event": "test", "tenant_id": "t-1", "custom_key": "custom_val", "count": 42},
        )
        entry = _LOG_STORE[0]
        assert entry["fields"] is not None
        assert entry["fields"]["custom_key"] == "custom_val"
        assert entry["fields"]["count"] == 42
        # Extracted fields should NOT be in fields
        assert "tenant_id" not in entry["fields"]
        assert "event" not in entry["fields"]

    def test_auto_incrementing_id(self):
        """Each log entry should get an auto-incrementing id."""
        db_log_sink(None, "info", {"event": "first"})
        db_log_sink(None, "info", {"event": "second"})
        db_log_sink(None, "info", {"event": "third"})
        assert _LOG_STORE[0]["id"] == 1
        assert _LOG_STORE[1]["id"] == 2
        assert _LOG_STORE[2]["id"] == 3

    def test_timestamp_is_iso8601(self):
        """Timestamp should be a valid ISO 8601 string."""
        db_log_sink(None, "info", {"event": "test"})
        ts = _LOG_STORE[0]["timestamp"]
        assert "T" in ts
        assert "+" in ts or "Z" in ts or ts.endswith("+00:00")

    def test_severity_normalization(self):
        """Various level names should be normalized correctly."""
        db_log_sink(None, "warn", {"event": "a"})
        db_log_sink(None, "error", {"event": "b"})
        db_log_sink(None, "critical", {"event": "c"})
        db_log_sink(None, "debug", {"event": "d"})
        assert _LOG_STORE[0]["severity"] == "warning"
        assert _LOG_STORE[1]["severity"] == "error"
        assert _LOG_STORE[2]["severity"] == "critical"
        assert _LOG_STORE[3]["severity"] == "debug"

    def test_handles_error_gracefully(self):
        """If event_dict causes an issue, the processor should not raise."""
        # Pass a non-dict-like object that would fail .get() — but since
        # we type-hint dict, let's test with a dict that has weird values
        event_dict = {"event": object()}  # non-string event
        result = db_log_sink(None, "info", event_dict)
        # Should not raise, should return event_dict
        assert result is event_dict

    def test_none_fields_excluded_from_fields_column(self):
        """None-valued extra fields should not appear in the fields dict."""
        db_log_sink(None, "info", {"event": "test", "optional_field": None})
        entry = _LOG_STORE[0]
        # fields should be None (empty) since the only extra field was None
        assert entry["fields"] is None

    def test_message_defaults_to_event_name(self):
        """If no explicit message, event name is used as message."""
        db_log_sink(None, "info", {"event": "user_logged_in"})
        assert _LOG_STORE[0]["message"] == "user_logged_in"

    def test_explicit_message_preserved(self):
        """An explicit message field should be stored separately."""
        db_log_sink(None, "info", {"event": "auth", "message": "Login successful"})
        assert _LOG_STORE[0]["message"] == "Login successful"
        assert _LOG_STORE[0]["event_name"] == "auth"


class TestGetLogs:
    """Tests for the get_logs helper function."""

    def _seed_logs(self):
        """Seed some test log entries."""
        db_log_sink(None, "info", {"event": "e1", "tenant_id": "t1", "job_id": "j1", "trace_id": "tr1"})
        db_log_sink(None, "warning", {"event": "e2", "tenant_id": "t1", "job_id": "j2", "trace_id": "tr1"})
        db_log_sink(None, "error", {"event": "e3", "tenant_id": "t2", "job_id": "j3", "trace_id": "tr2"})
        db_log_sink(None, "debug", {"event": "e4", "tenant_id": "t2", "job_id": "j4", "trace_id": "tr2"})

    def test_returns_all_logs_unfiltered(self):
        """Without filters, all logs should be returned."""
        self._seed_logs()
        result = get_logs()
        assert result["pagination"]["total"] == 4
        assert len(result["data"]) == 4

    def test_filter_by_tenant_id(self):
        """Filtering by tenant_id should return only matching entries."""
        self._seed_logs()
        result = get_logs(tenant_id="t1")
        assert result["pagination"]["total"] == 2
        assert all(e["tenant_id"] == "t1" for e in result["data"])

    def test_filter_by_job_id(self):
        """Filtering by job_id should return only matching entries."""
        self._seed_logs()
        result = get_logs(job_id="j3")
        assert result["pagination"]["total"] == 1
        assert result["data"][0]["job_id"] == "j3"

    def test_filter_by_trace_id(self):
        """Filtering by trace_id should return only matching entries."""
        self._seed_logs()
        result = get_logs(trace_id="tr1")
        assert result["pagination"]["total"] == 2
        assert all(e["trace_id"] == "tr1" for e in result["data"])

    def test_filter_by_severity(self):
        """Severity filter should return entries at or above the level."""
        self._seed_logs()
        result = get_logs(severity="warning")
        assert result["pagination"]["total"] == 2
        severities = {e["severity"] for e in result["data"]}
        assert severities <= {"warning", "error", "critical"}

    def test_pagination(self):
        """Pagination should correctly slice results."""
        self._seed_logs()
        result = get_logs(page=1, page_size=2)
        assert len(result["data"]) == 2
        assert result["pagination"]["total"] == 4
        assert result["pagination"]["total_pages"] == 2

        result2 = get_logs(page=2, page_size=2)
        assert len(result2["data"]) == 2

    def test_page_size_clamped_to_max_200(self):
        """Page size should be clamped to 200 max."""
        self._seed_logs()
        result = get_logs(page_size=500)
        assert result["pagination"]["page_size"] == 200

    def test_chronological_ordering(self):
        """Results should be in chronological order."""
        self._seed_logs()
        result = get_logs()
        timestamps = [e["timestamp"] for e in result["data"]]
        assert timestamps == sorted(timestamps)

    def test_combined_filters(self):
        """Multiple filters should combine with AND logic."""
        self._seed_logs()
        result = get_logs(tenant_id="t2", severity="error")
        assert result["pagination"]["total"] == 1
        assert result["data"][0]["event_name"] == "e3"


class TestClearLogs:
    """Tests for the clear_logs helper."""

    def test_clear_resets_store_and_counter(self):
        """clear_logs should empty the store and reset the ID counter."""
        db_log_sink(None, "info", {"event": "test"})
        assert len(_LOG_STORE) == 1
        clear_logs()
        assert len(_LOG_STORE) == 0
        # Next entry should start at id=1 again
        db_log_sink(None, "info", {"event": "after_clear"})
        assert _LOG_STORE[0]["id"] == 1
