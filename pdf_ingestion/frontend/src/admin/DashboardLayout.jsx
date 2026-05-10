import React from "react";
import { useAuth } from "./AuthContext.jsx";

/**
 * DashboardLayout — authenticated layout with sidebar navigation.
 *
 * Props:
 *   - activePage: string — current active page key
 *   - onNavigate: (page: string) => void — navigation handler
 *   - children: React node — content area
 */
export default function DashboardLayout({ activePage, onNavigate, children }) {
  const { user, logout } = useAuth();

  const navItems = [
    { key: "usage", label: "Usage", icon: "📊" },
    { key: "logs", label: "Logs", icon: "📋" },
    { key: "alerts", label: "Alerts", icon: "🔔" },
  ];

  // Users page only visible for admin role
  if (user && user.role === "admin") {
    navItems.push({ key: "users", label: "Users", icon: "👥" });
  }

  return (
    <div style={styles.container}>
      {/* Sidebar */}
      <aside style={styles.sidebar}>
        <div style={styles.sidebarHeader}>
          <h2 style={styles.sidebarTitle}>Admin</h2>
        </div>
        <nav style={styles.nav}>
          {navItems.map((item) => (
            <button
              key={item.key}
              onClick={() => onNavigate(item.key)}
              style={{
                ...styles.navButton,
                backgroundColor:
                  activePage === item.key ? "#2563eb" : "transparent",
                color: activePage === item.key ? "#fff" : "#d1d5db",
              }}
            >
              <span style={styles.navIcon}>{item.icon}</span>
              {item.label}
            </button>
          ))}
        </nav>
      </aside>

      {/* Main content area */}
      <div style={styles.main}>
        {/* Header */}
        <header style={styles.header}>
          <div style={styles.headerLeft}>
            <h1 style={styles.pageTitle}>
              {navItems.find((i) => i.key === activePage)?.label || "Dashboard"}
            </h1>
          </div>
          <div style={styles.headerRight}>
            <span style={styles.userInfo}>
              {user?.email}
              <span style={styles.roleBadge}>{user?.role}</span>
            </span>
            <button onClick={logout} style={styles.logoutButton}>
              Logout
            </button>
          </div>
        </header>

        {/* Content */}
        <main style={styles.content}>{children}</main>
      </div>
    </div>
  );
}

const styles = {
  container: {
    display: "flex",
    minHeight: "100vh",
    backgroundColor: "#f9fafb",
  },
  sidebar: {
    width: 220,
    backgroundColor: "#1f2937",
    display: "flex",
    flexDirection: "column",
    flexShrink: 0,
  },
  sidebarHeader: {
    padding: "20px 16px",
    borderBottom: "1px solid #374151",
  },
  sidebarTitle: {
    margin: 0,
    fontSize: 18,
    fontWeight: 700,
    color: "#fff",
  },
  nav: {
    display: "flex",
    flexDirection: "column",
    padding: "12px 8px",
    gap: 4,
  },
  navButton: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    padding: "10px 12px",
    border: "none",
    borderRadius: 6,
    cursor: "pointer",
    fontSize: 14,
    fontWeight: 500,
    textAlign: "left",
    transition: "background-color 0.15s ease",
  },
  navIcon: {
    fontSize: 16,
  },
  main: {
    flex: 1,
    display: "flex",
    flexDirection: "column",
    minWidth: 0,
  },
  header: {
    backgroundColor: "#fff",
    borderBottom: "1px solid #e5e7eb",
    padding: "16px 24px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
  },
  headerLeft: {},
  pageTitle: {
    margin: 0,
    fontSize: 20,
    fontWeight: 700,
    color: "#111827",
  },
  headerRight: {
    display: "flex",
    alignItems: "center",
    gap: 12,
  },
  userInfo: {
    fontSize: 13,
    color: "#6b7280",
    display: "flex",
    alignItems: "center",
    gap: 8,
  },
  roleBadge: {
    display: "inline-block",
    padding: "2px 8px",
    backgroundColor: "#e5e7eb",
    borderRadius: 4,
    fontSize: 11,
    fontWeight: 600,
    color: "#374151",
    textTransform: "uppercase",
  },
  logoutButton: {
    padding: "6px 14px",
    backgroundColor: "transparent",
    border: "1px solid #d1d5db",
    borderRadius: 6,
    cursor: "pointer",
    fontSize: 13,
    color: "#374151",
    fontWeight: 500,
    transition: "background-color 0.15s ease",
  },
  content: {
    flex: 1,
    padding: 24,
    overflowY: "auto",
  },
};
