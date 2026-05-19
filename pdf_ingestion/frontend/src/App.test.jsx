import React from "react";
import { render, screen, within, fireEvent, waitFor, act } from "@testing-library/react";
import { MemoryRouter, Routes, Route, Navigate } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import AppShell from "./components/AppShell";
import JobSubmissionScreen from "./screens/JobSubmissionScreen";
import JobQueueScreen from "./screens/JobQueueScreen";
import ResultsViewerScreen from "./screens/ResultsViewerScreen";
import FeedbackScreen from "./screens/FeedbackScreen";
import DeliverySettings from "./DeliverySettings";

// Mock fetch for screens that call APIs on mount
globalThis.fetch = vi.fn(() =>
  Promise.resolve({
    ok: true,
    json: () => Promise.resolve({ data: [] }),
  })
);

function renderWithRouter(initialRoute) {
  return render(
    <MemoryRouter initialEntries={[initialRoute]}>
      <AppShell>
        <Routes>
          <Route path="/" element={<Navigate to="/submit" replace />} />
          <Route path="/submit" element={<JobSubmissionScreen />} />
          <Route path="/queue" element={<JobQueueScreen />} />
          <Route path="/results/:jobId" element={<ResultsViewerScreen />} />
          <Route path="/results" element={<Navigate to="/queue" replace />} />
          <Route path="/feedback" element={<FeedbackScreen />} />
          <Route path="/settings/delivery" element={<DeliverySettings />} />
          <Route
            path="/settings/redaction"
            element={<div data-testid="redaction-settings">Redaction Settings</div>}
          />
        </Routes>
      </AppShell>
    </MemoryRouter>
  );
}

