import React, { useState, useEffect, useMemo } from "react";
import { useFetch } from "./useFetch.js";

/**
 * UsagePage — displays token consumption metrics with chart and table.
 *
 * Sub-components:
 *   - UsageFilters: filter controls for tenant_id, model_id, time range, granularity
 *   - UsageChart: CSS-based bar chart of token consumption over time
 *   - UsageTable: breakdown table of usage records
 */
export default function UsagePage({ apiBaseUrl = "" }) {
  const [filters, setFilters] = useState({
    tenant_id: "",
    model_id: "",
    start_time: "",
    end_time: "",
    granularity: "day",
  });

  // Build query strings from filters
  const buildParams = (extra = {}) => {
    const params = new URLSearchParams();
    if (filters.tenant_id) params.set("tenant_id", filters.tenant_id);
    if (filters.model_id) params.set("model_id", filters.model_id);
    if (filters.start_time) params.set("start_time", filters.start_time);
    if (filters.end_time) params.set("end_time", filters.end_time);
    Object.entries(extra).forEach(([k, v]) => {
      if (v) params.set(k, v);
    });
    return params.toString();
  };

  const summaryUrl = useMemo(() => {
    const qs = buildParams();
    return `${apiBaseUrl}/v1/admin/usage/summary${qs ? `?${qs}` : ""}`;
  }, [apiBaseUrl, filters.tenant_id, filters.model_id, filters.start_time, filters.end_time]);

  const timeseriesUrl = useMemo(() => {
    const qs = buildParams({ granularity: filters.granularity });
    return `${apiBaseUrl}/v1/admin/usage/timeseries${qs ? `?${qs}` : ""}`;
  }, [apiBaseUrl, filters.tenant_id, filters.model_id, filters.start_time, filters.end_time, filters.granularity]);

  const tableUrl = useMemo(() => {
    const qs = buildParams({ page_size: "50" });
    return `${apiBaseUrl}/v1/admin/usage${qs ? `?${qs}` : ""}`;
  }, [apiBaseUrl, filters.tenant_id, filters.model_id, filters.start_time, filters.end_time]);

  const { data: summaryData, loading: summaryLoading, error: summaryError } = useFetch(summaryUrl);
  const { data: timeseriesData, loading: timeseriesLoading, error: timeseriesError } = useFetch(timeseriesUrl);
  const { data: tableData, loading: tableLoading, error: tableError } = useFetch(tableUrl);

  const handleFilterChange = (key, value) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  };

  const hasError = summaryError || timeseriesError || tableError;
  const isLoading = summaryLoading || timeseriesLoading || tableLoading;

  return (
    <div style={styles.page}>
      <UsageFilters filters={filters} onChange={handleFilterChange} />

      {hasError && (
        <div style={styles.errorBanner}>
          {summaryError || timeseriesError || tableError}
        </div>
      )}

      <UsageSummaryCards
        data={summaryData?.data}
        loading={summaryLoading}
      />

      <UsageChart
        data={timeseriesData?.data}
        loading={timeseriesLoading}
        granularity={filters.granularity}
      />

      <UsageTable
        data={tableData?.data}
        loading={tableLoading}
      />
    </div>
  );
}

// ─── UsageFilters ────────────────────────────────────────────────────────────

function UsageFilters({ filters, onChange }) {
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
        <label style={styles.filterLabel}>Model</label>
        <input
          type="text"
          value={filters.model_id}
          onChange={(e) => onChange("model_id", e.target.value)}
          placeholder="All models"
          style={styles.filterInput}
        />
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

      <div style={styles.filterGroup}>
        <label style={styles.filterLabel}>Granularity</label>
        <select
          value={filters.granularity}
          onChange={(e) => onChange("granularity", e.target.value)}
          style={styles.filterSelect}
        >
          <option value="day">Day</option>
          <option value="week">Week</option>
          <option value="month">Month</option>
        </select>
      </div>
    </div>
  );
}

