# Implementation Plan: PDF–Table Sync

## Overview

Lift `currentPage` state from `PdfViewer` to `ResultsViewerScreen`, wire both panels together for bidirectional synchronisation, and add page-filtering with a "Show all tables" toggle to `ResultsTablesPanel`. Pure logic is extracted first into `syncUtils.js` to enable isolated testing before any component changes.

## Tasks

- [x] 1. Extract pure sync logic into `syncUtils.js`
  - [x] 1.1 Create `src/utils/syncUtils.js` with four exported pure functions
    - Implement `clampPage(requestedPage, totalPages)` — returns an integer in `[1, max(1, totalPages)]`; when `totalPages` is 0 returns 1
    - Implement `filterTablesByPage(tables, currentPage)` — returns tables whose `page_range` includes `currentPage`
    - Implement `resolveTableClickPage(table, totalPages)` — returns `clampPage(table.page_range[0], totalPages)` or leaves page unchanged when `page_range` is empty
    - Implement `applyPageChange(state, newPage)` — returns a new state object with `currentPage` updated and `showAllTables` unchanged
    - Add JSDoc comments for each function
    - _Requirements: 5.1, 5.2, 5.3, 3.1, 3.2, 4.5_

- [ ] 2. Unit and property tests for `syncUtils.js`
  - [ ]* 2.1 Write unit tests for pure functions in `src/utils/syncUtils.test.js`
    - `clampPage`: test boundary values (0, 1, totalPages, totalPages+1, negative, totalPages=0)
    - `filterTablesByPage`: test tables that match, tables that don't match, empty array, multi-page tables
    - `resolveTableClickPage`: test non-empty `page_range`, empty `page_range` (returns current page unchanged), clamping above/below bounds
    - `applyPageChange`: test that `showAllTables` is preserved for both true and false
    - _Requirements: 5.1, 5.2, 5.3, 3.1, 3.2, 4.5_

  - [ ]* 2.2 Write property-based tests in `src/utils/syncUtils.pbt.test.js` using `fast-check`
    - **Property 1: Active Page is always within valid bounds** — for any `totalPages` (0–100) and any sequence of requested pages (including out-of-range), `clampPage` always returns an integer in `[1, max(1, totalPages)]`
    - **Validates: Requirements 5.1, 5.2, 5.3, 1.5, 1.6**
    - **Property 2: Page filter is consistent with currentPage** — for any tables array and any `currentPage`, every table in the filtered result has `page_range` containing `currentPage`, and every table with `page_range` containing `currentPage` appears in the result (no false positives, no false negatives)
    - **Validates: Requirements 2.1, 4.2**
    - **Property 3: Show-all is a superset of page-filtered; toggle round-trip** — for any tables and `currentPage`, `filterTablesByPage` called twice with the same args returns equal results (idempotent); the full tables array is always a superset of the filtered result
    - **Validates: Requirements 2.4, 4.3, 4.4**
    - **Property 4: Table click sets page to first `page_range` element (clamped)** — for any non-empty `page_range` and any `totalPages ≥ 1`, `resolveTableClickPage` returns `clamp(page_range[0], 1, totalPages)`
    - **Validates: Requirements 3.1, 5.3**
    - **Property 5: Toggle state is preserved across page changes** — for any `showAllTables` boolean and any new page, `applyPageChange` leaves `showAllTables` unchanged
    - **Validates: Requirements 4.5**
    - Run each property with `numRuns: 100`
    - _Requirements: 5.1, 5.2, 5.3, 2.1, 2.4, 3.1, 4.2, 4.3, 4.4, 4.5_

- [x] 3. Refactor `PdfViewer` to a controlled component
  - [x] 3.1 Modify `src/components/PdfViewer.jsx` to accept controlled props
    - Remove `currentPage` and `setCurrentPage` from internal `useState`; keep `totalPages`, `scale`, `loading`, `error`, `hoveredHighlight` as internal state
    - Add required props: `currentPage: number`, `onPageChange: (page: number) => void`
    - Add optional prop: `onTotalPages: (total: number) => void`
    - In the PDF load `useEffect`, call `onTotalPages(doc.numPages)` after setting `totalPages`
    - Compute `safePage = clampPage(currentPage, totalPages)` (import from `syncUtils.js`) and pass `safePage` to `pdfDoc.getPage()` — do NOT call `onPageChange` with the clamped value
    - Replace `setCurrentPage(...)` calls in navigation buttons with `onPageChange(currentPage - 1)` and `onPageChange(currentPage + 1)`
    - Remove the `useEffect` that called `setCurrentPage(highlights[0].page)` when highlights changed
    - Add `aria-label="Previous page"` to the previous button and `aria-label="Next page"` to the next button; add `aria-label="Zoom out"` and `aria-label="Zoom in"` to zoom buttons
    - Add retry logic in `renderPage`: on catch, wait 300 ms and retry once; if second attempt fails, call `setError(...)`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 3.3, 6.6, 7.4_

