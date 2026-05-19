import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import ResultsAbstentionsPanel from "./ResultsAbstentionsPanel";

describe("ResultsAbstentionsPanel", () => {
  it("displays success message when abstentions array is empty", () => {
    render(<ResultsAbstentionsPanel abstentions={[]} />);
    expect(screen.getByText(/Full extraction — no abstentions/)).toBeInTheDocument();
  });

  it("displays success message when abstentions prop is undefined (defaults to empty)", () => {
    render(<ResultsAbstentionsPanel />);
    expect(screen.getByText(/Full extraction — no abstentions/)).toBeInTheDocument();
  });

  it("renders abstention entries using AbstentionRow component", () => {
    const abstentions = [
      { field: "account_number", reason: "FIELD_NOT_FOUND", detail: "Could not locate", vlm_attempted: true },
      { table_id: "transactions", reason: "TABLE_PARSE_ERROR", detail: "Malformed table", vlm_attempted: false },
    ];
    render(<ResultsAbstentionsPanel abstentions={abstentions} />);

    expect(screen.getByText("account_number")).toBeInTheDocument();
    expect(screen.getByText("FIELD_NOT_FOUND")).toBeInTheDocument();
    expect(screen.getByText("Could not locate")).toBeInTheDocument();
    expect(screen.getByText("VLM attempted")).toBeInTheDocument();

    expect(screen.getByText("transactions")).toBeInTheDocument();
    expect(screen.getByText("TABLE_PARSE_ERROR")).toBeInTheDocument();
    expect(screen.getByText("Malformed table")).toBeInTheDocument();
  });

  it("uses field name when available, falls back to table_id", () => {
    const abstentions = [
      { field: "iban", reason: "TIMEOUT", detail: "Timed out", vlm_attempted: false },
      { table_id: "positions", reason: "NO_DATA", detail: "Empty region", vlm_attempted: true },
    ];
    render(<ResultsAbstentionsPanel abstentions={abstentions} />);

    expect(screen.getByText("iban")).toBeInTheDocument();
    expect(screen.getByText("positions")).toBeInTheDocument();
  });

  it("does not show success message when abstentions exist", () => {
    const abstentions = [
      { field: "balance", reason: "LOW_CONFIDENCE", detail: "Below threshold", vlm_attempted: false },
    ];
    render(<ResultsAbstentionsPanel abstentions={abstentions} />);
    expect(screen.queryByText(/Full extraction — no abstentions/)).not.toBeInTheDocument();
  });
});
