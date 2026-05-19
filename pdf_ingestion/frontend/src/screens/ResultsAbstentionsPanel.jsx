import React from "react";
import AbstentionRow from "../components/AbstentionRow";

/**
 * Abstentions panel for the Results Viewer screen.
 * Lists all abstention entries using AbstentionRow component.
 * Displays a success message when there are no abstentions.
 *
 * Requirements: 7.1, 7.2, 7.3, 7.4
 */
export default function ResultsAbstentionsPanel({ abstentions = [] }) {
  if (abstentions.length === 0) {
    return <div style={styles.successPanel}>✓ Full extraction — no abstentions</div>;
  }

  return (
    <div style={styles.container}>
      {abstentions.map((a, i) => (
        <AbstentionRow
          key={i}
          fieldName={a.field || a.table_id}
          reasonCode={a.reason}
          detail={a.detail}
          vlmAttempted={a.vlm_attempted}
        />
      ))}
    </div>
  );
}

const styles = {
  container: {
    display: "flex",
    flexDirection: "column",
    gap: "var(--space-1)",
  },
  successPanel: {
    textAlign: "center",
    padding: "var(--space-8)",
    color: "var(--color-success)",
    fontWeight: 600,
  },
};
