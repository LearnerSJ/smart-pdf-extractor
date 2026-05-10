import React, { useState } from "react";
import { AuthProvider, useAuth } from "./AuthContext.jsx";
import LoginPage from "./LoginPage.jsx";
import DashboardLayout from "./DashboardLayout.jsx";
import UsagePage from "./UsagePage.jsx";
import LogsPage from "./LogsPage.jsx";
import AlertsPage from "./AlertsPage.jsx";
import UsersPage from "./UsersPage.jsx";

/**
 * AdminApp — top-level admin app component.
 *
 * - Wraps everything in AuthProvider
 * - Shows LoginPage when not authenticated
 * - Shows DashboardLayout when authenticated
 * - Manages which page is active (usage, logs, alerts, users)
 */
export default function AdminApp({ apiBaseUrl = "" }) {
  return (
    <AuthProvider>
      <AdminAppInner apiBaseUrl={apiBaseUrl} />
    </AuthProvider>
  );
}

function AdminAppInner({ apiBaseUrl }) {
  const { isAuthenticated, login } = useAuth();
  const [activePage, setActivePage] = useState("usage");

  if (!isAuthenticated) {
    return <LoginPage apiBaseUrl={apiBaseUrl} onLogin={login} />;
  }

  return (
    <DashboardLayout activePage={activePage} onNavigate={setActivePage}>
      <PageContent activePage={activePage} apiBaseUrl={apiBaseUrl} />
    </DashboardLayout>
  );
}

/**
 * PageContent — renders the active page component.
 */
function PageContent({ activePage, apiBaseUrl }) {
  switch (activePage) {
    case "usage":
      return <UsagePage apiBaseUrl={apiBaseUrl} />;
    case "logs":
      return <LogsPage apiBaseUrl={apiBaseUrl} />;
    case "alerts":
      return <AlertsPage apiBaseUrl={apiBaseUrl} />;
    case "users":
      return <UsersPage apiBaseUrl={apiBaseUrl} />;
    default:
      return <PlaceholderPage title="Dashboard" description="Select a page from the sidebar." />;
  }
}

function PlaceholderPage({ title, description }) {
  return (
    <div style={styles.placeholder}>
      <h2 style={styles.placeholderTitle}>{title}</h2>
      <p style={styles.placeholderDesc}>{description}</p>
      <p style={styles.placeholderNote}>This page will be implemented in a subsequent task.</p>
    </div>
  );
}

const styles = {
  placeholder: {
    textAlign: "center",
    padding: "60px 24px",
    color: "#6b7280",
  },
  placeholderTitle: {
    fontSize: 24,
    fontWeight: 700,
    color: "#111827",
    margin: "0 0 8px 0",
  },
  placeholderDesc: {
    fontSize: 15,
    margin: "0 0 16px 0",
  },
  placeholderNote: {
    fontSize: 13,
    fontStyle: "italic",
    color: "#9ca3af",
  },
};