- [ ] 4. Unit tests for controlled `PdfViewer`
  - [ ]* 4.1 Write unit tests in `src/components/PdfViewer.test.jsx`
    - Renders without error when `currentPage` and `onPageChange` props are provided (mock `pdfjs-dist`)
    - Calls `onPageChange` with `currentPage - 1` when previous button is clicked
    - Calls `onPageChange` with `currentPage + 1` when next button is clicked
    - Previous button is disabled when `currentPage === 1`
    - Next button is disabled when `currentPage >= totalPages`
    - Does NOT call `onPageChange` when `currentPage` prop is below 1 (clamps silently)
    - Does NOT call `onPageChange` when `currentPage` prop exceeds `totalPages` (clamps silently)
    - Navigation buttons have descriptive `aria-label` attributes (`getByRole("button", { name: /previous page/i })`)
    - Calls `onTotalPages` with the document's page count after PDF loads
    - Does NOT call `onPageChange` when `highlights` prop changes (side-effect removed)
    - _Requirements: 1.3, 1.4, 1.5, 1.6, 1.7, 7.4_

- [x] 5. Refactor `ResultsTablesPanel` with sync props
  - [x] 5.1 Modify `src/screens/ResultsTablesPanel.jsx` to accept and use sync props
    - Add new props: `currentPage: number`, `onTableClick: (table) => void`, `showAllTables: boolean`, `onToggleShowAll: () => void`
    - Import `filterTablesByPage` from `../utils/syncUtils`
    - Compute `visibleTables = showAllTables ? tables : filterTablesByPage(tables, currentPage)` before the render
    - Add `useRef` for `firstMatchRef`; attach it to the first element of `visibleTables` during render
    - Add `useEffect` that calls `firstMatchRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" })` when `currentPage` or `showAllTables` changes (only when `!showAllTables`)
    - Render "No tables on this page." message when `!showAllTables && visibleTables.length === 0` (replacing the existing "No tables extracted." path for this case)
    - Render the "Show all tables" toggle `<label>` with a checkbox when `tables.length > 0`; wire `checked={showAllTables}` and `onChange={onToggleShowAll}`; add `aria-label="Show all tables"` to the checkbox
    - Wrap each table block `<div>` with `role="button"`, `tabIndex={0}`, `onClick={() => onTableClick(table)}`, and `onKeyDown` handler that calls `onTableClick(table)` on Enter or Space
    - Apply active-page highlight styles: `borderLeft: isActive ? "3px solid var(--color-info)" : "3px solid transparent"` and `backgroundColor: isActive ? "rgba(52,152,219,0.04)" : undefined` where `isActive = !showAllTables && table.page_range.includes(currentPage)`
    - Add `cursor: "pointer"` to the table block style
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4, 4.1, 4.2, 4.3, 4.4, 4.5, 7.1, 7.2, 7.3_

- [ ] 6. Unit tests for `ResultsTablesPanel`
  - [ ]* 6.1 Write unit tests in `src/screens/ResultsTablesPanel.test.jsx`
    - Shows only tables matching `currentPage` when `showAllTables` is false
    - Shows all tables when `showAllTables` is true
    - Renders "No tables on this page." when no tables match and `showAllTables` is false
    - Does NOT render "No tables on this page." when `showAllTables` is true
    - Calls `onTableClick` with the correct table object when a table block is clicked
    - Calls `onTableClick` when Enter is pressed on a focused table block
    - Calls `onTableClick` when Space is pressed on a focused table block
    - Toggle checkbox is present and accessible via `getByRole("checkbox", { name: /show all tables/i })`
    - Calls `onToggleShowAll` when the toggle checkbox is changed
    - Active-page table block has the highlight border style applied; non-active blocks do not
    - Table blocks have `role="button"` and are reachable via Tab
    - _Requirements: 2.1, 2.3, 2.4, 3.1, 3.4, 4.1, 4.2, 4.3, 7.1, 7.2, 7.3_

