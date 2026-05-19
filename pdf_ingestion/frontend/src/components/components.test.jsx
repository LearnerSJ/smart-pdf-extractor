import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import ConfidenceBadge, { getConfidenceColour } from "./ConfidenceBadge";
import JobStatusBadge from "./JobStatusBadge";
import SchemaTypeTag from "./SchemaTypeTag";
import MonospaceField from "./MonospaceField";
import AbstentionRow from "./AbstentionRow";
import DataTable from "./DataTable";

describe("ConfidenceBadge", () => {
  it("renders value formatted to 2 decimal places", () => {
    render(<ConfidenceBadge value={0.95} />);
    expect(screen.getByText("0.95")).toBeInTheDocument();
  });

  it("renders dash for null value", () => {
    render(<ConfidenceBadge value={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("applies green colour for values >= 0.90", () => {
    expect(getConfidenceColour(0.95)).toBe("var(--color-success)");
    expect(getConfidenceColour(0.9)).toBe("var(--color-success)");
  });

  it("applies amber colour for values 0.70-0.89", () => {
    expect(getConfidenceColour(0.85)).toBe("var(--color-warning)");
    expect(getConfidenceColour(0.7)).toBe("var(--color-warning)");
  });

  it("applies red colour for values < 0.70", () => {
    expect(getConfidenceColour(0.5)).toBe("var(--color-error)");
    expect(getConfidenceColour(0.0)).toBe("var(--color-error)");
  });
});

describe("JobStatusBadge", () => {
  it("renders correct label for each status", () => {
    const { rerender } = render(<JobStatusBadge status="queued" />);
    expect(screen.getByText("Queued")).toBeInTheDocument();

    rerender(<JobStatusBadge status="processing" />);
    expect(screen.getByText("Processing")).toBeInTheDocument();

    rerender(<JobStatusBadge status="complete" />);
    expect(screen.getByText("Complete")).toBeInTheDocument();

    rerender(<JobStatusBadge status="failed" />);
    expect(screen.getByText("Failed")).toBeInTheDocument();

    rerender(<JobStatusBadge status="abstained" />);
    expect(screen.getByText("Abstained")).toBeInTheDocument();
  });

  it("handles unknown status gracefully", () => {
    render(<JobStatusBadge status="something_else" />);
    expect(screen.getByText("something_else")).toBeInTheDocument();
  });
});

describe("SchemaTypeTag", () => {
  it("renders formatted labels for known types", () => {
    const { rerender } = render(<SchemaTypeTag type="bank_statement" />);
    expect(screen.getByText("Bank Statement")).toBeInTheDocument();

    rerender(<SchemaTypeTag type="custody_statement" />);
    expect(screen.getByText("Custody Statement")).toBeInTheDocument();

    rerender(<SchemaTypeTag type="swift_confirm" />);
    expect(screen.getByText("SWIFT Confirm")).toBeInTheDocument();

    rerender(<SchemaTypeTag type="unknown" />);
    expect(screen.getByText("Unknown")).toBeInTheDocument();
  });

  it("falls back to raw type for unmapped values", () => {
    render(<SchemaTypeTag type="custom_type" />);
    expect(screen.getByText("custom_type")).toBeInTheDocument();
  });
});

describe("MonospaceField", () => {
  it("renders children text", () => {
    render(<MonospaceField>GB82WEST12345698765432</MonospaceField>);
    expect(screen.getByText("GB82WEST12345698765432")).toBeInTheDocument();
  });

  it("renders dash for empty/null children", () => {
    render(<MonospaceField>{null}</MonospaceField>);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

describe("AbstentionRow", () => {
  it("renders field name, reason code, and detail", () => {
    render(
      <AbstentionRow
        fieldName="account_number"
        reasonCode="FIELD_NOT_FOUND"
        detail="Could not locate field in document"
        vlmAttempted={true}
      />
    );
    expect(screen.getByText("account_number")).toBeInTheDocument();
    expect(screen.getByText("FIELD_NOT_FOUND")).toBeInTheDocument();
    expect(screen.getByText("Could not locate field in document")).toBeInTheDocument();
    expect(screen.getByText("VLM attempted")).toBeInTheDocument();
  });

  it("renders dash for missing field name", () => {
    render(<AbstentionRow reasonCode="TIMEOUT" vlmAttempted={false} />);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("TIMEOUT")).toBeInTheDocument();
  });
});

describe("DataTable", () => {
  const columns = [
    { key: "id", label: "ID" },
    { key: "name", label: "Name" },
  ];

  it("renders column headers", () => {
    render(<DataTable columns={columns} rows={[]} />);
    expect(screen.getByText("ID")).toBeInTheDocument();
    expect(screen.getByText("Name")).toBeInTheDocument();
  });

  it("renders 'No data' when rows are empty", () => {
    render(<DataTable columns={columns} rows={[]} />);
    expect(screen.getByText("No data")).toBeInTheDocument();
  });

  it("renders row data", () => {
    const rows = [
      { id: "job-001", name: "Test Job" },
      { id: "job-002", name: "Another Job" },
    ];
    render(<DataTable columns={columns} rows={rows} />);
    expect(screen.getByText("job-001")).toBeInTheDocument();
    expect(screen.getByText("Test Job")).toBeInTheDocument();
    expect(screen.getByText("job-002")).toBeInTheDocument();
  });

  it("supports custom render function", () => {
    const cols = [
      { key: "value", label: "Value", render: (v) => <strong>{v * 2}</strong> },
    ];
    render(<DataTable columns={cols} rows={[{ value: 5 }]} />);
    expect(screen.getByText("10")).toBeInTheDocument();
  });
});
