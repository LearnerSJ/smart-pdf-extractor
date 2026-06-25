import React from "react";
import { BrowserRouter, Routes, Route, Navigate, Link } from "react-router-dom";
import AppShell from "./components/AppShell";
import JobSubmissionScreen from "./screens/JobSubmissionScreen";
import JobQueueScreen from "./screens/JobQueueScreen";
import ResultsViewerScreen from "./screens/ResultsViewerScreen";
import FeedbackScreen from "./screens/FeedbackScreen";
import IntegrationGuideScreen from "./screens/IntegrationGuideScreen";
import DeliverySettings from "./DeliverySettings";
import RedactionSettings from "./RedactionSettings";

/**
 * Results landing — the "Results" LHS section with no job selected.
 * Routes to the last-viewed result (or most recent job); otherwise guides the
 * user to pick one from the Job Queue.
 */
function ResultsIndex() {
  const last = sessionStorage.getItem("last_result_job");
  const jobs = JSON.parse(sessionStorage.getItem("pdf_jobs") || "[]");
  const target = last || (jobs.length ? jobs[jobs.length - 1] : null);
  if (target) return <Navigate to={`/results/${target}`} replace />;
  return (
    <div style={{ textAlign: "center", padding: "var(--space-10)", color: "var(--color-text-muted)" }}>
      <h1 style={{ fontSize: "var(--text-xl)", fontWeight: 700, color: "var(--color-text-primary)", marginBottom: "var(--space-3)" }}>
        Results
      </h1>
      <p>No result selected. Open the <Link to="/queue">Job Queue</Link> and click “View Results”.</p>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppShell>
        <Routes>
          <Route path="/" element={<Navigate to="/submit" replace />} />
          <Route path="/submit" element={<JobSubmissionScreen />} />
          <Route path="/queue" element={<JobQueueScreen />} />
          <Route path="/results/:jobId" element={<ResultsViewerScreen />} />
          <Route path="/results" element={<ResultsIndex />} />
          <Route path="/feedback" element={<FeedbackScreen />} />
          <Route path="/integration" element={<IntegrationGuideScreen />} />
          <Route path="/settings/delivery" element={<DeliverySettings />} />
          <Route path="/settings/redaction" element={<RedactionSettings tenantId="demo-tenant" apiBaseUrl="" />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
  );
}
