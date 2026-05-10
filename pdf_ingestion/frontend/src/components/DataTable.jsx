import React from "react";

/**
 * Generic compact data table with sticky header, horizontal scroll, and row click.
 *
 * @param {Array} columns - [{key, label, align?, render?}]
 * @param {Array} rows - array of row objects
 * @param {Function} onRowClick - optional (row) => void
 */
export default function DataTable({ columns, rows, onRowClick }) {
  return (
    <div style={styles.wrapper}>
      <table style={styles.table}>
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col.key} style={{ ...styles.th, textAlign: col.align || "left" }}>
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} style={styles.empty}>
                No data
              </td>
            </tr>
          ) : (
            rows.map((row, i) => (
              <tr
                key={i}
                onClick={() => onRowClick?.(row)}
                style={onRowClick ? styles.clickableRow : undefined}
              >
                {columns.map((col) => (
                  <td key={col.key} style={{ textAlign: col.align || "left" }}>
                    {col.render ? col.render(row[col.key], row) : (row[col.key] ?? "—")}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

const styles = {
  wrapper: {
    overflowX: "auto",
    border: "1px solid var(--color-border-light)",
    borderRadius: "var(--border-radius)",
    backgroundColor: "#fff",
  },
  table: {
    width: "100%",
    borderCollapse: "collapse",
    fontSize: "var(--text-base)",
  },
  th: {
    padding: "var(--space-2) var(--space-3)",
    fontWeight: 600,
    fontSize: "var(--text-sm)",
    textTransform: "uppercase",
    letterSpacing: "0.03em",
    color: "var(--color-text-secondary)",
    backgroundColor: "var(--color-surface)",
    borderBottom: "1px solid var(--color-border-light)",
    position: "sticky",
    top: 0,
    zIndex: 1,
  },
  clickableRow: {
    cursor: "pointer",
  },
  empty: {
    textAlign: "center",
    padding: "var(--space-6)",
    color: "var(--color-text-muted)",
  },
};
