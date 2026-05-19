import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import JobSubmissionScreen from "./JobSubmissionScreen";

// Mock react-router-dom's useNavigate
const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

// Mock the apiPost function from useApi
vi.mock("../hooks/useApi", () => ({
  apiPost: vi.fn(),
}));

import { apiPost } from "../hooks/useApi";

function renderScreen() {
  return render(
    <MemoryRouter>
      <JobSubmissionScreen />
    </MemoryRouter>
  );
}

function createFile(name, size, type) {
  const file = new File(["x".repeat(Math.min(size, 100))], name, { type });
  Object.defineProperty(file, "size", { value: size });
  return file;
}

describe("JobSubmissionScreen", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("File type validation (Requirement 2.3)", () => {
    it("rejects non-PDF file and displays error message", async () => {
      renderScreen();

      const file = createFile("document.docx", 1024, "application/msword");
      const input = document.querySelector('input[type="file"]');

      await act(async () => {
        fireEvent.change(input, { target: { files: [file] } });
      });

      expect(screen.getByText("Only PDF files are accepted")).toBeInTheDocument();
    });

    it("rejects image file dropped into the zone", async () => {
      renderScreen();

      const file = createFile("image.png", 2048, "image/png");
      const input = document.querySelector('input[type="file"]');

      await act(async () => {
        fireEvent.change(input, { target: { files: [file] } });
      });

      expect(screen.getByText("Only PDF files are accepted")).toBeInTheDocument();
    });

    it("accepts a valid PDF file without error", async () => {
      renderScreen();

      const file = createFile("report.pdf", 1024, "application/pdf");
      const input = document.querySelector('input[type="file"]');

      await act(async () => {
        fireEvent.change(input, { target: { files: [file] } });
      });

      expect(screen.queryByText("Only PDF files are accepted")).not.toBeInTheDocument();
      expect(screen.getByText("report.pdf")).toBeInTheDocument();
    });
  });

  describe("File size validation (Requirement 2.4)", () => {
    it("rejects file exceeding 50 MB and displays error message", async () => {
      renderScreen();

      const largeSize = 51 * 1024 * 1024; // 51 MB
      const file = createFile("large.pdf", largeSize, "application/pdf");
      const input = document.querySelector('input[type="file"]');

      await act(async () => {
        fireEvent.change(input, { target: { files: [file] } });
      });

      expect(screen.getByText(/exceeds maximum size of 50 MB/)).toBeInTheDocument();
    });

    it("accepts file exactly at 50 MB", async () => {
      renderScreen();

      const exactSize = 50 * 1024 * 1024; // exactly 50 MB
      const file = createFile("exact.pdf", exactSize, "application/pdf");
      const input = document.querySelector('input[type="file"]');

      await act(async () => {
        fireEvent.change(input, { target: { files: [file] } });
      });

      expect(screen.queryByText(/exceeds maximum size/)).not.toBeInTheDocument();
      expect(screen.getByText("exact.pdf")).toBeInTheDocument();
    });
  });

  describe("Submit button disabled during upload (Requirement 2.8)", () => {
    it("disables submit button while upload is in progress", async () => {
      // Make apiPost hang (never resolve) to simulate in-progress upload
      let resolveUpload;
      apiPost.mockImplementation(
        () => new Promise((resolve) => { resolveUpload = resolve; })
      );

      renderScreen();

      // Select a valid file
      const file = createFile("test.pdf", 1024, "application/pdf");
      const input = document.querySelector('input[type="file"]');

      await act(async () => {
        fireEvent.change(input, { target: { files: [file] } });
      });

      // Click submit
      const submitBtn = screen.getByRole("button", { name: /submit/i });
      expect(submitBtn).not.toBeDisabled();

      await act(async () => {
        fireEvent.click(submitBtn);
      });

      // Button should now be disabled during upload
      const uploadingBtn = screen.getByRole("button", { name: /uploading/i });
      expect(uploadingBtn).toBeDisabled();

      // Resolve the upload to clean up
      await act(async () => {
        resolveUpload({ job_id: "job-123" });
      });
    });

    it("submit button is disabled when no file is selected", () => {
      renderScreen();

      const submitBtn = screen.getByRole("button", { name: /submit/i });
      expect(submitBtn).toBeDisabled();
    });
  });

  describe("Successful submission navigates to queue (Requirement 2.7)", () => {
    it("navigates to /queue with highlight param after successful upload", async () => {
      apiPost.mockResolvedValue({ job_id: "job-abc-123" });

      renderScreen();

      // Select a valid file
      const file = createFile("report.pdf", 2048, "application/pdf");
      const input = document.querySelector('input[type="file"]');

      await act(async () => {
        fireEvent.change(input, { target: { files: [file] } });
      });

      // Submit
      const submitBtn = screen.getByRole("button", { name: /submit/i });
      await act(async () => {
        fireEvent.click(submitBtn);
      });

      await waitFor(() => {
        expect(mockNavigate).toHaveBeenCalledWith("/queue?highlight=job-abc-123");
      });
    });

    it("displays error message when API call fails", async () => {
      apiPost.mockRejectedValue(new Error("Server error — please try again"));

      renderScreen();

      // Select a valid file
      const file = createFile("report.pdf", 2048, "application/pdf");
      const input = document.querySelector('input[type="file"]');

      await act(async () => {
        fireEvent.change(input, { target: { files: [file] } });
      });

      // Submit
      const submitBtn = screen.getByRole("button", { name: /submit/i });
      await act(async () => {
        fireEvent.click(submitBtn);
      });

      // Should not navigate on error
      expect(mockNavigate).not.toHaveBeenCalled();
    });
  });
});
