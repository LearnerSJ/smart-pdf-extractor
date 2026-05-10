import React, { useState, useMemo, useCallback } from "react";
import { useFetch } from "./useFetch.js";

/**
 * LogsPage — structured log viewer with trace correlation.
 *
 * Sub-components:
 *   - LogFilters: filter controls for tenant_id, job_id, trace_id, severity, time range
 *   - LogTable: table with columns: timestamp, severity, event_name, tenant_id, job_id, trace_id, message
 *   - LogDetailPanel: expandable detail view showing all structured fields as key-value pairs
 */
export default function LogsPage({ apiBaseUrl = "" }) {
  const [filters, setFilters] = useState({
    tenant_id: "",
    job_id: "",
    trace_id: "",
    severity: "",
    start_time: "",
    end_time: "",
  });
  const [page, setPage] = useState(1);
  const [pageSize] = useState(50);
  const [expandedRowId, setExpandedRowId] = useState(null);
  const [traceFilter, setTraceFilter] = useState(null);

  // Build query string from filters
  const buildParams = () => {
    const params = new URLSearchParams();
    if (filters.tenant_id) params.set("tenant_id", filters.tenant_id);
    if (filters.job_id) params.set("job_id", filters.job_id);
    if (filters.trace_id) params.set("trace_id", filters.trace_id);
    if (filters.severity) params.set("severity", filters.severity);
    if (filters.start_time) params.set("start_time", filters.start_time);
    if (filters.end_time) params.set("end_time", filters.end_time);
    params.set("page", String(page));
    params.set("page_size", String(pageSize));
    return params.toString();
  };

  // When traceFilter is set, use the trace endpoint; otherwise use the main logs endpoint
  const logsUrl = useMemo(() => {
    if (traceFilter) {
      return `${apiBaseUrl}/v1/admin/logs/trace/${encodeURIComponent(traceFilter)}`;
    }
    const qs = buildParams();
    return `${apiBaseUrl}/v1/admin/logs${qs ? `?${qs}` : ""}`;
  }, [
    apiBaseUrl,
    traceFilter,
    filters.tenant_id,
    filters.job_id,
    filters.trace_id,
    filters.severity,
    filters.start_time,
    filters.end_time,
    page,
    pageSize,
  ]);

  const { data, loading, error } = useFetch(logsUrl);

  const handleFilterChange = (key, value) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
    setPage(1);
    setTraceFilter(null);
    setExpandedRowId(null);
  };

  const handleTraceClick = useCallback((traceId) => {
    setTraceFilter(traceId);
    setPage(1);
    setExpandedRowId(null);
  }, []);

  const handleClearTrace = () => {
    setTraceFilter(null);
    setPage(1);
  };

  const handleRowClick = (id) => {
    setExpandedRowId((prev) => (prev === id ? null : id));
  };

  const entries = data?.data?.entries || [];
  const pagination = data?.data?.pagination || null;

  return (
    <div style={styles.page}>
      <LogFilters filters={filters} onChange={handleFilterChange} />

      {traceFilter && (
        <div style={styles.traceBanner}>
          <span>Showing logs for trace: <strong>{traceFilter}</strong></span>
          <button onClick={handleClearTrace} style={styles.clearTraceBtn}>
            Clear trace filter
          </button>
        </div>
      )}

      {error && <div style={styles.errorBanner}>{error}</div>}

      <LogTable
        entries={entries}
        loading={loading}
        expandedRowId={expandedRowId}
        onRowClick={handleRowClick}
        onTraceClick={handleTraceClick}
      />

      {pagination && !traceFilter && (
        <PaginationControls
          pagination={pagination}
          page={page}
          onPageChange={setPage}
        />
      )}
    </div>
  );
}

// ─── LogFilters ──────────────────────────────────────────────────────────────

function LogFilters({ filters, onChange }) {
  return (
    <div style={styles.filtersContainer}>
      <div style={styles.filterGroup}>
        <label style={styles.filterLabel}>Tenant ID</label>
        <input
          type="text"
          value={filters.tenant_id}
          onChange={(e) => onChange("tenant_id", e.target.value)}
          placeholder="All tenants"
          style={styles.filterInput}
        />
      </div>

      <div style={styles.filterGroup}>
        <label style={styles.filterLabel}>Job ID</label>
        <input
          type="text"
          value={filters.job_id}
          onChange={(e) => onChange("job_id", e.target.value)}
          placeholder="All jobs"
          style={styles.filterInput}
        />
      </div>

      <div style={styles.filterGroup}>
        <label style={styles.filterLabel}>Trace ID</label>
        <input
          type="text"
          value={filters.trace_id}
          onChange={(e) => onChange("trace_id", e.target.value)}
          placeholder="All traces"
          style={styles.filterInput}
        />
      </div>

      <div style={styles.filterGroup}>
        <label style={styles.filterLabel}>Severity</label>
        <select
          value={filters.severity}
          onChange={(e) => onChange("severity", e.target.value)}
          style={styles.filterSelect}
        >
          <option value="">All levels</option>
          <option value="debug">Debug</option>
          <option value="info">Info</option>
          <option value="warning">Warning</option>
          <option value="error">Error</option>
          <option value="critical">Critical</option>
        </select>
      </div>

      <div style={styles.filterGroup}>
        <label style={styles.filterLabel}>Start Time</label>
        <input
          type="datetime-local"
          value={filters.start_time}
          onChange={(e) => onChange("start_time", e.target.value)}
          style={styles.filterInput}
        />
      </div>

      <div style={styles.filterGroup}>
        <label style={styles.filterLabel}>End Time</label>
        <input
          type="datetime-local"
          value={filters.end_time}
          onChange={(e) => onChange("end_time", e.target.value)}
          style={styles.filterInput}
        />
      </div>
    </div>
  );
}

