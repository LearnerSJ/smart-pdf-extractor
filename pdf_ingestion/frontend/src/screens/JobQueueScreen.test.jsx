import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import JobQueueScreen from "./JobQueueScreen";

// Mock navigate
const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

// Helper to render with router context
function renderWithRouter(ui, { route = "/queue" } = {}) {
  return render(<MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>);
}

// Sample job data
const mockJobs = [
  {
    job_id: "job-001-abc",
    filename: "invoice.pdf",
    status: "complete",
    created_at: "2024-01-15T10:00:00Z",
    overall_confidence: 0.95,
  },
  {
    job_id: "job-002-def",
    filename: "statement.pdf",
    status: "processing",
    created_at: "2024-01-15T11:00:00Z",
    overall_confidence: null,
  },
  {
    job_id: "job-003-ghi",
    filename: "receipt.pdf",
    status: "failed",
    created_at: "2024-01-15T12:00:00Z",
    overall_confidence: null,
  },
];

function mockFetchForJobs(jobs) {
  return vi.fn((url) => {
    const job = jobs.find((j) => url.includes(j.job_id));
    if (job && !url.includes("/progress") && !url.includes("/cancel")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ data: job }),
      });
    }
    if (url.includes("/progress")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            progress_percent: 50,
            pages_processed: 2,
            total_pages: 4,
            estimated_remaining_seconds: 10,
          }),
      });
    }
    return Promise.resolve({ ok: false, status: 404 });
  });
}

