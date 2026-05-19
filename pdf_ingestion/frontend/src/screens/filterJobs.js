/**
 * Pure function that filters jobs based on active filter criteria using AND logic.
 *
 * @param {Array} jobs - Array of job objects
 * @param {Object} filters - Filter criteria object
 * @param {Array<string>} [filters.schemaTypes] - Array of schema_type values to include (empty = no filter)
 * @param {Array<string>} [filters.statuses] - Array of status values to include (empty = no filter)
 * @param {string|null} [filters.dateFrom] - ISO 8601 date string for start of date range (inclusive)
 * @param {string|null} [filters.dateTo] - ISO 8601 date string for end of date range (inclusive)
 * @returns {Array} Filtered array of jobs matching ALL active criteria
 */
export function filterJobs(jobs, filters = {}) {
  const { schemaTypes = [], statuses = [], dateFrom = null, dateTo = null } = filters;

  return jobs.filter((job) => {
    // Schema type filter (multi-select): if any types are selected, job must match one
    if (schemaTypes.length > 0 && !schemaTypes.includes(job.schema_type)) {
      return false;
    }

    // Status filter (multi-select): if any statuses are selected, job must match one
    if (statuses.length > 0 && !statuses.includes(job.status)) {
      return false;
    }

    // Date range filter for submitted_at
    if (dateFrom) {
      const jobDate = new Date(job.submitted_at);
      const fromDate = new Date(dateFrom);
      if (jobDate < fromDate) {
        return false;
      }
    }

    if (dateTo) {
      const jobDate = new Date(job.submitted_at);
      const toDate = new Date(dateTo);
      if (jobDate > toDate) {
        return false;
      }
    }

    return true;
  });
}
