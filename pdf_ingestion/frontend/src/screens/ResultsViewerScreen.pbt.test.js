import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { isFinancialIdentifier } from "./ResultsViewerScreen";

/**
 * Property 6: Financial identifier monospace rendering
 *
 * For any field whose name matches a financial identifier pattern
 * (iban, isin, bic, swift_code, account_number, doc_hash),
 * the Results Viewer SHALL render its value using the MonospaceField component.
 *
 * This test validates the pure function `isFinancialIdentifier(fieldName)` which
 * determines whether a field should be rendered in monospace.
 *
 * **Validates: Requirements 5.3**
 */
describe("Feature: operational-frontend-redesign, Property 6: Financial identifier monospace rendering", () => {
  // The known set of financial identifier field names
  const KNOWN_IDENTIFIERS = ["iban", "isin", "bic", "swift_code", "account_number", "doc_hash"];

  // Generator for known financial identifier names
  const knownIdentifierArb = fc.constantFrom(...KNOWN_IDENTIFIERS);

  // Generator for non-identifier field names that are guaranteed not to be in the known set
  const nonIdentifierArb = fc
    .string({ minLength: 1, maxLength: 50 })
    .filter((s) => !KNOWN_IDENTIFIERS.includes(s));

  it("returns true for all known financial identifier field names", () => {
    fc.assert(
      fc.property(knownIdentifierArb, (fieldName) => {
        expect(isFinancialIdentifier(fieldName)).toBe(true);
      }),
      { numRuns: 100 }
    );
  });

  it("returns false for non-identifier field names", () => {
    fc.assert(
      fc.property(nonIdentifierArb, (fieldName) => {
        expect(isFinancialIdentifier(fieldName)).toBe(false);
      }),
      { numRuns: 100 }
    );
  });

  it("returns false for common field names that are not financial identifiers", () => {
    const commonNonIdentifierArb = fc.constantFrom(
      "name",
      "date",
      "amount",
      "currency",
      "balance",
      "description",
      "reference",
      "status",
      "type",
      "value",
      "total",
      "address",
      "country",
      "bank_name",
      "transaction_id"
    );

    fc.assert(
      fc.property(commonNonIdentifierArb, (fieldName) => {
        expect(isFinancialIdentifier(fieldName)).toBe(false);
      }),
      { numRuns: 100 }
    );
  });

  it("correctly classifies a mix of identifiers and non-identifiers", () => {
    const mixedFieldArb = fc.oneof(
      knownIdentifierArb.map((name) => ({ name, expected: true })),
      nonIdentifierArb.map((name) => ({ name, expected: false }))
    );

    fc.assert(
      fc.property(mixedFieldArb, ({ name, expected }) => {
        expect(isFinancialIdentifier(name)).toBe(expected);
      }),
      { numRuns: 100 }
    );
  });
});
