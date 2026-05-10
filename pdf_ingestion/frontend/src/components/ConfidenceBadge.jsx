import React from "react";

/**
 * Colour-coded pill badge displaying a numeric confidence value (0.00–1.00).
 * Green ≥0.90, Amber 0.70–0.89, Red <0.70.
 */
export function getConfidenceColour(value) {
  if (value >= 0.9) return "var(--color-success)";
  if (value >= 0.7) return "var(--color-warning)";
  return "var(--color-error)";
}

export default function ConfidenceBadge({ value }) {
  if (value == null) return <span style={styles.empty}>—</span>;

  const colour = getConfidenceColour(value);

  return (
    <span
      style={{
        ...styles.badge,
        backgroundColor: colour,
      }}
    >
      {value.toFixed(2)}
    </span>
  );
}

const styles = {
  badge: {
    display: "inline-block",
    padding: "2px 8px",
    borderRadius: "10px",
    fontSize: "var(--text-xs)",
    fontWeight: 600,
    color: "#fff",
    lineHeight: 1.4,
  },
  empty: {
    color: "var(--color-text-muted)",
    fontSize: "var(--text-sm)",
  },
};
