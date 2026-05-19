import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { groupByValidator } from "./ResultsValidationPanel";

/**
 * Property 4: Validation failure grouping integrity
 *
 * For any list of validation failure objects with varying validator_name values,
 * grouping by validator_name SHALL produce groups where:
 * (a) every failure in a group has the same validator_name,
 * (b) the union of all groups equals the original list, and
 * (c) no failure appears in more than one group.
 *
 * **Validates: Requirements 8.3**
 */
describe("Feature: operational-frontend-redesign, Property 4: Validation failure grouping integrity", () => {
  // Generator for a single validation failure object
  const failureArb = fc.record({
    validator_name: fc.oneof(
      fc.constantFrom(
        "validate_amounts",
        "validate_dates",
        "validate_balances",
        "validate_references",
        "validate_totals"
      ),
      fc.string({ minLength: 1, maxLength: 30 })
    ),
    field_name: fc.string({ minLength: 1, maxLength: 50 }),
    error_code: fc.string({ minLength: 1, maxLength: 20 }),
    detail: fc.string({ maxLength: 100 }),
  });

  // Generator for an array of failure objects
  const failuresArb = fc.array(failureArb, { minLength: 0, maxLength: 50 });

  it("(a) every failure in a group has the same validator_name", () => {
    fc.assert(
      fc.property(failuresArb, (failures) => {
        const grouped = groupByValidator(failures);

        for (const [validatorName, items] of Object.entries(grouped)) {
          for (const item of items) {
            const expectedKey = item.validator_name || "unknown";
            expect(expectedKey).toBe(validatorName);
          }
        }
      }),
      { numRuns: 100 }
    );
  });

  it("(b) union of all groups equals the original list", () => {
    fc.assert(
      fc.property(failuresArb, (failures) => {
        const grouped = groupByValidator(failures);

        // Collect all items from all groups
        const allGrouped = Object.values(grouped).flat();

        // The total count must match
        expect(allGrouped.length).toBe(failures.length);

        // Every original failure must appear in the grouped result
        for (const failure of failures) {
          expect(allGrouped).toContain(failure);
        }
      }),
      { numRuns: 100 }
    );
  });

  it("(c) no failure appears in more than one group", () => {
    fc.assert(
      fc.property(failuresArb, (failures) => {
        const grouped = groupByValidator(failures);
        const groupKeys = Object.keys(grouped);

        // Check that no failure object reference appears in multiple groups
        for (let i = 0; i < groupKeys.length; i++) {
          for (let j = i + 1; j < groupKeys.length; j++) {
            const groupA = grouped[groupKeys[i]];
            const groupB = grouped[groupKeys[j]];

            for (const item of groupA) {
              expect(groupB).not.toContain(item);
            }
          }
        }
      }),
      { numRuns: 100 }
    );
  });
});