- [x] 7. Wire sync state in `ResultsViewerScreen`
  - [x] 7.1 Add sync state and handlers to `src/screens/ResultsViewerScreen.jsx`
    - Add three new state variables: `const [currentPage, setCurrentPage] = useState(1)`, `const [totalPages, setTotalPages] = useState(0)`, `const [showAllTables, setShowAllTables] = useState(false)`
    - Implement `handlePageChange(page)` using `clampPage` from `syncUtils.js`; call `setCurrentPage(clamped)`
    - Implement `handleTotalPages(n)` that calls `setTotalPages(n)`
    - Implement `handleTableClick(table)` that guards against empty `page_range`, resolves the target page using `resolveTableClickPage` from `syncUtils.js`, and calls `setCurrentPage(resolved)`
    - Update the `onViewSource` handler in `FieldsPanel` to also call `setCurrentPage(field.provenance.bbox.page ?? 1)` when setting `pdfHighlights` (removes the old highlights-driven side-effect in `PdfViewer`)
    - Pass `currentPage`, `onPageChange={handlePageChange}`, and `onTotalPages={handleTotalPages}` to `<PdfViewer>`
    - Pass `currentPage`, `onTableClick={handleTableClick}`, `showAllTables`, and `onToggleShowAll={() => setShowAllTables((v) => !v)}` to `<ResultsTablesPanel>`
    - _Requirements: 1.1, 1.2, 2.1, 2.2, 3.1, 3.2, 4.1, 5.1, 5.2, 5.3, 6.1, 6.2, 6.3, 6.4, 6.5_

- [ ] 8. Integration tests for `ResultsViewerScreen`
  - [ ]* 8.1 Write integration tests in `src/screens/ResultsViewerScreen.sync.test.jsx`
    - Clicking a table block in `ResultsTablesPanel` updates the `currentPage` prop passed to `PdfViewer` (mock `PdfViewer` to capture props)
    - Calling `onPageChange` from `PdfViewer` updates the `currentPage` prop passed to `ResultsTablesPanel`
    - Existing tabs (Fields, Abstentions, Validation) still render correctly after sync wiring is applied
    - `showPdfViewer=false` does not render `PdfViewer` and renders the full-width content panel
    - `onViewSource` on a field row sets `showPdfViewer=true` and passes the correct `currentPage` to `PdfViewer`
    - _Requirements: 1.1, 1.2, 2.1, 3.1, 6.1, 6.2, 6.3, 6.4, 6.5_

- [ ] 9. Property-based test for keyboard equivalence
  - [ ]* 9.1 Write Property 6 test in `src/utils/syncUtils.pbt.test.js` (append to existing file)
    - **Property 6: Keyboard activation is equivalent to mouse click on table blocks** — for any table with a non-empty `page_range`, pressing Enter and pressing Space on a focused table block each invoke `onTableClick` the same number of times as a mouse click
    - Use `@testing-library/react` `userEvent` inside `fc.assert` with `tableArbitrary`
    - **Validates: Requirements 7.3**
    - _Requirements: 7.3_

- [x] 10. Final checkpoint — ensure all tests pass
  - Run `npm test` (executes `vitest --run`) from `pdf_ingestion/frontend/`
  - All unit tests, integration tests, and property-based tests must pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Each task references specific requirements for traceability
- `syncUtils.js` pure functions are tested first (tasks 1–2) so property tests can run without DOM overhead
- `clampPage` is imported by both `PdfViewer` and `ResultsViewerScreen` — single source of truth for bounds logic
- The `highlights`-driven `setCurrentPage` side-effect in `PdfViewer` is intentionally removed in task 3.1; the parent takes over this responsibility in task 7.1
- Property tests use `fast-check` (already in `devDependencies`) with `numRuns: 100`
- Property 6 requires `@testing-library/react` and is placed in the `.pbt.test.js` file alongside the other properties

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "2.2"] },
    { "id": 2, "tasks": ["3.1"] },
    { "id": 3, "tasks": ["4.1", "5.1"] },
    { "id": 4, "tasks": ["6.1", "7.1"] },
    { "id": 5, "tasks": ["8.1"] },
    { "id": 6, "tasks": ["9.1"] }
  ]
}
```