// ─── LogTable ────────────────────────────────────────────────────────────────

function LogTable({ entries, loading, expandedRowId, onRowClick, onTraceClick }) {
  if (loading) {
    return <div style={styles.loadingText}>Loading logs...</div>;
  }

  if (entries.length === 0) {
    return (
      <div style={styles.tableContainer}>
        <div style={styles.emptyState}>No log entries found for the selected filters.</div>
      </div>
    );
  }

  return (
    <div style={styles.tableContainer}>
      <div style={styles.tableWrapper}>
        <table style={styles.table}>
          <thead>
            <tr>
              <th style={styles.th}>Timestamp</th>
              <th style={styles.th}>Severity</th>
              <th style={styles.th}>Event</th>
              <th style={styles.th}>Tenant ID</th>
              <th style={styles.th}>Job ID</th>
              <th style={styles.th}>Trace ID</th>
              <th style={styles.th}>Message</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <React.Fragment key={entry.id}>
                <tr
                  style={{
                    ...styles.tr,
                    cursor: "pointer",
                    backgroundColor: expandedRowId === entry.id ? "#f9fafb" : undefined,
                  }}
                  onClick={() => onRowClick(entry.id)}
                >
                  <td style={styles.td}>{formatTimestamp(entry.timestamp)}</td>
                  <td style={styles.td}>
                    <SeverityBadge severity={entry.severity} />
                  </td>
                  <td style={styles.td}>{entry.event_name}</td>
                  <td style={styles.td}>{entry.tenant_id || "—"}</td>
                  <td style={styles.td}>{entry.job_id || "—"}</td>
                  <td style={styles.td}>
                    {entry.trace_id ? (
                      <span
                        style={styles.traceLink}
                        onClick={(e) => {
                          e.stopPropagation();
                          onTraceClick(entry.trace_id);
                        }}
                      >
                        {entry.trace_id}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td style={styles.tdMessage}>{entry.message || "—"}</td>
                </tr>
                {expandedRowId === entry.id && (
                  <tr>
                    <td colSpan={7} style={styles.detailCell}>
                      <LogDetailPanel fields={entry.fields} />
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── LogDetailPanel ──────────────────────────────────────────────────────────

function LogDetailPanel({ fields }) {
  if (!fields || Object.keys(fields).length === 0) {
    return (
      <div style={styles.detailPanel}>
        <span style={styles.detailEmpty}>No additional fields.</span>
      </div>
    );
  }

  return (
    <div style={styles.detailPanel}>
      <div style={styles.detailTitle}>Structured Fields</div>
      <div style={styles.detailGrid}>
        {Object.entries(fields).map(([key, value]) => (
          <div key={key} style={styles.detailRow}>
            <span style={styles.detailKey}>{key}</span>
            <span style={styles.detailValue}>
              {typeof value === "object" ? JSON.stringify(value) : String(value)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── SeverityBadge ───────────────────────────────────────────────────────────

function SeverityBadge({ severity }) {
  const level = (severity || "").toLowerCase();
  const colorMap = {
    debug: { bg: "#f3f4f6", text: "#6b7280" },
    info: { bg: "#eff6ff", text: "#2563eb" },
    warning: { bg: "#fffbeb", text: "#d97706" },
    error: { bg: "#fef2f2", text: "#dc2626" },
    critical: { bg: "#fef2f2", text: "#7f1d1d" },
  };
  const colors = colorMap[level] || colorMap.info;

  return (
    <span
      style={{
        ...styles.badge,
        backgroundColor: colors.bg,
        color: colors.text,
      }}
    >
      {severity}
    </span>
  );
}

// ─── PaginationControls ──────────────────────────────────────────────────────

function PaginationControls({ pagination, page, onPageChange }) {
  const { total, total_pages } = pagination;

  return (
    <div style={styles.paginationContainer}>
      <span style={styles.paginationInfo}>
        Page {page} of {total_pages} ({total} total entries)
      </span>
      <div style={styles.paginationButtons}>
        <button
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          style={{
            ...styles.paginationBtn,
            ...(page <= 1 ? styles.paginationBtnDisabled : {}),
          }}
        >
          Previous
        </button>
        <button
          onClick={() => onPageChange(page + 1)}
          disabled={page >= total_pages}
          style={{
            ...styles.paginationBtn,
            ...(page >= total_pages ? styles.paginationBtnDisabled : {}),
          }}
        >
          Next
        </button>
      </div>
    </div>
  );
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatTimestamp(ts) {
  if (!ts) return "";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

// ─── Styles ──────────────────────────────────────────────────────────────────

const styles = {
  page: {
    display: "flex",
    flexDirection: "column",
    gap: 24,
  },
  errorBanner: {
    padding: "12px 16px",
    backgroundColor: "#fef2f2",
    border: "1px solid #fecaca",
    borderRadius: 8,
    color: "#dc2626",
    fontSize: 14,
  },
  loadingText: {
    padding: "24px 0",
    textAlign: "center",
    color: "#6b7280",
    fontSize: 14,
  },
  emptyState: {
    padding: "32px 0",
    textAlign: "center",
    color: "#9ca3af",
    fontSize: 14,
  },

  // Trace banner
  traceBanner: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "10px 16px",
    backgroundColor: "#eff6ff",
    border: "1px solid #bfdbfe",
    borderRadius: 8,
    fontSize: 13,
    color: "#1e40af",
  },
  clearTraceBtn: {
    padding: "4px 12px",
    fontSize: 12,
    border: "1px solid #93c5fd",
    borderRadius: 4,
    backgroundColor: "#fff",
    color: "#2563eb",
    cursor: "pointer",
  },

  // Filters
  filtersContainer: {
    display: "flex",
    flexWrap: "wrap",
    gap: 16,
    padding: 16,
    backgroundColor: "#fff",
    borderRadius: 8,
    border: "1px solid #e5e7eb",
  },
  filterGroup: {
    display: "flex",
    flexDirection: "column",
    gap: 4,
    minWidth: 140,
  },
  filterLabel: {
    fontSize: 12,
    fontWeight: 600,
    color: "#374151",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
  },
  filterInput: {
    padding: "8px 10px",
    border: "1px solid #d1d5db",
    borderRadius: 6,
    fontSize: 13,
    color: "#111827",
    outline: "none",
  },
  filterSelect: {
    padding: "8px 10px",
    border: "1px solid #d1d5db",
    borderRadius: 6,
    fontSize: 13,
    color: "#111827",
    backgroundColor: "#fff",
    outline: "none",
  },

  // Table
  tableContainer: {
    padding: 20,
    backgroundColor: "#fff",
    borderRadius: 8,
    border: "1px solid #e5e7eb",
  },
  tableWrapper: {
    overflowX: "auto",
  },
  table: {
    width: "100%",
    borderCollapse: "collapse",
    fontSize: 13,
  },
  th: {
    textAlign: "left",
    padding: "10px 12px",
    borderBottom: "2px solid #e5e7eb",
    fontSize: 12,
    fontWeight: 600,
    color: "#374151",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    whiteSpace: "nowrap",
  },
  tr: {
    borderBottom: "1px solid #f3f4f6",
  },
  td: {
    padding: "10px 12px",
    color: "#374151",
    whiteSpace: "nowrap",
  },
  tdMessage: {
    padding: "10px 12px",
    color: "#374151",
    maxWidth: 300,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },

  // Trace link
  traceLink: {
    color: "#2563eb",
    cursor: "pointer",
    textDecoration: "underline",
    fontSize: 12,
    fontFamily: "monospace",
  },

  // Severity badge
  badge: {
    display: "inline-block",
    padding: "2px 8px",
    borderRadius: 4,
    fontSize: 11,
    fontWeight: 600,
    textTransform: "uppercase",
    letterSpacing: "0.03em",
  },

  // Detail panel
  detailCell: {
    padding: 0,
    borderBottom: "1px solid #e5e7eb",
  },
  detailPanel: {
    padding: "12px 24px 16px 24px",
    backgroundColor: "#f9fafb",
  },
  detailTitle: {
    fontSize: 12,
    fontWeight: 600,
    color: "#374151",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    marginBottom: 8,
  },
  detailGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
    gap: 6,
  },
  detailRow: {
    display: "flex",
    gap: 8,
    fontSize: 12,
    padding: "4px 0",
  },
  detailKey: {
    fontWeight: 600,
    color: "#6b7280",
    minWidth: 100,
    fontFamily: "monospace",
  },
  detailValue: {
    color: "#111827",
    wordBreak: "break-all",
  },
  detailEmpty: {
    fontSize: 12,
    color: "#9ca3af",
    fontStyle: "italic",
  },

  // Pagination
  paginationContainer: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "12px 16px",
    backgroundColor: "#fff",
    borderRadius: 8,
    border: "1px solid #e5e7eb",
  },
  paginationInfo: {
    fontSize: 13,
    color: "#6b7280",
  },
  paginationButtons: {
    display: "flex",
    gap: 8,
  },
  paginationBtn: {
    padding: "6px 14px",
    fontSize: 13,
    border: "1px solid #d1d5db",
    borderRadius: 6,
    backgroundColor: "#fff",
    color: "#374151",
    cursor: "pointer",
  },
  paginationBtnDisabled: {
    opacity: 0.5,
    cursor: "not-allowed",
  },
};
