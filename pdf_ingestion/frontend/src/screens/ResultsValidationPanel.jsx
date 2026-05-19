import React from "react";
import MonospaceField from "../components/MonospaceField";

/**
 * Groups validation failures by validator_name.
 * Returns an object where keys are validator names and values are arrays of failures.
 *
 * Exported for property-based testing (Property 4: Validation failure grouping integrity).
 *
 * @param {Array} failures - Array of failure objects with validator_name, field_name, error_code, detail
 * @returns {Object} - Object mapping validator_name to array of failures
 */
export function groupByValidator(failures) {
  const grouped = Object.create(null);
  for (const failure of failures) {
    const key = failure.validator_name || "unknown";
    if (!grouped[key]) {
      grouped[key] = [];
    }
    grouped[key].push(failure);
  }
  return grouped;
}

/**
 * Validation checks panel for the Results Viewer screen.
 * Displays validation results with pass/fail indicator.
 * When all pass: shows success indicator with summary message.
 * When failures exist: groups by validator_name, displays each group with
 * validator label, failure count, and individual failure details.
 *
 * Requirements: 8.1, 8.2, 8.3, 8.4
 */
export default function ResultsValidationPanel({ failures = [] }) {
  if (failures.length === 0) {
    return (
      <div style={styles.successPanel}>
        <span style={styles.successIcon}>✓</span>
        All validation checks passed
      </div>
    );
  }

  const grouped = groupByValidator(failures);

  return (
    <div style={styles.container}>
      <div style={styles.summaryBanner}>
        {failures.length} validation issue{failures.length !== 1 ? "s" : ""}
      </div>
      {Object.entries(grouped).map(([validatorName, items]) => (
        <div key={validatorName} style={styles.group}>
          <div style={styles.groupHeader}>
            <span style={styles.groupLabel}>
              {validatorName.replace(/^validate_/, "").replace(/_/g, " ")}
            </span>
            <span style={styles.failureCount}>{items.length}</span>
          </div>
          <div style={styles.groupBody}>
            {items.map((item, i) => (
              <div key={i} style={styles.failureItem}>
                {item.field_name && (
                  <MonospaceField>{item.field_name}</MonospaceField>
                )}
                {item.error_code && (
                  <span style={styles.errorCode}>{item.error_code}</span>
                )}
                <span style={styles.detail}>{item.detail}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * Returns the total failure count for use as a badge on the tab header.
 * @param {Array} failures
 * @returns {number|null} - Count or null if no failures
 */
export function getValidationBadgeCount(failures) {
  return failures.length > 0 ? failures.length : null;
}

const styles = {
  container: {
    display: "flex",
    flexDirection: "column",
    gap: "var(--space-3)",
  },
  successPanel: {
    textAlign: "center",
    padding: "var(--space-8)",
    color: "var(--color-success)",
    fontWeight: 600,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "var(--space-2)",
  },
  successIcon: {
    fontSize: "var(--text-lg)",
  },
  summaryBanner: {
    padding: "var(--space-2) var(--space-3)",
    backgroundColor: "rgba(231, 76, 60, 0.08)",
    borderRadius: "var(--border-radius-sm)",
    color: "var(--color-error)",
    fontSize: "var(--text-sm)",
    fontWeight: 500,
  },
  group: {
    backgroundColor: "#fff",
    border: "1px solid var(--color-border-light)",
    borderRadius: "var(--border-radius)",
    overflow: "hidden",
  },
  groupHeader: {
    padding: "var(--space-2) var(--space-3)",
    fontWeight: 600,
    fontSize: "var(--text-sm)",
    textTransform: "capitalize",
    borderBottom: "1px solid var(--color-border-light)",
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    backgroundColor: "var(--color-surface)",
  },
  groupLabel: {
    color: "var(--color-text-primary)",
  },
  failureCount: {
    fontSize: "var(--text-xs)",
    backgroundColor: "var(--color-error)",
    color: "#fff",
    padding: "1px 6px",
    borderRadius: "8px",
    fontWeight: 600,
  },
  groupBody: {
    display: "flex",
    flexDirection: "column",
  },
  failureItem: {
    padding: "var(--space-2) var(--space-3)",
    fontSize: "var(--text-sm)",
    borderBottom: "1px solid var(--color-border-light)",
    display: "flex",
    gap: "var(--space-2)",
    alignItems: "baseline",
  },
  errorCode: {
    fontSize: "var(--text-xs)",
    color: "var(--color-error)",
    fontWeight: 500,
    backgroundColor: "rgba(231, 76, 60, 0.08)",
    padding: "1px 4px",
    borderRadius: "3px",
    whiteSpace: "nowrap",
  },
  detail: {
    color: "var(--color-text-secondary)",
    fontSize: "var(--text-xs)",
    flex: 1,
  },
};
