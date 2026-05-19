/**
 * Pure utility functions for PDF–Table synchronisation logic.
 *
 * These functions are intentionally free of side-effects so they can be
 * tested in isolation without any DOM or React overhead.
 */

/**
 * Clamps a requested page number to the valid range [1, max(1, totalPages)].
 *
 * When `totalPages` is 0 (PDF not yet loaded) the function returns 1 so that
 * the viewer always has a safe page to display.
 *
 * @param {number} requestedPage - The page number requested by the caller.
 * @param {number} totalPages    - The total number of pages in the document.
 *                                 Pass 0 when the document has not yet loaded.
 * @returns {number} An integer in [1, max(1, totalPages)].
 */
export function clampPage(requestedPage, totalPages) {
  const upper = Math.max(1, totalPages);
  return Math.max(1, Math.min(upper, Math.trunc(requestedPage)));
}

/**
 * Filters a list of tables to those whose `page_range` includes `currentPage`.
 *
 * A table is included in the result when its `page_range` array contains the
 * exact integer value of `currentPage`. Tables with a missing or empty
 * `page_range` are excluded.
 *
 * @param {Array<{page_range: number[], [key: string]: unknown}>} tables - The
 *   full list of extracted table objects.
 * @param {number} currentPage - The active PDF page number (1-indexed).
 * @returns {Array<{page_range: number[], [key: string]: unknown}>} The subset
 *   of tables whose `page_range` includes `currentPage`.
 */
export function filterTablesByPage(tables, currentPage) {
  return tables.filter(
    (table) =>
      // Tables with no page_range info are always shown (can't filter by page)
      !Array.isArray(table.page_range) ||
      table.page_range.length === 0 ||
      table.page_range.includes(currentPage)
  );
}

/**
 * Resolves the target page when the user clicks a table block.
 *
 * - If the table has a non-empty `page_range`, returns
 *   `clampPage(table.page_range[0], totalPages)`.
 * - If `page_range` is empty or absent, returns `currentPage` unchanged so
 *   the PDF viewer stays on the current page (Requirement 3.2).
 *
 * @param {{ page_range: number[] }} table - The table that was clicked.
 * @param {number} totalPages              - Total pages in the loaded document.
 * @param {number} currentPage             - The currently displayed page; used
 *   as the fallback when `page_range` is empty.
 * @returns {number} The page the viewer should navigate to.
 */
export function resolveTableClickPage(table, totalPages, currentPage) {
  if (!Array.isArray(table.page_range) || table.page_range.length === 0) {
    return currentPage;
  }
  return clampPage(table.page_range[0], totalPages);
}

/**
 * Applies a page change to the viewer state, returning a new state object.
 *
 * The returned object has `currentPage` updated to the clamped value of
 * `newPage` and all other state fields (including `showAllTables`) copied
 * over unchanged, satisfying Requirement 4.5.
 *
 * @param {{ currentPage: number, showAllTables: boolean, totalPages: number }} state
 *   The current viewer state.
 * @param {number} newPage - The requested new page number.
 * @returns {{ currentPage: number, showAllTables: boolean, totalPages: number }}
 *   A new state object with `currentPage` updated (clamped) and all other
 *   fields preserved.
 */
export function applyPageChange(state, newPage) {
  return {
    ...state,
    currentPage: clampPage(newPage, state.totalPages),
  };
}
