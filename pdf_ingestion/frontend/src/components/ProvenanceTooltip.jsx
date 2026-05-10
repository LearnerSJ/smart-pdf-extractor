import React, { useState } from "react";

/**
 * Hover-triggered tooltip showing provenance details for a field.
 */
export default function ProvenanceTooltip({ page, bbox, sourceRail, rule, children }) {
  const [show, setShow] = useState(false);

  return (
    <span
      style={styles.wrapper}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      {children || <span style={styles.trigger}>⊙</span>}
      {show && (
        <div style={styles.tooltip}>
          <div><strong>Page:</strong> {page}</div>
          <div><strong>BBox:</strong> <span style={styles.mono}>{(bbox || []).join(", ")}</span></div>
          <div><strong>Source:</strong> {sourceRail}</div>
          <div><strong>Rule:</strong> {rule}</div>
        </div>
      )}
    </span>
  );
}

const styles = {
  wrapper: {
    position: "relative",
    display: "inline-block",
    cursor: "help",
  },
  trigger: {
    color: "var(--color-slate-light)",
    fontSize: "var(--text-sm)",
  },
  tooltip: {
    position: "absolute",
    bottom: "100%",
    left: "50%",
    transform: "translateX(-50%)",
    backgroundColor: "var(--color-primary)",
    color: "var(--color-text-inverse)",
    padding: "var(--space-2) var(--space-3)",
    borderRadius: "var(--border-radius-sm)",
    fontSize: "var(--text-xs)",
    whiteSpace: "nowrap",
    zIndex: 1000,
    boxShadow: "var(--shadow-md)",
    marginBottom: "4px",
    lineHeight: 1.6,
  },
  mono: {
    fontFamily: "var(--font-mono)",
  },
};