describe("App navigation wiring", () => {
  it("renders JobSubmissionScreen at /submit", () => {
    renderWithRouter("/submit");
    const main = document.querySelector("main");
    expect(within(main).getByText("Submit Extraction Job")).toBeInTheDocument();
  });

  it("redirects / to /submit", () => {
    renderWithRouter("/");
    const main = document.querySelector("main");
    expect(within(main).getByText("Submit Extraction Job")).toBeInTheDocument();
  });

  it("renders JobQueueScreen at /queue", () => {
    renderWithRouter("/queue");
    const main = document.querySelector("main");
    expect(within(main).getByText("Job Queue")).toBeInTheDocument();
  });

  it("redirects /results (no id) to /queue", () => {
    renderWithRouter("/results");
    const main = document.querySelector("main");
    // Should redirect to queue screen which shows "Job Queue" heading
    expect(within(main).getByText("Job Queue")).toBeInTheDocument();
  });

  it("renders ResultsViewerScreen at /results/:id", () => {
    renderWithRouter("/results/test-job-123");
    const main = document.querySelector("main");
    expect(main).toBeInTheDocument();
  });

  it("renders FeedbackScreen at /feedback", () => {
    renderWithRouter("/feedback");
    const main = document.querySelector("main");
    expect(within(main).getByText("Feedback & Corrections")).toBeInTheDocument();
  });

  it("renders DeliverySettings at /settings/delivery", () => {
    renderWithRouter("/settings/delivery");
    const main = document.querySelector("main");
    expect(main).toBeInTheDocument();
  });

  it("renders RedactionSettings at /settings/redaction", () => {
    renderWithRouter("/settings/redaction");
    expect(screen.getByTestId("redaction-settings")).toBeInTheDocument();
  });

  it("AppShell displays PDF Ingestion title", () => {
    renderWithRouter("/submit");
    expect(screen.getByText("PDF Ingestion")).toBeInTheDocument();
  });

  it("AppShell displays subtitle", () => {
    renderWithRouter("/submit");
    expect(screen.getByText("Document extraction for reconciliation")).toBeInTheDocument();
  });

  it("AppShell displays navigation links for all screens", () => {
    renderWithRouter("/submit");
    const nav = document.querySelector("nav");
    expect(within(nav).getByText("Submit Job")).toBeInTheDocument();
    expect(within(nav).getByText("Job Queue")).toBeInTheDocument();
    expect(within(nav).getByText("Feedback")).toBeInTheDocument();
    expect(within(nav).getByText("Integration")).toBeInTheDocument();
    expect(within(nav).getByText("Delivery")).toBeInTheDocument();
    expect(within(nav).getByText("Redaction")).toBeInTheDocument();
  });

  it("highlights active nav link for current route", () => {
    renderWithRouter("/submit");
    const nav = document.querySelector("nav");
    const submitLink = within(nav).getByText("Submit Job");
    // NavLink applies aria-current="page" when active
    expect(submitLink).toHaveAttribute("aria-current", "page");
  });

  it("highlights queue nav link when on /queue", () => {
    renderWithRouter("/queue");
    const nav = document.querySelector("nav");
    const queueLink = within(nav).getByText("Job Queue");
    expect(queueLink).toHaveAttribute("aria-current", "page");
  });

  it("navigates from submit to queue after job creation", async () => {
    // Mock fetch to return a job_id when POST /v1/extract is called
    globalThis.fetch.mockImplementation((url, opts) => {
      if (url === "/v1/extract" && opts?.method === "POST") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ data: { job_id: "nav-test-job-001" } }),
        });
      }
      // Default: return empty data for other calls (e.g. job queue polling)
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ data: [] }),
      });
    });

    // Track location changes
    let currentLocation;
    function LocationTracker() {
      const { useLocation } = require("react-router-dom");
      currentLocation = useLocation();
      return null;
    }

    render(
      <MemoryRouter initialEntries={["/submit"]}>
        <AppShell>
          <Routes>
            <Route path="/submit" element={<JobSubmissionScreen />} />
            <Route path="/queue" element={<JobQueueScreen />} />
            <Route path="/results/:jobId" element={<ResultsViewerScreen />} />
          </Routes>
        </AppShell>
        <LocationTracker />
      </MemoryRouter>
    );

    const main = document.querySelector("main");
    expect(within(main).getByText("Submit Extraction Job")).toBeInTheDocument();

    // Simulate selecting a PDF file
    const file = new File(["dummy pdf content"], "test.pdf", { type: "application/pdf" });
    const dropZone = main.querySelector("[style]"); // The drop zone div
    const fileInput = main.querySelector('input[type="file"]');

    await act(async () => {
      fireEvent.change(fileInput, { target: { files: [file] } });
    });

    // Click submit button
    const submitBtn = within(main).getByText("Submit for Extraction");
    await act(async () => {
      fireEvent.click(submitBtn);
    });

    // Wait for navigation to /queue
    await waitFor(() => {
      expect(currentLocation.pathname).toBe("/queue");
      expect(currentLocation.search).toContain("highlight=nav-test-job-001");
    });
  });

  it("navigates from queue row click to results", async () => {
    // Mock sessionStorage with a job
    const mockJob = {
      job_id: "queue-nav-test-123",
      filename: "report.pdf",
      status: "complete",
      schema_type: "bank_statement",
      created_at: "2024-01-01T00:00:00Z",
      overall_confidence: 0.95,
    };

    // Set up sessionStorage with a job ID
    sessionStorage.setItem("pdf_jobs", JSON.stringify(["queue-nav-test-123"]));

    globalThis.fetch.mockImplementation((url) => {
      if (url.includes("/v1/jobs/queue-nav-test-123")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ data: mockJob }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ data: [] }),
      });
    });

    // Track location changes
    let currentLocation;
    function LocationTracker() {
      const { useLocation } = require("react-router-dom");
      currentLocation = useLocation();
      return null;
    }

    render(
      <MemoryRouter initialEntries={["/queue"]}>
        <AppShell>
          <Routes>
            <Route path="/queue" element={<JobQueueScreen />} />
            <Route path="/results/:jobId" element={<ResultsViewerScreen />} />
          </Routes>
        </AppShell>
        <LocationTracker />
      </MemoryRouter>
    );

    // Wait for the job to appear in the table - the job_id prefix is rendered in monospace
    await waitFor(() => {
      expect(screen.getByText("queue-na")).toBeInTheDocument();
    });

    // Click the row (the table row containing the job)
    const row = screen.getByText("queue-na").closest("tr");
    await act(async () => {
      fireEvent.click(row);
    });

    // Verify navigation to results page
    await waitFor(() => {
      expect(currentLocation.pathname).toBe("/results/queue-nav-test-123");
    });

    // Clean up sessionStorage
    sessionStorage.removeItem("pdf_jobs");
  });
});
