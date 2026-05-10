import React, { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import DataTable from "../components/DataTable";
import JobStatusBadge from "../components/JobStatusBadge";
import SchemaTypeTag from "../components/SchemaTypeTag";
import ConfidenceBadge from "../components/ConfidenceBadge";
import MonospaceField from "../components/MonospaceField";

const API_KEY = "demo-key";

export default function JobQueueScreen() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const highlightId = searchParams.get("highlight");

  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);

  // Filters
  const [statusFilter, setStatusFilter] = useState("");

  // Poll for jobs from session storage
  useEffect(() => {
    const fetchJobs = async () => {
      const stored = JSON.parse(sessionStorage.getItem("pdf_jobs") || "[]");
      if (stored.length === 0) {
        setLoading(false);
        return;
      }

      const validIds = [];
      const results = await Promise.all(
        stored.map(async (id) => {
          try {
            const res = await fetch(`/v1/jobs/${id}`, {
              headers: { Authorization: `Bearer ${API_KEY}` },
            });
            if (res.ok) {
              const json = await res.json();
              const job = json.data || json;
              validIds.push(id);

              // Fetch progress for non-terminal jobs
              if (job.status === "processing") {
                try {
                  const progRes = await fetch(`/v1/jobs/${id}/progress`, {
                    headers: { Authorization: `Bearer ${API_KEY}` },
                  });
                  if (progRes.ok) {
                    const progData = await progRes.json();
                    job._progress = progData;
                  }
                } catch {}
              }
              return job;
            }
            // Job not found (server restarted) — don't include
          } catch {}
          return null;
        })
      );

      // Clean up stale job IDs from sessionStorage
      if (validIds.length !== stored.length) {
        sessionStorage.setItem("pdf_jobs", JSON.stringify(validIds));
      }

      setJobs(results.filter(Boolean));
      setLoading(false);
    };

    fetchJobs();
    const interval = setInterval(fetchJobs, 3000);
    return () => clearInterval(interval);
  }, []);

  // Filter logic
  const filteredJobs = jobs.filter((job) => {
    if (statusFilter && job.status !== statusFilter) return false;
    return true;
  });

  const handleCancel = async (e, jobId) => {
    e.stopPropagation();
    try {
      await fetch(`/v1/jobs/${jobId}/cancel`, {
        method: "POST",
        headers: { Authorization: `Bearer ${API_KEY}` },
      });
    } catch {}
  };

  const handleDelete = (e, jobId) => {
    e.stopPropagation();
    const stored = JSON.parse(sessionStorage.getItem("pdf_jobs") || "[]");
    const updated = stored.filter((id) => id !== jobId);
    sessionStorage.setItem("pdf_jobs", JSON.stringify(updated));
    setJobs(jobs.filter((j) => j.job_id !== jobId));
  };

  const formatETA = (seconds) => {
    if (seconds == null) return "";
    if (seconds < 60) return `~${Math.ceil(seconds)}s`;
    return `~${Math.floor(seconds / 60)}m ${Math.ceil(seconds % 60)}s`;
  };

  const columns = [
    {
      key: "filename",
      label: "Document",
      render: (val, row) => (
        <div style={{ display: "flex", flexDirection: "column" }}>
          <span style={{ fontWeight: 500, color: "var(--color-text-primary)" }}>{val || "Untitled"}</span>
          <span style={{ fontSize: "var(--text-xs)", color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}>{row.job_id?.slice(0, 8)}</span>
        </div>
      ),
    },
    {
      key: "status",
      label: "Status",
      render: (val, row) => (
        <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
          <JobStatusBadge status={val} />
          {val === "processing" && row._progress && (
            <span style={styles.progressText}>
              {row._progress.progress_percent}%
            </span>
          )}
        </div>
      ),
    },
    {
      key: "_progress",
      label: "Progress",
      render: (prog, row) => {
        if (row.status === "cancelled") return <span style={styles.cancelledText}>Cancelled</span>;
        if (row.status !== "processing" || !prog) {
          return row.status === "complete" || row.status === "partial" ? "✓ Done" : "—";
        }
        return (
          <div style={styles.progressCell}>
            <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
              <div style={{ ...styles.progressBar, flex: 1 }}>
                <div style={{ ...styles.progressFill, width: `${prog.progress_percent || 0}%` }} />
              </div>
              <button
                onClick={(e) => handleCancel(e, row.job_id)}
                style={styles.cancelBtn}
                title="Cancel job"
              >
                ✕
              </button>
            </div>
            <span style={styles.progressDetail}>
              {prog.pages_processed}/{prog.total_pages} pages
              {prog.estimated_remaining_seconds != null && ` · ${formatETA(prog.estimated_remaining_seconds)}`}
            </span>
          </div>
        );
      },
    },
    {
      key: "created_at",
      label: "Submitted",
      render: (val) => val ? new Date(val).toLocaleString() : "—",
    },
    {
      key: "_actions",
      label: "",
      align: "right",
      render: (_, row) => (
        <div style={styles.actionsCell}>
          {(row.status === "complete" || row.status === "partial") && (
            <button
              onClick={(e) => { e.stopPropagation(); navigate(`/results/${row.job_id}`); }}
              style={styles.viewBtn}
            >
              View Results
            </button>
          )}
          {row.status === "failed" && (
            <button
              onClick={(e) => { e.stopPropagation(); navigate(`/results/${row.job_id}`); }}
              style={styles.viewBtnMuted}
            >
              View Details
            </button>
          )}
          {row.status !== "processing" && (
            <button
              onClick={(e) => handleDelete(e, row.job_id)}
              style={styles.removeBtn}
            >
              Remove
            </button>
          )}
        </div>
      ),
    },
  ];

  return (
    <div>
      <div style={styles.header}>
        <h1 style={styles.title}>Job Queue</h1>
        <div style={styles.filters}>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} style={styles.filterSelect}>
            <option value="">All Statuses</option>
            <option value="processing">Processing</option>
            <option value="complete">Complete</option>
            <option value="partial">Partial</option>
            <option value="failed">Failed</option>
          </select>
        </div>
      </div>

      {loading ? (
        <p style={styles.loading}>Loading jobs...</p>
      ) : filteredJobs.length === 0 ? (
        <div style={styles.empty}>
          <p>No jobs yet. Submit a PDF to get started.</p>
        </div>
      ) : (
        <DataTable
          columns={columns}
          rows={filteredJobs}
          onRowClick={(row) => navigate(`/results/${row.job_id}`)}
        />
      )}
    </div>
  );
}

