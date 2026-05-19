import { describe, it, expect } from "vitest";
import fc from "fast-check";
import { isSubmitEnabled } from "./CorrectionModal";

/**
 * Property 5: Correction submit button enablement
 *
 * For any string value, the CorrectionModal submit button SHALL be disabled
 * if and only if the trimmed value is empty (i.e., the string consists entirely
 * of whitespace characters or is the empty string).
 *
 * **Validates: Requirements 10.5**
 */
describe("Property 5: Correction submit button enablement", () => {
  it("submit is disabled if and only if trimmed value is empty (arbitrary strings)", () => {
    fc.assert(
      fc.property(fc.string(), (value) => {
        const result = isSubmitEnabled(value);
        const trimmedEmpty = value.trim().length === 0;
        expect(result).toBe(!trimmedEmpty);
      }),
      { numRuns: 100 }
    );
  });

  it("submit is always disabled for whitespace-only strings", () => {
    // Generate strings composed only of whitespace characters
    const whitespaceArb = fc
      .array(fc.constantFrom(" ", "\t", "\n", "\r", "\f", "\v"), { minLength: 0, maxLength: 50 })
      .map((chars) => chars.join(""));

    fc.assert(
      fc.property(whitespaceArb, (value) => {
        expect(isSubmitEnabled(value)).toBe(false);
      }),
      { numRuns: 100 }
    );
  });

  it("submit is always enabled for strings with at least one non-whitespace character", () => {
    // Generate strings that contain at least one non-whitespace character
    const nonEmptyArb = fc
      .tuple(
        fc.string(),
        fc.constantFrom("a", "B", "1", "!", "@", "#", "$", "é", "中", "日"),
        fc.string()
      )
      .map(([prefix, nonWs, suffix]) => prefix + nonWs + suffix);

    fc.assert(
      fc.property(nonEmptyArb, (value) => {
        expect(isSubmitEnabled(value)).toBe(true);
      }),
      { numRuns: 100 }
    );
  });

  it("submit is disabled for the empty string", () => {
    expect(isSubmitEnabled("")).toBe(false);
  });
});