// ─── UsageSummaryCards ────────────────────────────────────────────────────────

function UsageSummaryCards({ data, loading }) {
  if (loading) {
    return <div style={styles.loadingText}>Loading summary...</div>;
  }

  if (!data) return null;

  const cards = [
    { label: "Total Input Tokens", value: (data.total_input_tokens || 0).toLocaleString() },
    { label: "Total Output Tokens", value: (data.total_output_tokens || 0).toLocaleString() },
    { label: "Total Tokens", value: (data.total_tokens || 0).toLocaleString() },
    { label: "Estimated Cost", value: `$${(data.estimated_cost || 0).toFixed(4)}` },
  ];

  return (
    <div style={styles.summaryRow}>
      {cards.map((card) => (
        <div key={card.label} style={styles.summaryCard}>
          <div style={styles.summaryCardLabel}>{card.label}</div>
          <div style={styles.summaryCardValue}>{card.value}</div>
        </div>
      ))}
    </div>
  );
}

// ─── UsageChart ──────────────────────────────────────────────────────────────

function UsageChart({ data, loading, granularity }) {
  if (loading) {
    return <div style={styles.loadingText}>Loading chart...</div>;
  }

  const buckets = data?.buckets || [];

  if (buckets.length === 0) {
    return (
      <div style={styles.chartContainer}>
        <h3 style={styles.sectionTitle}>Token Consumption Over Time</h3>
        <div style={styles.emptyState}>No data available for the selected filters.</div>
      </div>
    );
  }

  const maxTokens = Math.max(...buckets.map((b) => b.total_tokens));

  return (
    <div style={styles.chartContainer}>
      <h3 style={styles.sectionTitle}>
        Token Consumption Over Time ({granularity})
      </h3>
      <div style={styles.chartArea}>
        <div style={styles.chartBars}>
          {buckets.map((bucket) => {
            const heightPercent = maxTokens > 0 ? (bucket.total_tokens / maxTokens) * 100 : 0;
            const inputPercent = bucket.total_tokens > 0
              ? (bucket.input_tokens / bucket.total_tokens) * heightPercent
              : 0;
            const outputPercent = heightPercent - inputPercent;

            return (
              <div key={bucket.period} style={styles.barColumn}>
                <div style={styles.barWrapper}>
                  <div
                    style={{
                      ...styles.barOutput,
                      height: `${outputPercent}%`,
                    }}
                    title={`Output: ${bucket.output_tokens.toLocaleString()}`}
                  />
                  <div
                    style={{
                      ...styles.barInput,
                      height: `${inputPercent}%`,
                    }}
                    title={`Input: ${bucket.input_tokens.toLocaleString()}`}
                  />
                </div>
                <div style={styles.barLabel}>{formatPeriodLabel(bucket.period, granularity)}</div>
              </div>
            );
          })}
        </div>
      </div>
      <div style={styles.chartLegend}>
        <span style={styles.legendItem}>
          <span style={{ ...styles.legendDot, backgroundColor: "#3b82f6" }} />
          Input Tokens
        </span>
        <span style={styles.legendItem}>
          <span style={{ ...styles.legendDot, backgroundColor: "#93c5fd" }} />
          Output Tokens
        </span>
      </div>
    </div>
  );
}

function formatPeriodLabel(period, granularity) {
  if (!period) return "";
  const parts = period.split("-");
  if (granularity === "month") {
    return `${parts[0]}-${parts[1]}`;
  }
  // day or week: show MM-DD
  return `${parts[1]}-${parts[2]}`;
}

// ─── UsageTable ──────────────────────────────────────────────────────────────

