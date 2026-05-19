import React, { useState, useMemo } from "react";
import { useApi } from "../hooks/useApi";
import DataTable from "../components/DataTable";
import MonospaceField from "../components/MonospaceField";
import { exportCSV } from "../utils/csvExport";

export default function FeedbackScreen() {
  const { data: feedback, loading } = useApi("/v1/feedback");
  const entries = feedback || [];

  // Filter state
  const [jobIdFilter, setJobIdFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  // Apply filters
  const filteredEntries = useMemo(() => {
    return entries.filter((entry) => {
      // Job ID filter (case-insensitive substring match)
      if (jobIdFilter.trim()) {
        const id = (entry.job_id || "").toLowerCase();
        if (!id.includes(jobIdFilter.trim().toLowerCase())) {
          return false;
        }
      }
      // Date range filter on submitted_at
      if (dateFrom) {
        const entryDate = entry.submitted_at ? new Date(entry.submitted_at) : null;
        if (!entryDate || entryDate < new Date(dateFrom)) {
          return false;
        }
      }
      if (dateTo) {
        const entryDate = entry.submitted_at ? new Date(entry.submitted_at) : null;
        // Include the entire "to" day
        const toEnd = new Date(dateTo);
        toEnd.setHours(23, 59, 59, 999);
        if (!entryDate || entryDate > toEnd) {
          return false;
        }
      }
      return true;
    });
  }, [entries, jobIdFilter, dateFrom, dateTo]);

  const handleExportCSV = () => {
    const csv = exportCSV(filteredEntries);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "feedback-corrections.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  const columns = [
    {
      key: "job_id",
      label: "Job ID",
      render: (val) => <MonospaceField>{val?.slice(0, 8)}</MonospaceField>,
    },
    { key: "field_name", label: "Field" },
    { key: "original_value", label: "Original" },
    { key: "corrected_value", label: "Corrected" },
    { key: "submitted_by", label: "Submitted By" },
    {
      key: "submitted_at",
      label: "Submitted",
      render: (val) => (val ? new Date(val).toLocaleString() : "—"),
    },
  ];

  return (
    <div>
      <div style={styles.header}>
        <h1 style={styles.title}>Feedback & Corrections</h1>
        <button
          onClick={handleExportCSV}
          style={styles.exportBtn}
          disabled={filteredEntries.length === 0}
        >
          ⬇ Export CSV
        </button>
      </div>

      {/* Filter controls */}
      <div style={styles.filters}>
        <div style={styles.filterGroup}>
          <label style={styles.filterLabel}>Job ID</label>
          <input
            type="text"
            placeholder="Filter by job ID..."
            value={jobIdFilter}
            onChange={(e) => setJobIdFilter(e.target.value)}
            style={styles.filterInput}
          />
        </div>
        <div style={styles.filterGroup}>
          <label style={styles.filterLabel}>From</label>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            style={styles.filterInput}
          />
        </div>
        <div style={styles.filterGroup}>
          <label style={styles.filterLabel}>To</label>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            style={styles.filterInput}
          />
        </div>
      </div>

      {loading ? (
        <p style={styles.loading}>Loading...</p>
      ) : filteredEntries.length === 0 ? (
        <div style={styles.empty}>
          {entries.length === 0
            ? "No corrections submitted yet."
            : "No entries match the current filters."}
        </div>
      ) : (
        <DataTable columns={columns} rows={filteredEntries} />
      )}
    </div>
  );
}

const styles = {
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "var(--space-4)",
  },
  title: {
    fontSize: "var(--text-xl)",
    fontWeight: 700,
    color: "var(--color-text-primary)",
  },
  exportBtn: {
    padding: "var(--space-2) var(--space-4)",
    backgroundColor: "#fff",
    border: "1px solid var(--color-border)",
    borderRadius: "var(--border-radius-sm)",
    fontSize: "var(--text-sm)",
    fontWeight: 500,
    cursor: "pointer",
  },
  filters: {
    display: "flex",
    gap: "var(--space-4)",
    marginBottom: "var(--space-4)",
    flexWrap: "wrap",
    alignItems: "flex-end",
  },
  filterGroup: {
    display: "flex",
    flexDirection: "column",
    gap: "var(--space-1)",
  },
  filterLabel: {
    fontSize: "var(--text-sm)",
    fontWeight: 500,
    color: "var(--color-text-secondary)",
  },
  filterInput: {
    padding: "var(--space-2) var(--space-3)",
    border: "1px solid var(--color-border)",
    borderRadius: "var(--border-radius-sm)",
    fontSize: "var(--text-base)",
    minWidth: "160px",
  },
  loading: {
    textAlign: "center",
    padding: "var(--space-10)",
    color: "var(--color-text-muted)",
  },
  empty: {
    textAlign: "center",
    padding: "var(--space-10)",
    color: "var(--color-text-muted)",
    backgroundColor: "#fff",
    borderRadius: "var(--border-radius)",
    border: "1px solid var(--color-border-light)",
  },
};
