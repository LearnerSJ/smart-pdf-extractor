import React from "react";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import FeedbackScreen from "./FeedbackScreen";

// Mock the useApi hook
vi.mock("../hooks/useApi", () => ({
  useApi: vi.fn(),
}));

import { useApi } from "../hooks/useApi";

const mockFeedbackEntries = [
  {
    job_id: "abc12345-6789-0000-1111-222233334444",
    field_name: "account_number",
    original_value: "123456",
    corrected_value: "654321",
    submitted_by: "user1@example.com",
    submitted_at: "2024-06-15T10:30:00Z",
  },
  {
    job_id: "def98765-4321-0000-5555-666677778888",
    field_name: "iban",
    original_value: "GB82WEST1234",
    corrected_value: "GB82WEST5678",
    submitted_by: "user2@example.com",
    submitted_at: "2024-07-20T14:00:00Z",
  },
  {
    job_id: "ghi55555-1111-2222-3333-444455556666",
    field_name: "bic",
    original_value: "DEUTDEFF",
    corrected_value: "COBADEFF",
    submitted_by: "user3@example.com",
    submitted_at: "2024-08-01T09:00:00Z",
  },
];

describe("FeedbackScreen", () => {
  beforeEach(() => {
    useApi.mockReturnValue({
      data: mockFeedbackEntries,
      loading: false,
      error: null,
      refetch: vi.fn(),
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("Table renders all columns", () => {
    it("renders all expected column headers", () => {
      render(<FeedbackScreen />);

      // "Job ID" appears both as a filter label and a table header, so scope to <th> elements
      const headers = screen.getAllByRole("columnheader");
      const headerTexts = headers.map((h) => h.textContent.trim());
      expect(headerTexts).toContain("Job ID");
      expect(headerTexts).toContain("Field");
      expect(headerTexts).toContain("Original");
      expect(headerTexts).toContain("Corrected");
      expect(headerTexts).toContain("Submitted By");
      expect(headerTexts).toContain("Submitted");
    });

    it("renders feedback entry data in the table", () => {
      render(<FeedbackScreen />);

      // Check field names are rendered
      expect(screen.getByText("account_number")).toBeInTheDocument();
      expect(screen.getByText("iban")).toBeInTheDocument();
      expect(screen.getByText("bic")).toBeInTheDocument();

      // Check original and corrected values
      expect(screen.getByText("123456")).toBeInTheDocument();
      expect(screen.getByText("654321")).toBeInTheDocument();
      expect(screen.getByText("GB82WEST1234")).toBeInTheDocument();
      expect(screen.getByText("GB82WEST5678")).toBeInTheDocument();

      // Check submitted_by
      expect(screen.getByText("user1@example.com")).toBeInTheDocument();
      expect(screen.getByText("user2@example.com")).toBeInTheDocument();
      expect(screen.getByText("user3@example.com")).toBeInTheDocument();
    });

    it("renders job_id using MonospaceField (truncated to 8 chars)", () => {
      render(<FeedbackScreen />);

      // Job IDs are truncated to first 8 characters — each is unique
      expect(screen.getByText("abc12345")).toBeInTheDocument();
      expect(screen.getByText("def98765")).toBeInTheDocument();
      expect(screen.getByText("ghi55555")).toBeInTheDocument();
    });

    it("shows empty state when no feedback entries exist", () => {
      useApi.mockReturnValue({
        data: [],
        loading: false,
        error: null,
        refetch: vi.fn(),
      });

      render(<FeedbackScreen />);
      expect(screen.getByText("No corrections submitted yet.")).toBeInTheDocument();
    });

    it("shows loading state", () => {
      useApi.mockReturnValue({
        data: null,
        loading: true,
        error: null,
        refetch: vi.fn(),
      });

      render(<FeedbackScreen />);
      expect(screen.getByText("Loading...")).toBeInTheDocument();
    });
  });

  describe("CSV export downloads file", () => {
    it("renders the export CSV button", () => {
      render(<FeedbackScreen />);
      expect(screen.getByText("⬇ Export CSV")).toBeInTheDocument();
    });

    it("triggers file download when export button is clicked", () => {
      // Mock URL.createObjectURL and URL.revokeObjectURL
      const mockUrl = "blob:http://localhost/mock-blob-url";
      const createObjectURLSpy = vi.fn(() => mockUrl);
      const revokeObjectURLSpy = vi.fn();
      global.URL.createObjectURL = createObjectURLSpy;
      global.URL.revokeObjectURL = revokeObjectURLSpy;

      // Track anchor element creation for download
      const clickSpy = vi.fn();
      const originalCreateElement = document.createElement;
      vi.spyOn(document, "createElement").mockImplementation(function (tag) {
        const el = originalCreateElement.call(document, tag);
        if (tag === "a") {
          Object.defineProperty(el, "click", { value: clickSpy, writable: true });
        }
        return el;
      });

      render(<FeedbackScreen />);

      const exportBtn = screen.getByText("⬇ Export CSV");
      fireEvent.click(exportBtn);

      // Verify blob was created and download triggered
      expect(createObjectURLSpy).toHaveBeenCalledWith(expect.any(Blob));
      expect(clickSpy).toHaveBeenCalled();
      expect(revokeObjectURLSpy).toHaveBeenCalledWith(mockUrl);
    });

    it("disables export button when no entries are visible", () => {
      useApi.mockReturnValue({
        data: [],
        loading: false,
        error: null,
        refetch: vi.fn(),
      });

      render(<FeedbackScreen />);
      const exportBtn = screen.getByText("⬇ Export CSV");
      expect(exportBtn).toBeDisabled();
    });

    it("enables export button when entries are visible", () => {
      render(<FeedbackScreen />);
      const exportBtn = screen.getByText("⬇ Export CSV");
      expect(exportBtn).not.toBeDisabled();
    });
  });

  describe("Filters reduce visible rows", () => {
    it("filters by job_id substring", () => {
      render(<FeedbackScreen />);

      const jobIdInput = screen.getByPlaceholderText("Filter by job ID...");
      fireEvent.change(jobIdInput, { target: { value: "abc12345" } });

      // Should show entries with job_id containing "abc12345"
      expect(screen.getByText("account_number")).toBeInTheDocument();
      // Should not show the other entries
      expect(screen.queryByText("iban")).not.toBeInTheDocument();
      expect(screen.queryByText("bic")).not.toBeInTheDocument();
    });

    it("filters by job_id case-insensitively", () => {
      render(<FeedbackScreen />);

      const jobIdInput = screen.getByPlaceholderText("Filter by job ID...");
      fireEvent.change(jobIdInput, { target: { value: "ABC12345" } });

      // Should still match (case-insensitive)
      expect(screen.getByText("account_number")).toBeInTheDocument();
      expect(screen.queryByText("iban")).not.toBeInTheDocument();
    });

    it("filters by date range (from)", () => {
      render(<FeedbackScreen />);

      // The date inputs don't have htmlFor, so query by type within the filter section
      const dateInputs = screen.getAllByDisplayValue("");
      // dateInputs: [0] = job_id text input (empty), [1] = from date, [2] = to date
      // But job_id has a placeholder, so let's use getAllByRole for date inputs
      const fromInput = dateInputs.filter(
        (el) => el.getAttribute("type") === "date"
      )[0];

      fireEvent.change(fromInput, { target: { value: "2024-07-01" } });

      // Only entries on or after 2024-07-01 should be visible
      expect(screen.queryByText("account_number")).not.toBeInTheDocument();
      expect(screen.getByText("iban")).toBeInTheDocument();
      expect(screen.getByText("bic")).toBeInTheDocument();
    });

    it("filters by date range (to)", () => {
      render(<FeedbackScreen />);

      const dateInputs = screen.getAllByDisplayValue("");
      const toInput = dateInputs.filter(
        (el) => el.getAttribute("type") === "date"
      )[1];

      fireEvent.change(toInput, { target: { value: "2024-06-30" } });

      // Only entries on or before 2024-06-30 should be visible
      expect(screen.getByText("account_number")).toBeInTheDocument();
      expect(screen.queryByText("iban")).not.toBeInTheDocument();
      expect(screen.queryByText("bic")).not.toBeInTheDocument();
    });

    it("applies combined filters (AND logic)", () => {
      render(<FeedbackScreen />);

      const jobIdInput = screen.getByPlaceholderText("Filter by job ID...");
      const dateInputs = screen.getAllByDisplayValue("");
      const fromInput = dateInputs.filter(
        (el) => el.getAttribute("type") === "date"
      )[0];

      // Filter by job_id "ghi55555" AND from date "2024-07-01"
      fireEvent.change(jobIdInput, { target: { value: "ghi55555" } });
      fireEvent.change(fromInput, { target: { value: "2024-07-01" } });

      // Only the "bic" entry matches both: job_id contains "ghi55555" AND submitted_at >= 2024-07-01
      expect(screen.queryByText("account_number")).not.toBeInTheDocument();
      expect(screen.queryByText("iban")).not.toBeInTheDocument();
      expect(screen.getByText("bic")).toBeInTheDocument();
    });

    it("shows 'no entries match' message when filters exclude all rows", () => {
      render(<FeedbackScreen />);

      const jobIdInput = screen.getByPlaceholderText("Filter by job ID...");
      fireEvent.change(jobIdInput, { target: { value: "nonexistent" } });

      expect(screen.getByText("No entries match the current filters.")).toBeInTheDocument();
    });
  });
});
