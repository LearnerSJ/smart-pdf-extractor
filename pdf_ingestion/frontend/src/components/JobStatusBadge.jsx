import React from "react";

const STATUS_MAP = {
  queued: { label: "Queued", bg: "var(--color-slate)", color: "#fff" },
  processing: { label: "Processing", bg: "var(--color-info)", color: "#fff" },
  complete: { label: "Complete", bg: "var(--color-success)", color: "#fff" },
  failed: { label: "Failed", bg: "var(--color-error)", color: "#fff" },
  abstained: { label: "Abstained", bg: "var(--color-warning)", color: "#fff" },
  partial: { label: "Partial", bg: "var(--color-warning)", color: "#fff" },
  cancelled: { label: "Cancelled", bg: "var(--color-slate-light)", color: "#fff" },
};

export default function JobStatusBadge({ status }) {
  const config = STATUS_MAP[status] || { label: status || "Unknown", bg: "var(--color-slate)", color: "#fff" };

  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 8px",
        borderRadius: "10px",
        fontSize: "var(--text-xs)",
        fontWeight: 600,
        backgroundColor: config.bg,
        color: config.color,
        textTransform: "capitalize",
      }}
    >
      {config.label}
    </span>
  );
}
