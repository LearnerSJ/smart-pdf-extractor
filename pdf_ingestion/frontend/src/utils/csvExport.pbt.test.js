/**
 * Property-Based Test: CSV export round-trip
 *
 * Validates: Requirements 9.4
 *
 * Property 3: For any array of feedback entries (where field values may contain
 * commas, double quotes, newlines, and Unicode characters), exporting to CSV and
 * parsing the resulting CSV back SHALL produce values equivalent to the original
 * entries with all special characters preserved.
 */
import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { exportCSV, parseCSV } from "./csvExport.js";

/**
 * Generator for a string that may contain CSV-problematic characters:
 * commas, double quotes, newlines (CR, LF, CRLF), and Unicode.
 */
const specialCharString = fc.oneof(
  // Plain ASCII strings
  fc.string(),
  // Strings with embedded commas
  fc.string().map((s) => s + "," + s),
  // Strings with embedded double quotes
  fc.string().map((s) => s + '"' + s),
  // Strings with embedded newlines (LF)
  fc.string().map((s) => s + "\n" + s),
  // Strings with embedded carriage return + newline (CRLF)
  fc.string().map((s) => s + "\r\n" + s),
  // Unicode strings (including emoji, CJK, etc.)
  fc.constantFrom("日本語", "中文测试", "🎉🚀", "café", "naïve", "über", "Ω∑π", "한국어"),
  // Mixed special characters
  fc
    .tuple(fc.string(), fc.constantFrom(",", '"', "\n", "\r\n", "日本語", "🎉"))
    .map(([s, special]) => s + special)
);

/**
 * Generator for a single feedback entry object with the expected CSV headers.
 */
const feedbackEntryArb = fc.record({
  job_id: specialCharString,
  field_name: specialCharString,
  original_value: specialCharString,
  corrected_value: specialCharString,
  submitted_by: specialCharString,
  submitted_at: specialCharString,
});

/**
 * Generator for an array of feedback entries (1 to 20 entries).
 */
const feedbackEntriesArb = fc.array(feedbackEntryArb, { minLength: 1, maxLength: 20 });

describe("Property 3: CSV export round-trip", () => {
  /**
   * **Validates: Requirements 9.4**
   *
   * For any array of feedback entries with special characters,
   * parseCSV(exportCSV(entries)) produces values equivalent to the original entries.
   */
  it("parseCSV(exportCSV(entries)) produces values equivalent to original entries", () => {
    fc.assert(
      fc.property(feedbackEntriesArb, (entries) => {
        const csv = exportCSV(entries);
        const parsed = parseCSV(csv);

        // Same number of entries
        expect(parsed.length).toBe(entries.length);

        // Each parsed entry matches the original
        for (let i = 0; i < entries.length; i++) {
          const original = entries[i];
          const result = parsed[i];

          // All field values should be preserved (null/undefined become empty string)
          expect(result.job_id).toBe(original.job_id == null ? "" : String(original.job_id));
          expect(result.field_name).toBe(
            original.field_name == null ? "" : String(original.field_name)
          );
          expect(result.original_value).toBe(
            original.original_value == null ? "" : String(original.original_value)
          );
          expect(result.corrected_value).toBe(
            original.corrected_value == null ? "" : String(original.corrected_value)
          );
          expect(result.submitted_by).toBe(
            original.submitted_by == null ? "" : String(original.submitted_by)
          );
          expect(result.submitted_at).toBe(
            original.submitted_at == null ? "" : String(original.submitted_at)
          );
        }
      }),
      { numRuns: 100 }
    );
  });
});
