import { describe, it, expect } from "vitest";
import fc from "fast-check";
import { getConfidenceColour } from "./ConfidenceBadge.jsx";

/**
 * Property 2: ConfidenceBadge colour threshold mapping
 *
 * For any numeric confidence value in the range [0, 1], the ConfidenceBadge
 * component SHALL render with green background when value ≥ 0.90, amber
 * background when 0.70 ≤ value < 0.90, and red background when value < 0.70.
 *
 * **Validates: Requirements 12.1**
 */
describe("Feature: operational-frontend-redesign, Property 2: ConfidenceBadge colour threshold mapping", () => {
  // Custom arbitrary that generates floats in [0, 1] with bias toward boundaries (0.70, 0.90)
  const confidenceArb = fc.oneof(
    // Uniform distribution across [0, 1]
    { weight: 3, arbitrary: fc.double({ min: 0, max: 1, noNaN: true }) },
    // Bias toward the 0.70 boundary
    { weight: 2, arbitrary: fc.double({ min: 0.68, max: 0.72, noNaN: true }) },
    // Bias toward the 0.90 boundary
    { weight: 2, arbitrary: fc.double({ min: 0.88, max: 0.92, noNaN: true }) },
    // Exact boundary values
    { weight: 1, arbitrary: fc.constantFrom(0, 0.7, 0.9, 1) }
  );

  it("returns green (var(--color-success)) for values >= 0.90", () => {
    fc.assert(
      fc.property(
        fc.double({ min: 0.9, max: 1, noNaN: true }),
        (value) => {
          expect(getConfidenceColour(value)).toBe("var(--color-success)");
        }
      ),
      { numRuns: 100 }
    );
  });

  it("returns amber (var(--color-warning)) for values in [0.70, 0.90)", () => {
    fc.assert(
      fc.property(
        fc.double({ min: 0.7, max: 0.9, noNaN: true, maxExcluded: true }),
        (value) => {
          expect(getConfidenceColour(value)).toBe("var(--color-warning)");
        }
      ),
      { numRuns: 100 }
    );
  });

  it("returns red (var(--color-error)) for values < 0.70", () => {
    fc.assert(
      fc.property(
        fc.double({ min: 0, max: 0.7, noNaN: true, maxExcluded: true }),
        (value) => {
          expect(getConfidenceColour(value)).toBe("var(--color-error)");
        }
      ),
      { numRuns: 100 }
    );
  });

  it("maps any value in [0, 1] to exactly one of the three colours", () => {
    const validColours = [
      "var(--color-success)",
      "var(--color-warning)",
      "var(--color-error)",
    ];

    fc.assert(
      fc.property(confidenceArb, (value) => {
        const colour = getConfidenceColour(value);
        expect(validColours).toContain(colour);
      }),
      { numRuns: 100 }
    );
  });

  it("colour thresholds are mutually exclusive and exhaustive for all values in [0, 1]", () => {
    fc.assert(
      fc.property(confidenceArb, (value) => {
        const colour = getConfidenceColour(value);

        if (value >= 0.9) {
          expect(colour).toBe("var(--color-success)");
        } else if (value >= 0.7) {
          expect(colour).toBe("var(--color-warning)");
        } else {
          expect(colour).toBe("var(--color-error)");
        }
      }),
      { numRuns: 100 }
    );
  });
});
