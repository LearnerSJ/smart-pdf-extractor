import React, { useState } from "react";
import { useApi } from "../hooks/useApi";
import DataTable from "../components/DataTable";
import MonospaceField from "../components/MonospaceField";

export default function FeedbackScreen() {
  const { data: feedback, loading } = useApi("/v1/feedback");
  const entries = feedback || [];

  const handleExportCSV = () => {
    const headers = ["job_id", "field_name", "original_value", "corrected_value", "submitted_at"];
    const rows = entries.map((e) =>
      headers.map((h) => `"${String(e[h] || "").replace(/"/g, '""')}"`)
    );
    const csv = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "feedback-corrections.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  const columns = [
    { key: "job_id", label: "Job ID", render: (val) => <MonospaceField>{val?.slice(0, 8)}</MonospaceField> },
    { key: "field_name", label: "Field" },
    { key: "original_value", label: "Original" },
    { key: "corrected_value", label: "Corrected" },
    { key: "submitted_at", label: "Submitted", render: (val) => val ? new Date(val).toLocaleString() : "—" },
  ];

  return (
    <div>
      <div style={styles.header}>
        <h1 style={styles.title}>Feedback & Corrections</h1>
        <button onClick={handleExportCSV} style={styles.exportBtn} disabled={entries.length === 0}>
          ⬇ Export CSV
        </button>
      </div>

      {loading ? (
        <p style={styles.loading}>Loading...</p>
      ) : entries.length === 0 ? (
        <div style={styles.empty}>No corrections submitted yet.</div>
      ) : (
        <DataTable columns={columns} rows={entries} />
      )}
    </div>
  );
}

const styles = {
  header: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "var(--space-5)" },
  title: { fontSize: "var(--text-xl)", fontWeight: 700, color: "var(--color-text-primary)" },
  exportBtn: { padding: "var(--space-2) var(--space-4)", backgroundColor: "#fff", border: "1px solid var(--color-border)", borderRadius: "var(--border-radius-sm)", fontSize: "var(--text-sm)", fontWeight: 500, cursor: "pointer" },
  loading: { textAlign: "center", padding: "var(--space-10)", color: "var(--color-text-muted)" },
  empty: { textAlign: "center", padding: "var(--space-10)", color: "var(--color-text-muted)", backgroundColor: "#fff", borderRadius: "var(--border-radius)", border: "1px solid var(--color-border-light)" },
};
