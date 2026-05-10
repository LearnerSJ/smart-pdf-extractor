import React from "react";
import { NavLink, useLocation } from "react-router-dom";

const NAV_ITEMS = [
  { label: "Submit Job", path: "/submit" },
  { label: "Job Queue", path: "/queue" },
  { label: "Feedback", path: "/feedback" },
  { label: "Integration", path: "/settings/delivery" },
  { label: "Redaction", path: "/settings/redaction" },
];

export default function AppShell({ children }) {
  return (
    <div style={styles.container}>
      <aside style={styles.sidebar}>
        <div style={styles.brand}>
          <div style={styles.brandTitle}>Smart PDF</div>
          <div style={styles.brandSubtitle}>Document extraction for reconciliation</div>
        </div>
        <nav style={styles.nav}>
          {NAV_ITEMS.map((item, i) =>
            item.divider ? (
              <div key={i} style={styles.divider} />
            ) : (
              <NavLink
                key={item.path}
                to={item.path}
                style={({ isActive }) => ({
                  ...styles.navLink,
                  ...(isActive ? styles.navLinkActive : {}),
                })}
              >
                {item.label}
              </NavLink>
            )
          )}
        </nav>
      </aside>
      <main style={styles.main}>{children}</main>
    </div>
  );
}

const styles = {
  container: {
    display: "flex",
    minHeight: "100vh",
  },
  sidebar: {
    width: "var(--sidebar-width)",
    backgroundColor: "var(--color-primary)",
    color: "var(--color-text-inverse)",
    display: "flex",
    flexDirection: "column",
    position: "fixed",
    top: 0,
    left: 0,
    bottom: 0,
    zIndex: 100,
  },
  brand: {
    padding: "var(--space-5) var(--space-4)",
    borderBottom: "1px solid rgba(255,255,255,0.1)",
  },
  brandTitle: {
    fontSize: "var(--text-lg)",
    fontWeight: 700,
    marginBottom: "2px",
  },
  brandSubtitle: {
    fontSize: "var(--text-xs)",
    opacity: 0.6,
  },
  nav: {
    padding: "var(--space-3) 0",
    flex: 1,
  },
  navLink: {
    display: "flex",
    alignItems: "center",
    padding: "var(--space-2) var(--space-4)",
    color: "rgba(245, 245, 240, 0.7)",
    textDecoration: "none",
    fontSize: "var(--text-md)",
    transition: "all 150ms ease",
  },
  navLinkActive: {
    color: "#FFFFFF",
    backgroundColor: "rgba(255,255,255,0.08)",
    fontWeight: 600,
  },
  navIcon: {
    width: "20px",
    textAlign: "center",
    fontSize: "var(--text-md)",
  },
  divider: {
    height: "1px",
    backgroundColor: "rgba(255,255,255,0.1)",
    margin: "var(--space-2) var(--space-4)",
  },
  main: {
    marginLeft: "var(--sidebar-width)",
    flex: 1,
    padding: "var(--space-6)",
    minHeight: "100vh",
  },
};