function UsageTable({ data, loading }) {
  if (loading) {
    return <div style={styles.loadingText}>Loading table...</div>;
  }

  const records = data?.data || [];

  if (records.length === 0) {
    return (
      <div style={styles.tableContainer}>
        <h3 style={styles.sectionTitle}>Usage Breakdown</h3>
        <div style={styles.emptyState}>No usage records found.</div>
      </div>
    );
  }

  return (
    <div style={styles.tableContainer}>
      <h3 style={styles.sectionTitle}>Usage Breakdown</h3>
      <div style={styles.tableWrapper}>
        <table style={styles.table}>
          <thead>
            <tr>
              <th style={styles.th}>Job ID</th>
              <th style={styles.th}>Model</th>
              <th style={styles.thRight}>Input Tokens</th>
              <th style={styles.thRight}>Output Tokens</th>
              <th style={styles.thRight}>Total Tokens</th>
              <th style={styles.thRight}>Est. Cost</th>
              <th style={styles.th}>Timestamp</th>
            </tr>
          </thead>
          <tbody>
            {records.map((record) => (
              <tr key={record.id} style={styles.tr}>
                <td style={styles.td}>{record.job_id}</td>
                <td style={styles.td}>{record.model_id}</td>
                <td style={styles.tdRight}>{record.input_tokens.toLocaleString()}</td>
                <td style={styles.tdRight}>{record.output_tokens.toLocaleString()}</td>
                <td style={styles.tdRight}>{record.total_tokens.toLocaleString()}</td>
                <td style={styles.tdRight}>${record.estimated_cost.toFixed(4)}</td>
                <td style={styles.td}>{formatTimestamp(record.timestamp)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data?.pagination && (
        <div style={styles.paginationInfo}>
          Showing {records.length} of {data.pagination.total} records (page {data.pagination.page})
        </div>
      )}
    </div>
  );
}

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

  // Summary cards
  summaryRow: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
    gap: 16,
  },
  summaryCard: {
    padding: 16,
    backgroundColor: "#fff",
    borderRadius: 8,
    border: "1px solid #e5e7eb",
  },
  summaryCardLabel: {
    fontSize: 12,
    fontWeight: 600,
    color: "#6b7280",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    marginBottom: 4,
  },
  summaryCardValue: {
    fontSize: 22,
    fontWeight: 700,
    color: "#111827",
  },

  // Chart
  chartContainer: {
    padding: 20,
    backgroundColor: "#fff",
    borderRadius: 8,
    border: "1px solid #e5e7eb",
  },
  sectionTitle: {
    margin: "0 0 16px 0",
    fontSize: 16,
    fontWeight: 600,
    color: "#111827",
  },
  chartArea: {
    height: 200,
    display: "flex",
    alignItems: "flex-end",
  },
  chartBars: {
    display: "flex",
    alignItems: "flex-end",
    gap: 4,
    width: "100%",
    height: "100%",
  },
  barColumn: {
    flex: 1,
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    height: "100%",
    minWidth: 0,
  },
  barWrapper: {
    flex: 1,
    width: "100%",
    maxWidth: 40,
    display: "flex",
    flexDirection: "column",
    justifyContent: "flex-end",
    alignItems: "stretch",
  },
  barInput: {
    backgroundColor: "#3b82f6",
    borderRadius: "0 0 2px 2px",
    minHeight: 0,
  },
  barOutput: {
    backgroundColor: "#93c5fd",
    borderRadius: "2px 2px 0 0",
    minHeight: 0,
  },
  barLabel: {
    fontSize: 10,
    color: "#6b7280",
    marginTop: 4,
    textAlign: "center",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    maxWidth: "100%",
  },
  chartLegend: {
    display: "flex",
    gap: 16,
    marginTop: 12,
    justifyContent: "center",
  },
  legendItem: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    fontSize: 12,
    color: "#6b7280",
  },
  legendDot: {
    display: "inline-block",
    width: 10,
    height: 10,
    borderRadius: 2,
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
  thRight: {
    textAlign: "right",
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
  tdRight: {
    padding: "10px 12px",
    color: "#374151",
    textAlign: "right",
    fontFamily: "monospace",
  },
  paginationInfo: {
    marginTop: 12,
    fontSize: 12,
    color: "#6b7280",
    textAlign: "right",
  },
};
