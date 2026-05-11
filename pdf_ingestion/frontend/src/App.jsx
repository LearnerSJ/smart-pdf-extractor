import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import AppShell from "./components/AppShell";
import JobSubmissionScreen from "./screens/JobSubmissionScreen";
import JobQueueScreen from "./screens/JobQueueScreen";
import ResultsViewerScreen from "./screens/ResultsViewerScreen";
import FeedbackScreen from "./screens/FeedbackScreen";
import IntegrationGuideScreen from "./screens/IntegrationGuideScreen";
import ComparisonScreen from "./screens/ComparisonScreen";
import DeliverySettings from "./DeliverySettings";
import RedactionSettings from "../RedactionSettings";

export default function App() {
  return (
    <BrowserRouter>
      <AppShell>
        <Routes>
          <Route path="/" element={<Navigate to="/submit" replace />} />
          <Route path="/submit" element={<JobSubmissionScreen />} />
          <Route path="/queue" element={<JobQueueScreen />} />
          <Route path="/results/:jobId" element={<ResultsViewerScreen />} />
          <Route path="/results" element={<Navigate to="/queue" replace />} />
          <Route path="/feedback" element={<FeedbackScreen />} />
          <Route path="/integration" element={<IntegrationGuideScreen />} />
          <Route path="/compare" element={<ComparisonScreen />} />
          <Route path="/settings/delivery" element={<DeliverySettings />} />
          <Route path="/settings/redaction" element={<RedactionSettings tenantId="demo-tenant" apiBaseUrl="" />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
  );
}