describe("JobQueueScreen", () => {
  beforeEach(() => {
    mockNavigate.mockClear();
    // Set up sessionStorage with job IDs
    sessionStorage.setItem(
      "pdf_jobs",
      JSON.stringify(mockJobs.map((j) => j.job_id))
    );
    global.fetch = mockFetchForJobs(mockJobs);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    sessionStorage.clear();
  });

  describe("Table renders all columns with correct components", () => {
    it("renders the Document column with filename and job_id", async () => {
      renderWithRouter(<JobQueueScreen />);

      await waitFor(() => {
        expect(screen.getByText("invoice.pdf")).toBeInTheDocument();
      });

      // Job ID is rendered (first 8 chars) in monospace
      expect(screen.getByText("job-001-")).toBeInTheDocument();
    });

    it("renders the Status column with JobStatusBadge", async () => {
      renderWithRouter(<JobQueueScreen />);

      await waitFor(() => {
        expect(screen.getByText("Complete")).toBeInTheDocument();
      });

      // "Processing" and "Failed" appear both in the filter dropdown and as badges
      // Use getAllByText and verify at least one is a badge (span element)
      const processingElements = screen.getAllByText("Processing");
      expect(processingElements.length).toBeGreaterThanOrEqual(2); // option + badge
      const processingBadge = processingElements.find(
        (el) => el.tagName === "SPAN"
      );
      expect(processingBadge).toBeInTheDocument();

      const failedElements = screen.getAllByText("Failed");
      expect(failedElements.length).toBeGreaterThanOrEqual(2); // option + badge
      const failedBadge = failedElements.find((el) => el.tagName === "SPAN");
      expect(failedBadge).toBeInTheDocument();
    });

    it("renders the Submitted column with formatted dates", async () => {
      renderWithRouter(<JobQueueScreen />);

      await waitFor(() => {
        expect(screen.getByText("invoice.pdf")).toBeInTheDocument();
      });

      // Dates should be rendered (locale-dependent format)
      const cells = screen.getAllByRole("cell");
      const submittedCells = cells.filter(
        (cell) => cell.textContent && cell.textContent.includes("2024")
      );
      expect(submittedCells.length).toBeGreaterThan(0);
    });

    it("renders column headers", async () => {
      renderWithRouter(<JobQueueScreen />);

      await waitFor(() => {
        expect(screen.getByText("Document")).toBeInTheDocument();
      });

      expect(screen.getByText("Status")).toBeInTheDocument();
      expect(screen.getByText("Progress")).toBeInTheDocument();
      expect(screen.getByText("Submitted")).toBeInTheDocument();
    });
  });

  describe("Filter application reduces visible rows", () => {
    it("shows all jobs when no filter is applied", async () => {
      renderWithRouter(<JobQueueScreen />);

      await waitFor(() => {
        expect(screen.getByText("invoice.pdf")).toBeInTheDocument();
      });

      expect(screen.getByText("statement.pdf")).toBeInTheDocument();
      expect(screen.getByText("receipt.pdf")).toBeInTheDocument();
    });

    it("filters jobs by status when a status filter is selected", async () => {
      renderWithRouter(<JobQueueScreen />);

      await waitFor(() => {
        expect(screen.getByText("invoice.pdf")).toBeInTheDocument();
      });

      // Select "Complete" status filter
      const select = screen.getByRole("combobox");
      fireEvent.change(select, { target: { value: "complete" } });

      // Only the complete job should be visible
      expect(screen.getByText("invoice.pdf")).toBeInTheDocument();
      expect(screen.queryByText("statement.pdf")).not.toBeInTheDocument();
      expect(screen.queryByText("receipt.pdf")).not.toBeInTheDocument();
    });

    it("shows empty state when filter matches no jobs", async () => {
      // Only have a complete job, filter by processing
      const limitedJobs = [mockJobs[0]]; // only complete
      sessionStorage.setItem(
        "pdf_jobs",
        JSON.stringify(limitedJobs.map((j) => j.job_id))
      );
      global.fetch = mockFetchForJobs(limitedJobs);

      renderWithRouter(<JobQueueScreen />);

      await waitFor(() => {
        expect(screen.getByText("invoice.pdf")).toBeInTheDocument();
      });

      // Select "Processing" filter - no jobs match
      const select = screen.getByRole("combobox");
      fireEvent.change(select, { target: { value: "processing" } });

      expect(screen.queryByText("invoice.pdf")).not.toBeInTheDocument();
      expect(
        screen.getByText("No jobs yet. Submit a PDF to get started.")
      ).toBeInTheDocument();
    });
  });

  describe("Row click navigates to results", () => {
    it("navigates to /results/{job_id} when a row is clicked", async () => {
      renderWithRouter(<JobQueueScreen />);

      await waitFor(() => {
        expect(screen.getByText("invoice.pdf")).toBeInTheDocument();
      });

      // Click the row containing invoice.pdf
      const row = screen.getByText("invoice.pdf").closest("tr");
      fireEvent.click(row);

      expect(mockNavigate).toHaveBeenCalledWith("/results/job-001-abc");
    });

    it("navigates via View Results button for complete jobs", async () => {
      renderWithRouter(<JobQueueScreen />);

      await waitFor(() => {
        expect(screen.getByText("View Results")).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText("View Results"));

      expect(mockNavigate).toHaveBeenCalledWith("/results/job-001-abc");
    });
  });

  describe("Polling stops for terminal statuses", () => {
    it("does not fetch progress for terminal status jobs", async () => {
      // All jobs are terminal (complete/failed)
      const terminalJobs = [
        { ...mockJobs[0], status: "complete" },
        { ...mockJobs[2], status: "failed" },
      ];
      sessionStorage.setItem(
        "pdf_jobs",
        JSON.stringify(terminalJobs.map((j) => j.job_id))
      );
      global.fetch = mockFetchForJobs(terminalJobs);

      renderWithRouter(<JobQueueScreen />);

      await waitFor(() => {
        expect(screen.getByText("invoice.pdf")).toBeInTheDocument();
      });

      // No progress endpoint should have been called for terminal jobs
      const progressCalls = global.fetch.mock.calls.filter((call) =>
        call[0].includes("/progress")
      );
      expect(progressCalls.length).toBe(0);
    });

    it("fetches progress only for processing jobs", async () => {
      renderWithRouter(<JobQueueScreen />);

      await waitFor(() => {
        expect(screen.getByText("invoice.pdf")).toBeInTheDocument();
      });

      // Only job-002-def is processing, so only it should have progress fetched
      const progressCalls = global.fetch.mock.calls.filter((call) =>
        call[0].includes("/progress")
      );
      expect(progressCalls.length).toBe(1);
      expect(progressCalls[0][0]).toContain("job-002-def");
    });

    it("sets up polling interval for job updates", async () => {
      vi.useFakeTimers();
      // Use a fetch that resolves immediately with fake timers
      let fetchCallCount = 0;
      global.fetch = vi.fn((url) => {
        fetchCallCount++;
        const job = mockJobs.find((j) => url.includes(j.job_id));
        if (job && !url.includes("/progress") && !url.includes("/cancel")) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ data: job }),
          });
        }
        if (url.includes("/progress")) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                progress_percent: 50,
                pages_processed: 2,
                total_pages: 4,
                estimated_remaining_seconds: 10,
              }),
          });
        }
        return Promise.resolve({ ok: false, status: 404 });
      });

      renderWithRouter(<JobQueueScreen />);

      // Flush initial fetch
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });

      const initialCallCount = global.fetch.mock.calls.length;

      // Advance past the polling interval (3000ms in the component)
      await act(async () => {
        await vi.advanceTimersByTimeAsync(3100);
      });

      // Should have made additional fetch calls for polling
      expect(global.fetch.mock.calls.length).toBeGreaterThan(initialCallCount);

      vi.useRealTimers();
    });
  });

  describe("Loading and empty states", () => {
    it("shows empty state when no jobs exist", async () => {
      sessionStorage.setItem("pdf_jobs", JSON.stringify([]));

      renderWithRouter(<JobQueueScreen />);

      await waitFor(() => {
        expect(
          screen.getByText("No jobs yet. Submit a PDF to get started.")
        ).toBeInTheDocument();
      });
    });
  });
});