const styles = {
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "var(--space-5)",
  },
  title: {
    fontSize: "var(--text-xl)",
    fontWeight: 700,
    color: "var(--color-text-primary)",
  },
  filters: {
    display: "flex",
    gap: "var(--space-2)",
  },
  filterSelect: {
    padding: "var(--space-1) var(--space-3)",
    border: "1px solid var(--color-border)",
    borderRadius: "var(--border-radius-sm)",
    fontSize: "var(--text-sm)",
    backgroundColor: "#fff",
  },
  loading: {
    color: "var(--color-text-muted)",
    textAlign: "center",
    padding: "var(--space-10)",
  },
  empty: {
    textAlign: "center",
    padding: "var(--space-10)",
    color: "var(--color-text-muted)",
    backgroundColor: "#fff",
    borderRadius: "var(--border-radius)",
    border: "1px solid var(--color-border-light)",
  },
  progressText: {
    fontSize: "var(--text-xs)",
    color: "var(--color-text-muted)",
  },
  progressCell: {
    display: "flex",
    flexDirection: "column",
    gap: "2px",
    minWidth: 140,
  },
  progressBar: {
    height: 4,
    backgroundColor: "var(--color-border-light)",
    borderRadius: 2,
    overflow: "hidden",
  },
  progressFill: {
    height: "100%",
    backgroundColor: "var(--color-info)",
    borderRadius: 2,
    transition: "width 0.5s ease",
  },
  progressDetail: {
    fontSize: "var(--text-xs)",
    color: "var(--color-text-muted)",
  },
  cancelBtn: {
    width: 20,
    height: 20,
    padding: 0,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "transparent",
    border: "1px solid var(--color-border)",
    borderRadius: "50%",
    fontSize: "10px",
    color: "var(--color-text-muted)",
    cursor: "pointer",
    flexShrink: 0,
  },
  cancelledText: {
    fontSize: "var(--text-sm)",
    color: "var(--color-error)",
    fontWeight: 500,
  },
  viewBtn: {
    padding: "var(--space-1) var(--space-3)",
    backgroundColor: "var(--color-info)",
    color: "#fff",
    border: "none",
    borderRadius: "var(--border-radius-sm)",
    fontSize: "var(--text-xs)",
    fontWeight: 600,
    cursor: "pointer",
    whiteSpace: "nowrap",
    minWidth: 100,
    textAlign: "center",
  },
  viewBtnMuted: {
    padding: "var(--space-1) var(--space-3)",
    backgroundColor: "transparent",
    color: "var(--color-text-muted)",
    border: "1px solid var(--color-border)",
    borderRadius: "var(--border-radius-sm)",
    fontSize: "var(--text-xs)",
    fontWeight: 600,
    cursor: "pointer",
    whiteSpace: "nowrap",
    minWidth: 100,
    textAlign: "center",
  },
  actionsCell: {
    display: "flex",
    gap: "var(--space-3)",
    alignItems: "center",
    justifyContent: "flex-end",
  },
  removeBtn: {
    padding: 0,
    backgroundColor: "transparent",
    border: "none",
    fontSize: "var(--text-xs)",
    color: "var(--color-text-muted)",
    cursor: "pointer",
    textDecoration: "underline",
  },
};

