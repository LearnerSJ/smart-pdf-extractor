import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { filterJobs } from "./filterJobs";

/**
 * Property 1: AND-filter correctness
 *
 * For any list of jobs and any combination of active filters (schema_type set,
 * status set, date range), the filtered result SHALL contain only jobs that
 * satisfy ALL active filter criteria simultaneously, and SHALL contain every
 * job from the original list that satisfies all criteria.
 *
 * **Validates: Requirements 3.8**
 */
describe("Feature: operational-frontend-redesign, Property 1: AND-filter correctness", () => {
  // Valid schema types and statuses from the design
  const SCHEMA_TYPES = ["bank_statement", "custody_statement", "swift_confirm", "unknown"];
  const STATUSES = ["queued", "processing", "complete", "failed", "abstained"];

  // Date range as timestamps (ms) for safe ISO string generation
  const MIN_TS = new Date("2023-01-01T00:00:00Z").getTime();
  const MAX_TS = new Date("2025-12-31T23:59:59Z").getTime();

  // Generator for a valid ISO date string within range
  const isoDateArb = fc.integer({ min: MIN_TS, max: MAX_TS }).map(
    (ts) => new Date(ts).toISOString()
  );

  // Generator for a single job object
  const jobArb = fc.record({
    job_id: fc.uuid(),
    schema_type: fc.constantFrom(...SCHEMA_TYPES),
    status: fc.constantFrom(...STATUSES),
    pages: fc.integer({ min: 1, max: 100 }),
    submitted_at: isoDateArb,
    completed_at: fc.oneof(fc.constant(null), isoDateArb),
    overall_confidence: fc.oneof(
      fc.constant(null),
      fc.double({ min: 0, max: 1, noNaN: true })
    ),
  });

  // Generator for an array of jobs
  const jobsArb = fc.array(jobArb, { minLength: 0, maxLength: 30 });

  // Generator for filter criteria
  const filtersArb = fc.record({
    schemaTypes: fc.subarray(SCHEMA_TYPES),
    statuses: fc.subarray(STATUSES),
    dateFrom: fc.oneof(fc.constant(null), isoDateArb),
    dateTo: fc.oneof(fc.constant(null), isoDateArb),
  });

  // Helper: check if a single job satisfies all filter criteria
  function jobSatisfiesAllCriteria(job, filters) {
    const { schemaTypes = [], statuses = [], dateFrom = null, dateTo = null } = filters;

    if (schemaTypes.length > 0 && !schemaTypes.includes(job.schema_type)) {
      return false;
    }
    if (statuses.length > 0 && !statuses.includes(job.status)) {
      return false;
    }
    if (dateFrom && new Date(job.submitted_at) < new Date(dateFrom)) {
      return false;
    }
    if (dateTo && new Date(job.submitted_at) > new Date(dateTo)) {
      return false;
    }
    return true;
  }

  it("filtered result contains only jobs satisfying ALL active criteria", () => {
    fc.assert(
      fc.property(jobsArb, filtersArb, (jobs, filters) => {
        const result = filterJobs(jobs, filters);

        // Every job in the result must satisfy all active filter criteria
        for (const job of result) {
          expect(jobSatisfiesAllCriteria(job, filters)).toBe(true);
        }
      }),
      { numRuns: 100 }
    );
  });

  it("filtered result contains every job that satisfies all criteria (no false exclusions)", () => {
    fc.assert(
      fc.property(jobsArb, filtersArb, (jobs, filters) => {
        const result = filterJobs(jobs, filters);

        // Every job from the original list that satisfies all criteria must be in the result
        for (const job of jobs) {
          if (jobSatisfiesAllCriteria(job, filters)) {
            expect(result).toContain(job);
          }
        }
      }),
      { numRuns: 100 }
    );
  });

  it("filtered result is a subset of the original jobs array", () => {
    fc.assert(
      fc.property(jobsArb, filtersArb, (jobs, filters) => {
        const result = filterJobs(jobs, filters);

        // Result length cannot exceed original
        expect(result.length).toBeLessThanOrEqual(jobs.length);

        // Every item in result must be from the original array
        for (const job of result) {
          expect(jobs).toContain(job);
        }
      }),
      { numRuns: 100 }
    );
  });

  it("with no active filters, all jobs are returned", () => {
    fc.assert(
      fc.property(jobsArb, (jobs) => {
        const result = filterJobs(jobs, {
          schemaTypes: [],
          statuses: [],
          dateFrom: null,
          dateTo: null,
        });

        expect(result.length).toBe(jobs.length);
      }),
      { numRuns: 100 }
    );
  });
});
